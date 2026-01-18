"""
Probability Calibration Script

Tunes SENSITIVITY constant (currently 4.5) to achieve proper probability calibration.
Uses backtest results to find optimal sigmoid slope where predicted probabilities
match actual win rates.

Usage:
    python scripts/calibrate_probability.py [--backtest-csv data/backtest_results/raw_backtest.csv]
"""

import os
import sys
import argparse
from pathlib import Path
import json
import logging

import pandas as pd
import numpy as np
from scipy.optimize import minimize_scalar

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sigmoid(x: float, sensitivity: float) -> float:
    """Sigmoid function with sensitivity parameter"""
    return 1 / (1 + np.exp(-sensitivity * x))


def calculate_calibration_error(
    sensitivity: float,
    raw_df: pd.DataFrame,
    buckets: list
) -> float:
    """
    Calculate calibration error for a given sensitivity value.
    
    Returns mean absolute difference between predicted and actual win rates.
    """
    # Recalculate win probabilities with new sensitivity
    # We need to recalculate from composite_diff
    if 'composite_diff' not in raw_df.columns:
        logger.error("Missing 'composite_diff' column in backtest data")
        return float('inf')
    
    # Recalculate win probabilities
    win_prob_a_new = sigmoid(raw_df['composite_diff'].values, sensitivity)
    win_prob_b_new = 1 - win_prob_a_new
    
    # Use max probability for bucket assignment
    max_prob = np.maximum(win_prob_a_new, win_prob_b_new)
    
    bucket_errors = []
    for min_prob, max_prob_bound in buckets:
        mask = (max_prob >= min_prob) & (max_prob < max_prob_bound)
        bucket_data = raw_df[mask]
        
        if len(bucket_data) < 10:  # Skip buckets with too few games
            continue
        
        # Predicted probability (average of max probabilities in bucket)
        predicted_prob = max_prob[mask].mean()
        
        # Actual win rate
        predicted_winner = np.where(win_prob_a_new[mask] > win_prob_b_new[mask], 'team_a', 'team_b')
        actual_winner = bucket_data['actual_winner'].values
        correct = (predicted_winner == actual_winner).sum()
        actual_win_rate = correct / len(bucket_data)
        
        # Calibration error for this bucket
        error = abs(predicted_prob - actual_win_rate)
        bucket_errors.append(error)
    
    if not bucket_errors:
        return float('inf')
    
    return np.mean(bucket_errors)


def find_optimal_sensitivity(raw_df: pd.DataFrame) -> dict:
    """
    Find optimal SENSITIVITY value using optimization.
    
    Returns dict with optimal sensitivity and calibration metrics.
    """
    # Define probability buckets
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
    
    logger.info("Finding optimal SENSITIVITY value...")
    
    # Search range: 2.0 to 8.0 (current is 4.5)
    result = minimize_scalar(
        lambda s: calculate_calibration_error(s, raw_df, buckets),
        bounds=(2.0, 8.0),
        method='bounded'
    )
    
    optimal_sensitivity = result.x
    min_error = result.fun
    
    logger.info(f"Optimal SENSITIVITY: {optimal_sensitivity:.3f} (calibration error: {min_error:.4f})")
    
    # Calculate bucket accuracy for optimal sensitivity
    win_prob_a_opt = sigmoid(raw_df['composite_diff'].values, optimal_sensitivity)
    win_prob_b_opt = 1 - win_prob_a_opt
    max_prob_opt = np.maximum(win_prob_a_opt, win_prob_b_opt)
    
    bucket_accuracy = {}
    for min_prob, max_prob_bound in buckets:
        mask = (max_prob_opt >= min_prob) & (max_prob_opt < max_prob_bound)
        bucket_data = raw_df[mask]
        
        if len(bucket_data) < 10:
            continue
        
        bucket_key = f"{int(min_prob*100)}-{int(max_prob_bound*100)}%"
        predicted_prob = max_prob_opt[mask].mean()
        
        predicted_winner = np.where(win_prob_a_opt[mask] > win_prob_b_opt[mask], 'team_a', 'team_b')
        actual_winner = bucket_data['actual_winner'].values
        correct = (predicted_winner == actual_winner).sum()
        actual_win_rate = correct / len(bucket_data)
        
        bucket_accuracy[bucket_key] = {
            'predicted_prob': float(predicted_prob),
            'actual_win_rate': float(actual_win_rate),
            'games': int(len(bucket_data)),
            'calibration_error': float(abs(predicted_prob - actual_win_rate))
        }
    
    return {
        'sensitivity': float(optimal_sensitivity),
        'calibration_error': float(min_error),
        'bucket_accuracy': bucket_accuracy,
        'current_sensitivity': 4.5,
        'improvement': float(abs(calculate_calibration_error(4.5, raw_df, buckets) - min_error))
    }


def main():
    parser = argparse.ArgumentParser(description='Calibrate probability sigmoid slope')
    parser.add_argument(
        '--backtest-csv',
        type=str,
        default='data/backtest_results/raw_backtest.csv',
        help='Path to raw_backtest.csv file'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/calibration/probability_parameters.json',
        help='Output JSON file path'
    )
    
    args = parser.parse_args()
    
    # Load backtest data
    csv_path = Path(args.backtest_csv)
    if not csv_path.exists():
        logger.error(f"Backtest CSV not found: {csv_path}")
        return
    
    logger.info(f"Loading backtest data from {csv_path}...")
    raw_df = pd.read_csv(csv_path)
    logger.info(f"Loaded {len(raw_df):,} games")
    
    # Check required columns
    required_cols = ['composite_diff', 'actual_winner']
    missing_cols = [col for col in required_cols if col not in raw_df.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        return
    
    # Find optimal sensitivity
    results = find_optimal_sensitivity(raw_df)
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"Saved probability parameters to {output_path}")
    logger.info(f"Optimal SENSITIVITY: {results['sensitivity']:.3f} (current: {results['current_sensitivity']:.1f})")
    logger.info(f"Calibration error: {results['calibration_error']:.4f}")


if __name__ == '__main__':
    main()



















