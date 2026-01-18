"""
Run all Calibration v2 scripts after full backtest completes

This script runs all calibration scripts in sequence and copies results to frontend.

Usage:
    python scripts/run_calibration_v2.py [--backtest-csv data/backtest_results/raw_backtest.csv]
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
import time

import pandas as pd

def check_backtest_complete(csv_path: Path, min_rows: int = 10000) -> bool:
    """Check if backtest CSV has enough rows"""
    if not csv_path.exists():
        return False
    
    try:
        # Quick row count without loading full file
        df = pd.read_csv(csv_path, nrows=min_rows + 1)
        return len(df) >= min_rows
    except Exception:
        return False

def wait_for_backtest(csv_path: Path, timeout_minutes: int = 120, check_interval: int = 30):
    """Wait for backtest to complete, checking every check_interval seconds"""
    print(f"Waiting for backtest to complete (checking every {check_interval}s)...")
    print(f"Looking for: {csv_path}")
    print(f"Minimum rows: 10,000")
    
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60
    
    while True:
        if check_backtest_complete(csv_path):
            print(f"✅ Backtest complete! Found {len(pd.read_csv(csv_path)):,} rows")
            return True
        
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            print(f"⏱️  Timeout after {timeout_minutes} minutes")
            return False
        
        print(f"  Waiting... ({int(elapsed/60)}m elapsed)")
        time.sleep(check_interval)

def run_calibration_scripts(csv_path: Path):
    """Run all calibration scripts"""
    scripts = [
        ('scripts/calibrate_probability.py', 'Probability Calibration'),
        ('scripts/calibrate_margin_v2.py', 'Margin Calibration v2'),
        ('scripts/calibrate_confidence_v2.py', 'Confidence Calibration v2'),
    ]
    
    for script_path, name in scripts:
        print(f"\n{'='*60}")
        print(f"Running: {name}")
        print(f"{'='*60}")
        
        try:
            result = subprocess.run(
                [sys.executable, script_path, '--backtest-csv', str(csv_path)],
                check=True,
                capture_output=True,
                text=True
            )
            print(result.stdout)
            if result.stderr:
                print("Warnings:", result.stderr)
        except subprocess.CalledProcessError as e:
            print(f"❌ Error running {name}:")
            print(e.stdout)
            print(e.stderr)
            return False
    
    return True

def copy_to_frontend():
    """Copy calibrated JSONs to frontend public directory"""
    import shutil
    
    files_to_copy = [
        'data/calibration/probability_parameters.json',
        'data/calibration/margin_parameters_v2.json',
        'data/calibration/confidence_parameters_v2.json',
    ]
    
    print(f"\n{'='*60}")
    print("Copying calibrated JSONs to frontend...")
    print(f"{'='*60}")
    
    for src_file in files_to_copy:
        src_path = Path(src_file)
        dst_path = Path(f'frontend/public/{src_file}')
        
        if not src_path.exists():
            print(f"⚠️  Skipping {src_file} (not found)")
            continue
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        print(f"✅ Copied {src_file} → {dst_path}")

def main():
    parser = argparse.ArgumentParser(description='Run calibration v2 scripts after backtest')
    parser.add_argument(
        '--backtest-csv',
        type=str,
        default='data/backtest_results/raw_backtest.csv',
        help='Path to raw_backtest.csv file'
    )
    parser.add_argument(
        '--wait',
        action='store_true',
        help='Wait for backtest to complete before running calibrations'
    )
    parser.add_argument(
        '--skip-copy',
        action='store_true',
        help='Skip copying JSONs to frontend'
    )
    
    args = parser.parse_args()
    
    csv_path = Path(args.backtest_csv)
    
    # Wait for backtest if requested
    if args.wait:
        if not wait_for_backtest(csv_path):
            print("❌ Backtest did not complete in time")
            return
    else:
        # Check if backtest exists and has enough data
        if not check_backtest_complete(csv_path):
            print(f"⚠️  Backtest CSV has fewer than 10,000 rows")
            print(f"   File: {csv_path}")
            if csv_path.exists():
                df = pd.read_csv(csv_path)
                print(f"   Current rows: {len(df):,}")
            print(f"\n   Run with --wait to wait for backtest completion")
            print(f"   Or run backtest manually:")
            print(f"   python scripts/backtest_predictor.py --lookback-days 365 --limit None --no-charts")
            return
    
    # Run calibration scripts
    if not run_calibration_scripts(csv_path):
        print("\n❌ Calibration scripts failed")
        return
    
    # Copy to frontend
    if not args.skip_copy:
        copy_to_frontend()
    
    print(f"\n{'='*60}")
    print("✅ Calibration v2 complete!")
    print(f"{'='*60}")
    print("\nNext step: Run cross-validation")
    print("  python scripts/cross_validate_predictor.py")

if __name__ == '__main__':
    main()



















