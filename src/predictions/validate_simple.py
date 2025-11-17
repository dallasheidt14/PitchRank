"""
Simple Validation Script: Test Match Prediction Accuracy

This is a simplified version that avoids complex dependencies.
Reads data directly from CSV exports or uses existing database queries.

Usage:
    python src/predictions/validate_simple.py
"""

import math
import sys
from collections import defaultdict

# Simpler approach: Use CSV exports from Supabase
print("\n" + "="*70)
print("MATCH PREDICTION VALIDATION - SIMPLE VERSION")
print("="*70)

print("\nThis validation script requires CSV exports from your Supabase database.")
print("\nPlease run these queries in Supabase SQL Editor:")
print("\n1. Export recent games:")
print("""
   SELECT
     id, game_date,
     home_team_master_id, away_team_master_id,
     home_score, away_score
   FROM games
   WHERE game_date >= CURRENT_DATE - INTERVAL '180 days'
     AND home_score IS NOT NULL
     AND away_score IS NOT NULL
   ORDER BY game_date DESC
   LIMIT 1000;
""")

print("\n2. Export current rankings:")
print("""
   SELECT
     team_id_master, team_name,
     power_score_final, sos_norm,
     offense_norm, defense_norm,
     win_percentage, games_played
   FROM rankings_view;
""")

print("\n3. Save as:")
print("   - /tmp/validation_games.csv")
print("   - /tmp/validation_rankings.csv")
print("\nThen run this script again.")
print("\n" + "="*70)

# Check if CSVs exist
import os
games_csv = '/tmp/validation_games.csv'
rankings_csv = '/tmp/validation_rankings.csv'

if not os.path.exists(games_csv) or not os.path.exists(rankings_csv):
    print("\n❌ CSV files not found. Please export data from Supabase first.")
    print(f"   Looking for: {games_csv} and {rankings_csv}")
    sys.exit(1)

print("\n✅ CSV files found! Starting validation...")

# Simple CSV reader (no pandas required for basic validation)
import csv

def load_rankings(csv_path):
    """Load rankings from CSV"""
    rankings = {}
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = row['team_id_master']
            rankings[team_id] = {
                'team_name': row['team_name'],
                'power_score_final': float(row['power_score_final'] or 0.5),
                'sos_norm': float(row['sos_norm'] or 0.5),
                'offense_norm': float(row.get('offense_norm') or 0.5) if row.get('offense_norm') else None,
                'defense_norm': float(row.get('defense_norm') or 0.5) if row.get('defense_norm') else None,
                'win_percentage': float(row.get('win_percentage') or 0) if row.get('win_percentage') else None,
                'games_played': int(row.get('games_played') or 0),
            }
    return rankings

def load_games(csv_path):
    """Load games from CSV"""
    games = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['home_score'] and row['away_score']:
                games.append({
                    'id': row['id'],
                    'game_date': row['game_date'],
                    'home_team_master_id': row['home_team_master_id'],
                    'away_team_master_id': row['away_team_master_id'],
                    'home_score': int(row['home_score']),
                    'away_score': int(row['away_score']),
                })
    return games

def predict_match(team_a, team_b):
    """Simple power score-based prediction"""
    power_diff = team_a['power_score_final'] - team_b['power_score_final']

    # Win probability (logistic function)
    k = 5.0  # sensitivity
    win_prob_a = 1 / (1 + math.exp(-k * power_diff))

    # Expected margin
    predicted_margin = power_diff * 8.0

    return {
        'predicted_margin': predicted_margin,
        'win_prob_a': win_prob_a,
        'power_diff': power_diff,
    }

# Load data
print("\nLoading rankings...")
rankings = load_rankings(rankings_csv)
print(f"Loaded {len(rankings)} team rankings")

print("\nLoading games...")
games = load_games(games_csv)
print(f"Loaded {len(games)} games")

# Validate
print("\nValidating predictions...")
predictions = []
skipped = 0

for game in games:
    team_a_id = game['home_team_master_id']
    team_b_id = game['away_team_master_id']

    # Skip if rankings not available
    if team_a_id not in rankings or team_b_id not in rankings:
        skipped += 1
        continue

    team_a = rankings[team_a_id]
    team_b = rankings[team_b_id]

    # Skip if insufficient games
    if team_a['games_played'] < 3 or team_b['games_played'] < 3:
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
    pred = predict_match(team_a, team_b)

    # Predicted winner
    if pred['win_prob_a'] > 0.55:
        predicted_winner = 'a'
    elif pred['win_prob_a'] < 0.45:
        predicted_winner = 'b'
    else:
        predicted_winner = 'draw'

    predictions.append({
        'game_date': game['game_date'],
        'team_a_name': team_a['team_name'],
        'team_b_name': team_b['team_name'],
        'actual_score_a': actual_score_a,
        'actual_score_b': actual_score_b,
        'actual_margin': actual_margin,
        'actual_winner': actual_winner,
        'predicted_margin': pred['predicted_margin'],
        'win_prob_a': pred['win_prob_a'],
        'predicted_winner': predicted_winner,
        'correct': predicted_winner == actual_winner,
        'power_diff': pred['power_diff'],
    })

print(f"Validated {len(predictions)} games (skipped {skipped})")

# Calculate metrics
if not predictions:
    print("\n❌ No predictions to validate!")
    sys.exit(1)

correct = sum(1 for p in predictions if p['correct'])
total = len(predictions)
direction_accuracy = correct / total

margin_errors = [abs(p['predicted_margin'] - p['actual_margin']) for p in predictions]
mae = sum(margin_errors) / len(margin_errors)
rmse = math.sqrt(sum(e**2 for e in margin_errors) / len(margin_errors))

# Brier score
brier_scores = []
for p in predictions:
    actual_outcome = 1.0 if p['actual_winner'] == 'a' else 0.0
    brier_scores.append((p['win_prob_a'] - actual_outcome) ** 2)
brier_score = sum(brier_scores) / len(brier_scores)

# Confidence breakdown
high_conf = [p for p in predictions if abs(p['win_prob_a'] - 0.5) > 0.2]
low_conf = [p for p in predictions if abs(p['win_prob_a'] - 0.5) <= 0.2]

high_conf_accuracy = sum(1 for p in high_conf if p['correct']) / len(high_conf) if high_conf else 0
low_conf_accuracy = sum(1 for p in low_conf if p['correct']) / len(low_conf) if low_conf else 0

# Print report
print("\n" + "="*70)
print("VALIDATION RESULTS")
print("="*70)

print(f"\n📊 OVERALL METRICS (n={total} games)")
print("-" * 70)
print(f"Direction Accuracy:     {direction_accuracy:.1%} ({correct}/{total})")
print(f"MAE (Goal Margin):      {mae:.2f} goals")
print(f"RMSE (Goal Margin):     {rmse:.2f} goals")
print(f"Brier Score:            {brier_score:.3f} (lower is better, <0.20 is good)")

print(f"\n🎯 BY CONFIDENCE LEVEL")
print("-" * 70)
print(f"High Confidence (>70%): {high_conf_accuracy:.1%} accurate (n={len(high_conf)})")
print(f"Low Confidence (50-70%): {low_conf_accuracy:.1%} accurate (n={len(low_conf)})")

# Calibration bins
print(f"\n📈 CALIBRATION ANALYSIS")
print("-" * 70)
print(f"{'Probability Bin':<20} {'Count':<10} {'Predicted':<12} {'Actual':<12} {'Error':<10}")
print("-" * 70)

bins = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5),
        (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]

for bin_min, bin_max in bins:
    bin_preds = [p for p in predictions if bin_min <= p['win_prob_a'] < bin_max]
    if not bin_preds:
        continue

    actual_wins = sum(1 for p in bin_preds if p['actual_winner'] == 'a')
    actual_rate = actual_wins / len(bin_preds)
    expected_rate = (bin_min + bin_max) / 2

    print(
        f"{bin_min:.1f}-{bin_max:.1f}        "
        f"{len(bin_preds):<10} "
        f"{expected_rate:<12.1%} "
        f"{actual_rate:<12.1%} "
        f"{abs(actual_rate - expected_rate):<10.1%}"
    )

# Sample predictions
print(f"\n📋 SAMPLE PREDICTIONS")
print("-" * 70)

correct_samples = [p for p in predictions if p['correct']][:5]
incorrect_samples = [p for p in predictions if not p['correct']][:5]

print("\n✅ CORRECT PREDICTIONS:")
for p in correct_samples:
    print(f"  {p['team_a_name']} vs {p['team_b_name']}")
    print(f"    Actual: {p['actual_score_a']}-{p['actual_score_b']} | Predicted: {p['win_prob_a']:.0%} for {p['team_a_name']}")
    print(f"    Power diff: {p['power_diff']:+.3f}")

print("\n❌ INCORRECT PREDICTIONS:")
for p in incorrect_samples:
    print(f"  {p['team_a_name']} vs {p['team_b_name']}")
    print(f"    Actual: {p['actual_score_a']}-{p['actual_score_b']} | Predicted: {p['win_prob_a']:.0%} for {p['team_a_name']}")
    print(f"    Power diff: {p['power_diff']:+.3f}")

# Interpretation
print("\n" + "="*70)
print("INTERPRETATION")
print("="*70)

if direction_accuracy >= 0.70:
    print("✅ EXCELLENT: >70% direction accuracy is very good for sports prediction")
elif direction_accuracy >= 0.60:
    print("✅ GOOD: 60-70% direction accuracy is solid and useful")
elif direction_accuracy >= 0.55:
    print("⚠️  FAIR: 55-60% is better than random but could be improved")
else:
    print("❌ POOR: <55% accuracy suggests predictions need improvement")

if brier_score < 0.20:
    print("✅ GOOD: Brier score <0.20 indicates well-calibrated probabilities")
elif brier_score < 0.25:
    print("⚠️  FAIR: Brier score shows room for calibration improvement")
else:
    print("❌ POOR: Probabilities are poorly calibrated")

print("\n" + "="*70)
print("\nNext steps:")
print("- If accuracy is >60%, build the explanation engine")
print("- If accuracy is <60%, tune the prediction formula (k and margin coefficients)")
print("- Review incorrect predictions to find patterns")
print("="*70)
