#!/usr/bin/env python3
"""
Validate Cross-Age Opponent Adjustment Fix — Live Data
=======================================================
Runs the v53e ranking engine on live Supabase data twice for the U12M cohort:
  - Run 1: CROSS_AGE_OPPONENT_ADJUST_ENABLED = False (old behavior)
  - Run 2: CROSS_AGE_OPPONENT_ADJUST_ENABLED = True  (new behavior)

Compares Phoenix United Elite metrics and shows cohort-wide impact.

Usage:
    python scripts/validate_cross_age_fix.py
"""

import os
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# ── Setup path (before any project imports) ───────────────────────────
sys.path.append(str(Path(__file__).resolve().parent.parent))

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from src.etl.v53e import V53EConfig, compute_rankings  # noqa: E402
from src.rankings.data_adapter import age_group_to_age  # noqa: E402
from src.rankings.shared import normalize_gender  # noqa: E402
from supabase import create_client  # noqa: E402

# ── Constants ─────────────────────────────────────────────────────────
PHOENIX_TEAM_ID = "691eb36d-95b2-4a08-bd59-13c1b0e830bb"
TARGET_AGE = 12
TARGET_GENDER = "male"  # Normalized form (DB stores "Male", normalize_gender maps to "male")
FEEDER_AGE = 13  # Build global_strength_map from U13M
SEP = "=" * 80
THIN = "-" * 80

COMPARE_COLS = [
    "off_raw",
    "off_norm",
    "def_norm",
    "sos_norm",
    "powerscore_adj",
    "abs_strength",
    "power_presos",
]


# ── Supabase helpers ──────────────────────────────────────────────────


def setup_supabase():
    """Create Supabase client."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: Missing SUPABASE_URL or SUPABASE_KEY in environment")
        sys.exit(1)
    return create_client(url, key)


def paginated_fetch(sb, table: str, select: str, filters: dict | None = None, limit: int = 1000) -> list:
    """Fetch all rows from a Supabase table with offset-based pagination."""
    all_rows: list = []
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + limit - 1)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        result = q.execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < limit:
            break
        offset += limit
    return all_rows


def fetch_teams_for_age_groups(sb, age_groups: list[str], gender: str) -> pd.DataFrame:
    """Fetch team metadata for given age groups and gender.

    Args:
        gender: Normalized gender ("male"/"female"). Mapped to DB form ("Male"/"Female").
    """
    # DB stores "Male"/"Female", normalize_gender maps to "male"/"female"
    db_gender = gender.capitalize()
    print(f"  Fetching teams for age_groups={age_groups}, gender={db_gender}...")
    all_teams = []
    for ag in age_groups:
        rows = paginated_fetch(
            sb,
            "teams",
            "team_id_master, age_group, gender, team_name, is_deprecated",
            filters={"age_group": ag, "gender": db_gender},
        )
        all_teams.extend(rows)
    df = pd.DataFrame(all_teams) if all_teams else pd.DataFrame()
    if not df.empty:
        # Filter out deprecated teams
        df = df[not df.get("is_deprecated", False)].copy()
        df["age"] = df["age_group"].apply(age_group_to_age)
        df["gender_norm"] = normalize_gender(df["gender"])
    print(f"  Found {len(df)} teams")
    return df


def fetch_games_for_teams(sb, team_ids: set[str], lookback_days: int = 365) -> pd.DataFrame:
    """Fetch games involving any of the given team IDs within the lookback window."""
    cutoff = (pd.Timestamp.now("UTC") - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    today_str = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")

    print(f"  Fetching games for {len(team_ids):,} teams (since {cutoff})...")
    team_ids_list = list(team_ids)
    all_games = []
    batch_size = 80  # Keep batches small to avoid URI length limits

    for i in range(0, len(team_ids_list), batch_size):
        batch = team_ids_list[i : i + batch_size]
        # Fetch games where team is home
        offset = 0
        while True:
            result = (
                sb.table("games")
                .select("id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score")
                .in_("home_team_master_id", batch)
                .gte("game_date", cutoff)
                .lte("game_date", today_str)
                .not_.is_("away_team_master_id", "null")
                .not_.is_("home_score", "null")
                .not_.is_("away_score", "null")
                .eq("is_excluded", False)
                .range(offset, offset + 999)
                .execute()
            )
            if not result.data:
                break
            all_games.extend(result.data)
            if len(result.data) < 1000:
                break
            offset += 1000

        # Fetch games where team is away
        offset = 0
        while True:
            result = (
                sb.table("games")
                .select("id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score")
                .in_("away_team_master_id", batch)
                .gte("game_date", cutoff)
                .lte("game_date", today_str)
                .not_.is_("home_team_master_id", "null")
                .not_.is_("home_score", "null")
                .not_.is_("away_score", "null")
                .eq("is_excluded", False)
                .range(offset, offset + 999)
                .execute()
            )
            if not result.data:
                break
            all_games.extend(result.data)
            if len(result.data) < 1000:
                break
            offset += 1000

        if (i + batch_size) % 400 == 0:
            print(f"    ... fetched {len(all_games):,} game rows so far")

    # Deduplicate
    df = pd.DataFrame(all_games) if all_games else pd.DataFrame()
    if not df.empty:
        df = df.drop_duplicates(subset=["id"])
    print(f"  Fetched {len(df):,} unique games")
    return df


def build_v53e_format(games_df: pd.DataFrame, team_meta: pd.DataFrame) -> pd.DataFrame:
    """Convert raw games + team metadata into v53e perspective-based format."""
    if games_df.empty:
        return pd.DataFrame()

    # Build team lookups
    team_age_map = dict(zip(team_meta["team_id_master"].astype(str), team_meta["age"]))
    team_gender_map = dict(zip(team_meta["team_id_master"].astype(str), team_meta["gender_norm"]))

    games = games_df.copy()
    games["_game_id"] = (
        games["game_uid"].fillna(games["id"]).astype(str) if "game_uid" in games.columns else games["id"].astype(str)
    )
    games["_date"] = pd.to_datetime(games["game_date"])

    # Map age/gender for home and away teams
    games["_home_age"] = games["home_team_master_id"].astype(str).map(team_age_map)
    games["_home_gender"] = games["home_team_master_id"].astype(str).map(team_gender_map)
    games["_away_age"] = games["away_team_master_id"].astype(str).map(team_age_map)
    games["_away_gender"] = games["away_team_master_id"].astype(str).map(team_gender_map)

    # Keep only games where both teams have metadata
    mask = (
        games["_home_age"].notna()
        & (games["_home_age"] != "")
        & games["_home_gender"].notna()
        & (games["_home_gender"] != "")
        & games["_away_age"].notna()
        & (games["_away_age"] != "")
        & games["_away_gender"].notna()
        & (games["_away_gender"] != "")
    )
    games = games[mask]

    # Build home perspective
    home_df = pd.DataFrame(
        {
            "game_id": games["_game_id"].values,
            "id": games["id"].values,
            "date": games["_date"].values,
            "team_id": games["home_team_master_id"].astype(str).values,
            "opp_id": games["away_team_master_id"].astype(str).values,
            "home_team_master_id": games["home_team_master_id"].astype(str).values,
            "age": games["_home_age"].values,
            "gender": games["_home_gender"].values,
            "opp_age": games["_away_age"].values,
            "opp_gender": games["_away_gender"].values,
            "gf": pd.to_numeric(games["home_score"], errors="coerce").values,
            "ga": pd.to_numeric(games["away_score"], errors="coerce").values,
        }
    )

    # Build away perspective
    away_df = pd.DataFrame(
        {
            "game_id": games["_game_id"].values,
            "id": games["id"].values,
            "date": games["_date"].values,
            "team_id": games["away_team_master_id"].astype(str).values,
            "opp_id": games["home_team_master_id"].astype(str).values,
            "home_team_master_id": games["home_team_master_id"].astype(str).values,
            "age": games["_away_age"].values,
            "gender": games["_away_gender"].values,
            "opp_age": games["_home_age"].values,
            "opp_gender": games["_home_gender"].values,
            "gf": pd.to_numeric(games["away_score"], errors="coerce").values,
            "ga": pd.to_numeric(games["home_score"], errors="coerce").values,
        }
    )

    v53e_df = pd.concat([home_df, away_df], ignore_index=True)
    return v53e_df


# ── Core logic ────────────────────────────────────────────────────────


def fetch_cohort_data(sb, ages: list[int], gender: str) -> pd.DataFrame:
    """Fetch games and build v53e format for given age groups."""
    # Map ages to age_group strings (e.g., 12 -> "u12")
    age_groups = [f"u{a}" for a in ages]

    # Fetch teams
    team_meta = fetch_teams_for_age_groups(sb, age_groups, gender)
    if team_meta.empty:
        print("  WARNING: No teams found for cohort")
        return pd.DataFrame()

    team_ids = set(team_meta["team_id_master"].astype(str).tolist())

    # Fetch games involving these teams
    games_df = fetch_games_for_teams(sb, team_ids)
    if games_df.empty:
        print("  WARNING: No games found for cohort")
        return pd.DataFrame()

    # We also need metadata for opponents who may be in different age groups
    # Collect all team IDs from games
    all_team_ids = set()
    all_team_ids.update(games_df["home_team_master_id"].astype(str).tolist())
    all_team_ids.update(games_df["away_team_master_id"].astype(str).tolist())

    # Fetch metadata for any teams not already in team_meta
    missing_ids = all_team_ids - team_ids
    if missing_ids:
        print(f"  Fetching metadata for {len(missing_ids)} opponent teams outside cohort...")
        missing_list = list(missing_ids)
        extra_teams = []
        batch_size = 100
        for i in range(0, len(missing_list), batch_size):
            batch = missing_list[i : i + batch_size]
            result = (
                sb.table("teams")
                .select("team_id_master, age_group, gender, team_name, is_deprecated")
                .in_("team_id_master", batch)
                .execute()
            )
            if result.data:
                extra_teams.extend(result.data)

        if extra_teams:
            extra_df = pd.DataFrame(extra_teams)
            extra_df = extra_df[not extra_df.get("is_deprecated", False)].copy()
            extra_df["age"] = extra_df["age_group"].apply(age_group_to_age)
            extra_df["gender_norm"] = normalize_gender(extra_df["gender"])
            team_meta = pd.concat([team_meta, extra_df], ignore_index=True)
            team_meta = team_meta.drop_duplicates(subset=["team_id_master"])

    # Build v53e format
    v53e_df = build_v53e_format(games_df, team_meta)
    print(f"  Built {len(v53e_df):,} v53e perspective rows")

    return v53e_df


def split_cohort(games_df: pd.DataFrame, age: int, gender: str) -> pd.DataFrame:
    """Extract a single (age, gender) cohort from v53e games."""
    mask = (games_df["age"].astype(str) == str(age)) & (games_df["gender"] == gender)
    return games_df.loc[mask].copy()


def build_global_strength_map(games_df: pd.DataFrame, cfg: V53EConfig) -> dict:
    """Run U13M cohort to build a global_strength_map for cross-age SOS."""
    print(f"\nBuilding global_strength_map from U{FEEDER_AGE}M cohort...")
    feeder_games = split_cohort(games_df, FEEDER_AGE, TARGET_GENDER)
    print(f"  U{FEEDER_AGE}M games: {len(feeder_games):,} rows")

    if feeder_games.empty:
        print("  WARNING: No feeder cohort games found, returning empty map")
        return {}

    result = compute_rankings(feeder_games, cfg=cfg)
    teams_df = result["teams"]
    strength_map = {}
    if not teams_df.empty and "abs_strength" in teams_df.columns:
        strength_map = dict(
            zip(
                teams_df["team_id"].astype(str),
                teams_df["abs_strength"].astype(float),
            )
        )
    print(f"  Global strength map: {len(strength_map):,} teams from U{FEEDER_AGE}M")
    return strength_map


def run_cohort(
    games_df: pd.DataFrame,
    cfg: V53EConfig,
    global_strength_map: dict,
    label: str,
) -> pd.DataFrame:
    """Run compute_rankings for U12M with a given config and return teams_df."""
    cohort_games = split_cohort(games_df, TARGET_AGE, TARGET_GENDER)
    print(f"\n{label}: Running v53e on U{TARGET_AGE}M ({len(cohort_games):,} game rows)...")

    if cohort_games.empty:
        print(f"  ERROR: No U{TARGET_AGE}M games found")
        return pd.DataFrame()

    result = compute_rankings(
        cohort_games,
        cfg=cfg,
        global_strength_map=global_strength_map,
        pass_label=label,
    )
    teams_df = result["teams"]
    print(f"  {label}: {len(teams_df)} teams ranked")
    return teams_df


def compare_phoenix(before_df: pd.DataFrame, after_df: pd.DataFrame):
    """Compare Phoenix United Elite metrics between runs."""
    print(f"\n{SEP}")
    print("  Phoenix United Elite (U12M) -- Before vs After Cross-Age Fix")
    print(SEP)

    before_row = before_df[before_df["team_id"].astype(str) == PHOENIX_TEAM_ID]
    after_row = after_df[after_df["team_id"].astype(str) == PHOENIX_TEAM_ID]

    if before_row.empty:
        print(f"  ERROR: Phoenix ({PHOENIX_TEAM_ID}) not found in BEFORE results")
        return
    if after_row.empty:
        print(f"  ERROR: Phoenix ({PHOENIX_TEAM_ID}) not found in AFTER results")
        return

    before_row = before_row.iloc[0]
    after_row = after_row.iloc[0]

    print(f"\n  {'Metric':<20} {'Before':>10} {'After':>10} {'Delta':>10} {'Change':>10}")
    print(f"  {THIN}")

    for col in COMPARE_COLS:
        bv = before_row.get(col)
        av = after_row.get(col)
        if bv is None or av is None:
            print(f"  {col:<20} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'N/A':>10}")
            continue
        bv = float(bv)
        av = float(av)
        delta = av - bv
        pct = (delta / bv * 100) if bv != 0 else 0
        print(f"  {col:<20} {bv:>10.4f} {av:>10.4f} {delta:>+10.4f} {pct:>+9.1f}%")

    # Rank comparison
    if "rank" in before_df.columns and "rank" in after_df.columns:
        before_rank_row = before_df[before_df["team_id"].astype(str) == PHOENIX_TEAM_ID]
        after_rank_row = after_df[after_df["team_id"].astype(str) == PHOENIX_TEAM_ID]
        if not before_rank_row.empty and not after_rank_row.empty:
            br = int(before_rank_row.iloc[0]["rank"])
            ar = int(after_rank_row.iloc[0]["rank"])
            print(f"\n  Rank: {br} -> {ar} (delta: {ar - br:+d})")


def show_top_movers(before_df: pd.DataFrame, after_df: pd.DataFrame, n: int = 10):
    """Show top N teams with largest positive off_norm shift."""
    print(f"\n{SEP}")
    print(f"  Top {n} Most-Helped U12M Teams (largest positive off_norm shift)")
    print(SEP)

    if "off_norm" not in before_df.columns or "off_norm" not in after_df.columns:
        print("  ERROR: off_norm column not found")
        return

    merged = before_df[["team_id", "off_norm"]].merge(
        after_df[["team_id", "off_norm"]],
        on="team_id",
        suffixes=("_before", "_after"),
    )
    merged["off_norm_delta"] = merged["off_norm_after"] - merged["off_norm_before"]

    # Get team names if available
    name_col = "team_name" if "team_name" in before_df.columns else None
    if name_col:
        name_map = dict(
            zip(
                before_df["team_id"].astype(str),
                before_df[name_col].astype(str),
            )
        )
        merged["name"] = merged["team_id"].astype(str).map(name_map).fillna("Unknown")
    else:
        merged["name"] = merged["team_id"].astype(str).str[:12] + "..."

    top = merged.nlargest(n, "off_norm_delta")

    print(f"\n  {'#':<4} {'Team':<40} {'Before':>8} {'After':>8} {'Delta':>8}")
    print(f"  {THIN}")
    for i, (_, row) in enumerate(top.iterrows(), 1):
        is_phoenix = str(row["team_id"]) == PHOENIX_TEAM_ID
        marker = " <-- Phoenix" if is_phoenix else ""
        print(
            f"  {i:<4} {row['name'][:38]:<40} "
            f"{row['off_norm_before']:>8.4f} {row['off_norm_after']:>8.4f} "
            f"{row['off_norm_delta']:>+8.4f}{marker}"
        )


def show_cohort_impact(before_df: pd.DataFrame, after_df: pd.DataFrame):
    """Show cohort-wide impact statistics."""
    print(f"\n{SEP}")
    print("  Cohort-Wide Impact (U12M)")
    print(SEP)

    for col in ["off_norm", "def_norm", "sos_norm", "powerscore_adj"]:
        if col not in before_df.columns or col not in after_df.columns:
            continue

        merged = before_df[["team_id", col]].merge(
            after_df[["team_id", col]],
            on="team_id",
            suffixes=("_before", "_after"),
        )
        delta = merged[f"{col}_after"] - merged[f"{col}_before"]

        print(f"\n  {col}:")
        print(f"    Mean shift:   {delta.mean():+.6f}")
        print(f"    Median shift: {delta.median():+.6f}")
        print(f"    Std of shift: {delta.std():.6f}")
        print(f"    Max increase: {delta.max():+.6f}")
        print(f"    Max decrease: {delta.min():+.6f}")
        teams_changed = (delta.abs() > 0.001).sum()
        print(f"    Teams changed (|delta| > 0.001): {teams_changed} / {len(delta)}")


def main():
    sb = setup_supabase()

    # 1. Fetch games for U12M and U13M cohorts (targeted, not all 700K+ games)
    print("Fetching cohort data for U12M and U13M...\n")
    v53e_df = fetch_cohort_data(sb, ages=[TARGET_AGE, FEEDER_AGE], gender=TARGET_GENDER)

    if v53e_df.empty:
        print("ERROR: No games fetched. Aborting.")
        sys.exit(1)

    # Quick summary
    for age in [TARGET_AGE, FEEDER_AGE]:
        cohort = split_cohort(v53e_df, age, TARGET_GENDER)
        n_teams = cohort["team_id"].nunique()
        print(f"  U{age}M: {len(cohort):,} perspective rows, {n_teams} teams")

    # 2. Build global_strength_map from U13M (same for both runs)
    base_cfg = V53EConfig()
    global_strength_map = build_global_strength_map(v53e_df, base_cfg)

    # 3. Run 1: CROSS_AGE_OPPONENT_ADJUST_ENABLED = False (old behavior)
    cfg_off = deepcopy(base_cfg)
    cfg_off.CROSS_AGE_OPPONENT_ADJUST_ENABLED = False
    before_df = run_cohort(v53e_df, cfg_off, global_strength_map, "OLD (flag=OFF)")

    # 4. Run 2: CROSS_AGE_OPPONENT_ADJUST_ENABLED = True (new behavior)
    cfg_on = deepcopy(base_cfg)
    cfg_on.CROSS_AGE_OPPONENT_ADJUST_ENABLED = True
    after_df = run_cohort(v53e_df, cfg_on, global_strength_map, "NEW (flag=ON)")

    if before_df.empty or after_df.empty:
        print("\nERROR: One or both runs produced no results. Aborting comparison.")
        sys.exit(1)

    # 5. Compare
    compare_phoenix(before_df, after_df)
    show_top_movers(before_df, after_df, n=10)
    show_cohort_impact(before_df, after_df)

    print(f"\n{SEP}")
    print("  Validation complete.")
    print(SEP)


if __name__ == "__main__":
    main()
