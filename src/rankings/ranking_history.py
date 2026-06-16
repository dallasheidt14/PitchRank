"""
Ranking History Management

This module handles saving and retrieving historical ranking snapshots
to enable accurate rank change calculations (7-day and 30-day).

Supports both national rank changes and state rank changes:
- rank_change_7d / rank_change_30d: National rank changes
- rank_change_state_7d / rank_change_state_30d: State rank changes
"""

import logging
from datetime import date, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def _compute_state_ranks(df: pd.DataFrame, active_mask: "pd.Series[bool]", score_col: str) -> "pd.Series[int]":
    """Compute unique state ranks for active teams using canonical tiebreaker (team_id ASC)."""
    active_subset = df.loc[active_mask].sort_values([score_col, "team_id"], ascending=[False, True], na_position="last")
    return active_subset.groupby(["state_code", "age_group", "gender"]).cumcount() + 1


def _canonicalize_age_group(value) -> str:
    """Coerce age_group to canonical 'u{N}' form. Returns '' for missing/unparseable input.

    Upstream callers may pass numeric strings ("14"), capitalized ("U14"),
    or the canonical form ("u14"); all flatten to "u14".
    """
    if pd.isna(value):
        return ""
    digits = "".join(ch for ch in str(value).strip().lower() if ch.isdigit())
    return f"u{int(digits)}" if digits else ""


def _apply_age_group_canonicalization(df: pd.DataFrame) -> None:
    """Canonicalize df['age_group'] in place, deriving from 'age' when needed."""
    if "age_group" in df.columns:
        df["age_group"] = df["age_group"].apply(_canonicalize_age_group)
        if "age" in df.columns:
            empty = df["age_group"].eq("")
            if empty.any():
                df.loc[empty, "age_group"] = df.loc[empty, "age"].apply(_canonicalize_age_group)
    elif "age" in df.columns:
        df["age_group"] = df["age"].apply(_canonicalize_age_group)


async def save_ranking_snapshot(
    supabase_client, rankings_df: pd.DataFrame, snapshot_date: Optional[date] = None
) -> int:
    """
    Save a daily snapshot of rankings to ranking_history table.

    Includes both national ranks and state ranks for tracking rank changes.

    Args:
        supabase_client: Supabase client instance
        rankings_df: DataFrame with columns: team_id, age_group, gender, rank_in_cohort,
                     rank_in_cohort_ml, power_score_final, powerscore_ml, state_code (optional)
        snapshot_date: Date of snapshot (defaults to today)

    Returns:
        Number of records saved

    Example:
        >>> snapshot_df = teams_df[['team_id', 'age', 'gender', 'rank_in_cohort',
        ...     'rank_in_cohort_ml', 'power_score_final', 'powerscore_ml', 'state_code']]
        >>> count = await save_ranking_snapshot(supabase, snapshot_df)
        >>> logger.info(f"Saved {count} ranking snapshots")
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    if rankings_df.empty:
        logger.warning("⚠️ No rankings to save in snapshot")
        return 0

    # Make a copy to avoid modifying original DataFrame
    df = rankings_df.copy()

    # Canonicalize age_group to 'u{N}' form before any downstream use.
    # Upstream callers (e.g. Glicko engine) may set this to a bare numeric
    # string ("14"); canonicalizing here keeps ranking_history consistent
    # with rankings_full and the teams table.
    _apply_age_group_canonicalization(df)

    # Calculate state ranks within each (state_code, age_group, gender) cohort
    # Only Active teams get state ranks — consistent with state_rankings_view
    if "state_code" in df.columns and "power_score_final" in df.columns:
        # Use power_score_final (canonical score) for state rank computation
        score_col = "power_score_final"

        # Initialize all state ranks as NULL
        df["rank_in_state"] = pd.array([pd.NA] * len(df), dtype="Int64")

        # Only rank Active teams (8+ games) to match ranking engine behavior
        if "status" in df.columns:
            active_mask = df["status"] == "Active"
        else:
            logger.warning("⚠️ 'status' column missing in snapshot — all teams treated as Active for state ranking")
            active_mask = pd.Series(True, index=df.index)
        if active_mask.any():
            active_ranks = _compute_state_ranks(df, active_mask, score_col)
            df.loc[active_ranks.index, "rank_in_state"] = active_ranks.astype("Int64")

        state_count = df.loc[active_mask, "state_code"].notna().sum() if active_mask.any() else 0
        logger.info(
            f"📍 Calculated state ranks for {state_count:,} Active teams across {df['state_code'].nunique()} states"
        )
    else:
        df["rank_in_state"] = None
        logger.warning("⚠️ state_code or power_score_final not available - state ranks will be NULL")

    # Prepare data for insertion
    snapshot_records = []
    for _, row in df.iterrows():
        # Get age_group (already computed above or from original data)
        age_group = str(row.get("age_group", ""))
        if not age_group:
            age_val = row.get("age")
            if pd.notna(age_val):
                age_group = f"u{int(float(age_val))}"

        record = {
            "snapshot_date": snapshot_date.isoformat(),
            "team_id": str(row.get("team_id")),
            "age_group": age_group,
            "gender": str(row.get("gender", "")),
            "rank_in_cohort": int(row.get("rank_in_cohort")) if pd.notna(row.get("rank_in_cohort")) else None,
            "rank_in_cohort_ml": int(row.get("rank_in_cohort_ml")) if pd.notna(row.get("rank_in_cohort_ml")) else None,
            "rank_in_cohort_final": int(row.get("rank_in_cohort_final"))
            if pd.notna(row.get("rank_in_cohort_final"))
            else None,
            "power_score_final": float(row.get("power_score_final"))
            if pd.notna(row.get("power_score_final"))
            else None,
            "powerscore_ml": float(row.get("powerscore_ml")) if pd.notna(row.get("powerscore_ml")) else None,
            # NEW: State rank tracking
            "state_code": str(row.get("state_code")) if pd.notna(row.get("state_code")) else None,
            "rank_in_state": int(row.get("rank_in_state")) if pd.notna(row.get("rank_in_state")) else None,
        }
        snapshot_records.append(record)

    if not snapshot_records:
        logger.warning("⚠️ No valid records to save in snapshot")
        return 0

    # Guard: deduplicate by team_id (constraint is UNIQUE(team_id, snapshot_date))
    seen_team_ids: set = set()
    unique_records = []
    for rec in snapshot_records:
        tid = rec["team_id"]
        if tid not in seen_team_ids:
            seen_team_ids.add(tid)
            unique_records.append(rec)
    if len(unique_records) < len(snapshot_records):
        logger.warning(
            f"⚠️ Removed {len(snapshot_records) - len(unique_records)} duplicate team_id entries "
            f"before snapshot upsert"
        )
    snapshot_records = unique_records

    # Batch upsert with exponential backoff retries to handle Supabase timeouts
    try:
        import time

        total_records = len(snapshot_records)
        logger.info(f"💾 Saving {total_records:,} ranking snapshots for {snapshot_date}...")

        batch_size = 1000
        max_retries = 4
        saved_count = 0
        failed_batches = []

        for i in range(0, total_records, batch_size):
            batch = snapshot_records[i : i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_records + batch_size - 1) // batch_size

            for attempt in range(max_retries + 1):
                try:
                    response = (
                        supabase_client.table("ranking_history")
                        .upsert(batch, on_conflict="team_id,snapshot_date")
                        .execute()
                    )

                    batch_saved = len(response.data) if response.data else len(batch)
                    saved_count += batch_saved

                    if total_batches > 1:
                        label = f" (retry {attempt})" if attempt > 0 else ""
                        logger.info(
                            f"   Batch {batch_num}/{total_batches}{label}: "
                            f"Saved {batch_saved:,} snapshots ({saved_count:,}/{total_records:,} total)"
                        )
                    break
                except Exception as batch_error:
                    if attempt < max_retries:
                        wait = 2 ** (attempt + 1)
                        logger.warning(
                            f"⚠️ Batch {batch_num}/{total_batches} attempt {attempt + 1} failed, "
                            f"retrying in {wait}s: {batch_error}"
                        )
                        time.sleep(wait)
                    else:
                        logger.error(
                            f"❌ Batch {batch_num}/{total_batches} failed after "
                            f"{max_retries + 1} attempts: {batch_error}"
                        )
                        failed_batches.append(batch_num)

        # Verify saved count matches expected count
        if failed_batches:
            raise RuntimeError(
                f"Snapshot save incomplete: {len(failed_batches)} batch(es) failed "
                f"(batches {failed_batches}). Saved {saved_count:,}/{total_records:,} records."
            )

        if saved_count < total_records:
            logger.warning(f"⚠️ Snapshot count mismatch: saved {saved_count:,} vs expected {total_records:,}")

        logger.info(f"✅ Saved {saved_count:,}/{total_records:,} ranking snapshots")
        return saved_count

    except Exception as e:
        logger.error(f"❌ Error saving ranking snapshots: {e}")
        raise


async def get_historical_ranks(
    supabase_client, team_ids: list[str], days_ago: int, reference_date: Optional[date] = None
) -> Dict[str, Optional[int]]:
    """
    Get historical ranks for multiple teams from N days ago.

    Args:
        supabase_client: Supabase client instance
        team_ids: List of team_id_master UUIDs
        days_ago: Number of days in the past (7, 30, etc.)
        reference_date: Reference date (defaults to today)

    Returns:
        Dictionary mapping team_id -> historical rank (None if not found)

    Example:
        >>> team_ids = ['abc-123', 'def-456']
        >>> ranks_7d_ago = await get_historical_ranks(supabase, team_ids, days_ago=7)
        >>> print(ranks_7d_ago)
        {'abc-123': 5, 'def-456': 12}
    """
    if reference_date is None:
        reference_date = date.today()

    target_date = reference_date - timedelta(days=days_ago)
    date_range_start = target_date - timedelta(days=3)  # Allow ±3 days tolerance
    date_range_end = target_date + timedelta(days=3)

    if not team_ids:
        return {}

    try:
        # Batch queries to avoid URL length limits (Supabase has ~8KB URL limit)
        # With 150 teams per batch, we stay well under the limit
        batch_size = 150
        all_records = []

        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i : i + batch_size]
            try:
                # Query snapshots within date range for this batch
                response = (
                    supabase_client.table("ranking_history")
                    .select("team_id, snapshot_date, rank_in_cohort, rank_in_cohort_ml, rank_in_cohort_final")
                    .in_("team_id", batch)
                    .gte("snapshot_date", date_range_start.isoformat())
                    .lte("snapshot_date", date_range_end.isoformat())
                    .execute()
                )

                if response.data:
                    all_records.extend(response.data)
            except Exception as batch_error:
                logger.warning(f"❌ Error fetching historical ranks for batch {i // batch_size + 1}: {batch_error}")
                continue

        if not all_records:
            logger.info(
                f"📍 No historical national rankings found for {len(team_ids)} teams "
                f"around {target_date} ({days_ago}d ago)"
            )
            return {team_id: None for team_id in team_ids}

        # Build mapping of team_id -> rank (prefer ML rank, fallback to cohort rank)
        # If multiple snapshots exist, pick the closest to target_date
        historical_ranks = {}
        snapshots_by_team = {}

        for record in all_records:
            team_id = record["team_id"]
            snapshot_date = date.fromisoformat(record["snapshot_date"])
            # 3-level fallback: final → ML → raw (handles pre-migration snapshots)
            final_rank = record.get("rank_in_cohort_final")
            ml_rank = record.get("rank_in_cohort_ml")
            rank = (
                final_rank
                if final_rank is not None
                else (ml_rank if ml_rank is not None else record.get("rank_in_cohort"))
            )

            # Calculate date distance
            distance = abs((snapshot_date - target_date).days)

            # Keep closest snapshot for each team
            if team_id not in snapshots_by_team or distance < snapshots_by_team[team_id]["distance"]:
                snapshots_by_team[team_id] = {"rank": rank, "distance": distance, "snapshot_date": snapshot_date}

        # Extract ranks from best snapshots
        for team_id in team_ids:
            if team_id in snapshots_by_team:
                historical_ranks[team_id] = snapshots_by_team[team_id]["rank"]
            else:
                historical_ranks[team_id] = None

        found_count = sum(1 for v in historical_ranks.values() if v is not None)
        logger.debug(f"Found {found_count}/{len(team_ids)} historical ranks from ~{days_ago}d ago")

        return historical_ranks

    except Exception as e:
        logger.error(f"❌ Error fetching historical ranks: {e}")
        # Return None for all teams on error
        return {team_id: None for team_id in team_ids}


async def get_prior_cohort_ranks(
    supabase_client, team_ids: list[str], days_ago: int, reference_date: Optional[date] = None
) -> Dict[str, Dict[str, object]]:
    """
    Get each team's prior published rank AND the cohort it held in that snapshot.

    Returns ``{team_id: {"age_group": str, "gender": str, "rank": int}}`` for the snapshot
    ~``days_ago`` days before ``reference_date`` (±3 days, closest wins; rank via the same
    final → ml → raw fallback as get_historical_ranks). The snapshot cohort lets callers that
    freeze the evidence-gate reference skip teams whose cohort has since changed (e.g. aged up),
    so a stale rank is never applied to a different cohort. Empty dict when no snapshot is found.
    """
    if reference_date is None:
        reference_date = date.today()

    target_date = reference_date - timedelta(days=days_ago)
    date_range_start = target_date - timedelta(days=3)
    date_range_end = target_date + timedelta(days=3)

    if not team_ids:
        return {}

    try:
        batch_size = 150
        all_records = []

        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i : i + batch_size]
            try:
                response = (
                    supabase_client.table("ranking_history")
                    .select(
                        "team_id, snapshot_date, age_group, gender, "
                        "rank_in_cohort, rank_in_cohort_ml, rank_in_cohort_final"
                    )
                    .in_("team_id", batch)
                    .gte("snapshot_date", date_range_start.isoformat())
                    .lte("snapshot_date", date_range_end.isoformat())
                    .execute()
                )
                if response.data:
                    all_records.extend(response.data)
            except Exception as batch_error:
                logger.warning(f"❌ Error fetching prior cohort ranks for batch {i // batch_size + 1}: {batch_error}")
                continue

        if not all_records:
            logger.info(f"📍 No prior cohort ranking snapshot found for {len(team_ids)} teams around {target_date}")
            return {}

        # Keep the snapshot closest to target_date for each team
        best_by_team: Dict[str, Dict[str, object]] = {}
        for record in all_records:
            final_rank = record.get("rank_in_cohort_final")
            ml_rank = record.get("rank_in_cohort_ml")
            rank = (
                final_rank
                if final_rank is not None
                else (ml_rank if ml_rank is not None else record.get("rank_in_cohort"))
            )
            age_group = str(record.get("age_group") or "")
            gender = str(record.get("gender") or "")
            if rank is None or not age_group or not gender:
                continue

            team_id = str(record["team_id"])
            distance = abs((date.fromisoformat(record["snapshot_date"]) - target_date).days)
            existing = best_by_team.get(team_id)
            if existing is None or distance < existing["distance"]:
                best_by_team[team_id] = {
                    "age_group": age_group,
                    "gender": gender,
                    "rank": int(rank),
                    "distance": distance,
                }

        return {
            team_id: {"age_group": v["age_group"], "gender": v["gender"], "rank": v["rank"]}
            for team_id, v in best_by_team.items()
        }

    except Exception as e:
        logger.error(f"❌ Error fetching prior cohort ranks: {e}")
        return {}


async def get_historical_state_ranks(
    supabase_client, team_ids: list[str], days_ago: int, reference_date: Optional[date] = None
) -> Dict[str, Optional[int]]:
    """
    Get historical STATE ranks for multiple teams from N days ago.

    Args:
        supabase_client: Supabase client instance
        team_ids: List of team_id_master UUIDs
        days_ago: Number of days in the past (7, 30, etc.)
        reference_date: Reference date (defaults to today)

    Returns:
        Dictionary mapping team_id -> historical state rank (None if not found)

    Example:
        >>> team_ids = ['abc-123', 'def-456']
        >>> state_ranks_7d_ago = await get_historical_state_ranks(supabase, team_ids, days_ago=7)
        >>> print(state_ranks_7d_ago)
        {'abc-123': 5, 'def-456': 12}
    """
    if reference_date is None:
        reference_date = date.today()

    target_date = reference_date - timedelta(days=days_ago)
    date_range_start = target_date - timedelta(days=3)  # Allow ±3 days tolerance
    date_range_end = target_date + timedelta(days=3)

    if not team_ids:
        return {}

    try:
        # Batch queries to avoid URL length limits (Supabase has ~8KB URL limit)
        batch_size = 150
        all_records = []

        for i in range(0, len(team_ids), batch_size):
            batch = team_ids[i : i + batch_size]
            try:
                # Query snapshots within date range for this batch
                # Include state_code and rank_in_state
                response = (
                    supabase_client.table("ranking_history")
                    .select("team_id, snapshot_date, state_code, rank_in_state")
                    .in_("team_id", batch)
                    .gte("snapshot_date", date_range_start.isoformat())
                    .lte("snapshot_date", date_range_end.isoformat())
                    .not_.is_("rank_in_state", "null")
                    .execute()
                )  # Only get records with state rank

                if response.data:
                    all_records.extend(response.data)
            except Exception as batch_error:
                logger.warning(
                    f"❌ Error fetching historical state ranks for batch {i // batch_size + 1}: {batch_error}"
                )
                continue

        if not all_records:
            logger.info(
                f"📍 No historical state rankings found for {len(team_ids)} teams "
                f"around {target_date} ({days_ago}d ago)"
            )
            return {team_id: None for team_id in team_ids}

        # Build mapping of team_id -> state rank
        # If multiple snapshots exist, pick the closest to target_date
        historical_state_ranks = {}
        snapshots_by_team = {}

        for record in all_records:
            team_id = record["team_id"]
            snapshot_date_val = date.fromisoformat(record["snapshot_date"])
            state_rank = record.get("rank_in_state")

            if state_rank is None:
                continue

            # Calculate date distance
            distance = abs((snapshot_date_val - target_date).days)

            # Keep closest snapshot for each team
            if team_id not in snapshots_by_team or distance < snapshots_by_team[team_id]["distance"]:
                snapshots_by_team[team_id] = {
                    "rank": state_rank,
                    "distance": distance,
                    "snapshot_date": snapshot_date_val,
                    "state_code": record.get("state_code"),
                }

        # Extract ranks from best snapshots
        for team_id in team_ids:
            if team_id in snapshots_by_team:
                historical_state_ranks[team_id] = snapshots_by_team[team_id]["rank"]
            else:
                historical_state_ranks[team_id] = None

        found_count = sum(1 for v in historical_state_ranks.values() if v is not None)
        logger.debug(f"Found {found_count}/{len(team_ids)} historical state ranks from ~{days_ago}d ago")

        return historical_state_ranks

    except Exception as e:
        logger.error(f"❌ Error fetching historical state ranks: {e}")
        # Return None for all teams on error
        return {team_id: None for team_id in team_ids}


async def calculate_rank_changes(
    supabase_client, current_rankings_df: pd.DataFrame, reference_date: Optional[date] = None
) -> pd.DataFrame:
    """
    Calculate rank changes (7-day and 30-day) for current rankings.

    Calculates both national rank changes and state rank changes.

    Args:
        supabase_client: Supabase client instance
        current_rankings_df: DataFrame with current rankings
            (must have 'team_id' and 'rank_in_cohort_ml' or 'rank_in_cohort')
        reference_date: Reference date for calculating changes (defaults to today)

    Returns:
        DataFrame with added columns:
        - rank_change_7d, rank_change_30d: National rank changes
        - rank_change_state_7d, rank_change_state_30d: State rank changes

    Logic:
        rank_change = historical_rank - current_rank
        Positive = improved (moved UP, e.g., rank 10 -> 5 = +5)
        Negative = declined (moved DOWN, e.g., rank 5 -> 10 = -5)
        NULL/NaN = no historical data available

    Example:
        >>> teams_with_changes = await calculate_rank_changes(supabase, current_rankings)
        >>> print(teams_with_changes[['team_name', 'rank_in_cohort', 'rank_change_7d', 'rank_change_state_7d']])
    """
    if current_rankings_df.empty:
        logger.warning("⚠️ No rankings to calculate rank changes for")
        current_rankings_df["rank_change_7d"] = None
        current_rankings_df["rank_change_30d"] = None
        current_rankings_df["rank_change_state_7d"] = None
        current_rankings_df["rank_change_state_30d"] = None
        return current_rankings_df

    # Extract team IDs
    team_ids = current_rankings_df["team_id"].dropna().unique().tolist()

    if not team_ids:
        logger.warning("⚠️ No valid team IDs found in rankings")
        current_rankings_df["rank_change_7d"] = None
        current_rankings_df["rank_change_30d"] = None
        current_rankings_df["rank_change_state_7d"] = None
        current_rankings_df["rank_change_state_30d"] = None
        return current_rankings_df

    logger.info(f"📊 Calculating rank changes for {len(team_ids):,} teams...")

    # Get historical NATIONAL ranks
    ranks_7d_ago = await get_historical_ranks(supabase_client, team_ids, days_ago=7, reference_date=reference_date)
    ranks_30d_ago = await get_historical_ranks(supabase_client, team_ids, days_ago=30, reference_date=reference_date)

    # Get historical STATE ranks
    state_ranks_7d_ago = await get_historical_state_ranks(
        supabase_client, team_ids, days_ago=7, reference_date=reference_date
    )
    state_ranks_30d_ago = await get_historical_state_ranks(
        supabase_client, team_ids, days_ago=30, reference_date=reference_date
    )

    # Calculate current state ranks if not already present
    # This matches the logic in save_ranking_snapshot()
    has_state_data = "state_code" in current_rankings_df.columns and "power_score_final" in current_rankings_df.columns
    if has_state_data:
        df = current_rankings_df.copy()
        _apply_age_group_canonicalization(df)

        # Use power_score_final to match save_ranking_snapshot() — both must use
        # the same score column to avoid phantom rank changes
        score_col = "power_score_final"

        # Calculate current rank within state for each cohort — Active teams only
        current_rankings_df["current_state_rank"] = pd.array([pd.NA] * len(current_rankings_df), dtype="Int64")
        if "status" in df.columns:
            active_mask = df["status"] == "Active"
        else:
            logger.warning("⚠️ 'status' column missing — all teams treated as Active for state rank changes")
            active_mask = pd.Series(True, index=df.index)
        if active_mask.any():
            active_ranks = _compute_state_ranks(df, active_mask, score_col)
            current_rankings_df.loc[active_ranks.index, "current_state_rank"] = active_ranks.astype("Int64")
    else:
        current_rankings_df["current_state_rank"] = None

    # Calculate changes for each team
    def calculate_change(row) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
        team_id = row["team_id"]

        # Use published final rank, with 3-level fallback for pre-migration data
        final_rank = row.get("rank_in_cohort_final")
        ml_rank = row.get("rank_in_cohort_ml")
        current_national_rank = (
            final_rank if pd.notna(final_rank) else (ml_rank if pd.notna(ml_rank) else row.get("rank_in_cohort"))
        )
        current_state_rank = row.get("current_state_rank")

        # National rank changes
        if pd.isna(current_national_rank):
            national_change_7d = None
            national_change_30d = None
        else:
            rank_7d = ranks_7d_ago.get(team_id)
            rank_30d = ranks_30d_ago.get(team_id)
            national_change_7d = (rank_7d - current_national_rank) if rank_7d is not None else None
            national_change_30d = (rank_30d - current_national_rank) if rank_30d is not None else None

        # State rank changes
        if pd.isna(current_state_rank):
            state_change_7d = None
            state_change_30d = None
        else:
            state_rank_7d = state_ranks_7d_ago.get(team_id)
            state_rank_30d = state_ranks_30d_ago.get(team_id)
            state_change_7d = (state_rank_7d - current_state_rank) if state_rank_7d is not None else None
            state_change_30d = (state_rank_30d - current_state_rank) if state_rank_30d is not None else None

        return national_change_7d, national_change_30d, state_change_7d, state_change_30d

    # Apply calculation
    changes = current_rankings_df.apply(calculate_change, axis=1, result_type="expand")
    current_rankings_df["rank_change_7d"] = changes[0]
    current_rankings_df["rank_change_30d"] = changes[1]
    current_rankings_df["rank_change_state_7d"] = changes[2]
    current_rankings_df["rank_change_state_30d"] = changes[3]

    # Clean up temporary column
    if "current_state_rank" in current_rankings_df.columns:
        current_rankings_df.drop(columns=["current_state_rank"], inplace=True)

    # Convert to numeric dtype to ensure .nlargest() works properly
    for col in ["rank_change_7d", "rank_change_30d", "rank_change_state_7d", "rank_change_state_30d"]:
        current_rankings_df[col] = pd.to_numeric(current_rankings_df[col], errors="coerce")

    # Log statistics
    total_teams = len(current_rankings_df)
    teams_with_7d = current_rankings_df["rank_change_7d"].notna().sum()
    teams_with_30d = current_rankings_df["rank_change_30d"].notna().sum()
    teams_with_state_7d = current_rankings_df["rank_change_state_7d"].notna().sum()
    teams_with_state_30d = current_rankings_df["rank_change_state_30d"].notna().sum()

    logger.info(
        f"✅ Rank changes: national 7d={teams_with_7d:,}/{total_teams:,} ({teams_with_7d / total_teams * 100:.0f}%), "
        f"30d={teams_with_30d:,}/{total_teams:,} ({teams_with_30d / total_teams * 100:.0f}%) | "
        f"state 7d={teams_with_state_7d:,}/{total_teams:,} ({teams_with_state_7d / total_teams * 100:.0f}%), "
        f"30d={teams_with_state_30d:,}/{total_teams:,} ({teams_with_state_30d / total_teams * 100:.0f}%)"
    )

    # Show examples of big movers (only if we have data)
    if teams_with_7d > 0:
        big_movers_7d = current_rankings_df[current_rankings_df["rank_change_7d"].notna()].nlargest(
            3, "rank_change_7d", keep="first"
        )
    else:
        big_movers_7d = pd.DataFrame()

    if not big_movers_7d.empty:
        logger.info("📈 Top 3 biggest improvers (7-day national):")
        for _, team in big_movers_7d.iterrows():
            team_name = team.get("team_name", team.get("team_id", "Unknown"))
            ml_rank_val = team.get("rank_in_cohort_ml")
            current = ml_rank_val if pd.notna(ml_rank_val) else team.get("rank_in_cohort")
            change = team.get("rank_change_7d")
            state_change = team.get("rank_change_state_7d")
            state_info = f", state: +{state_change:.0f}" if pd.notna(state_change) and state_change > 0 else ""
            logger.info(f"   - {team_name}: moved up {change:.0f} spots (now rank #{current:.0f}){state_info}")

    return current_rankings_df
