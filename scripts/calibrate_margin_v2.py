"""
Margin Calibration v2 Script

Refines margin_mult per age and adds global margin_scale factor based on
actual margin errors from backtest results.

Usage:
    python scripts/calibrate_margin_v2.py [--backtest-csv data/backtest_results/raw_backtest.csv]
"""

import os
import sys
import argparse
from pathlib import Path
import json
import logging

import pandas as pd
import numpy as np
from scipy.optimize import minimize

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_margin_error(
    params: np.ndarray,
    raw_df: pd.DataFrame,
    age_groups: list,
    current_margin_mults: dict
) -> float:
    """
    Calculate mean absolute margin error for given parameters.
    
    Args:
        params: [margin_scale, margin_mult_u10, margin_mult_u11, ...]
        raw_df: Backtest DataFrame
        age_groups: List of age group strings
        current_margin_mults: Current margin_mult values per age
    
    Returns:
        Mean absolute error
    """
    margin_scale = params[0]
    margin_mults = dict(zip(age_groups, params[1:]))
    
    errors = []
    
    for age_group in age_groups:
        age_df = raw_df[raw_df['age_group'] == age_group].copy()
        
        if len(age_df) == 0:
            continue
        
        # Get margin multiplier for this age
        margin_mult = margin_mults.get(age_group, current_margin_mults.get(age_group, 1.0))
        
        # Recalculate predicted margin with new parameters
        # Formula: expectedMargin = compositeDiff * MARGIN_COEFFICIENT * marginMultiplier * margin_scale
        MARGIN_COEFFICIENT = 8.0  # From matchPredictor.ts
        
        # Apply age-specific margin_mult and compositeDiff-based scaling
        abs_composite_diff = age_df['composite_diff'].abs()
        
        # Apply compositeDiff-based scaling (from matchPredictor.ts logic)
        composite_scaling = np.ones(len(age_df))
        mask_large = abs_composite_diff > 0.12
        mask_medium = (abs_composite_diff > 0.08) & (abs_composite_diff <= 0.12)
        
        composite_scaling[mask_large] = 2.5
        composite_scaling[mask_medium] = 1.0 + 1.5 * ((abs_composite_diff[mask_medium] - 0.08) / (0.12 - 0.08))
        
        # Calculate predicted margin
        predicted_margin = (
            age_df['composite_diff'].values *
            MARGIN_COEFFICIENT *
            margin_mult *
            composite_scaling *
            margin_scale
        )
        
        # Calculate error
        actual_margin = age_df['actual_margin'].values
        error = np.abs(predicted_margin - actual_margin)
        errors.extend(error.tolist())
    
    if not errors:
        return float('inf')
    
    return np.mean(errors)


def optimize_margin_parameters(raw_df: pd.DataFrame) -> dict:
    """
    Optimize margin_scale and per-age margin_mult values.
    
    Returns dict with optimal parameters and metrics.
    """
    # Get unique age groups
    age_groups = sorted(raw_df['age_group'].dropna().unique().tolist())
    logger.info(f"Optimizing for {len(age_groups)} age groups: {age_groups}")
    
    # Load current margin_mult values from age_group_parameters.json
    current_margin_mults = {}
    age_params_path = Path('data/calibration/age_group_parameters.json')
    if age_params_path.exists():
        with open(age_params_path, 'r') as f:
            age_params = json.load(f)
            for age_group in age_groups:
                if age_group in age_params:
                    current_margin_mults[age_group] = age_params[age_group].get('margin_mult', 1.0)
                else:
                    current_margin_mults[age_group] = 1.0
    else:
        current_margin_mults = {age: 1.0 for age in age_groups}
    
    logger.info(f"Current margin_mult values: {current_margin_mults}")
    
    # Initial parameters: [margin_scale, margin_mult_u10, margin_mult_u11, ...]
    initial_params = [1.0] + [current_margin_mults.get(age, 1.0) for age in age_groups]
    
    # Bounds: margin_scale [0.5, 1.5], margin_mult [0.5, 2.5] per age
    bounds = [(0.5, 1.5)] + [(0.5, 2.5) for _ in age_groups]
    
    logger.info("Optimizing margin parameters...")
    
    result = minimize(
        lambda p: calculate_margin_error(p, raw_df, age_groups, current_margin_mults),
        initial_params,
        method='L-BFGS-B',
        bounds=bounds,
        options={'maxiter': 100}
    )
    
    optimal_margin_scale = result.x[0]
    optimal_margin_mults = dict(zip(age_groups, result.x[1:]))
    
    # Calculate MAE for optimal parameters
    optimal_mae = result.fun
    
    # Calculate MAE for current parameters (baseline)
    baseline_params = [1.0] + [current_margin_mults.get(age, 1.0) for age in age_groups]
    baseline_mae = calculate_margin_error(baseline_params, raw_df, age_groups, current_margin_mults)
    
    logger.info(f"Optimal margin_scale: {optimal_margin_scale:.3f}")
    logger.info(f"Optimal MAE: {optimal_mae:.3f} (baseline: {baseline_mae:.3f})")
    logger.info(f"Improvement: {baseline_mae - optimal_mae:.3f} goals")
    
    # Calculate per-age metrics
    age_metrics = {}
    for age_group in age_groups:
        age_df = raw_df[raw_df['age_group'] == age_group].copy()
        
        if len(age_df) == 0:
            continue
        
        margin_mult = optimal_margin_mults[age_group]
        
        # Recalculate predicted margin
        MARGIN_COEFFICIENT = 8.0
        abs_composite_diff = age_df['composite_diff'].abs()
        
        composite_scaling = np.ones(len(age_df))
        mask_large = abs_composite_diff > 0.12
        mask_medium = (abs_composite_diff > 0.08) & (abs_composite_diff <= 0.12)
        
        composite_scaling[mask_large] = 2.5
        composite_scaling[mask_medium] = 1.0 + 1.5 * ((abs_composite_diff[mask_medium] - 0.08) / (0.12 - 0.08))
        
        predicted_margin = (
            age_df['composite_diff'].values *
            MARGIN_COEFFICIENT *
            margin_mult *
            composite_scaling *
            optimal_margin_scale
        )
        
        actual_margin = age_df['actual_margin'].values
        errors = np.abs(predicted_margin - actual_margin)
        
        # Blowout analysis (>4 goal margin)
        blowout_mask = np.abs(actual_margin) > 4
        blowout_errors = errors[blowout_mask] if blowout_mask.any() else np.array([])
        
        age_metrics[age_group] = {
            'margin_mult': float(margin_mult),
            'mae': float(np.mean(errors)),
            'rmse': float(np.sqrt(np.mean(errors ** 2))),
            'blowout_mae': float(np.mean(blowout_errors)) if len(blowout_errors) > 0 else None,
            'blowout_count': int(blowout_mask.sum()),
            'games': int(len(age_df))
        }
    
    return {
        'margin_scale': float(optimal_margin_scale),
        'age_groups': age_metrics,
        'overall_mae': float(optimal_mae),
        'baseline_mae': float(baseline_mae),
        'improvement': float(baseline_mae - optimal_mae)
    }


def main():
    parser = argparse.ArgumentParser(description='Calibrate margin parameters v2')
    parser.add_argument(
        '--backtest-csv',
        type=str,
        default='data/backtest_results/raw_backtest.csv',
        help='Path to raw_backtest.csv file'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/calibration/margin_parameters_v2.json',
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
    required_cols = ['composite_diff', 'actual_margin', 'age_group']
    missing_cols = [col for col in required_cols if col not in raw_df.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        return
    
    # Optimize parameters
    results = optimize_margin_parameters(raw_df)
    
    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    logger.info(f"Saved margin parameters v2 to {output_path}")
    logger.info(f"Optimal margin_scale: {results['margin_scale']:.3f}")
    logger.info(f"Overall MAE: {results['overall_mae']:.3f} (improvement: {results['improvement']:.3f})")


if __name__ == '__main__':
    main()



















