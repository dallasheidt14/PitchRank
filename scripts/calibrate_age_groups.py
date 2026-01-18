"""
Age-Specific Margin + Goals Calibration Script

Computes per-age metrics from historical game data and generates
calibration parameters for the match predictor.

Usage:
    python scripts/calibrate_age_groups.py [--lookback-days 365]

Output:
    data/calibration/age_group_parameters.json
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging

import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from supabase import create_client, Client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def fetch_games_by_age_group(
    supabase: Client,
    lookback_days: int = 365
) -> pd.DataFrame:
    """
    Fetch historical games grouped by age_group
    
    Returns DataFrame with games and age_group information
    """
    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    logger.info(f"Fetching games from {cutoff_date}...")
    
    # Fetch games with scores
    all_games = []
    batch_size = 1000
    offset = 0
    
    while True:
        try:
            response = (
                supabase.table('games')
                .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
                .not_.is_('home_team_master_id', 'null')
                .not_.is_('away_team_master_id', 'null')
                .not_.is_('home_score', 'null')
                .not_.is_('away_score', 'null')
                .gte('game_date', cutoff_date)
                .order('game_date', desc=False)
                .range(offset, offset + batch_size - 1)
                .execute()
            )
            
            if not response.data:
                break
            
            all_games.extend(response.data)
            offset += batch_size
            
            if len(response.data) < batch_size:
                break
            
            if offset % 10000 == 0:
                logger.info(f"  Fetched {len(all_games):,} games...")
                
        except Exception as e:
            logger.error(f"Error fetching games at offset {offset}: {e}")
            break
    
    games_df = pd.DataFrame(all_games)
    logger.info(f"Fetched {len(games_df):,} games")
    
    # Fetch team age groups
    team_ids = list(set(
        list(games_df['home_team_master_id'].dropna().astype(str)) +
        list(games_df['away_team_master_id'].dropna().astype(str))
    ))
    
    logger.info(f"Fetching age groups for {len(team_ids):,} teams...")
    
    team_age_map = {}
    batch_size = 100
    
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i:i + batch_size]
        
        try:
            response = (
                supabase.table('teams')
                .select('team_id_master, age_group')
                .in_('team_id_master', batch)
                .execute()
            )
            
            if response.data:
                for team in response.data:
                    team_id = str(team['team_id_master'])
                    age_group = team.get('age_group', '')
                    team_age_map[team_id] = age_group
                    
        except Exception as e:
            logger.warning(f"Error fetching team batch {i}: {e}")
            continue
    
    # Add age_group to games (use home team's age_group)
    games_df['home_id_str'] = games_df['home_team_master_id'].astype(str)
    games_df['age_group'] = games_df['home_id_str'].map(team_age_map)
    
    # Filter out games without age_group
    games_df = games_df[games_df['age_group'].notna()].copy()
    
    logger.info(f"Games with age_group: {len(games_df):,}")
    
    return games_df


def normalize_age_group(age_group: str) -> str:
    """Normalize age_group to standard format (u10, u11, etc.)"""
    if not age_group:
        return None
    
    age_str = str(age_group).strip().lower()
    
    # Extract number
    import re
    match = re.search(r'\d+', age_str.lstrip('u'))
    if match:
        age_num = int(match.group())
        return f"u{age_num}"
    
    return None


def calculate_age_metrics(games_df: pd.DataFrame) -> dict:
    """
    Calculate per-age metrics from game data
    
    Returns dict mapping age_group -> metrics
    """
    logger.info("Calculating per-age metrics...")
    
    # Normalize age groups
    games_df['age_group_norm'] = games_df['age_group'].apply(normalize_age_group)
    games_df = games_df[games_df['age_group_norm'].notna()].copy()
    
    # Calculate goal margins
    games_df['goal_margin'] = (games_df['home_score'] - games_df['away_score']).abs()
    games_df['total_goals'] = games_df['home_score'] + games_df['away_score']
    
    age_metrics = {}
    
    for age_group, age_df in games_df.groupby('age_group_norm'):
        if len(age_df) < 10:  # Skip age groups with too few games
            continue
        
        # Calculate metrics
        median_goal_margin = age_df['goal_margin'].median()
        variance_margins = age_df['goal_margin'].var()
        blowout_frequency = (age_df['goal_margin'] > 4).sum() / len(age_df)
        
        # Goals per team (home_score and away_score combined, divided by 2)
        mean_goals_per_team = age_df['total_goals'].mean() / 2.0
        variance_goals = age_df[['home_score', 'away_score']].stack().var()
        
        # Calculate recommended parameters
        # margin_multiplier: based on blowout frequency and variance
        # Higher blowout frequency -> higher multiplier needed
        margin_mult = 1.0 + (blowout_frequency * 1.5)  # Scale based on blowout rate
        
        age_metrics[age_group] = {
            'avg_goals': round(mean_goals_per_team, 2),
            'margin_mult': round(margin_mult, 2),
            'blowout_freq': round(blowout_frequency, 3),
            'median_margin': round(median_goal_margin, 2),
            'variance_margins': round(variance_margins, 2),
            'variance_goals': round(variance_goals, 2),
            'games_count': len(age_df),
        }
        
        logger.info(
            f"  {age_group}: {len(age_df)} games, "
            f"avg_goals={mean_goals_per_team:.2f}, "
            f"margin_mult={margin_mult:.2f}, "
            f"blowout_freq={blowout_frequency:.3f}"
        )
    
    return age_metrics


async def main():
    parser = argparse.ArgumentParser(description='Calibrate age group parameters')
    parser.add_argument('--lookback-days', type=int, default=365,
                       help='Number of days to look back (default: 365)')
    
    args = parser.parse_args()
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY')
    
    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")
        sys.exit(1)
    
    try:
        supabase = create_client(supabase_url, supabase_key)
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        sys.exit(1)
    
    # Fetch games
    games_df = await fetch_games_by_age_group(supabase, lookback_days=args.lookback_days)
    
    if games_df.empty:
        logger.error("No games found")
        sys.exit(1)
    
    # Calculate metrics
    age_metrics = calculate_age_metrics(games_df)
    
    # Create output directory
    output_dir = Path('data/calibration')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save JSON
    output_path = output_dir / 'age_group_parameters.json'
    with open(output_path, 'w') as f:
        json.dump(age_metrics, f, indent=2)
    
    logger.info(f"Saved age group parameters to {output_path}")
    logger.info(f"Calibrated {len(age_metrics)} age groups")


if __name__ == '__main__':
    asyncio.run(main())



















