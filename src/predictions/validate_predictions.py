"""
Validation Script: Test Match Prediction Accuracy

This script validates prediction accuracy against historical game outcomes.

Metrics measured:
- Direction Accuracy: % of games where we predicted the correct winner
- MAE (Mean Absolute Error): Average error in goal margin prediction
- RMSE: Root mean squared error
- Calibration: Do predicted probabilities match actual outcomes?
- Brier Score: Measure of probability prediction accuracy

Usage:
    python src/predictions/validate_predictions.py

Environment:
    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables
"""

import os
import sys
import asyncio
import math
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import numpy as np
import pandas as pd

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from supabase import create_client, Client


@dataclass
class TeamRanking:
    """Team ranking data at a point in time"""
    team_id: str
    team_name: str
    power_score_final: float
    sos_norm: float
    offense_norm: Optional[float]
    defense_norm: Optional[float]
    win_percentage: Optional[float]
    games_played: int


@dataclass
class GamePrediction:
    """Prediction for a single game"""
    game_id: str
    game_date: str
    team_a_id: str
    team_b_id: str
    team_a_name: str
    team_b_name: str

    # Actual outcome
    actual_score_a: int
    actual_score_b: int
    actual_margin: float  # team_a - team_b
    actual_winner: str  # 'a', 'b', or 'draw'

    # Prediction
    predicted_margin: float
    predicted_win_prob_a: float
    predicted_winner: str  # 'a', 'b', or 'draw'
    prediction_correct: bool

    # Additional context
    power_diff: float
    sos_diff: float


class PredictionValidator:
    """Validates match predictions against historical outcomes"""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def get_current_rankings(self) -> Dict[str, TeamRanking]:
        """Fetch current rankings from rankings_view"""
        print("Fetching current rankings...")

        response = self.supabase.table('rankings_view').select('*').execute()

        rankings = {}
        for row in response.data:
            rankings[row['team_id_master']] = TeamRanking(
                team_id=row['team_id_master'],
                team_name=row['team_name'],
                power_score_final=row['power_score_final'] or 0.5,
                sos_norm=row['sos_norm'] or 0.5,
                offense_norm=row.get('offense_norm'),
                defense_norm=row.get('defense_norm'),
                win_percentage=row.get('win_percentage'),
                games_played=row.get('games_played', 0)
            )

        print(f"Loaded {len(rankings)} team rankings")
        return rankings

    async def get_recent_games(self, days: int = 180, limit: int = 1000) -> pd.DataFrame:
        """Fetch recent games for validation"""
        print(f"Fetching games from last {days} days (limit: {limit})...")

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        response = (
            self.supabase.table('games')
            .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
            .gte('game_date', cutoff_date)
            .not_.is_('home_score', 'null')
            .not_.is_('away_score', 'null')
            .order('game_date', desc=True)
            .limit(limit)
            .execute()
        )

        games_df = pd.DataFrame(response.data)
        print(f"Loaded {len(games_df)} games with valid scores")

        return games_df

    def predict_match(self, team_a: TeamRanking, team_b: TeamRanking) -> Dict:
        """
        Predict match outcome using power score differential

        This is a simple formula-based prediction:
        - Win probability: logistic function of power differential
        - Expected margin: linear scaling of power differential
        """
        # Power score differential
        power_diff = team_a.power_score_final - team_b.power_score_final

        # Win probability using logistic (sigmoid) function
        # Coefficient 5.0 is a tunable parameter
        # Higher = more sensitive to small differences
        # Typical range: 3-8 for sports predictions
        k = 5.0  # sensitivity coefficient
        win_prob_a = 1 / (1 + math.exp(-k * power_diff))

        # Expected goal margin
        # Typical youth soccer: 0.1 power diff ≈ 0.8 goals
        # This coefficient (8.0) is tunable
        margin_coefficient = 8.0
        predicted_margin = power_diff * margin_coefficient

        return {
            'predicted_margin': predicted_margin,
            'win_prob_a': win_prob_a,
            'power_diff': power_diff,
        }

    def validate_games(
        self,
        games_df: pd.DataFrame,
        rankings: Dict[str, TeamRanking]
    ) -> List[GamePrediction]:
        """Validate predictions against actual game outcomes"""

        predictions = []
        skipped = 0

        print(f"\nValidating {len(games_df)} games...")

        for idx, game in games_df.iterrows():
            # Get team rankings
            team_a_id = game['home_team_master_id']
            team_b_id = game['away_team_master_id']

            # Skip if rankings not available
            if team_a_id not in rankings or team_b_id not in rankings:
                skipped += 1
                continue

            team_a = rankings[team_a_id]
            team_b = rankings[team_b_id]

            # Skip if no games played (unranked)
            if team_a.games_played < 3 or team_b.games_played < 3:
                skipped += 1
                continue

            # Actual outcome
            actual_score_a = game['home_score']
            actual_score_b = game['away_score']
            actual_margin = actual_score_a - actual_score_b

            if actual_margin > 0:
                actual_winner = 'a'
            elif actual_margin < 0:
                actual_winner = 'b'
            else:
                actual_winner = 'draw'

            # Predict
            pred = self.predict_match(team_a, team_b)

            # Predicted winner
            if pred['win_prob_a'] > 0.55:  # Add 5% threshold to avoid ties
                predicted_winner = 'a'
            elif pred['win_prob_a'] < 0.45:
                predicted_winner = 'b'
            else:
                predicted_winner = 'draw'

            # Check if correct
            prediction_correct = (predicted_winner == actual_winner)

            predictions.append(GamePrediction(
                game_id=game['id'],
                game_date=game['game_date'],
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                team_a_name=team_a.team_name,
                team_b_name=team_b.team_name,
                actual_score_a=actual_score_a,
                actual_score_b=actual_score_b,
                actual_margin=actual_margin,
                actual_winner=actual_winner,
                predicted_margin=pred['predicted_margin'],
                predicted_win_prob_a=pred['win_prob_a'],
                predicted_winner=predicted_winner,
                prediction_correct=prediction_correct,
                power_diff=pred['power_diff'],
                sos_diff=team_a.sos_norm - team_b.sos_norm,
            ))

        print(f"Validated {len(predictions)} games (skipped {skipped} due to missing rankings)")
        return predictions

    def calculate_metrics(self, predictions: List[GamePrediction]) -> Dict:
        """Calculate accuracy metrics"""

        if not predictions:
            return {
                'error': 'No predictions to validate',
                'total_games': 0
            }

        # Direction accuracy (winner prediction)
        correct = sum(1 for p in predictions if p.prediction_correct)
        total = len(predictions)
        direction_accuracy = correct / total

        # Margin error metrics
        margin_errors = [abs(p.predicted_margin - p.actual_margin) for p in predictions]
        mae = np.mean(margin_errors)
        rmse = np.sqrt(np.mean([e**2 for e in margin_errors]))

        # Brier score (probability accuracy)
        # For each game: (predicted_prob - actual_outcome)^2
        # actual_outcome = 1 if team_a won, 0 if lost
        brier_scores = []
        for p in predictions:
            actual_outcome = 1.0 if p.actual_winner == 'a' else 0.0
            brier_scores.append((p.predicted_win_prob_a - actual_outcome) ** 2)
        brier_score = np.mean(brier_scores)

        # Calibration analysis (bin by predicted probability)
        calibration_bins = self._calculate_calibration(predictions)

        # Breakdown by confidence level
        high_conf = [p for p in predictions if abs(p.predicted_win_prob_a - 0.5) > 0.2]
        low_conf = [p for p in predictions if abs(p.predicted_win_prob_a - 0.5) <= 0.2]

        high_conf_accuracy = (
            sum(1 for p in high_conf if p.prediction_correct) / len(high_conf)
            if high_conf else 0
        )
        low_conf_accuracy = (
            sum(1 for p in low_conf if p.prediction_correct) / len(low_conf)
            if low_conf else 0
        )

        return {
            'total_games': total,
            'direction_accuracy': direction_accuracy,
            'correct_predictions': correct,
            'mae': mae,
            'rmse': rmse,
            'brier_score': brier_score,
            'calibration_bins': calibration_bins,
            'high_confidence_games': len(high_conf),
            'high_confidence_accuracy': high_conf_accuracy,
            'low_confidence_games': len(low_conf),
            'low_confidence_accuracy': low_conf_accuracy,
        }

    def _calculate_calibration(self, predictions: List[GamePrediction]) -> List[Dict]:
        """
        Calibration analysis: Do predicted probabilities match actual outcomes?

        For example, of all games predicted at 70% probability, do we win 70% of them?
        """
        bins = [
            (0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
            (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)
        ]

        calibration = []

        for bin_min, bin_max in bins:
            bin_predictions = [
                p for p in predictions
                if bin_min <= p.predicted_win_prob_a < bin_max
            ]

            if not bin_predictions:
                continue

            # Actual win rate for team_a in this bin
            actual_wins = sum(1 for p in bin_predictions if p.actual_winner == 'a')
            actual_rate = actual_wins / len(bin_predictions)

            # Expected win rate (midpoint of bin)
            expected_rate = (bin_min + bin_max) / 2

            calibration.append({
                'bin': f'{bin_min:.1f}-{bin_max:.1f}',
                'count': len(bin_predictions),
                'predicted_rate': expected_rate,
                'actual_rate': actual_rate,
                'difference': abs(actual_rate - expected_rate),
            })

        return calibration

    def print_report(self, metrics: Dict, predictions: List[GamePrediction]):
        """Print validation report"""

        print("\n" + "="*70)
        print("MATCH PREDICTION VALIDATION REPORT")
        print("="*70)

        if 'error' in metrics:
            print(f"\nERROR: {metrics['error']}")
            return

        print(f"\n📊 OVERALL METRICS (n={metrics['total_games']} games)")
        print("-" * 70)
        print(f"Direction Accuracy:     {metrics['direction_accuracy']:.1%} ({metrics['correct_predictions']}/{metrics['total_games']})")
        print(f"MAE (Goal Margin):      {metrics['mae']:.2f} goals")
        print(f"RMSE (Goal Margin):     {metrics['rmse']:.2f} goals")
        print(f"Brier Score:            {metrics['brier_score']:.3f} (lower is better, <0.20 is good)")

        print(f"\n🎯 BY CONFIDENCE LEVEL")
        print("-" * 70)
        print(f"High Confidence (>70%): {metrics['high_confidence_accuracy']:.1%} accurate (n={metrics['high_confidence_games']})")
        print(f"Low Confidence (50-70%): {metrics['low_confidence_accuracy']:.1%} accurate (n={metrics['low_confidence_games']})")

        print(f"\n📈 CALIBRATION ANALYSIS")
        print("-" * 70)
        print(f"{'Probability Bin':<20} {'Count':<10} {'Predicted':<12} {'Actual':<12} {'Error':<10}")
        print("-" * 70)

        for cal in metrics['calibration_bins']:
            print(
                f"{cal['bin']:<20} "
                f"{cal['count']:<10} "
                f"{cal['predicted_rate']:<12.1%} "
                f"{cal['actual_rate']:<12.1%} "
                f"{cal['difference']:<10.1%}"
            )

        # Sample predictions
        print(f"\n📋 SAMPLE PREDICTIONS")
        print("-" * 70)

        # Show 5 correct and 5 incorrect
        correct_samples = [p for p in predictions if p.prediction_correct][:5]
        incorrect_samples = [p for p in predictions if not p.prediction_correct][:5]

        print("\n✅ CORRECT PREDICTIONS:")
        for p in correct_samples:
            print(f"  {p.team_a_name} vs {p.team_b_name}")
            print(f"    Actual: {p.actual_score_a}-{p.actual_score_b} | Predicted: {p.predicted_win_prob_a:.0%} for {p.team_a_name}")
            print(f"    Power diff: {p.power_diff:+.3f}")

        print("\n❌ INCORRECT PREDICTIONS:")
        for p in incorrect_samples:
            print(f"  {p.team_a_name} vs {p.team_b_name}")
            print(f"    Actual: {p.actual_score_a}-{p.actual_score_b} | Predicted: {p.predicted_win_prob_a:.0%} for {p.team_a_name}")
            print(f"    Power diff: {p.power_diff:+.3f}")

        # Interpretation
        print("\n" + "="*70)
        print("INTERPRETATION")
        print("="*70)

        if metrics['direction_accuracy'] >= 0.70:
            print("✅ EXCELLENT: >70% direction accuracy is very good for sports prediction")
        elif metrics['direction_accuracy'] >= 0.60:
            print("✅ GOOD: 60-70% direction accuracy is solid and useful")
        elif metrics['direction_accuracy'] >= 0.55:
            print("⚠️  FAIR: 55-60% is better than random but could be improved")
        else:
            print("❌ POOR: <55% accuracy suggests predictions need improvement")

        if metrics['brier_score'] < 0.20:
            print("✅ GOOD: Brier score <0.20 indicates well-calibrated probabilities")
        elif metrics['brier_score'] < 0.25:
            print("⚠️  FAIR: Brier score shows room for calibration improvement")
        else:
            print("❌ POOR: Probabilities are poorly calibrated")

        print("\n" + "="*70)


async def main():
    """Main validation script"""

    # Check environment
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY')

    if not url or not key:
        print("ERROR: Missing environment variables")
        print("Required: SUPABASE_URL and SUPABASE_SERVICE_KEY")
        sys.exit(1)

    # Create client
    supabase = create_client(url, key)
    validator = PredictionValidator(supabase)

    # Run validation
    try:
        # Get current rankings
        rankings = await validator.get_current_rankings()

        if not rankings:
            print("ERROR: No rankings found in database")
            sys.exit(1)

        # Get recent games
        games_df = await validator.get_recent_games(days=180, limit=1000)

        if games_df.empty:
            print("ERROR: No games found in database")
            sys.exit(1)

        # Validate
        predictions = validator.validate_games(games_df, rankings)

        if not predictions:
            print("ERROR: Could not validate any games (no matching rankings?)")
            sys.exit(1)

        # Calculate metrics
        metrics = validator.calculate_metrics(predictions)

        # Print report
        validator.print_report(metrics, predictions)

        # Export results (optional)
        export_path = '/tmp/prediction_validation_results.csv'
        predictions_df = pd.DataFrame([
            {
                'game_date': p.game_date,
                'team_a': p.team_a_name,
                'team_b': p.team_b_name,
                'actual_score': f"{p.actual_score_a}-{p.actual_score_b}",
                'predicted_win_prob_a': f"{p.predicted_win_prob_a:.1%}",
                'correct': p.prediction_correct,
                'power_diff': f"{p.power_diff:+.3f}",
            }
            for p in predictions
        ])
        predictions_df.to_csv(export_path, index=False)
        print(f"\n💾 Results exported to: {export_path}")

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
