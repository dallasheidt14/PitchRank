"""
ML Weight Optimization for Match Predictor

Uses historical backtest data to find optimal weights via logistic regression.
Also performs probability calibration using isotonic regression.

Usage:
    python scripts/optimize_predictor_weights.py

Outputs:
    - Optimal weights for powerDiff, sosDiff, formDiff, matchupAdvantage
    - Calibration parameters for probability adjustment
    - Comparison of hand-tuned vs ML-optimized accuracy
"""

import os
import sys
from pathlib import Path
import json
import logging

import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def load_backtest_data(backtest_path: Path) -> pd.DataFrame:
    """Load raw backtest results"""
    raw_csv = backtest_path / 'raw_backtest.csv'
    if not raw_csv.exists():
        raise FileNotFoundError(f"Backtest data not found at {raw_csv}")

    df = pd.read_csv(raw_csv)
    logger.info(f"Loaded {len(df):,} games from backtest data")
    return df


def prepare_features(df: pd.DataFrame) -> tuple:
    """
    Prepare features and target for ML training

    Features: powerDiff, sosDiff, formDiffNorm, matchupAdvantage
    Target: 1 if team_a won, 0 if team_b won (exclude draws for cleaner signal)
    """
    # Filter out draws for training (they add noise)
    df_nodraw = df[df['actual_winner'] != 'draw'].copy()
    logger.info(f"After removing draws: {len(df_nodraw):,} games")

    # Create binary target: 1 if team_a won
    df_nodraw['target'] = (df_nodraw['actual_winner'] == 'team_a').astype(int)

    # Features
    feature_cols = ['power_diff', 'sos_diff', 'form_diff_norm', 'matchup_advantage']

    # Check for missing features
    missing = [col for col in feature_cols if col not in df_nodraw.columns]
    if missing:
        logger.warning(f"Missing columns: {missing}")
        # Try alternative column names
        if 'form_diff_norm' not in df_nodraw.columns and 'form_diff_raw' in df_nodraw.columns:
            # Normalize form_diff_raw using sigmoid
            df_nodraw['form_diff_norm'] = 1 / (1 + np.exp(-df_nodraw['form_diff_raw'] * 0.5)) - 0.5

    # Drop rows with NaN features
    df_clean = df_nodraw.dropna(subset=feature_cols + ['target'])
    logger.info(f"After dropping NaN: {len(df_clean):,} games")

    X = df_clean[feature_cols].values
    y = df_clean['target'].values

    return X, y, feature_cols, df_clean


def train_optimal_weights(X: np.ndarray, y: np.ndarray, feature_names: list) -> dict:
    """
    Train logistic regression to find optimal feature weights

    The coefficients represent the optimal weights for each feature.
    """
    logger.info("Training logistic regression for optimal weights...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Train model
    model = LogisticRegression(
        penalty='l2',
        C=1.0,
        solver='lbfgs',
        max_iter=1000,
        random_state=42
    )
    model.fit(X_train, y_train)

    # Get coefficients
    coefficients = model.coef_[0]
    intercept = model.intercept_[0]

    # Normalize coefficients to sum to 1 (like our current weights)
    abs_coefs = np.abs(coefficients)
    normalized_weights = abs_coefs / abs_coefs.sum()

    # Create weights dict
    weights = {}
    for name, coef, norm_weight in zip(feature_names, coefficients, normalized_weights):
        weights[name] = {
            'raw_coefficient': float(coef),
            'normalized_weight': float(norm_weight),
            'sign': 'positive' if coef > 0 else 'negative'
        }

    # Calculate accuracy
    train_acc = model.score(X_train, y_train)
    test_acc = model.score(X_test, y_test)

    # Cross-validation
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')

    logger.info(f"Train accuracy: {train_acc:.1%}")
    logger.info(f"Test accuracy: {test_acc:.1%}")
    logger.info(f"CV accuracy: {cv_scores.mean():.1%} (+/- {cv_scores.std()*2:.1%})")

    # Compare with hand-tuned weights
    logger.info("\nOptimal weights vs hand-tuned:")
    hand_tuned = {
        'power_diff': 0.58,
        'sos_diff': 0.18,
        'form_diff_norm': 0.20,
        'matchup_advantage': 0.04
    }

    for name in feature_names:
        ht = hand_tuned.get(name, 0)
        ml = weights[name]['normalized_weight']
        logger.info(f"  {name}: hand-tuned={ht:.2f}, ML={ml:.2f}, diff={ml-ht:+.2f}")

    return {
        'weights': weights,
        'intercept': float(intercept),
        'train_accuracy': float(train_acc),
        'test_accuracy': float(test_acc),
        'cv_accuracy': float(cv_scores.mean()),
        'cv_std': float(cv_scores.std()),
        'model': model
    }


def calibrate_probabilities(model, X: np.ndarray, y: np.ndarray) -> dict:
    """
    Calibrate probabilities using isotonic regression

    Returns calibration parameters and improved Brier score.
    """
    logger.info("\nCalibrating probabilities...")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # Get uncalibrated probabilities
    uncal_probs = model.predict_proba(X_test)[:, 1]
    uncal_brier = brier_score_loss(y_test, uncal_probs)

    # Calibrate using isotonic regression
    calibrated_model = CalibratedClassifierCV(
        model, method='isotonic', cv=5
    )
    calibrated_model.fit(X_train, y_train)

    # Get calibrated probabilities
    cal_probs = calibrated_model.predict_proba(X_test)[:, 1]
    cal_brier = brier_score_loss(y_test, cal_probs)

    # Calculate calibration curve
    prob_true, prob_pred = calibration_curve(y_test, cal_probs, n_bins=10)

    logger.info(f"Uncalibrated Brier score: {uncal_brier:.4f}")
    logger.info(f"Calibrated Brier score: {cal_brier:.4f}")
    logger.info(f"Improvement: {(uncal_brier - cal_brier) / uncal_brier * 100:.1f}%")

    # Calculate calibration error per bucket
    calibration_buckets = []
    for i in range(len(prob_true)):
        calibration_buckets.append({
            'predicted_prob': float(prob_pred[i]),
            'actual_rate': float(prob_true[i]),
            'error': float(abs(prob_pred[i] - prob_true[i]))
        })

    return {
        'uncalibrated_brier': float(uncal_brier),
        'calibrated_brier': float(cal_brier),
        'improvement_pct': float((uncal_brier - cal_brier) / uncal_brier * 100),
        'calibration_buckets': calibration_buckets,
        'calibrated_model': calibrated_model
    }


def calculate_optimal_sensitivity(X: np.ndarray, y: np.ndarray, feature_weights: dict) -> float:
    """
    Find optimal sensitivity coefficient for sigmoid function

    The sensitivity controls how quickly probability changes with composite diff.
    """
    logger.info("\nOptimizing sensitivity coefficient...")

    # Calculate composite diff using ML weights
    weights = [feature_weights[f]['raw_coefficient'] for f in
               ['power_diff', 'sos_diff', 'form_diff_norm', 'matchup_advantage']]

    composite_diffs = X @ np.array(weights)

    # Test different sensitivity values
    sensitivities = np.arange(2.0, 10.0, 0.5)
    best_sens = 4.5
    best_brier = float('inf')

    for sens in sensitivities:
        probs = 1 / (1 + np.exp(-sens * composite_diffs))
        brier = brier_score_loss(y, probs)

        if brier < best_brier:
            best_brier = brier
            best_sens = sens

    logger.info(f"Optimal sensitivity: {best_sens} (Brier: {best_brier:.4f})")

    return float(best_sens)


def generate_output(results: dict, output_dir: Path):
    """Generate output files with optimal parameters"""

    output_dir.mkdir(parents=True, exist_ok=True)

    # Create summary for matchPredictor.ts
    weights = results['weights']

    typescript_weights = {
        'POWER_SCORE': weights['power_diff']['normalized_weight'],
        'SOS': weights['sos_diff']['normalized_weight'],
        'RECENT_FORM': weights['form_diff_norm']['normalized_weight'],
        'MATCHUP': weights['matchup_advantage']['normalized_weight'],
    }

    output = {
        'generated_at': pd.Timestamp.now().isoformat(),
        'training_games': results.get('training_games', 0),
        'optimal_weights': typescript_weights,
        'raw_coefficients': {k: v['raw_coefficient'] for k, v in weights.items()},
        'intercept': results['intercept'],
        'optimal_sensitivity': results.get('optimal_sensitivity', 4.5),
        'accuracy': {
            'train': results['train_accuracy'],
            'test': results['test_accuracy'],
            'cv_mean': results['cv_accuracy'],
            'cv_std': results['cv_std']
        },
        'calibration': results.get('calibration', {})
    }

    # Save JSON
    output_path = output_dir / 'ml_optimized_weights.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    logger.info(f"\nSaved ML-optimized weights to {output_path}")

    # Print TypeScript code snippet
    logger.info("\n" + "="*60)
    logger.info("COPY THIS TO matchPredictor.ts:")
    logger.info("="*60)
    logger.info(f"""
// ML-optimized weights (trained on {results.get('training_games', 0):,} games)
// Test accuracy: {results['test_accuracy']:.1%}, CV accuracy: {results['cv_accuracy']:.1%}
const BASE_WEIGHTS = {{
  POWER_SCORE: {typescript_weights['POWER_SCORE']:.4f},
  SOS: {typescript_weights['SOS']:.4f},
  RECENT_FORM: {typescript_weights['RECENT_FORM']:.4f},
  MATCHUP: {typescript_weights['MATCHUP']:.4f},
}};

// Optimal sensitivity coefficient
const DEFAULT_SENSITIVITY = {results.get('optimal_sensitivity', 4.5):.2f};
""")

    return output


def main():
    # Paths
    backtest_dir = Path('data/backtest_results')
    output_dir = Path('frontend/public/data/calibration')

    try:
        # Load data
        df = load_backtest_data(backtest_dir)

        # Prepare features
        X, y, feature_names, df_clean = prepare_features(df)

        # Train optimal weights
        weight_results = train_optimal_weights(X, y, feature_names)
        weight_results['training_games'] = len(df_clean)

        # Calibrate probabilities
        calibration_results = calibrate_probabilities(
            weight_results['model'], X, y
        )
        weight_results['calibration'] = {
            k: v for k, v in calibration_results.items()
            if k != 'calibrated_model'
        }

        # Find optimal sensitivity
        optimal_sens = calculate_optimal_sensitivity(
            X, y, weight_results['weights']
        )
        weight_results['optimal_sensitivity'] = optimal_sens

        # Generate output
        output = generate_output(weight_results, output_dir)

        logger.info("\n" + "="*60)
        logger.info("OPTIMIZATION COMPLETE")
        logger.info("="*60)
        logger.info(f"Training games: {weight_results['training_games']:,}")
        logger.info(f"Test accuracy: {weight_results['test_accuracy']:.1%}")
        logger.info(f"CV accuracy: {weight_results['cv_accuracy']:.1%}")

    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        logger.error("Please run backtest_predictor.py first to generate data")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error during optimization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
