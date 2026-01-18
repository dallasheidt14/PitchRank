"""
Cross-Validation Script for Match Predictor

Performs 5-fold time-split validation to assess stability across months and ages.
Each fold uses sequential monthly windows for training and testing.

Usage:
    python scripts/cross_validate_predictor.py [--lookback-days 365]
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
from scripts.backtest_predictor import (
    fetch_historical_games,
    fetch_rankings,
    fetch_team_game_histories,
    run_backtest,
    generate_derived_outputs
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def split_time_windows(games_df: pd.DataFrame, n_folds: int = 5) -> list:
    """
    Split games into sequential monthly windows for cross-validation.
    
    Returns list of (train_df, test_df) tuples
    """
    games_df = games_df.copy()
    games_df['game_date'] = pd.to_datetime(games_df['game_date'])
    games_df = games_df.sort_values('game_date')
    
    # Calculate date ranges
    min_date = games_df['game_date'].min()
    max_date = games_df['game_date'].max()
    total_days = (max_date - min_date).days
    
    # Each fold uses ~1 month for testing
    days_per_fold = total_days // (n_folds + 1)  # +1 for initial training period
    
    folds = []
    for fold_idx in range(n_folds):
        # Training: from start to (fold_idx + 1) months
        train_end = min_date + timedelta(days=(fold_idx + 1) * days_per_fold)
        
        # Testing: next month after training
        test_start = train_end
        test_end = min(test_start + timedelta(days=days_per_fold), max_date)
        
        train_df = games_df[
            (games_df['game_date'] >= min_date) &
            (games_df['game_date'] < train_end)
        ].copy()
        
        test_df = games_df[
            (games_df['game_date'] >= test_start) &
            (games_df['game_date'] < test_end)
        ].copy()
        
        if len(train_df) > 0 and len(test_df) > 0:
            folds.append({
                'fold': fold_idx + 1,
                'train_start': min_date.strftime('%Y-%m-%d'),
                'train_end': train_end.strftime('%Y-%m-%d'),
                'test_start': test_start.strftime('%Y-%m-%d'),
                'test_end': test_end.strftime('%Y-%m-%d'),
                'train_df': train_df,
                'test_df': test_df
            })
            logger.info(
                f"Fold {fold_idx + 1}: Train {len(train_df):,} games ({min_date.date()} to {train_end.date()}), "
                f"Test {len(test_df):,} games ({test_start.date()} to {test_end.date()})"
            )
    
    return folds


def calculate_fold_metrics(results_df: pd.DataFrame) -> dict:
    """Calculate accuracy and error metrics for a fold"""
    if len(results_df) == 0:
        return {}
    
    # Overall accuracy
    correct = (results_df['predicted_winner'] == results_df['actual_winner']).sum()
    accuracy = correct / len(results_df)
    
    # Margin error
    margin_error = results_df['predicted_margin'] - results_df['actual_margin']
    mae = margin_error.abs().mean()
    rmse = np.sqrt((margin_error ** 2).mean())
    
    # By age group
    by_age = {}
    for age_group, age_df in results_df.groupby('age_group'):
        age_correct = (age_df['predicted_winner'] == age_df['actual_winner']).sum()
        age_accuracy = age_correct / len(age_df)
        age_mae = (age_df['predicted_margin'] - age_df['actual_margin']).abs().mean()
        
        by_age[age_group] = {
            'accuracy': float(age_accuracy),
            'mae': float(age_mae),
            'games': int(len(age_df))
        }
    
    return {
        'accuracy': float(accuracy),
        'mae': float(mae),
        'rmse': float(rmse),
        'games': int(len(results_df)),
        'by_age': by_age
    }


async def run_cross_validation(supabase: Client, lookback_days: int = 365) -> dict:
    """
    Run 5-fold cross-validation.
    
    Returns dict with fold results and stability metrics.
    """
    logger.info("Starting cross-validation...")
    
    # Fetch all historical games
    logger.info(f"Fetching historical games (last {lookback_days} days)...")
    all_games_df = await fetch_historical_games(supabase, lookback_days=lookback_days, limit=None)
    
    if all_games_df.empty:
        logger.error("No games found")
        return {}
    
    logger.info(f"Fetched {len(all_games_df):,} total games")
    
    # Split into folds
    folds = split_time_windows(all_games_df, n_folds=5)
    
    if not folds:
        logger.error("No valid folds created")
        return {}
    
    # Fetch rankings (use current rankings for all folds - point-in-time would be ideal but complex)
    logger.info("Fetching current rankings...")
    rankings_df = await fetch_rankings(supabase)
    
    fold_results = []
    
    for fold_info in folds:
        fold_num = fold_info['fold']
        test_df = fold_info['test_df']
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing Fold {fold_num}/{len(folds)}")
        logger.info(f"{'='*60}")
        
        # Fetch team histories (use all games up to test period)
        train_df = fold_info['train_df']
        team_ids = list(set(
            list(test_df['home_team_master_id'].dropna().astype(str)) +
            list(test_df['away_team_master_id'].dropna().astype(str))
        ))
        
        logger.info(f"Fetching histories for {len(team_ids):,} teams...")
        team_histories = await fetch_team_game_histories(supabase, team_ids, lookback_days=lookback_days)
        
        # Run backtest on test period
        output_dir = Path(f'data/backtest_results/cv_fold_{fold_num}')
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Running backtest on {len(test_df):,} test games...")
        results_df = await run_backtest(
            supabase,
            test_df,
            rankings_df,
            team_histories,
            output_dir
        )
        
        # Calculate metrics
        metrics = calculate_fold_metrics(results_df)
        metrics['fold'] = fold_num
        metrics['test_period'] = {
            'start': fold_info['test_start'],
            'end': fold_info['test_end']
        }
        
        fold_results.append(metrics)
        
        logger.info(f"Fold {fold_num} results:")
        logger.info(f"  Accuracy: {metrics['accuracy']:.3f}")
        logger.info(f"  MAE: {metrics['mae']:.3f}")
        logger.info(f"  Games: {metrics['games']:,}")
    
    # Calculate stability metrics
    accuracies = [r['accuracy'] for r in fold_results]
    maes = [r['mae'] for r in fold_results]
    
    stability = {
        'accuracy_mean': float(np.mean(accuracies)),
        'accuracy_std': float(np.std(accuracies)),
        'accuracy_range': float(max(accuracies) - min(accuracies)),
        'mae_mean': float(np.mean(maes)),
        'mae_std': float(np.std(maes)),
        'mae_range': float(max(maes) - min(maes)),
        'seasonal_drift': abs(accuracies[-1] - accuracies[0]) > 0.05  # >5% change from first to last fold
    }
    
    logger.info(f"\n{'='*60}")
    logger.info("Cross-Validation Summary")
    logger.info(f"{'='*60}")
    logger.info(f"Accuracy: {stability['accuracy_mean']:.3f} ± {stability['accuracy_std']:.3f}")
    logger.info(f"MAE: {stability['mae_mean']:.3f} ± {stability['mae_std']:.3f}")
    logger.info(f"Seasonal drift detected: {stability['seasonal_drift']}")
    
    return {
        'folds': fold_results,
        'stability': stability
    }


async def main():
    parser = argparse.ArgumentParser(description='Cross-validate match predictor')
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=365,
        help='Number of days to look back for games'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/calibration/cross_validation_results.json',
        help='Output JSON file path'
    )
    
    args = parser.parse_args()
    
    # Initialize Supabase client
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables")
        return
    
    supabase = create_client(supabase_url, supabase_key)
    
    # Run cross-validation
    results = await run_cross_validation(supabase, lookback_days=args.lookback_days)
    
    if not results:
        logger.error("Cross-validation failed")
        return
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"\nSaved cross-validation results to {output_path}")


if __name__ == '__main__':
    asyncio.run(main())

