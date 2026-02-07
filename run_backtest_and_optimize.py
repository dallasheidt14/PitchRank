"""Run backtest and optimization, then report results"""
import subprocess
import sys
import pandas as pd
import json
from pathlib import Path

print("="*70)
print("STEP 1: Running backtest with draw threshold fix...")
print("="*70)

# Run backtest
result = subprocess.run(
    [sys.executable, 'scripts/backtest_predictor.py', '--limit', '50000'],
    capture_output=True,
    text=True
)

if result.returncode != 0:
    print(f"ERROR: Backtest failed with return code {result.returncode}")
    print("STDERR:", result.stderr[:500])
    sys.exit(1)

print("Backtest completed successfully!")
print("\n" + "="*70)
print("STEP 2: Checking results...")
print("="*70)

# Check results
bucket_df = pd.read_csv('data/backtest_results/bucket_accuracy.csv')
bucket_50_55 = bucket_df[bucket_df['bucket'] == '50-55%']

if len(bucket_50_55) > 0:
    acc = float(bucket_50_55['actual_win_rate'].iloc[0])
    games = int(bucket_50_55['games'].iloc[0])
    print(f"50-55% bucket: {games:,} games, Accuracy: {acc:.1%}")
    print(f"Expected: 55-60% (was 16% before fix)")
    if acc > 0.30:
        print("✅ Fix is working! Accuracy improved significantly!")
    else:
        print("⚠️  Accuracy still low - may need to check fix")

# Check raw data for draws
raw_df = pd.read_csv('data/backtest_results/raw_backtest.csv')
bucket_raw = raw_df[(raw_df['predicted_win_prob_a'] >= 0.50) & 
                     (raw_df['predicted_win_prob_a'] < 0.55)]
draws = (bucket_raw['predicted_winner'] == 'draw').sum()
print(f"\nDraw predictions in 50-55% bucket: {draws} (should be 0)")

print("\n" + "="*70)
print("STEP 3: Running weight optimization...")
print("="*70)

# Run optimization
opt_result = subprocess.run(
    [sys.executable, 'scripts/optimize_predictor_weights.py', 
     '--backtest-csv', 'data/backtest_results/raw_backtest.csv'],
    capture_output=True,
    text=True
)

print(opt_result.stdout)
if opt_result.stderr:
    print("STDERR:", opt_result.stderr)

if opt_result.returncode == 0:
    # Read optimization results
    opt_file = Path('data/calibration/optimal_weights.json')
    if opt_file.exists():
        with open(opt_file) as f:
            opt_data = json.load(f)
        
        print("\n" + "="*70)
        print("OPTIMIZATION RESULTS")
        print("="*70)
        print(f"Current weights:")
        for key, val in opt_data['current_weights'].items():
            print(f"  {key}: {val:.4f}")
        print(f"\nOptimal weights:")
        for key, val in opt_data['weights'].items():
            print(f"  {key}: {val:.4f}")
        print(f"\nAccuracy improvement: {opt_data['accuracy']['improvement']*100:+.2f}%")
        
        if opt_data['accuracy']['improvement'] > 0.001:
            print("\n✅ RECOMMENDATION: Update weights for better accuracy!")
        else:
            print("\n⚠️  Current weights are already near-optimal")
    else:
        print("⚠️  Optimization results file not found")
else:
    print(f"ERROR: Optimization failed with return code {opt_result.returncode}")
    print("STDERR:", opt_result.stderr[:500])

print("\n" + "="*70)
print("COMPLETE")
print("="*70)












