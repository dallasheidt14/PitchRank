"""
Ranking History Management

This module handles saving and retrieving historical ranking snapshots
to enable accurate rank change calculations (7-day and 30-day).
"""

import logging
from datetime import date, timedelta
from typing import Optional, Dict
import pandas as pd

logger = logging.getLogger(__name__)


async def save_ranking_snapshot(
    supabase_client,
    rankings_df: pd.DataFrame,
    snapshot_date: Optional[date] = None
) -> int:
    """
    Save a daily snapshot of rankings to ranking_history table.

    Args:
        supabase_client: Supabase client instance
        rankings_df: DataFrame with columns: team_id, age_group, gender, rank_in_cohort, rank_in_cohort_ml, power_score_final, powerscore_ml
        snapshot_date: Date of snapshot (defaults to today)

    Returns:
        Number of records saved

    Example:
        >>> snapshot_df = teams_df[['team_id', 'age', 'gender', 'rank_in_cohort', 'rank_in_cohort_ml', 'power_score_final', 'powerscore_ml']]
        >>> count = await save_ranking_snapshot(supabase, snapshot_df)
        >>> logger.info(f"Saved {count} ranking snapshots")
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    if rankings_df.empty:
        logger.warning("⚠️ No rankings to save in snapshot")
        return 0

    # Prepare data for insertion
    snapshot_records = []
    for _, row in rankings_df.iterrows():
        # Always derive age_group from 'age' field to match ranking calculation
        age_val = row.get("age")
        if pd.notna(age_val):
            age_group = f"u{int(float(age_val))}"
        else:
            age_group = str(row.get("age_group", ""))

        record = {
            "snapshot_date": snapshot_date.isoformat(),
            "team_id": str(row.get("team_id")),
            "age_group": age_group,
            "gender": str(row.get("gender", "")),
            "rank_in_cohort": int(row.get("rank_in_cohort")) if pd.notna(row.get("rank_in_cohort")) else None,
            "rank_in_cohort_ml": int(row.get("rank_in_cohort_ml")) if pd.notna(row.get("rank_in_cohort_ml")) else None,
            "power_score_final": float(row.get("power_score_final")) if pd.notna(row.get("power_score_final")) else None,
            "powerscore_ml": float(row.get("powerscore_ml")) if pd.notna(row.get("powerscore_ml")) else None,
        }
        snapshot_records.append(record)

    if not snapshot_records:
        logger.warning("⚠️ No valid records to save in snapshot")
        return 0

    # Batch upsert (insert or update on conflict) to avoid timeout
    # Process in batches to prevent statement timeout errors
    try:
        total_records = len(snapshot_records)
        logger.info(f"💾 Saving {total_records:,} ranking snapshots for {snapshot_date}...")
        
        # Batch size: 2000 records per batch (safe for Supabase upsert operations)
        batch_size = 2000
        saved_count = 0
        
        for i in range(0, total_records, batch_size):
            batch = snapshot_records[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (total_records + batch_size - 1) // batch_size
            
            try:
                # Supabase upsert - will insert or update based on (team_id, snapshot_date) unique constraint
                response = supabase_client.table("ranking_history").upsert(
                    batch,
                    on_conflict="team_id,snapshot_date"
                ).execute()
                
                batch_saved = len(response.data) if response.data else len(batch)
                saved_count += batch_saved
                
                if total_batches > 1:
                    logger.info(f"   Batch {batch_num}/{total_batches}: Saved {batch_saved:,} snapshots ({saved_count:,}/{total_records:,} total)")
                
            except Exception as batch_error:
                logger.error(f"❌ Error saving batch {batch_num}/{total_batches}: {batch_error}")
                # Continue with next batch instead of failing completely
                continue
        
        logger.info(f"✅ Saved {saved_count:,}/{total_records:,} ranking snapshots")
        return saved_count

    except Exception as e:
        logger.error(f"❌ Error saving ranking snapshots: {e}")
        raise


async def get_historical_ranks(
    supabase_client,
    team_ids: list[str],
    days_ago: int,
    reference_date: Optional[date] = None
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
            batch = team_ids[i:i+batch_size]
            try:
                # Query snapshots within date range for this batch
                response = supabase_client.table("ranking_history").select(
                    "team_id, snapshot_date, rank_in_cohort, rank_in_cohort_ml"
                ).in_("team_id", batch).gte(
                    "snapshot_date", date_range_start.isoformat()
                ).lte(
                    "snapshot_date", date_range_end.isoformat()
                ).execute()

                if response.data:
                    all_records.extend(response.data)
            except Exception as batch_error:
                logger.warning(f"❌ Error fetching historical ranks for batch {i//batch_size + 1}: {batch_error}")
                continue

        if not all_records:
            logger.debug(f"No historical rankings found for {len(team_ids)} teams around {target_date}")
            return {team_id: None for team_id in team_ids}

        # Build mapping of team_id -> rank (prefer ML rank, fallback to cohort rank)
        # If multiple snapshots exist, pick the closest to target_date
        historical_ranks = {}
        snapshots_by_team = {}

        for record in all_records:
            team_id = record["team_id"]
            snapshot_date = date.fromisoformat(record["snapshot_date"])
            rank = record.get("rank_in_cohort_ml") or record.get("rank_in_cohort")

            # Calculate date distance
            distance = abs((snapshot_date - target_date).days)

            # Keep closest snapshot for each team
            if team_id not in snapshots_by_team or distance < snapshots_by_team[team_id]["distance"]:
                snapshots_by_team[team_id] = {
                    "rank": rank,
                    "distance": distance,
                    "snapshot_date": snapshot_date
                }

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


async def calculate_rank_changes(
    supabase_client,
    current_rankings_df: pd.DataFrame,
    reference_date: Optional[date] = None
) -> pd.DataFrame:
    """
    Calculate rank changes (7-day and 30-day) for current rankings.

    Args:
        supabase_client: Supabase client instance
        current_rankings_df: DataFrame with current rankings (must have 'team_id' and 'rank_in_cohort_ml' or 'rank_in_cohort')
        reference_date: Reference date for calculating changes (defaults to today)

    Returns:
        DataFrame with added columns: rank_change_7d, rank_change_30d

    Logic:
        rank_change = historical_rank - current_rank
        Positive = improved (moved UP, e.g., rank 10 → 5 = +5)
        Negative = declined (moved DOWN, e.g., rank 5 → 10 = -5)
        NULL/NaN = no historical data available

    Example:
        >>> teams_with_changes = await calculate_rank_changes(supabase, current_rankings)
        >>> print(teams_with_changes[['team_name', 'rank_in_cohort', 'rank_change_7d']])
    """
    if current_rankings_df.empty:
        logger.warning("⚠️ No rankings to calculate rank changes for")
        current_rankings_df["rank_change_7d"] = None
        current_rankings_df["rank_change_30d"] = None
        return current_rankings_df

    # Extract team IDs
    team_ids = current_rankings_df["team_id"].dropna().unique().tolist()

    if not team_ids:
        logger.warning("⚠️ No valid team IDs found in rankings")
        current_rankings_df["rank_change_7d"] = None
        current_rankings_df["rank_change_30d"] = None
        return current_rankings_df

    logger.info(f"📊 Calculating rank changes for {len(team_ids):,} teams...")

    # Get historical ranks
    ranks_7d_ago = await get_historical_ranks(supabase_client, team_ids, days_ago=7, reference_date=reference_date)
    ranks_30d_ago = await get_historical_ranks(supabase_client, team_ids, days_ago=30, reference_date=reference_date)

    # Calculate changes for each team
    def calculate_change(row):
        team_id = row["team_id"]
        # Use ML rank if available, otherwise use cohort rank
        current_rank = row.get("rank_in_cohort_ml") or row.get("rank_in_cohort")

        if pd.isna(current_rank):
            return None, None

        # Get historical ranks
        rank_7d = ranks_7d_ago.get(team_id)
        rank_30d = ranks_30d_ago.get(team_id)

        # Calculate changes (positive = improved)
        change_7d = (rank_7d - current_rank) if rank_7d is not None else None
        change_30d = (rank_30d - current_rank) if rank_30d is not None else None

        return change_7d, change_30d

    # Apply calculation
    changes = current_rankings_df.apply(calculate_change, axis=1, result_type="expand")
    current_rankings_df["rank_change_7d"] = changes[0]
    current_rankings_df["rank_change_30d"] = changes[1]

    # Convert to numeric dtype to ensure .nlargest() works properly
    # pd.to_numeric will convert None to NaN and ensure numeric dtype
    current_rankings_df["rank_change_7d"] = pd.to_numeric(current_rankings_df["rank_change_7d"], errors='coerce')
    current_rankings_df["rank_change_30d"] = pd.to_numeric(current_rankings_df["rank_change_30d"], errors='coerce')

    # Log statistics
    total_teams = len(current_rankings_df)
    teams_with_7d = current_rankings_df["rank_change_7d"].notna().sum()
    teams_with_30d = current_rankings_df["rank_change_30d"].notna().sum()

    logger.info(f"✅ Rank changes calculated:")
    logger.info(f"   - Teams with 7-day data: {teams_with_7d:,}/{total_teams:,} ({teams_with_7d/total_teams*100:.1f}%)")
    logger.info(f"   - Teams with 30-day data: {teams_with_30d:,}/{total_teams:,} ({teams_with_30d/total_teams*100:.1f}%)")

    # Show examples of big movers (only if we have data)
    if teams_with_7d > 0:
        big_movers_7d = current_rankings_df[
            current_rankings_df["rank_change_7d"].notna()
        ].nlargest(3, "rank_change_7d", keep="first")
    else:
        big_movers_7d = pd.DataFrame()

    if not big_movers_7d.empty:
        logger.info("📈 Top 3 biggest improvers (7-day):")
        for _, team in big_movers_7d.iterrows():
            team_name = team.get("team_name", team.get("team_id", "Unknown"))
            current = team.get("rank_in_cohort_ml") or team.get("rank_in_cohort")
            change = team.get("rank_change_7d")
            logger.info(f"   - {team_name}: moved up {change:.0f} spots (now rank #{current:.0f})")

    return current_rankings_df


async def cleanup_old_snapshots(
    supabase_client,
    days_to_keep: int = 90
) -> int:
    """
    Delete ranking snapshots older than specified days.

    Args:
        supabase_client: Supabase client instance
        days_to_keep: Number of days to retain (default: 90)

    Returns:
        Number of snapshots deleted
    """
    cutoff_date = date.today() - timedelta(days=days_to_keep)

    try:
        logger.info(f"🧹 Cleaning up ranking snapshots older than {cutoff_date}...")

        response = supabase_client.table("ranking_history").delete().lt(
            "snapshot_date", cutoff_date.isoformat()
        ).execute()

        deleted_count = len(response.data) if response.data else 0
        logger.info(f"✅ Deleted {deleted_count:,} old ranking snapshots")
        return deleted_count

    except Exception as e:
        logger.error(f"❌ Error cleaning up old snapshots: {e}")
        return 0
