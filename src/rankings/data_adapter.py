"""Data adapter to convert between Supabase format and v53e format"""
from __future__ import annotations

import pandas as pd
import re
from typing import Dict, Optional, List, TYPE_CHECKING
from datetime import datetime, timedelta
import logging
import time

if TYPE_CHECKING:
    from src.utils.merge_resolver import MergeResolver

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------
#  Retry wrapper for Supabase queries
# --------------------------------------------------------------------
def retry_supabase_query(query_func, max_retries=4, initial_delay=2.0, description="Query"):
    """
    Retry a Supabase query with exponential backoff.

    Args:
        query_func: Function that executes the query (should return result)
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        description: Description of the query for logging

    Returns:
        Query result

    Raises:
        Exception: If all retries fail
    """
    delay = initial_delay
    last_error = None

    for attempt in range(max_retries):
        try:
            return query_func()
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()

            # Check if it's a retryable error (network/SSL/timeout)
            is_retryable = any(keyword in error_msg for keyword in [
                'ssl', 'timeout', 'connection', 'reset', 'network',
                'temporarily unavailable', 'bad record', 'remote host'
            ])

            if attempt < max_retries - 1 and is_retryable:
                logger.warning(
                    f"⚠️  {description} failed (attempt {attempt + 1}/{max_retries}): {str(e)[:100]}"
                )
                logger.info(f"   Retrying in {delay:.1f}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            elif not is_retryable:
                # Non-retryable error (404, 401, permission denied, etc.) - fail immediately
                logger.error(f"❌ {description} failed with non-retryable error: {str(e)[:200]}")
                raise
            else:
                # Last attempt failed
                logger.error(f"❌ {description} failed after {max_retries} attempts")
                raise

    # Should never reach here, but just in case
    raise last_error


# --------------------------------------------------------------------
#  Safe numeric conversion
# --------------------------------------------------------------------
def safe_int(val):
    """Convert numeric values safely, handling floats and empty strings."""
    try:
        if pd.isna(val) or val == "":
            return None
        return int(float(val))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------
#  Normalize Age Group -> Age
# --------------------------------------------------------------------
def age_group_to_age(age_group: str) -> str:
    """Normalize 'U12', 'u11', '11.0' → '12', '11'"""
    if not age_group:
        return ""
    s = str(age_group).strip().lower().lstrip("u")
    match = re.search(r"\d+", s)
    return str(int(float(match.group()))) if match else ""


async def fetch_games_for_rankings(
    supabase_client,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    today: Optional[pd.Timestamp] = None,
    merge_resolver: Optional['MergeResolver'] = None
) -> pd.DataFrame:
    """
    Fetch games from Supabase and convert to v53e format

    Args:
        supabase_client: Supabase client instance
        lookback_days: Number of days to look back
        provider_filter: Optional provider code filter
        today: Reference date (defaults to today)
        merge_resolver: Optional MergeResolver for resolving deprecated team IDs

    Returns:
        DataFrame in v53e format with columns:
        - game_id, date, team_id, opp_id, age, gender, opp_age, opp_gender, gf, ga
    """
    if today is None:
        today = pd.Timestamp.utcnow().normalize()
    
    cutoff = today - pd.Timedelta(days=lookback_days)
    cutoff_date_str = cutoff.strftime('%Y-%m-%d')
    
    # Fetch games with pagination (Supabase defaults to 1000 rows per query)
    base_query = supabase_client.table('games').select(
        'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
        'home_score, away_score, provider_id'
    ).gte('game_date', cutoff_date_str).order('game_date', desc=False)  # Order for consistent pagination
    
    if provider_filter:
        # Get provider ID with retry logic
        try:
            provider_result = retry_supabase_query(
                lambda: supabase_client.table('providers').select('id').eq(
                    'code', provider_filter
                ).single().execute(),
                max_retries=4,
                initial_delay=2.0,
                description=f"Fetching provider filter '{provider_filter}'"
            )
            if getattr(provider_result, 'data', None):
                base_query = base_query.eq('provider_id', provider_result.data['id'])
        except Exception as e:
            logger.warning(f"⚠️  Failed to fetch provider filter '{provider_filter}' after retries: {str(e)[:100]}")
            # Continue without provider filter
    
    # Paginate to fetch all games (Supabase max is 1000 per query)
    games_data = []
    page_size = 1000
    offset = 0
    max_games = 1000000  # Safety limit
    
    logger.info(f"📥 Fetching games from Supabase (cutoff: {cutoff_date_str})...")

    while len(games_data) < max_games:
        query = base_query.range(offset, offset + page_size - 1)

        try:
            # Use retry wrapper for resilient fetching
            games_result = retry_supabase_query(
                lambda: query.execute(),
                max_retries=4,
                initial_delay=2.0,
                description=f"Fetching games batch at offset {offset}"
            )
        except Exception as e:
            # If all retries fail, log and break (use what we have)
            logger.warning(
                f"⚠️  Failed to fetch games at offset {offset} after retries. "
                f"Using {len(games_data):,} games fetched so far."
            )
            logger.warning(f"   Error: {str(e)[:200]}")
            break

        if not games_result.data:
            break

        games_data.extend(games_result.data)

        # If we got fewer than page_size, we've reached the end
        if len(games_result.data) < page_size:
            break

        offset += page_size

        # Progress indicator for large fetches (every 10k games)
        if len(games_data) % 10000 == 0:
            logger.info(f"  ✓ Fetched {len(games_data):,} games...")
    
    logger.info(f"✅ Fetched {len(games_data):,} total games from database")

    if not games_data:
        logger.warning("⚠️  No games found in database")
        return pd.DataFrame()

    games_df = pd.DataFrame(games_data)

    # Deduplicate games by ID to prevent duplicate perspective rows
    # (can occur from pagination overlap or duplicate inserts in source)
    before_dedup = len(games_df)
    games_df = games_df.drop_duplicates(subset=['id'])
    after_dedup = len(games_df)
    if before_dedup != after_dedup:
        logger.warning(f"⚠️  Removed {before_dedup - after_dedup:,} duplicate games")

    logger.info(f"📊 Processing {len(games_df):,} games...")
    
    # Fetch teams for age_group and gender
    team_ids = set()
    team_ids.update(games_df['home_team_master_id'].dropna().tolist())
    team_ids.update(games_df['away_team_master_id'].dropna().tolist())
    
    if not team_ids:
        logger.warning("⚠️  No team IDs found in games")
        return pd.DataFrame()
    
    logger.info(f"👥 Fetching metadata for {len(team_ids):,} unique teams...")
    
    # Fetch teams in batches (Supabase has URI length limit - UUIDs are long)
    teams_data = []
    team_ids_list = list(team_ids)
    batch_size = 100  # Reduced from 1000 to avoid URI too long errors
    
    for i in range(0, len(team_ids_list), batch_size):
        batch = team_ids_list[i:i + batch_size]
        try:
            # Use retry wrapper for team metadata fetching
            teams_result = retry_supabase_query(
                lambda: supabase_client.table('teams').select(
                    'team_id_master, age_group, gender'
                ).in_('team_id_master', batch).execute(),
                max_retries=4,
                initial_delay=2.0,
                description=f"Fetching team metadata batch {i}-{i+batch_size}"
            )

            if getattr(teams_result, 'data', None):
                teams_data.extend(teams_result.data)
        except Exception as e:
            logger.warning(f"⚠️  Team metadata batch failed ({i}-{i+batch_size}) after retries: {str(e)[:100]}")
            continue

        # Progress indicator for team fetching
        if (i + batch_size) % 1000 == 0 or (i + batch_size) >= len(team_ids_list):
            logger.info(f"  ✓ Fetched metadata for {len(teams_data):,} teams...")
    
    if not teams_data:
        logger.warning("⚠️  No team metadata found")
        return pd.DataFrame()
    
    teams_df = pd.DataFrame(teams_data)
    teams_df['age'] = teams_df['age_group'].apply(age_group_to_age)
    # Normalize gender values
    teams_df["gender"] = (
        teams_df["gender"]
        .astype(str)
        .str.lower()
        .str.strip()
        .replace({
            "boys": "male",
            "boy": "male",
            "girls": "female",
            "girl": "female",
        })
    )
    
    logger.info(f"🔄 Converting {len(games_df):,} games to v53e format (perspective-based)...")
    
    # Create team lookup dicts
    team_age_map = dict(zip(teams_df['team_id_master'], teams_df['age']))
    team_gender_map = dict(zip(teams_df['team_id_master'], teams_df['gender']))
    
    # Convert to v53e format (perspective-based: each game appears twice)
    v53e_rows = []
    processed_count = 0
    
    for _, game in games_df.iterrows():
        game_id = str(game.get('game_uid') or game.get('id', ''))
        game_uuid = game.get('id')  # Keep original UUID for ML residual mapping
        game_date = pd.to_datetime(game.get('game_date'))
        home_team_id = game.get('home_team_master_id')
        away_team_id = game.get('away_team_master_id')
        home_score = game.get('home_score')
        away_score = game.get('away_score')

        # Skip if missing required data
        if pd.isna(home_team_id) or pd.isna(away_team_id) or pd.isna(game_date):
            continue

        # Get team metadata
        home_age = team_age_map.get(home_team_id, '')
        home_gender = team_gender_map.get(home_team_id, '')
        away_age = team_age_map.get(away_team_id, '')
        away_gender = team_gender_map.get(away_team_id, '')

        # Skip if missing age/gender
        if not home_age or not home_gender or not away_age or not away_gender:
            continue

        # Home perspective
        v53e_rows.append({
            'game_id': game_id,
            'id': game_uuid,  # Include UUID for ML residual mapping
            'date': game_date,
            'team_id': str(home_team_id),
            'opp_id': str(away_team_id),
            'home_team_master_id': str(home_team_id),  # Track which team is home
            'age': home_age,
            'gender': home_gender,
            'opp_age': away_age,
            'opp_gender': away_gender,
            'gf': safe_int(home_score),
            'ga': safe_int(away_score),
        })

        # Away perspective
        v53e_rows.append({
            'game_id': game_id,
            'id': game_uuid,  # Include UUID for ML residual mapping
            'date': game_date,
            'team_id': str(away_team_id),
            'opp_id': str(home_team_id),
            'home_team_master_id': str(home_team_id),  # Track which team is home
            'age': away_age,
            'gender': away_gender,
            'opp_age': home_age,
            'opp_gender': home_gender,
            'gf': safe_int(away_score),
            'ga': safe_int(home_score),
        })
        
        processed_count += 1
        # Progress indicator every 50k games
        if processed_count % 50000 == 0:
            logger.info(f"  ✓ Processed {processed_count:,} games ({len(v53e_rows):,} rows)...")
    
    if not v53e_rows:
        logger.warning("⚠️  No valid games after conversion")
        return pd.DataFrame()

    v53e_df = pd.DataFrame(v53e_rows)
    logger.info(f"📋 Created {len(v53e_df):,} perspective rows from {processed_count:,} games")

    # Apply merge resolution if resolver provided
    if merge_resolver is not None and merge_resolver.has_merges:
        logger.info(f"🔀 Applying merge resolution ({merge_resolver.merge_count} merges, version: {merge_resolver.version})")
        v53e_df = merge_resolver.resolve_dataframe(v53e_df, ['team_id', 'opp_id'])

    # Filter out rows with missing scores
    before_filter = len(v53e_df)
    v53e_df = v53e_df.dropna(subset=['gf', 'ga'])
    after_filter = len(v53e_df)
    
    if before_filter != after_filter:
        logger.info(f"🔍 Filtered out {before_filter - after_filter:,} rows with missing scores")
    
    # Ensure date is datetime
    v53e_df['date'] = pd.to_datetime(v53e_df['date'])
    
    logger.info(f"✅ Final v53e dataset: {len(v53e_df):,} rows ready for rankings")
    
    return v53e_df


def supabase_to_v53e_format(
    games_df: pd.DataFrame,
    teams_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Convert Supabase games DataFrame to v53e format
    
    Args:
        games_df: DataFrame with Supabase game columns
        teams_df: DataFrame with team metadata (team_id_master, age_group, gender)
    
    Returns:
        DataFrame in v53e format
    """
    if games_df.empty or teams_df.empty:
        return pd.DataFrame()
    
    # Prepare team lookup
    teams_df = teams_df.copy()
    teams_df['age'] = teams_df['age_group'].apply(age_group_to_age)
    # Normalize gender values
    teams_df["gender"] = (
        teams_df["gender"]
        .astype(str)
        .str.lower()
        .str.strip()
        .replace({
            "boys": "male",
            "boy": "male",
            "girls": "female",
            "girl": "female",
        })
    )
    team_age_map = dict(zip(teams_df['team_id_master'], teams_df['age']))
    team_gender_map = dict(zip(teams_df['team_id_master'], teams_df['gender']))
    
    # Convert to v53e format (perspective-based)
    v53e_rows = []
    
    for _, game in games_df.iterrows():
        game_id = str(game.get('game_uid') or game.get('id', ''))
        game_uuid = game.get('id')  # Keep original UUID for ML residual mapping
        game_date = pd.to_datetime(game.get('game_date'))
        home_team_id = game.get('home_team_master_id')
        away_team_id = game.get('away_team_master_id')
        home_score = game.get('home_score')
        away_score = game.get('away_score')

        if pd.isna(home_team_id) or pd.isna(away_team_id) or pd.isna(game_date):
            continue

        home_age = team_age_map.get(home_team_id, '')
        home_gender = team_gender_map.get(home_team_id, '')
        away_age = team_age_map.get(away_team_id, '')
        away_gender = team_gender_map.get(away_team_id, '')

        if not home_age or not home_gender or not away_age or not away_gender:
            continue

        # Home perspective
        v53e_rows.append({
            'game_id': game_id,
            'id': game_uuid,  # Include UUID for ML residual mapping
            'date': game_date,
            'team_id': str(home_team_id),
            'opp_id': str(away_team_id),
            'home_team_master_id': str(home_team_id),  # Track which team is home
            'age': home_age,
            'gender': home_gender,
            'opp_age': away_age,
            'opp_gender': away_gender,
            'gf': safe_int(home_score),
            'ga': safe_int(away_score),
        })

        # Away perspective
        v53e_rows.append({
            'game_id': game_id,
            'id': game_uuid,  # Include UUID for ML residual mapping
            'date': game_date,
            'team_id': str(away_team_id),
            'opp_id': str(home_team_id),
            'home_team_master_id': str(home_team_id),  # Track which team is home
            'age': away_age,
            'gender': away_gender,
            'opp_age': home_age,
            'opp_gender': home_gender,
            'gf': safe_int(away_score),
            'ga': safe_int(home_score),
        })
    
    if not v53e_rows:
        return pd.DataFrame()
    
    v53e_df = pd.DataFrame(v53e_rows)
    v53e_df = v53e_df.dropna(subset=['gf', 'ga'])
    v53e_df['date'] = pd.to_datetime(v53e_df['date'])
    
    return v53e_df


def v53e_to_supabase_format(teams_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert v53e teams output to Supabase current_rankings format
    
    Args:
        teams_df: DataFrame from v53e compute_rankings() output
    
    Returns:
        DataFrame ready for current_rankings table
    """
    if teams_df.empty:
        logger.warning("⚠️ Empty rankings DataFrame — nothing to convert.")
        return pd.DataFrame()
    
    # Map v53e columns to Supabase columns
    rankings_df = teams_df.copy()
    
    # Ensure team_id is UUID string
    rankings_df['team_id'] = rankings_df['team_id'].astype(str)
    
    # Map PowerScore columns and clip to valid bounds
    if 'powerscore_ml' in rankings_df.columns:
        col = 'powerscore_ml'
    elif 'powerscore_adj' in rankings_df.columns:
        col = 'powerscore_adj'
    elif 'powerscore_core' in rankings_df.columns:
        col = 'powerscore_core'
    else:
        logger.warning("⚠️ No PowerScore column found during export.")
        col = None
    
    if col:
        rankings_df['national_power_score'] = rankings_df[col].clip(0.0, 1.0)
    else:
        rankings_df['national_power_score'] = 0.0
    
    # Map rank with proper defaults and dtype
    if 'rank_in_cohort_ml' in rankings_df.columns:
        rankings_df['national_rank'] = rankings_df['rank_in_cohort_ml']
    elif 'rank_in_cohort' in rankings_df.columns:
        rankings_df['national_rank'] = rankings_df['rank_in_cohort']
    else:
        rankings_df['national_rank'] = 0
    
    # Ensure rank is int and fill nulls
    rankings_df['national_rank'] = rankings_df['national_rank'].fillna(0).astype(int)
    
    logger.info(f"🧾 Prepared {len(rankings_df):,} records for Supabase upload.")
    
    return rankings_df


def v53e_to_rankings_full_format(
    teams_df: pd.DataFrame,
    teams_metadata_df: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Convert v53e + Layer 13 teams output to Supabase rankings_full format
    
    This function maps ALL fields from the ranking engine to the comprehensive
    rankings_full table, preserving all v53E and ML layer outputs.
    
    Args:
        teams_df: DataFrame from v53e compute_rankings() + Layer 13 ML adjustment
        teams_metadata_df: Optional DataFrame with team metadata (team_id_master, age_group, gender, state_code)
                          If not provided, will extract from teams_df if available
    
    Returns:
        DataFrame ready for rankings_full table with all fields mapped
    """
    if teams_df.empty:
        logger.warning("⚠️ Empty rankings DataFrame — nothing to convert.")
        return pd.DataFrame()
    
    # Start with a copy
    rankings_df = teams_df.copy()
    
    # Ensure team_id is UUID string
    rankings_df['team_id'] = rankings_df['team_id'].astype(str)
    
    # Map team identity fields
    # If teams_metadata_df is provided, merge it; otherwise try to extract from teams_df
    # NOTE: Don't merge gender from metadata - v53e always provides it and it's the source of truth
    # NOTE: Only merge columns that don't already exist in rankings_df to avoid _x/_y suffix issues
    if teams_metadata_df is not None and not teams_metadata_df.empty:
        # Merge team metadata (only columns not already in rankings_df)
        teams_metadata_df = teams_metadata_df.copy()
        teams_metadata_df['team_id_master'] = teams_metadata_df['team_id_master'].astype(str)

        # Determine which metadata columns to merge (skip if already present in rankings_df)
        # NOTE: Never merge age_group from metadata - always derive from actual 'age' field
        # to ensure rankings match the age group of games played, not team registration
        merge_cols = ['team_id_master']
        if 'state_code' not in rankings_df.columns and 'state_code' in teams_metadata_df.columns:
            merge_cols.append('state_code')

        if len(merge_cols) > 1:  # More than just team_id_master
            rankings_df = rankings_df.merge(
                teams_metadata_df[merge_cols],
                left_on='team_id',
                right_on='team_id_master',
                how='left'
            )
            # Drop duplicate column if it exists
            if 'team_id_master' in rankings_df.columns and 'team_id' in rankings_df.columns:
                rankings_df = rankings_df.drop(columns=['team_id_master'])

    # ALWAYS derive age_group from the actual 'age' field used in ranking calculation
    # This ensures teams are ranked in the age group they actually played in, not their registration
    if 'age' in rankings_df.columns:
        rankings_df['age_group'] = rankings_df['age'].apply(lambda x: f"u{int(float(x))}" if pd.notna(x) and str(x).strip() else None)
        # Create numeric age column for anchor scaling
        rankings_df['age_num'] = rankings_df['age'].astype(int)
    
    # Normalize gender to match database format (Male/Female)
    # CRITICAL: gender is NOT NULL in rankings_full, so ensure it's always populated
    if 'gender' in rankings_df.columns:
        rankings_df['gender'] = (
            rankings_df['gender']
            .astype(str)
            .str.strip()
            .str.title()
            .replace({
                'Male': 'Male',
                'Female': 'Female',
                'Boys': 'Male',
                'Girls': 'Female',
                'Boy': 'Male',
                'Girl': 'Female',
                'Nan': None,  # Handle NaN string
                'None': None,
            })
        )
        # Replace invalid values with None, then fill with a default
        rankings_df['gender'] = rankings_df['gender'].replace(['', 'Nan', 'None', 'Null'], None)
        # If still NULL after normalization, use 'Unknown' as fallback (or skip record)
        # But ideally this shouldn't happen since v53e always provides gender
        if rankings_df['gender'].isna().any():
            logger.warning(f"⚠️ Found {rankings_df['gender'].isna().sum()} teams with NULL gender. Using 'Unknown' as fallback.")
            rankings_df['gender'] = rankings_df['gender'].fillna('Unknown')
    else:
        # If gender column doesn't exist at all, create it (shouldn't happen with v53e)
        logger.warning("⚠️ Gender column missing from teams_df. Creating with 'Unknown' default.")
        rankings_df['gender'] = 'Unknown'
    
    # Map status field (from v53e)
    if 'status' in rankings_df.columns:
        rankings_df['status'] = rankings_df['status'].astype(str)
    else:
        rankings_df['status'] = None
    
    # Map last_game timestamp
    if 'last_game' in rankings_df.columns:
        rankings_df['last_game'] = pd.to_datetime(rankings_df['last_game'], errors='coerce')
    else:
        rankings_df['last_game'] = None
    
    # Map game statistics (these may need to be calculated from games if not present)
    # For now, use what's available in teams_df
    if 'gp' in rankings_df.columns:
        rankings_df['games_played'] = rankings_df['gp'].fillna(0).astype(int)
    elif 'games_played' not in rankings_df.columns:
        rankings_df['games_played'] = 0

    # Map games in last 180 days (used for activity filtering)
    if 'gp_last_180' in rankings_df.columns:
        rankings_df['games_last_180_days'] = rankings_df['gp_last_180'].fillna(0).astype(int)
    elif 'games_last_180_days' not in rankings_df.columns:
        rankings_df['games_last_180_days'] = 0
    
    # Wins/losses/draws may not be in v53e output - will need to calculate from games
    # For now, set defaults
    for col in ['wins', 'losses', 'draws', 'goals_for', 'goals_against']:
        if col not in rankings_df.columns:
            rankings_df[col] = 0
    
    # Calculate win_percentage if we have wins and games_played
    if 'wins' in rankings_df.columns and 'games_played' in rankings_df.columns:
        rankings_df['win_percentage'] = (
            rankings_df.apply(
                lambda row: (row['wins'] / row['games_played'] * 100) 
                if pd.notna(row.get('wins')) and pd.notna(row.get('games_played')) and row['games_played'] > 0 else None,
                axis=1
            )
        )
    else:
        rankings_df['win_percentage'] = None
    
    # Map Offense/Defense metrics (v53E Layers 2-5, 7, 9)
    for col in ['off_raw', 'sad_raw', 'off_shrunk', 'sad_shrunk', 'def_shrunk', 'off_norm', 'def_norm']:
        if col not in rankings_df.columns:
            rankings_df[col] = None
    
    # Map Strength of Schedule (v53E Layer 8)
    if 'sos' in rankings_df.columns:
        rankings_df['sos'] = rankings_df['sos'].astype(float)
        rankings_df['strength_of_schedule'] = rankings_df['sos']  # Alias for backward compatibility
    else:
        rankings_df['sos'] = None
        rankings_df['strength_of_schedule'] = None

    if 'sos_norm' in rankings_df.columns:
        rankings_df['sos_norm'] = rankings_df['sos_norm'].astype(float)
    else:
        rankings_df['sos_norm'] = None

    # Map National/State SOS fields (computed in calculator.py Pass 3)
    # sos_raw: post-shrinkage SOS value used for national/state ranking
    if 'sos_raw' in rankings_df.columns:
        rankings_df['sos_raw'] = rankings_df['sos_raw'].astype(float)
    else:
        rankings_df['sos_raw'] = None

    # sos_norm_national: percentile rank across all states in cohort (age, gender)
    if 'sos_norm_national' in rankings_df.columns:
        rankings_df['sos_norm_national'] = rankings_df['sos_norm_national'].astype(float)
    else:
        rankings_df['sos_norm_national'] = None

    # sos_norm_state: percentile rank within state for cohort (age, gender, state)
    if 'sos_norm_state' in rankings_df.columns:
        rankings_df['sos_norm_state'] = rankings_df['sos_norm_state'].astype(float)
    else:
        rankings_df['sos_norm_state'] = None

    # sos_rank_national: descending rank across all states in cohort
    # Preserve NULL values (don't convert to 0, as 0 is not a valid rank)
    if 'sos_rank_national' in rankings_df.columns:
        # Use nullable Int64 type to preserve NULL values
        rankings_df['sos_rank_national'] = pd.to_numeric(rankings_df['sos_rank_national'], errors='coerce').astype('Int64')
    else:
        rankings_df['sos_rank_national'] = None

    # sos_rank_state: descending rank within state for cohort
    # Preserve NULL values (don't convert to 0, as 0 is not a valid rank)
    if 'sos_rank_state' in rankings_df.columns:
        # Use nullable Int64 type to preserve NULL values
        rankings_df['sos_rank_state'] = pd.to_numeric(rankings_df['sos_rank_state'], errors='coerce').astype('Int64')
    else:
        rankings_df['sos_rank_state'] = None

    # sample_flag: LOW_SAMPLE or OK based on games played threshold
    if 'sample_flag' in rankings_df.columns:
        rankings_df['sample_flag'] = rankings_df['sample_flag'].astype(str)
    else:
        rankings_df['sample_flag'] = None
    
    # Map Power Score layers (v53E Layer 10)
    for col in ['power_presos', 'anchor', 'abs_strength', 'powerscore_core', 'provisional_mult', 'powerscore_adj']:
        if col not in rankings_df.columns:
            rankings_df[col] = None
        else:
            rankings_df[col] = rankings_df[col].astype(float)
    
    # Map Performance metrics (v53E Layer 6)
    for col in ['perf_raw', 'perf_centered']:
        if col not in rankings_df.columns:
            rankings_df[col] = None
        else:
            rankings_df[col] = rankings_df[col].astype(float)
    
    # Map ML Layer fields (Layer 13)
    for col in ['ml_overperf', 'ml_norm', 'powerscore_ml']:
        if col not in rankings_df.columns:
            rankings_df[col] = None
        else:
            rankings_df[col] = rankings_df[col].astype(float)
    
    if 'rank_in_cohort_ml' in rankings_df.columns:
        rankings_df['rank_in_cohort_ml'] = rankings_df['rank_in_cohort_ml'].fillna(0).astype(int)
    else:
        rankings_df['rank_in_cohort_ml'] = None
    
    # Map Ranking fields
    if 'rank_in_cohort' in rankings_df.columns:
        rankings_df['rank_in_cohort'] = rankings_df['rank_in_cohort'].fillna(0).astype(int)
    else:
        rankings_df['rank_in_cohort'] = None
    
    # National/state/global ranks will be computed in views, but store rank_in_cohort values
    # Set these to None initially - they'll be computed dynamically in views
    rankings_df['national_rank'] = None
    rankings_df['state_rank'] = None
    rankings_df['global_rank'] = None
    
    # Map Rank change tracking (from calculator.py)
    for col in ['rank_change_7d', 'rank_change_30d']:
        if col not in rankings_df.columns:
            rankings_df[col] = None
        else:
            rankings_df[col] = rankings_df[col].fillna(0).astype(int)
    
    # Map Final power scores
    # Determine primary power score: ML > adj > core
    if 'powerscore_ml' in rankings_df.columns and rankings_df['powerscore_ml'].notna().any():
        rankings_df['national_power_score'] = rankings_df['powerscore_ml'].clip(0.0, 1.0)
    elif 'powerscore_adj' in rankings_df.columns:
        rankings_df['national_power_score'] = rankings_df['powerscore_adj'].clip(0.0, 1.0)
    elif 'powerscore_core' in rankings_df.columns:
        rankings_df['national_power_score'] = rankings_df['powerscore_core'].clip(0.0, 1.0)
    else:
        rankings_df['national_power_score'] = 0.0
    
    # Global power score (may not be computed yet)
    if 'global_power_score' not in rankings_df.columns:
        rankings_df['global_power_score'] = None
    
    # Anchor values for age-based power score scaling
    AGE_ANCHORS = {
        10: 0.400, 11: 0.475, 12: 0.550, 13: 0.625,
        14: 0.700, 15: 0.775, 16: 0.850, 17: 0.925,
        18: 1.000, 19: 1.000,
    }

    # Calculate power_score_final with fallback
    # If power_score_final already exists and has non-null values (e.g., from anchor scaling in compute_all_cohorts),
    # preserve it instead of recalculating
    if 'power_score_final' in rankings_df.columns and rankings_df['power_score_final'].notna().any():
        # power_score_final already exists (likely anchor-scaled), preserve it
        logger.info(f"✅ Preserving existing power_score_final (anchor-scaled) - {rankings_df['power_score_final'].notna().sum()} values")
        # Just ensure it's clipped (should already be, but safety check)
        rankings_df['power_score_final'] = rankings_df['power_score_final'].clip(0.0, 1.0)
    else:
        # Calculate power_score_final from fallback sources WITH anchor scaling
        logger.warning("⚠️  power_score_final not found or all null - calculating from fallback sources WITH anchor scaling")

        def calculate_anchor_scaled_power(row):
            # Get base power score
            if pd.notna(row.get('powerscore_ml')):
                base = float(row['powerscore_ml'])
            elif pd.notna(row.get('global_power_score')):
                base = float(row['global_power_score'])
            elif pd.notna(row.get('powerscore_adj')):
                base = float(row['powerscore_adj'])
            elif pd.notna(row.get('national_power_score')):
                base = float(row['national_power_score'])
            else:
                base = 0.5

            # Clip base to [0, 1]
            base = max(0.0, min(1.0, base))

            # Get anchor for this age
            age_num = row.get('age_num', 0)
            if pd.isna(age_num):
                age_num = 0
            age_num = int(age_num)
            anchor = AGE_ANCHORS.get(age_num, 0.70)  # Default to median anchor

            # Apply anchor scaling and clip
            return min(base * anchor, anchor)

        rankings_df['power_score_final'] = rankings_df.apply(calculate_anchor_scaled_power, axis=1)
    
    # Rename team_id to match database column name
    rankings_df = rankings_df.rename(columns={'team_id': 'team_id'})
    # Ensure team_id column exists (it should already be there)
    
    # Select only columns that exist in rankings_full table
    # This ensures we don't include extra columns that might cause issues
    expected_columns = [
        'team_id', 'age_group', 'gender', 'state_code',
        'status', 'last_game', 'last_calculated',
        'games_played', 'games_last_180_days', 'wins', 'losses', 'draws', 'goals_for', 'goals_against', 'win_percentage',
        'off_raw', 'sad_raw', 'off_shrunk', 'sad_shrunk', 'def_shrunk', 'off_norm', 'def_norm',
        'sos', 'sos_norm', 'sos_raw', 'sos_norm_national', 'sos_norm_state', 'sos_rank_national', 'sos_rank_state',
        'sample_flag', 'strength_of_schedule',
        'power_presos', 'anchor', 'abs_strength', 'powerscore_core', 'provisional_mult', 'powerscore_adj',
        'perf_raw', 'perf_centered',
        'ml_overperf', 'ml_norm', 'powerscore_ml', 'rank_in_cohort_ml',
        'rank_in_cohort', 'national_rank', 'state_rank', 'global_rank',
        'rank_change_7d', 'rank_change_30d',
        'rank_change_state_7d', 'rank_change_state_30d',  # State rank changes
        'national_power_score', 'global_power_score', 'power_score_final'
    ]
    
    # Create result DataFrame with all expected columns
    result_df = pd.DataFrame(index=rankings_df.index)
    for col in expected_columns:
        if col in rankings_df.columns:
            result_df[col] = rankings_df[col]
        else:
            result_df[col] = None
    
    logger.info(f"🧾 Prepared {len(result_df):,} records for rankings_full table upload.")
    logger.info(f"   Fields populated: {sum(result_df[col].notna().any() for col in result_df.columns)}/{len(result_df.columns)}")
    
    return result_df

