#!/usr/bin/env python3
"""
Demonstration of different normalization methods
Shows how each handles identical values
"""
import pandas as pd
import numpy as np

print("=" * 80)
print("NORMALIZATION METHODS COMPARISON")
print("=" * 80)

# Create realistic scenario: U12 Boys division with 20 teams
# Many teams have similar SOS because they play in same league
np.random.seed(42)

teams = {
    'team_id': [f'team_{i:02d}' for i in range(20)],
    # Realistic SOS distribution:
    # - 8 teams have SOS ~0.50 (played average opponents)
    # - 6 teams have SOS ~0.45 (played weaker opponents)
    # - 4 teams have SOS ~0.55 (played stronger opponents)
    # - 2 teams have extreme values
    'sos_raw': [
        0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50,  # 8 teams with 0.50
        0.45, 0.45, 0.45, 0.45, 0.45, 0.45,              # 6 teams with 0.45
        0.55, 0.55, 0.55, 0.55,                          # 4 teams with 0.55
        0.35, 0.65                                       # 2 extremes
    ],
    # Secondary metric for tie-breaking (e.g., win percentage)
    'win_pct': np.random.uniform(0.3, 0.7, 20)
}

df = pd.DataFrame(teams)

print("\nSCENARIO: 20 teams in U12 Boys division")
print("-" * 80)
print("Raw SOS distribution:")
print(df['sos_raw'].value_counts().sort_index())
print()
print("PROBLEM: 8 teams have identical SOS = 0.50")
print("         6 teams have identical SOS = 0.45")
print("         4 teams have identical SOS = 0.55")
print()

# ============================================================================
# Method 1: CURRENT (Percentile)
# ============================================================================
print("=" * 80)
print("METHOD 1: CURRENT PERCENTILE NORMALIZATION")
print("=" * 80)

def percentile_norm(x):
    return x.rank(method="average", pct=True).astype(float)

df['method1_percentile'] = percentile_norm(df['sos_raw'])

print("\nResults:")
for _, row in df.iterrows():
    print(f"  {row['team_id']}: SOS={row['sos_raw']:.2f} → Normalized={row['method1_percentile']:.6f}")

# Count unique values
unique_after = df['method1_percentile'].nunique()
print(f"\n✗ PROBLEM: Only {unique_after} unique normalized values (was 5 unique raw values)")
print(f"  8 teams with SOS=0.50 all get: {df[df['sos_raw']==0.50]['method1_percentile'].iloc[0]:.6f}")
print(f"  6 teams with SOS=0.45 all get: {df[df['sos_raw']==0.45]['method1_percentile'].iloc[0]:.6f}")

# ============================================================================
# Method 2: Min-Max Scaling
# ============================================================================
print("\n" + "=" * 80)
print("METHOD 2: MIN-MAX SCALING (Linear)")
print("=" * 80)

def minmax_norm(x):
    min_val = x.min()
    max_val = x.max()
    if max_val == min_val:
        return pd.Series([0.5] * len(x), index=x.index)
    return (x - min_val) / (max_val - min_val)

df['method2_minmax'] = minmax_norm(df['sos_raw'])

print("\nResults:")
for _, row in df[df['sos_raw'].isin([0.35, 0.45, 0.50, 0.55, 0.65])].head(10).iterrows():
    print(f"  {row['team_id']}: SOS={row['sos_raw']:.2f} → Normalized={row['method2_minmax']:.6f}")

unique_after = df['method2_minmax'].nunique()
print(f"\n✗ PROBLEM: Still only {unique_after} unique normalized values")
print(f"  8 teams with SOS=0.50 all get: {df[df['sos_raw']==0.50]['method2_minmax'].iloc[0]:.6f}")

# ============================================================================
# Method 3: Hash-Based Tie Breaking
# ============================================================================
print("\n" + "=" * 80)
print("METHOD 3: HASH-BASED TIE BREAKING (Deterministic)")
print("=" * 80)

def percentile_with_hash_tiebreak(df, value_col):
    df = df.copy()
    # Add tiny tie-breaker based on team_id hash
    df['tiebreak'] = df['team_id'].apply(lambda x: hash(x) % 10000 / 10000000.0)
    df['combined'] = df[value_col] + df['tiebreak']
    return df['combined'].rank(method="min", pct=True).astype(float)

df['method3_hash'] = percentile_with_hash_tiebreak(df, 'sos_raw')

print("\nResults (showing teams with SOS=0.50):")
subset = df[df['sos_raw'] == 0.50].copy()
for _, row in subset.iterrows():
    print(f"  {row['team_id']}: SOS={row['sos_raw']:.2f} → Normalized={row['method3_hash']:.6f}")

unique_after = df['method3_hash'].nunique()
print(f"\n✓ SOLVED: Now {unique_after} unique normalized values (all teams different!)")
print(f"  But tie-breaking order is based on hash (arbitrary)")

# ============================================================================
# Method 4: Secondary Metric Tie Breaking
# ============================================================================
print("\n" + "=" * 80)
print("METHOD 4: SECONDARY METRIC TIE BREAKING (Win %)")
print("=" * 80)

def percentile_with_secondary(df, primary_col, secondary_col):
    df = df.copy()
    # Combine primary with tiny fraction of secondary
    df['combined'] = df[primary_col] + df[secondary_col] * 0.00001
    return df['combined'].rank(method="min", pct=True).astype(float)

df['method4_secondary'] = percentile_with_secondary(df, 'sos_raw', 'win_pct')

print("\nResults (showing teams with SOS=0.50):")
subset = df[df['sos_raw'] == 0.50].copy().sort_values('win_pct')
for _, row in subset.iterrows():
    print(f"  {row['team_id']}: SOS={row['sos_raw']:.2f}, Win%={row['win_pct']:.3f} → Norm={row['method4_secondary']:.6f}")

unique_after = df['method4_secondary'].nunique()
print(f"\n✓ SOLVED: Now {unique_after} unique normalized values")
print(f"  Tie-breaking uses win% (meaningful!)")

# ============================================================================
# Method 5: Random Jitter
# ============================================================================
print("\n" + "=" * 80)
print("METHOD 5: RANDOM JITTER (Small Noise)")
print("=" * 80)

def percentile_with_jitter(x, noise=0.0001):
    np.random.seed(42)
    jittered = x + np.random.uniform(-noise, noise, len(x))
    return jittered.rank(method="min", pct=True).astype(float)

df['method5_jitter'] = percentile_with_jitter(df['sos_raw'])

print("\nResults (showing teams with SOS=0.50):")
subset = df[df['sos_raw'] == 0.50].copy()
for _, row in subset.iterrows():
    print(f"  {row['team_id']}: SOS={row['sos_raw']:.2f} → Normalized={row['method5_jitter']:.6f}")

unique_after = df['method5_jitter'].nunique()
print(f"\n✓ SOLVED: Now {unique_after} unique normalized values")
print(f"  ⚠ But uses randomness (controversial)")

# ============================================================================
# COMPARISON SUMMARY
# ============================================================================
print("\n" + "=" * 80)
print("SUMMARY: How many teams with SOS=0.50 get DIFFERENT normalized values?")
print("=" * 80)

methods = {
    'Method 1 (Current Percentile)': 'method1_percentile',
    'Method 2 (Min-Max)': 'method2_minmax',
    'Method 3 (Hash Tie-Break)': 'method3_hash',
    'Method 4 (Win% Tie-Break)': 'method4_secondary',
    'Method 5 (Random Jitter)': 'method5_jitter',
}

for name, col in methods.items():
    subset = df[df['sos_raw'] == 0.50]
    unique = subset[col].nunique()
    total = len(subset)
    print(f"{name:35s}: {unique}/{total} unique values")

print("\n" + "=" * 80)
print("RECOMMENDATION")
print("=" * 80)
print("Use METHOD 4 (Secondary Metric Tie-Breaking) because:")
print("  ✓ Breaks ties meaningfully (better team gets better rank)")
print("  ✓ Deterministic (same input = same output)")
print("  ✓ No randomness")
print("  ✓ Easy to explain to users")
print("  ✓ Minimal change to existing system")
print("\nSecondary metrics to consider:")
print("  1. Win percentage (best)")
print("  2. Goal differential")
print("  3. Offensive power (off_norm)")
print("  4. Games played (more games = more reliable)")
print("=" * 80)
