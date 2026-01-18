"""
Historical Backtesting Engine for Match Predictor

Fetches historical games, runs predictions using Python port of matchPredictor.ts,
and generates calibration outputs for analysis.

Usage:
    python scripts/backtest_predictor.py [--lookback-days 365] [--limit 10000] [--test-slice]

Environment:
    Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

import pandas as pd
import numpy as np
from dotenv import load_dotenv
from tqdm import tqdm

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from supabase import create_client, Client
from scripts.predictor_python import (
    TeamRanking, Game as PredictorGame, predict_match
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def fetch_historical_games(
    supabase: Client,
    lookback_days: int = 365,
    limit: Optional[int] = None,
    test_slice: Optional[Tuple[str, str]] = None
) -> pd.DataFrame:
    """
    Fetch historical games from database
    
    Args:
        supabase: Supabase client
        lookback_days: Number of days to look back
        limit: Maximum number of games to fetch (None = all)
        test_slice: Optional tuple (state, age_group) for testing (e.g., ('AZ', 'u12'))
    """
    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    logger.info(f"Fetching historical games from {cutoff_date}...")
    
    # Base query
    query = (
        supabase.table('games')
        .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
        .not_.is_('home_team_master_id', 'null')
        .not_.is_('away_team_master_id', 'null')
        .not_.is_('home_score', 'null')
        .not_.is_('away_score', 'null')
        .gte('game_date', cutoff_date)
        .order('game_date', desc=False)  # Oldest first for consistent processing
    )
    
    # If test slice specified, filter by state and age_group via teams table
    if test_slice:
        state_code, age_group = test_slice
        logger.info(f"Test slice mode: filtering to {state_code} {age_group}")
        # This requires a join - we'll filter after fetching for simplicity
        # In production, could use RPC or more complex query
    
    # Fetch games in batches
    all_games = []
    batch_size = 1000
    offset = 0
    
    while True:
        batch_query = query.range(offset, offset + batch_size - 1)
        
        try:
            response = batch_query.execute()
            if not response.data:
                break
            
            all_games.extend(response.data)
            offset += batch_size
            
            if len(response.data) < batch_size:
                break
            
            if limit and len(all_games) >= limit:
                all_games = all_games[:limit]
                break
            
            if offset % 10000 == 0:
                logger.info(f"  Fetched {len(all_games):,} games...")
                
        except Exception as e:
            logger.error(f"Error fetching games at offset {offset}: {e}")
            break
    
    games_df = pd.DataFrame(all_games)
    logger.info(f"Fetched {len(games_df):,} games total")
    
    # If test slice, filter by joining with teams table
    if test_slice and len(games_df) > 0:
        state_code, age_group = test_slice
        
        # Fetch team IDs matching criteria
        team_ids_query = (
            supabase.table('teams')
            .select('team_id_master')
            .eq('state_code', state_code)
            .ilike('age_group', f'%{age_group}%')
            .execute()
        )
        
        if team_ids_query.data:
            matching_team_ids = {str(t['team_id_master']) for t in team_ids_query.data}
            games_df['home_id_str'] = games_df['home_team_master_id'].astype(str)
            games_df['away_id_str'] = games_df['away_team_master_id'].astype(str)
            
            # Filter games where both teams match criteria
            games_df = games_df[
                games_df['home_id_str'].isin(matching_team_ids) &
                games_df['away_id_str'].isin(matching_team_ids)
            ].copy()
            
            logger.info(f"Filtered to {len(games_df):,} games matching {state_code} {age_group}")
    
    return games_df


async def fetch_rankings(supabase: Client) -> pd.DataFrame:
    """Fetch current team rankings from rankings_full"""
    logger.info("Fetching team rankings...")
    
    try:
        # Fetch from rankings_full (has all fields we need)
        response = (
            supabase.table('rankings_full')
            .select('team_id, power_score_final, sos_norm, off_norm, def_norm, age_group, games_played')
            .limit(50000)
            .execute()
        )
        
        rankings_df = pd.DataFrame(response.data)
        
        # Map column names
        if 'off_norm' in rankings_df.columns:
            rankings_df['offense_norm'] = rankings_df['off_norm']
        if 'def_norm' in rankings_df.columns:
            rankings_df['defense_norm'] = rankings_df['def_norm']
        
        logger.info(f"Fetched rankings for {len(rankings_df):,} teams")
        return rankings_df
        
    except Exception as e:
        logger.error(f"Error fetching rankings: {e}")
        return pd.DataFrame()


async def fetch_team_game_histories(
    supabase: Client,
    team_ids: List[str],
    lookback_days: int = 365
) -> Dict[str, List[PredictorGame]]:
    """
    Fetch game histories for teams (for recent form calculation)
    
    Returns dict mapping team_id -> list of Game objects
    """
    logger.info(f"Fetching game histories for {len(team_ids):,} teams...")
    
    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    team_histories = {}
    batch_size = 100  # Process teams in batches
    
    for i in tqdm(range(0, len(team_ids), batch_size), desc="Fetching histories"):
        batch = team_ids[i:i + batch_size]
        
        # Fetch games for this batch
        try:
            # Build OR conditions for batch
            or_conditions = []
            for team_id in batch:
                or_conditions.append(f'home_team_master_id.eq.{team_id}')
                or_conditions.append(f'away_team_master_id.eq.{team_id}')
            
            # Supabase limits OR conditions, so split into smaller batches
            sub_batch_size = 10
            for sub_i in range(0, len(batch), sub_batch_size):
                sub_batch = batch[sub_i:sub_i + sub_batch_size]
                sub_or = []
                for tid in sub_batch:
                    sub_or.append(f'home_team_master_id.eq.{tid}')
                    sub_or.append(f'away_team_master_id.eq.{tid}')
                
                response = (
                    supabase.table('games')
                    .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
                    .gte('game_date', cutoff_date)
                    .or_(','.join(sub_or))
                    .order('game_date', desc=True)
                    .limit(1000)  # Limit per sub-batch
                    .execute()
                )
                
                if response.data:
                    for game_data in response.data:
                        game = PredictorGame(
                            id=str(game_data['id']),
                            home_team_master_id=str(game_data['home_team_master_id']) if game_data.get('home_team_master_id') else None,
                            away_team_master_id=str(game_data['away_team_master_id']) if game_data.get('away_team_master_id') else None,
                            home_score=game_data.get('home_score'),
                            away_score=game_data.get('away_score'),
                            game_date=game_data['game_date']
                        )
                        
                        # Add to histories for both teams
                        for team_id in [game.home_team_master_id, game.away_team_master_id]:
                            if team_id and team_id in batch:
                                if team_id not in team_histories:
                                    team_histories[team_id] = []
                                team_histories[team_id].append(game)
        
        except Exception as e:
            logger.warning(f"Error fetching history batch {i}: {e}")
            continue
    
    # Sort histories by date (most recent first)
    for team_id in team_histories:
        team_histories[team_id].sort(key=lambda g: g.game_date, reverse=True)
    
    logger.info(f"Fetched histories for {len(team_histories):,} teams")
    return team_histories


def get_team_age_from_rankings(rankings_df: pd.DataFrame, team_id: str) -> Optional[int]:
    """Extract numeric age from age_group string"""
    team_row = rankings_df[rankings_df['team_id'] == team_id]
    if team_row.empty:
        return None
    
    age_group = str(team_row.iloc[0].get('age_group', ''))
    # Extract number from 'u12', '12', etc.
    import re
    match = re.search(r'\d+', age_group.lower().lstrip('u'))
    if match:
        return int(match.group())
    return None


async def run_backtest(
    supabase: Client,
    games_df: pd.DataFrame,
    rankings_df: pd.DataFrame,
    team_histories: Dict[str, List[PredictorGame]],
    output_dir: Path
) -> pd.DataFrame:
    """
    Run backtest predictions on historical games
    
    Returns DataFrame with raw backtest results
    """
    logger.info(f"Running backtest on {len(games_df):,} games...")
    
    # Convert rankings to dict for fast lookup
    rankings_dict = {}
    for _, row in rankings_df.iterrows():
        team_id = str(row['team_id'])
        rankings_dict[team_id] = {
            'power_score_final': row.get('power_score_final'),
            'sos_norm': row.get('sos_norm'),
            'offense_norm': row.get('offense_norm'),
            'defense_norm': row.get('defense_norm'),
            'age': get_team_age_from_rankings(rankings_df, team_id),
            'games_played': row.get('games_played', 0),
        }
    
    results = []
    
    for idx, game_row in tqdm(games_df.iterrows(), total=len(games_df), desc="Predicting"):
        game_id = str(game_row['id'])
        home_id = str(game_row['home_team_master_id'])
        away_id = str(game_row['away_team_master_id'])
        home_score = game_row['home_score']
        away_score = game_row['away_score']
        game_date = game_row['game_date']
        
        # Get team rankings
        home_rank = rankings_dict.get(home_id, {})
        away_rank = rankings_dict.get(away_id, {})
        
        # Create TeamRanking objects
        team_a = TeamRanking(
            team_id_master=home_id,
            power_score_final=home_rank.get('power_score_final'),
            sos_norm=home_rank.get('sos_norm'),
            offense_norm=home_rank.get('offense_norm'),
            defense_norm=home_rank.get('defense_norm'),
            age=home_rank.get('age'),
            games_played=home_rank.get('games_played', 0),
        )
        
        team_b = TeamRanking(
            team_id_master=away_id,
            power_score_final=away_rank.get('power_score_final'),
            sos_norm=away_rank.get('sos_norm'),
            offense_norm=away_rank.get('offense_norm'),
            defense_norm=away_rank.get('defense_norm'),
            age=away_rank.get('age'),
            games_played=away_rank.get('games_played', 0),
        )
        
        # Get game histories for recent form
        all_games_list = []
        if home_id in team_histories:
            all_games_list.extend(team_histories[home_id])
        if away_id in team_histories:
            all_games_list.extend(team_histories[away_id])
        
        # Remove duplicates by game ID
        seen_ids = set()
        unique_games = []
        for g in all_games_list:
            if g.id not in seen_ids:
                seen_ids.add(g.id)
                unique_games.append(g)
        
        # Games are already in PredictorGame format
        predictor_games = unique_games
        
        # Run prediction
        try:
            prediction = predict_match(team_a, team_b, predictor_games)
            
            # Determine actual winner
            if home_score > away_score:
                actual_winner = 'team_a'
            elif away_score > home_score:
                actual_winner = 'team_b'
            else:
                actual_winner = 'draw'
            
            actual_margin = home_score - away_score
            
            # Get age_group from rankings
            age_group = home_rank.get('age') or away_rank.get('age')
            age_group_str = f"u{age_group}" if age_group else "unknown"
            
            # Store result
            results.append({
                'game_id': game_id,
                'game_date': game_date,
                'team_a_id': home_id,
                'team_b_id': away_id,
                'age_group': age_group_str,
                'predicted_winner': prediction.predicted_winner,
                'actual_winner': actual_winner,
                'predicted_win_prob_a': prediction.win_probability_a,
                'predicted_win_prob_b': prediction.win_probability_b,
                'predicted_margin': prediction.expected_margin,
                'actual_margin': actual_margin,
                'composite_diff': prediction.components['compositeDiff'],
                'power_diff': prediction.components['powerDiff'],
                'sos_diff': prediction.components['sosDiff'],
                'form_diff_raw': prediction.components['formDiffRaw'],
                'form_diff_norm': prediction.components['formDiffNorm'],
                'matchup_advantage': prediction.components['matchupAdvantage'],
                'confidence': prediction.confidence,
                'form_a': prediction.form_a,
                'form_b': prediction.form_b,
            })
            
        except Exception as e:
            logger.warning(f"Error predicting game {game_id}: {e}")
            continue
    
    results_df = pd.DataFrame(results)
    logger.info(f"Completed {len(results_df):,} predictions")
    
    # Save raw backtest CSV
    raw_csv_path = output_dir / 'raw_backtest.csv'
    results_df.to_csv(raw_csv_path, index=False)
    logger.info(f"Saved raw backtest results to {raw_csv_path}")
    
    return results_df


def generate_derived_outputs(raw_df: pd.DataFrame, output_dir: Path):
    """Generate derived CSV outputs from raw_backtest.csv"""
    logger.info("Generating derived outputs...")
    
    # 1. Bucket accuracy
    buckets = [
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.65),
        (0.65, 0.70),
        (0.70, 0.75),
        (0.75, 0.80),
        (0.80, 0.90),
        (0.90, 1.00),
    ]
    
    bucket_results = []
    for min_prob, max_prob in buckets:
        # Use max predicted probability for bucket assignment
        bucket_df = raw_df[
            (raw_df[['predicted_win_prob_a', 'predicted_win_prob_b']].max(axis=1) >= min_prob) &
            (raw_df[['predicted_win_prob_a', 'predicted_win_prob_b']].max(axis=1) < max_prob)
        ]
        
        if len(bucket_df) > 0:
            predicted_prob = bucket_df[['predicted_win_prob_a', 'predicted_win_prob_b']].max(axis=1).mean()
            # Check if predicted winner matches actual winner
            correct = (bucket_df['predicted_winner'] == bucket_df['actual_winner']).sum()
            actual_win_rate = correct / len(bucket_df)
            
            bucket_results.append({
                'bucket': f'{int(min_prob*100)}-{int(max_prob*100)}%',
                'games': len(bucket_df),
                'predicted_avg_prob': predicted_prob,
                'actual_win_rate': actual_win_rate,
            })
    
    bucket_df = pd.DataFrame(bucket_results)
    bucket_df.to_csv(output_dir / 'bucket_accuracy.csv', index=False)
    logger.info(f"Saved bucket_accuracy.csv ({len(bucket_df)} buckets)")
    
    # 2. Margin error
    raw_df['margin_error'] = raw_df['predicted_margin'] - raw_df['actual_margin']
    raw_df['abs_margin_error'] = raw_df['margin_error'].abs()
    
    margin_stats = {
        'mean_error': raw_df['margin_error'].mean(),
        'median_error': raw_df['margin_error'].median(),
        'mean_abs_error': raw_df['abs_margin_error'].mean(),
        'median_abs_error': raw_df['abs_margin_error'].median(),
        'rmse': np.sqrt((raw_df['margin_error'] ** 2).mean()),
        'total_games': len(raw_df),
    }
    
    margin_df = pd.DataFrame([margin_stats])
    margin_df.to_csv(output_dir / 'margin_error.csv', index=False)
    logger.info("Saved margin_error.csv")
    
    # 3. Age accuracy
    age_accuracy = raw_df.groupby('age_group').agg({
        'game_id': 'count',
        'predicted_winner': lambda x: (x == raw_df.loc[x.index, 'actual_winner']).sum(),
    }).reset_index()
    age_accuracy.columns = ['age_group', 'games', 'correct']
    age_accuracy['accuracy'] = age_accuracy['correct'] / age_accuracy['games']
    
    age_accuracy.to_csv(output_dir / 'age_accuracy.csv', index=False)
    logger.info(f"Saved age_accuracy.csv ({len(age_accuracy)} age groups)")
    
    # 4. SOS vs accuracy
    raw_df['abs_sos_diff'] = raw_df['sos_diff'].abs()
    raw_df['sos_bucket'] = pd.cut(raw_df['abs_sos_diff'], bins=5, labels=['Very Low', 'Low', 'Medium', 'High', 'Very High'])
    
    sos_accuracy = raw_df.groupby('sos_bucket', observed=True).agg({
        'game_id': 'count',
        'predicted_winner': lambda x: (x == raw_df.loc[x.index, 'actual_winner']).sum(),
    }).reset_index()
    sos_accuracy.columns = ['sos_diff_level', 'games', 'correct']
    sos_accuracy['accuracy'] = sos_accuracy['correct'] / sos_accuracy['games']
    
    sos_accuracy.to_csv(output_dir / 'sos_vs_accuracy.csv', index=False)
    logger.info("Saved sos_vs_accuracy.csv")
    
    # 5. Form vs accuracy
    raw_df['abs_form_diff'] = raw_df['form_diff_raw'].abs()
    raw_df['form_bucket'] = pd.cut(raw_df['abs_form_diff'], bins=5, labels=['Very Low', 'Low', 'Medium', 'High', 'Very High'])
    
    form_accuracy = raw_df.groupby('form_bucket', observed=True).agg({
        'game_id': 'count',
        'predicted_winner': lambda x: (x == raw_df.loc[x.index, 'actual_winner']).sum(),
    }).reset_index()
    form_accuracy.columns = ['form_diff_level', 'games', 'correct']
    form_accuracy['accuracy'] = form_accuracy['correct'] / form_accuracy['games']
    
    form_accuracy.to_csv(output_dir / 'form_vs_accuracy.csv', index=False)
    logger.info("Saved form_vs_accuracy.csv")


def generate_charts(raw_df: pd.DataFrame, output_dir: Path):
    """Generate optional matplotlib charts"""
    try:
        import matplotlib.pyplot as plt
        
        logger.info("Generating charts...")
        
        # 1. Calibration curve
        buckets = np.arange(0.5, 1.0, 0.05)
        predicted_probs = []
        actual_rates = []
        
        for i in range(len(buckets) - 1):
            min_prob = buckets[i]
            max_prob = buckets[i + 1]
            bucket_df = raw_df[
                (raw_df[['predicted_win_prob_a', 'predicted_win_prob_b']].max(axis=1) >= min_prob) &
                (raw_df[['predicted_win_prob_a', 'predicted_win_prob_b']].max(axis=1) < max_prob)
            ]
            
            if len(bucket_df) > 0:
                predicted_probs.append((min_prob + max_prob) / 2)
                correct = (bucket_df['predicted_winner'] == bucket_df['actual_winner']).sum()
                actual_rates.append(correct / len(bucket_df))
        
        plt.figure(figsize=(8, 6))
        plt.plot(predicted_probs, actual_rates, 'o-', label='Actual')
        plt.plot([0.5, 1.0], [0.5, 1.0], 'r--', label='Perfect Calibration')
        plt.xlabel('Predicted Probability')
        plt.ylabel('Actual Win Rate')
        plt.title('Calibration Curve')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(output_dir / 'calibration_curve.png', dpi=150, bbox_inches='tight')
        plt.close()
        logger.info("Saved calibration_curve.png")
        
        # 2. Margin scatter
        plt.figure(figsize=(8, 6))
        plt.scatter(raw_df['predicted_margin'], raw_df['actual_margin'], alpha=0.3, s=10)
        plt.plot([-10, 10], [-10, 10], 'r--', label='Perfect Prediction')
        plt.xlabel('Predicted Margin')
        plt.ylabel('Actual Margin')
        plt.title('Predicted vs Actual Margin')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.savefig(output_dir / 'margin_scatter.png', dpi=150, bbox_inches='tight')
        plt.close()
        logger.info("Saved margin_scatter.png")
        
        # 3. CompositeDiff distribution
        plt.figure(figsize=(8, 6))
        plt.hist(raw_df['composite_diff'], bins=50, edgecolor='black', alpha=0.7)
        plt.xlabel('Composite Differential')
        plt.ylabel('Frequency')
        plt.title('Distribution of Composite Differential')
        plt.grid(True, alpha=0.3)
        plt.savefig(output_dir / 'composite_diff_distribution.png', dpi=150, bbox_inches='tight')
        plt.close()
        logger.info("Saved composite_diff_distribution.png")
        
    except ImportError:
        logger.warning("matplotlib not available, skipping chart generation")
    except Exception as e:
        logger.warning(f"Error generating charts: {e}")


async def main():
    parser = argparse.ArgumentParser(description='Backtest match predictor on historical games')
    parser.add_argument('--lookback-days', type=int, default=365,
                       help='Number of days to look back (default: 365)')
    parser.add_argument('--limit', type=lambda x: None if x.lower() == 'none' else int(x), default=None,
                       help='Maximum number of games to process (default: all, use "None" for no limit)')
    parser.add_argument('--test-slice', nargs=2, metavar=('STATE', 'AGE_GROUP'),
                       help='Test on specific slice, e.g., --test-slice AZ u12')
    parser.add_argument('--no-charts', action='store_true',
                       help='Skip chart generation')
    
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
    
    # Create output directory
    output_dir = Path('data/backtest_results')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Fetch data
    test_slice = tuple(args.test_slice) if args.test_slice else None
    games_df = await fetch_historical_games(
        supabase,
        lookback_days=args.lookback_days,
        limit=args.limit,
        test_slice=test_slice
    )
    
    if games_df.empty:
        logger.error("No games found")
        sys.exit(1)
    
    rankings_df = await fetch_rankings(supabase)
    
    # Get unique team IDs
    team_ids = list(set(
        list(games_df['home_team_master_id'].dropna().astype(str)) +
        list(games_df['away_team_master_id'].dropna().astype(str))
    ))
    
    team_histories = await fetch_team_game_histories(supabase, team_ids, lookback_days=args.lookback_days)
    
    # Run backtest
    raw_df = await run_backtest(supabase, games_df, rankings_df, team_histories, output_dir)
    
    # Generate derived outputs
    generate_derived_outputs(raw_df, output_dir)
    
    # Generate charts
    if not args.no_charts:
        generate_charts(raw_df, output_dir)
    
    logger.info("Backtest complete!")


if __name__ == '__main__':
    asyncio.run(main())

