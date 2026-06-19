#!/usr/bin/env python3
"""
SCF-off staging board producer — zero prod-write.
=================================================
Builds a staging-only Glicko-2 ranking board with SCF disabled and loads it into
a persistent scratch table ``rankings_full_scf_off`` (``LIKE rankings_full``) so
the existing read-only harnesses can score it:

    scripts/diagnose_bubble_teams.py   --rankings-table rankings_full_scf_off
    scripts/ranking_stability_check.py --compare-table  rankings_full_scf_off

The board is produced DB-read-only: compute_all_cohorts runs with save_snapshot,
persist_game_residuals, persist_game_explainability, and calculate_rank_changes
all disabled, and force_rebuild=True. Because the engine cache key includes
SCF_ENABLED, this run writes a distinct-hash parquet cache that cannot overwrite
the prod (SCF-on) cache. No row in rankings_full / current_rankings /
ranking_history / games is mutated.

SCF is flipped via the env-backed default on GlickoConfig.SCF_ENABLED — set to
"false" in this process only, after dotenv load and before any GlickoConfig is
constructed.

Usage (run from the SCF-off worktree with C:/Python313/python.exe):
    python scripts/run_scf_off_staging.py                 # build board + load scratch table
    python scripts/run_scf_off_staging.py --teardown      # drop the scratch table
The only mutation is the scratch table this script owns; prod tables are read-only.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import execute_values

from src.etl.glicko_config import GlickoConfig
from src.rankings.calculator import compute_all_cohorts
from src.rankings.data_adapter import batch_fetch_rows, v53e_to_rankings_full_format
from src.utils.merge_resolver import MergeResolver
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler()])
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Force SCF off for THIS process AFTER dotenv load, so a stray SCF_ENABLED in
# .env.local cannot override the forced value. GlickoConfig reads this env-backed
# default only when constructed (compute_all_cohorts / _assert_scf_off below),
# never at import, so setting it here is early enough.
os.environ["SCF_ENABLED"] = "false"

SEP = "=" * 78
SCRATCH_TABLE = "rankings_full_scf_off"
STAGING_PARQUET = Path("data/staging/scf_off_teams.parquet")

# Columns the bubble-guardrail and stability harnesses read off the board. The
# formatter always emits these; a present-but-all-NULL column is the real failure
# mode, so the gate checks both presence and non-emptiness.
HARNESS_REQUIRED_COLUMNS = [
    "team_id",
    "age_group",
    "gender",
    "status",
    "games_played",
    "win_percentage",
    "rank_in_cohort",
    "rank_in_cohort_final",
    "sos_norm",
    "powerscore_adj",
    "powerscore_ml",
    "power_score_true",
    "last_game",
    "national_power_score",
]
# Legitimately NULL for many teams (uncapped / fully-trusted), so the all-NULL
# gate must not fire on them — presence is enough.
HARNESS_NULLABLE_COLUMNS = {"publication_cap_score", "positive_ml_evidence_scale"}


def _open_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment (.env / .env.local)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def _assert_scf_off() -> None:
    effective = GlickoConfig().SCF_ENABLED
    print(f"  effective GlickoConfig().SCF_ENABLED = {effective}")
    if effective is not False:
        print("ERROR: SCF_ENABLED did not resolve to False — aborting to avoid an SCF-on staging board")
        sys.exit(1)


def _fetch_teams_metadata(supabase_client, team_ids: list[str]) -> pd.DataFrame:
    """Batch-fetch team_id_master/age_group/gender/state_code via the shared retrying helper."""
    rows = batch_fetch_rows(
        supabase_client,
        "teams",
        "team_id_master, age_group, gender, state_code",
        "team_id_master",
        team_ids,
    )
    return pd.DataFrame(rows)


def _backfill_last_game(conn, board: pd.DataFrame) -> pd.DataFrame:
    """The engine always sets last_game; if it arrived all-NULL, hydrate from games."""
    if board["last_game"].notna().any():
        return board
    print("  last_game is all-NULL on the board — hydrating from games.max(game_date)...")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT team_id_master, max(game_date) FROM (
                SELECT home_team_master_id AS team_id_master, game_date FROM games
                WHERE is_excluded = false AND home_score IS NOT NULL
                UNION ALL
                SELECT away_team_master_id AS team_id_master, game_date FROM games
                WHERE is_excluded = false AND away_score IS NOT NULL
            ) g
            WHERE team_id_master IS NOT NULL
            GROUP BY team_id_master
            """
        )
        last_game_map = {str(tid): ts for tid, ts in cur.fetchall()}
    board = board.copy()
    board["last_game"] = board["team_id"].astype(str).map(last_game_map)
    return board


def _verify_board_columns(board: pd.DataFrame) -> None:
    missing = [c for c in HARNESS_REQUIRED_COLUMNS if c not in board.columns]
    if missing:
        print(f"ERROR: board is missing required columns: {missing}")
        sys.exit(1)
    all_null = [c for c in HARNESS_REQUIRED_COLUMNS if not board[c].notna().any()]
    if all_null:
        print(f"ERROR: board has present-but-all-NULL required columns: {all_null}")
        sys.exit(1)
    for col in sorted(HARNESS_NULLABLE_COLUMNS):
        if col not in board.columns:
            print(f"  WARNING: optional harness column missing from board: {col}")


def _to_pg(value):
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return value


def _load_scratch_table(conn, board: pd.DataFrame) -> int:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(SCRATCH_TABLE)))
        cur.execute(
            sql.SQL("CREATE TABLE {} (LIKE rankings_full INCLUDING DEFAULTS)").format(sql.Identifier(SCRATCH_TABLE))
        )
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (SCRATCH_TABLE,),
        )
        table_cols = {row[0] for row in cur.fetchall()}
        cols = [c for c in board.columns if c in table_cols]
        dropped = [c for c in board.columns if c not in table_cols]
        if dropped:
            print(f"  Board columns absent from rankings_full (skipped on insert): {dropped}")
        rows = [tuple(_to_pg(v) for v in rec) for rec in board[cols].itertuples(index=False, name=None)]
        insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
            sql.Identifier(SCRATCH_TABLE),
            sql.SQL(", ").join(sql.Identifier(c) for c in cols),
        )
        execute_values(cur, insert_sql.as_string(cur), rows, page_size=1000)
    conn.commit()
    return len(rows)


async def _build_board(lookback_days: int) -> pd.DataFrame:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env.local")
        sys.exit(1)
    supabase = create_client(supabase_url, supabase_key)

    merge_resolver = MergeResolver(supabase)
    merge_resolver.load_merge_map()
    if merge_resolver.has_merges:
        print(f"  Loaded {merge_resolver.merge_count} team merges (version: {merge_resolver.version})")
    else:
        print(f"  WARNING: no team merges loaded (version: {merge_resolver.version})")

    result = await compute_all_cohorts(
        supabase_client=supabase,
        today=None,
        fetch_from_supabase=True,
        lookback_days=lookback_days,
        force_rebuild=True,
        merge_resolver=merge_resolver,
        use_glicko=True,
        save_snapshot=False,
        persist_game_residuals=False,
        persist_game_explainability=False,
        calculate_rank_changes_enabled=False,
    )
    teams_df = result["teams"]
    if teams_df.empty:
        print("ERROR: compute_all_cohorts returned an empty board")
        sys.exit(1)

    team_ids = teams_df["team_id"].astype(str).unique().tolist()
    teams_metadata_df = _fetch_teams_metadata(supabase, team_ids)
    return v53e_to_rankings_full_format(teams_df, teams_metadata_df)


async def _run_build(args) -> None:
    print(f"\n{SEP}\n  SCF-off staging board producer (zero prod-write)\n{SEP}")
    _assert_scf_off()

    formatted = await _build_board(args.lookback_days)

    conn = _open_connection()
    try:
        formatted = _backfill_last_game(conn, formatted)
        _verify_board_columns(formatted)

        STAGING_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        formatted.to_parquet(STAGING_PARQUET, index=False)
        print(f"  Dumped {len(formatted):,} rows to {STAGING_PARQUET}")

        inserted = _load_scratch_table(conn, formatted)
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(SCRATCH_TABLE)))
            scratch_count = cur.fetchone()[0]
            cur.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE status = 'Active'").format(sql.Identifier(SCRATCH_TABLE))
            )
            active_count = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"\n{SEP}")
    print(f"  Loaded {inserted:,} rows into {SCRATCH_TABLE} (table count {scratch_count:,}, Active {active_count:,})")
    print("  Score it with:")
    print(f"    python scripts/diagnose_bubble_teams.py   --rankings-table {SCRATCH_TABLE}")
    print(f"    python scripts/ranking_stability_check.py --compare-table  {SCRATCH_TABLE}")
    print("  Tear down with: python scripts/run_scf_off_staging.py --teardown")
    print(SEP)


def _run_teardown() -> None:
    conn = _open_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(SCRATCH_TABLE)))
        conn.commit()
    finally:
        conn.close()
    print(f"  Dropped {SCRATCH_TABLE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce an SCF-off staging board and load it into a scratch table.")
    parser.add_argument("--lookback-days", type=int, default=365, help="Days to look back for rankings (default: 365)")
    parser.add_argument("--teardown", action="store_true", help="Drop the scratch table and exit")
    args = parser.parse_args()

    if args.teardown:
        _run_teardown()
        return
    asyncio.run(_run_build(args))


if __name__ == "__main__":
    main()
