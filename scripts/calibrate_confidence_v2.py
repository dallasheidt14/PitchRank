"""
Confidence Calibration v2 Script

Fits optimal weights for confidence formula using logistic regression on backtest results.
Uses actual prediction correctness as target variable.

Usage:
    python scripts/calibrate_confidence_v2.py [--backtest-csv data/backtest_results/raw_backtest.csv]
"""

import os
import sys
import argparse
from pathlib import Path
import json
import logging
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from dotenv import load_dotenv

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client, Client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_variance(values: np.ndarray) -> float:
    """Calculate variance of an array"""
    if len(values) < 2:
        return 0.0
    return float(np.var(values, ddof=0))


def fetch_team_game_histories(
    supabase: Client,
    team_ids: list,
    lookback_days: int = 365
) -> dict:
    """
    Fetch game histories for teams to calculate variance.
    
    Returns dict mapping team_id -> list of (goals_for, goals_against) tuples
    """
    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    logger.info(f"Fetching game histories for {len(team_ids):,} teams...")
    
    team_histories = {}
    batch_size = 10  # Small batches due to OR query limits
    
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i:i + batch_size]
        
        # Build OR conditions
        or_conditions = []
        for team_id in batch:
            or_conditions.append(f'home_team_master_id.eq.{team_id}')
            or_conditions.append(f'away_team_master_id.eq.{team_id}')
        
        try:
            response = (
                supabase.table('games')
                .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
                .gte('game_date', cutoff_date)
                .or_(','.join(or_conditions))
                .order('game_date', desc=True)
                .limit(1000)
                .execute()
            )
            
            if response.data:
                for game_data in response.data:
                    home_id = str(game_data.get('home_team_master_id', ''))
                    away_id = str(game_data.get('away_team_master_id', ''))
                    home_score = game_data.get('home_score')
                    away_score = game_data.get('away_score')
                    
                    if home_score is None or away_score is None:
                        continue
                    
                    # Add to home team history
                    if home_id in batch:
                        if home_id not in team_histories:
                            team_histories[home_id] = {'goals_for': [], 'goals_against': []}
                        team_histories[home_id]['goals_for'].append(home_score)
                        team_histories[home_id]['goals_against'].append(away_score)
                    
                    # Add to away team history
                    if away_id in batch:
                        if away_id not in team_histories:
                            team_histories[away_id] = {'goals_for': [], 'goals_against': []}
                        team_histories[away_id]['goals_for'].append(away_score)
                        team_histories[away_id]['goals_against'].append(home_score)
        
        except Exception as e:
            logger.warning(f"Error fetching history batch {i}: {e}")
            continue
    
    logger.info(f"Fetched histories for {len(team_histories):,} teams")
    return team_histories


def calculate_team_variance(team_id: str, team_histories: dict) -> float:
    """Calculate combined variance for a team"""
    if team_id not in team_histories:
        return 1.0  # Default high variance
    
    history = team_histories[team_id]
    goals_for = np.array(history['goals_for'])
    goals_against = np.array(history['goals_against'])
    
    if len(goals_for) < 2 or len(goals_against) < 2:
        return 1.0
    
    var_for = calculate_variance(goals_for)
    var_against = calculate_variance(goals_against)
    
    # Combined variance (sum, matching confidenceEngine.ts)
    return var_for + var_against


def fit_confidence_weights(raw_df: pd.DataFrame, supabase: Client) -> dict:
    """
    Fit optimal confidence weights using logistic regression.
    
    Returns dict with fitted weights and metrics.
    """
    logger.info("Preparing features for logistic regression...")
    
    # Get unique team IDs
    team_ids = list(set(
        list(raw_df['team_a_id'].dropna().astype(str)) +
        list(raw_df['team_b_id'].dropna().astype(str))
    ))
    
    # Fetch game histories for variance calculation
    team_histories = fetch_team_game_histories(supabase, team_ids)
    
    # Fetch games_played from rankings (batch to avoid URI length limits)
    logger.info(f"Fetching games_played from rankings for {len(team_ids):,} teams...")
    games_played_map = {}
    batch_size = 50  # Small batches to avoid URI length limits
    
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i:i + batch_size]
        try:
            rankings_response = (
                supabase.table('rankings_full')
                .select('team_id, games_played')
                .in_('team_id', batch)
                .execute()
            )
            
            if rankings_response.data:
                for row in rankings_response.data:
                    games_played_map[str(row['team_id'])] = row.get('games_played', 0)
        except Exception as e:
            logger.warning(f"Error fetching rankings batch {i}: {e}")
            continue
        
        if (i + batch_size) % 500 == 0:
            logger.info(f"  Fetched games_played for {len(games_played_map):,} teams...")
    
    logger.info(f"Fetched games_played for {len(games_played_map):,} teams")
    
    # Prepare features
    features = []
    targets = []
    
    for _, row in raw_df.iterrows():
        # Feature 1: abs_composite_diff
        abs_composite_diff = abs(row['composite_diff'])
        
        # Feature 2: combined_variance
        team_a_id = str(row['team_a_id'])
        team_b_id = str(row['team_b_id'])
        
        variance_a = calculate_team_variance(team_a_id, team_histories)
        variance_b = calculate_team_variance(team_b_id, team_histories)
        combined_variance = np.sqrt(variance_a + variance_b)  # sqrt as in confidenceEngine.ts
        
        # Feature 3: sample_strength
        games_a = games_played_map.get(team_a_id, 0)
        games_b = games_played_map.get(team_b_id, 0)
        min_games = min(games_a, games_b)
        sample_strength = min(1.0, min_games / 30.0)
        
        # Target: actual_correct (1 if prediction correct, 0 otherwise)
        predicted_winner = row['predicted_winner']
        actual_winner = row['actual_winner']
        actual_correct = 1 if predicted_winner == actual_winner else 0
        
        features.append([abs_composite_diff, combined_variance, sample_strength])
        targets.append(actual_correct)
    
    features = np.array(features)
    targets = np.array(targets)
    
    logger.info(f"Prepared {len(features):,} samples for training")
    logger.info(f"Baseline accuracy: {targets.mean():.3f}")
    
    # Fit logistic regression
    logger.info("Fitting logistic regression...")
    model = LogisticRegression(
        fit_intercept=True,
        max_iter=1000,
        random_state=42
    )
    model.fit(features, targets)
    
    # Extract coefficients
    coefficients = model.coef_[0]
    intercept = model.intercept_[0]
    
    logger.info(f"Fitted coefficients:")
    logger.info(f"  abs_composite_diff: {coefficients[0]:.3f}")
    logger.info(f"  combined_variance: {coefficients[1]:.3f}")
    logger.info(f"  sample_strength: {coefficients[2]:.3f}")
    logger.info(f"  intercept: {intercept:.3f}")
    
    # Calculate accuracy improvement
    predictions = model.predict(features)
    fitted_accuracy = (predictions == targets).mean()
    baseline_accuracy = targets.mean()
    improvement = fitted_accuracy - baseline_accuracy
    
    logger.info(f"Fitted model accuracy: {fitted_accuracy:.3f}")
    logger.info(f"Baseline accuracy: {baseline_accuracy:.3f}")
    logger.info(f"Improvement: {improvement:.3f}")
    
    # Normalize coefficients to match current formula structure
    # Current formula: sigmoid(1.6 * |compositeDiff| - 1.0 * variance + 0.6 * sample_strength)
    # We want to preserve the sign structure but scale appropriately
    
    # Normalize to match magnitude of current weights
    current_weights = {'composite_diff': 1.6, 'variance': -1.0, 'sample_strength': 0.6}
    
    # Scale coefficients to similar magnitude (preserve signs)
    scale_composite = abs(coefficients[0]) / abs(current_weights['composite_diff']) if coefficients[0] != 0 else 1.0
    scale_variance = abs(coefficients[1]) / abs(current_weights['variance']) if coefficients[1] != 0 else 1.0
    scale_sample = abs(coefficients[2]) / abs(current_weights['sample_strength']) if coefficients[2] != 0 else 1.0
    
    # Use fitted coefficients directly (they're already optimized)
    normalized_weights = {
        'composite_diff': float(coefficients[0]),
        'variance': float(coefficients[1]),
        'sample_strength': float(coefficients[2])
    }
    
    # Determine optimal thresholds using fitted model probabilities
    probabilities = model.predict_proba(features)[:, 1]
    
    # Find thresholds that maximize separation
    # High: top 33%, Medium: middle 33%, Low: bottom 33%
    sorted_probs = np.sort(probabilities)
    high_threshold = float(np.percentile(sorted_probs, 67))
    medium_threshold = float(np.percentile(sorted_probs, 33))
    
    return {
        'weights': normalized_weights,
        'intercept': float(intercept),
        'thresholds': {
            'high': high_threshold,
            'medium': medium_threshold
        },
        'accuracy_improvement': float(improvement),
        'fitted_accuracy': float(fitted_accuracy),
        'baseline_accuracy': float(baseline_accuracy),
        'current_weights': current_weights
    }


def main():
    parser = argparse.ArgumentParser(description='Calibrate confidence weights v2')
    parser.add_argument(
        '--backtest-csv',
        type=str,
        default='data/backtest_results/raw_backtest.csv',
        help='Path to raw_backtest.csv file'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/calibration/confidence_parameters_v2.json',
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
    
    # Load backtest data
    csv_path = Path(args.backtest_csv)
    if not csv_path.exists():
        logger.error(f"Backtest CSV not found: {csv_path}")
        return
    
    logger.info(f"Loading backtest data from {csv_path}...")
    raw_df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(raw_df):,} games")
    
    # Limit to reasonable sample size for variance calculation (can be slow)
    if len(raw_df) > 10000:
        logger.info(f"Sampling 10,000 games for variance calculation (full dataset: {len(raw_df):,})")
        raw_df = raw_df.sample(n=10000, random_state=42)
    
    # Check required columns
    required_cols = ['composite_diff', 'predicted_winner', 'actual_winner', 'team_a_id', 'team_b_id']
    missing_cols = [col for col in required_cols if col not in raw_df.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        return
    
    # Fit weights
    results = fit_confidence_weights(raw_df, supabase)
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"Saved confidence parameters v2 to {output_path}")
    logger.info(f"Accuracy improvement: {results['accuracy_improvement']:.3f}")


if __name__ == '__main__':
    main()


