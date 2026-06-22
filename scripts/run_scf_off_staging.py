#!/usr/bin/env python3
"""
SCF staging board producer — zero prod-write, one candidate per invocation.
===========================================================================
Builds a staging-only Glicko-2 ranking board for ONE SCF candidate (mode on/off,
and when on, a chosen SCF_FLOOR / SCF_DIVERSITY_DIVISOR) and loads it into a named
scratch table (``LIKE rankings_full``) so the read-only harnesses can score it:

    scripts/diagnose_bubble_teams.py   --rankings-table <table>
    scripts/ranking_stability_check.py --compare-table  <table> --baseline-table <baseline>

The board is produced DB-read-only: compute_all_cohorts runs with save_snapshot,
persist_game_residuals, persist_game_explainability, and calculate_rank_changes
all disabled, and force_rebuild=True. The engine cache key includes the SCF dials
(SCF_ENABLED + SCF_FLOOR + SCF_DIVERSITY_DIVISOR), so each candidate writes a
distinct-hash parquet cache that cannot overwrite another candidate's or prod's.
No row in rankings_full / current_rankings / ranking_history / games is mutated.

The SCF dials are flipped via env-backed defaults on GlickoConfig — forced in this
process only, after dotenv load and before any GlickoConfig is constructed.

Same-snapshot guarantee: pass --fetch-snapshot once to dump the games dataset to a
parquet (pinned to --today), then build every candidate board from that identical
dataset with --games-snapshot <parquet> --today <date>, so every board-to-board
delta is pure dial effect rather than a re-fetch confound.

Usage (run from the SCF worktree with C:/Python313/python.exe):
    # 1. Fetch the shared games snapshot once (pin today):
    python scripts/run_scf_off_staging.py --fetch-snapshot \
        --games-snapshot data/staging/sweep_games_snapshot.parquet --today 2026-06-19
    # 2. Build the SCF-on baseline (prod dials) and each floor candidate from it:
    python scripts/run_scf_off_staging.py --scf-mode on --scf-floor 0.4 --scf-divisor 4.0 \
        --table rankings_full_scf_on_base \
        --games-snapshot data/staging/sweep_games_snapshot.parquet --today 2026-06-19
    python scripts/run_scf_off_staging.py --scf-mode on --scf-floor 0.55 \
        --table rankings_full_scf_floor055 \
        --games-snapshot data/staging/sweep_games_snapshot.parquet --today 2026-06-19
    # Legacy single-board SCF-off (live fetch, default table):
    python scripts/run_scf_off_staging.py
    # Drop one scratch table:
    python scripts/run_scf_off_staging.py --teardown --table rankings_full_scf_floor055
The only mutation is the scratch table each invocation owns; prod tables are read-only.
"""

import argparse
import asyncio
import logging
import os
import re
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
from src.rankings.calculator import _effective_fetch_lookback_days, compute_all_cohorts
from src.rankings.data_adapter import batch_fetch_rows, fetch_games_for_rankings, v53e_to_rankings_full_format
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

SEP = "=" * 78
DEFAULT_TABLE = "rankings_full_scf_off"
SNAPSHOT_PARQUET_DEFAULT = Path("data/staging/sweep_games_snapshot.parquet")

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


def _force_scf_env(mode: str, floor: float, divisor: float) -> None:
    """Force the SCF dials for THIS process AFTER dotenv load, so a stray value in
    .env.local cannot win. GlickoConfig reads these env-backed defaults only when
    constructed (compute_all_cohorts / _assert_effective_config below), never at
    import, so forcing here — before any GlickoConfig() — is early enough."""
    os.environ["SCF_ENABLED"] = "true" if mode == "on" else "false"
    if mode == "on":
        os.environ["SCF_FLOOR"] = str(floor)
        os.environ["SCF_DIVERSITY_DIVISOR"] = str(divisor)


def _assert_effective_config(mode: str, floor: float, divisor: float) -> None:
    cfg = GlickoConfig()
    print(f"  effective GlickoConfig().SCF_ENABLED           = {cfg.SCF_ENABLED}")
    print(f"  effective GlickoConfig().SCF_FLOOR             = {cfg.SCF_FLOOR}")
    print(f"  effective GlickoConfig().SCF_DIVERSITY_DIVISOR = {cfg.SCF_DIVERSITY_DIVISOR}")
    want_enabled = mode == "on"
    if cfg.SCF_ENABLED is not want_enabled:
        print(f"ERROR: SCF_ENABLED resolved to {cfg.SCF_ENABLED}, expected {want_enabled} — aborting")
        sys.exit(1)
    if want_enabled:
        if abs(cfg.SCF_FLOOR - floor) > 1e-9:
            print(f"ERROR: SCF_FLOOR resolved to {cfg.SCF_FLOOR}, expected {floor} — aborting")
            sys.exit(1)
        if abs(cfg.SCF_DIVERSITY_DIVISOR - divisor) > 1e-9:
            print(
                f"ERROR: SCF_DIVERSITY_DIVISOR resolved to {cfg.SCF_DIVERSITY_DIVISOR}, expected {divisor} — aborting"
            )
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


def _load_scratch_table(conn, board: pd.DataFrame, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
        cur.execute(sql.SQL("CREATE TABLE {} (LIKE rankings_full INCLUDING DEFAULTS)").format(sql.Identifier(table)))
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        table_cols = {row[0] for row in cur.fetchall()}
        cols = [c for c in board.columns if c in table_cols]
        dropped = [c for c in board.columns if c not in table_cols]
        if dropped:
            print(f"  Board columns absent from rankings_full (skipped on insert): {dropped}")
        rows = [tuple(_to_pg(v) for v in rec) for rec in board[cols].itertuples(index=False, name=None)]
        insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(c) for c in cols),
        )
        execute_values(cur, insert_sql.as_string(cur), rows, page_size=1000)
    conn.commit()
    return len(rows)


def _supabase_with_merges():
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
    return supabase, merge_resolver


async def _fetch_snapshot(lookback_days: int, today: pd.Timestamp, out_path: Path) -> None:
    """Fetch the games dataset once (pinned to `today`) and persist it, so every
    candidate board can be built from byte-identical input via --games-snapshot.
    Uses the same fetch path compute_all_cohorts uses internally, so a board built
    from this parquet matches a live fetch run on the same date."""
    supabase, merge_resolver = _supabase_with_merges()
    fetch_lookback_days = _effective_fetch_lookback_days(lookback_days, use_glicko=True)
    games_df = await fetch_games_for_rankings(
        supabase_client=supabase,
        lookback_days=fetch_lookback_days,
        provider_filter=None,
        today=today,
        merge_resolver=merge_resolver,
    )
    if games_df.empty:
        print("ERROR: fetch returned zero games — refusing to write an empty snapshot")
        sys.exit(1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    games_df.to_parquet(out_path, index=False)
    print(f"  Wrote {len(games_df):,} game perspectives to {out_path} (today pinned {today.date()})")
    print("  Build every board from this snapshot with:")
    print(f"    --games-snapshot {out_path} --today {today.date()}")


async def _build_board(lookback_days: int, games_snapshot: Path | None, today: pd.Timestamp | None) -> pd.DataFrame:
    supabase, merge_resolver = _supabase_with_merges()

    games_df = None
    if games_snapshot is not None:
        if not games_snapshot.exists():
            print(f"ERROR: --games-snapshot {games_snapshot} not found (run --fetch-snapshot first)")
            sys.exit(1)
        games_df = pd.read_parquet(games_snapshot)
        print(f"  Loaded {len(games_df):,} game perspectives from {games_snapshot} (today pinned {today.date()})")

    result = await compute_all_cohorts(
        supabase_client=supabase,
        games_df=games_df,
        today=today,
        fetch_from_supabase=games_df is None,
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
    table = args.table
    mode = args.scf_mode
    print(f"\n{SEP}\n  SCF staging board producer (zero prod-write) — mode {mode}, table {table}\n{SEP}")
    _assert_effective_config(mode, args.scf_floor, args.scf_divisor)

    today = pd.Timestamp(args.today) if args.today else None
    games_snapshot = Path(args.games_snapshot) if args.games_snapshot else None
    formatted = await _build_board(args.lookback_days, games_snapshot, today)

    conn = _open_connection()
    try:
        formatted = _backfill_last_game(conn, formatted)
        _verify_board_columns(formatted)

        board_parquet = Path(f"data/staging/{table}.parquet")
        board_parquet.parent.mkdir(parents=True, exist_ok=True)
        formatted.to_parquet(board_parquet, index=False)
        print(f"  Dumped {len(formatted):,} rows to {board_parquet}")

        inserted = _load_scratch_table(conn, formatted, table)
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            scratch_count = cur.fetchone()[0]
            cur.execute(sql.SQL("SELECT count(*) FROM {} WHERE status = 'Active'").format(sql.Identifier(table)))
            active_count = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"\n{SEP}")
    print(f"  Loaded {inserted:,} rows into {table} (table count {scratch_count:,}, Active {active_count:,})")
    print("  Score it with:")
    print(f"    python scripts/diagnose_bubble_teams.py   --rankings-table {table}")
    print(
        f"    python scripts/ranking_stability_check.py --compare-table {table} "
        "--baseline-table rankings_full_scf_on_base"
    )
    print(f"  Tear down with: python scripts/run_scf_off_staging.py --teardown --table {table}")
    print(SEP)


def _run_teardown(table: str) -> None:
    conn = _open_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
        conn.commit()
    finally:
        conn.close()
    print(f"  Dropped {table}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Produce one SCF staging board (any mode/floor/divisor) and load it into a scratch table."
    )
    parser.add_argument("--lookback-days", type=int, default=365, help="Days to look back for rankings (default: 365)")
    parser.add_argument(
        "--scf-mode",
        choices=("on", "off"),
        default="off",
        help="SCF on (apply --scf-floor/--scf-divisor) or off (default: off, backward-compat).",
    )
    parser.add_argument(
        "--scf-floor", type=float, default=0.4, help="SCF_FLOOR when --scf-mode on (default: 0.4 = prod)."
    )
    parser.add_argument(
        "--scf-divisor", type=float, default=4.0, help="SCF_DIVERSITY_DIVISOR when --scf-mode on (default: 4.0 = prod)."
    )
    parser.add_argument(
        "--table", default=DEFAULT_TABLE, help=f"Scratch table to (re)create and load (default: {DEFAULT_TABLE})."
    )
    parser.add_argument(
        "--games-snapshot", help="Parquet of pre-fetched games to build from (requires --today). Omit to fetch live."
    )
    parser.add_argument(
        "--today",
        help="Reference date YYYY-MM-DD pinning the run (required with --games-snapshot or --fetch-snapshot).",
    )
    parser.add_argument(
        "--fetch-snapshot",
        action="store_true",
        help="Fetch games once into --games-snapshot (or the default path) and exit; build candidates from it after.",
    )
    parser.add_argument("--teardown", action="store_true", help="Drop the --table scratch table and exit.")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z_][a-z0-9_]*", args.table):
        parser.error(f"--table must match [a-z_][a-z0-9_]* (got {args.table!r})")
    if args.today is not None:
        try:
            pd.Timestamp(args.today)
        except ValueError:
            parser.error(f"--today must be a valid date (YYYY-MM-DD); got {args.today!r}")

    if args.teardown:
        _run_teardown(args.table)
        return

    if args.fetch_snapshot:
        if not args.today:
            parser.error("--fetch-snapshot requires --today to pin the reference date")
        out_path = Path(args.games_snapshot) if args.games_snapshot else SNAPSHOT_PARQUET_DEFAULT
        asyncio.run(_fetch_snapshot(args.lookback_days, pd.Timestamp(args.today), out_path))
        return

    if args.games_snapshot and not args.today:
        parser.error("--games-snapshot requires --today (the same date used to fetch the snapshot)")

    _force_scf_env(args.scf_mode, args.scf_floor, args.scf_divisor)
    asyncio.run(_run_build(args))


if __name__ == "__main__":
    main()
