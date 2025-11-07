"""Data adapter to convert between Supabase format and v53e format"""
from __future__ import annotations

import pandas as pd
import re
from typing import Dict, Optional, List
from datetime import datetime, timedelta


def age_group_to_age(age_group: str) -> str:
    """Convert age_group format ('u10', 'u11') to age format ('10', '11')"""
    if not age_group:
        return ''
    
    age_group = str(age_group).strip().lower()
    
    # Remove 'u' prefix if present
    if age_group.startswith('u'):
        age_group = age_group[1:]
    
    # Try to extract number and convert to clean integer string
    match = re.search(r'\d+', age_group)
    if match:
        # Convert to int then back to string to ensure clean integer (e.g., "12.0" -> "12")
        try:
            age_num = int(float(match.group()))
            return str(age_num)
        except (ValueError, TypeError):
            return match.group()
    
    # If already numeric, convert to clean integer string
    try:
        age_num = int(float(age_group))
        return str(age_num)
    except (ValueError, TypeError):
        return age_group


async def fetch_games_for_rankings(
    supabase_client,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    today: Optional[pd.Timestamp] = None
) -> pd.DataFrame:
    """
    Fetch games from Supabase and convert to v53e format
    
    Args:
        supabase_client: Supabase client instance
        lookback_days: Number of days to look back
        provider_filter: Optional provider code filter
        today: Reference date (defaults to today)
    
    Returns:
        DataFrame in v53e format with columns:
        - game_id, date, team_id, opp_id, age, gender, opp_age, opp_gender, gf, ga
    """
    if today is None:
        today = pd.Timestamp.utcnow().normalize()
    
    cutoff = today - pd.Timedelta(days=lookback_days)
    cutoff_iso = cutoff.isoformat()
    
    # Fetch games
    query = supabase_client.table('games').select(
        'id, game_uid, game_date, home_team_master_id, away_team_master_id, '
        'home_score, away_score, provider_id'
    ).gte('game_date', cutoff_iso.strftime('%Y-%m-%d')).limit(1000000)
    
    if provider_filter:
        # Get provider ID
        provider_result = supabase_client.table('providers').select('id').eq(
            'code', provider_filter
        ).single().execute()
        if provider_result.data:
            query = query.eq('provider_id', provider_result.data['id'])
    
    games_result = query.execute()
    games_data = games_result.data if games_result.data else []
    
    if not games_data:
        return pd.DataFrame()
    
    games_df = pd.DataFrame(games_data)
    
    # Fetch teams for age_group and gender
    team_ids = set()
    team_ids.update(games_df['home_team_master_id'].dropna().tolist())
    team_ids.update(games_df['away_team_master_id'].dropna().tolist())
    
    if not team_ids:
        return pd.DataFrame()
    
    # Fetch teams in batches (Supabase has limit)
    teams_data = []
    team_ids_list = list(team_ids)
    batch_size = 1000
    
    for i in range(0, len(team_ids_list), batch_size):
        batch = team_ids_list[i:i + batch_size]
        teams_result = supabase_client.table('teams').select(
            'team_id_master, age_group, gender'
        ).in_('team_id_master', batch).execute()
        
        if teams_result.data:
            teams_data.extend(teams_result.data)
    
    if not teams_data:
        return pd.DataFrame()
    
    teams_df = pd.DataFrame(teams_data)
    teams_df['age'] = teams_df['age_group'].apply(age_group_to_age)
    # Normalize gender values
    teams_df["gender"] = teams_df["gender"].astype(str).str.lower().str.strip()
    
    # Create team lookup dicts
    team_age_map = dict(zip(teams_df['team_id_master'], teams_df['age']))
    team_gender_map = dict(zip(teams_df['team_id_master'], teams_df['gender']))
    
    # Convert to v53e format (perspective-based: each game appears twice)
    v53e_rows = []
    
    for _, game in games_df.iterrows():
        game_id = str(game.get('game_uid') or game.get('id', ''))
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
            'date': game_date,
            'team_id': str(home_team_id),
            'opp_id': str(away_team_id),
            'age': home_age,
            'gender': home_gender,
            'opp_age': away_age,
            'opp_gender': away_gender,
            'gf': int(home_score) if pd.notna(home_score) else None,
            'ga': int(away_score) if pd.notna(away_score) else None,
        })
        
        # Away perspective
        v53e_rows.append({
            'game_id': game_id,
            'date': game_date,
            'team_id': str(away_team_id),
            'opp_id': str(home_team_id),
            'age': away_age,
            'gender': away_gender,
            'opp_age': home_age,
            'opp_gender': home_gender,
            'gf': int(away_score) if pd.notna(away_score) else None,
            'ga': int(home_score) if pd.notna(home_score) else None,
        })
    
    if not v53e_rows:
        return pd.DataFrame()
    
    v53e_df = pd.DataFrame(v53e_rows)
    
    # Filter out rows with missing scores
    v53e_df = v53e_df.dropna(subset=['gf', 'ga'])
    
    # Ensure date is datetime
    v53e_df['date'] = pd.to_datetime(v53e_df['date'])
    
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
    teams_df["gender"] = teams_df["gender"].astype(str).str.lower().str.strip()
    team_age_map = dict(zip(teams_df['team_id_master'], teams_df['age']))
    team_gender_map = dict(zip(teams_df['team_id_master'], teams_df['gender']))
    
    # Convert to v53e format (perspective-based)
    v53e_rows = []
    
    for _, game in games_df.iterrows():
        game_id = str(game.get('game_uid') or game.get('id', ''))
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
            'date': game_date,
            'team_id': str(home_team_id),
            'opp_id': str(away_team_id),
            'age': home_age,
            'gender': home_gender,
            'opp_age': away_age,
            'opp_gender': away_gender,
            'gf': int(home_score) if pd.notna(home_score) else None,
            'ga': int(away_score) if pd.notna(away_score) else None,
        })
        
        # Away perspective
        v53e_rows.append({
            'game_id': game_id,
            'date': game_date,
            'team_id': str(away_team_id),
            'opp_id': str(home_team_id),
            'age': away_age,
            'gender': away_gender,
            'opp_age': home_age,
            'opp_gender': home_gender,
            'gf': int(away_score) if pd.notna(away_score) else None,
            'ga': int(home_score) if pd.notna(home_score) else None,
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
        return pd.DataFrame()
    
    # Map v53e columns to Supabase columns
    rankings_df = teams_df.copy()
    
    # Ensure team_id is UUID string
    rankings_df['team_id'] = rankings_df['team_id'].astype(str)
    
    # Map PowerScore columns
    if 'powerscore_ml' in rankings_df.columns:
        rankings_df['national_power_score'] = rankings_df['powerscore_ml']
    elif 'powerscore_adj' in rankings_df.columns:
        rankings_df['national_power_score'] = rankings_df['powerscore_adj']
    elif 'powerscore_core' in rankings_df.columns:
        rankings_df['national_power_score'] = rankings_df['powerscore_core']
    else:
        rankings_df['national_power_score'] = 0.0
    
    # Map rank
    if 'rank_in_cohort_ml' in rankings_df.columns:
        rankings_df['national_rank'] = rankings_df['rank_in_cohort_ml']
    elif 'rank_in_cohort' in rankings_df.columns:
        rankings_df['national_rank'] = rankings_df['rank_in_cohort']
    else:
        rankings_df['national_rank'] = None
    
    # Keep other columns as needed
    return rankings_df

