#!/usr/bin/env python3
"""
Debug script to check percentile normalization behavior with identical values
"""
import pandas as pd
import numpy as np

def _percentile_norm(x: pd.Series) -> pd.Series:
    if len(x) == 0:
        return x
    return x.rank(method="average", pct=True).astype(float)

print("=" * 60)
print("TESTING PERCENTILE NORMALIZATION")
print("=" * 60)

# Scenario 1: Many teams have the same SOS value
print("\nScenario 1: Many teams with identical SOS values")
print("-" * 60)
sos_values = pd.Series([0.35, 0.35, 0.35, 0.35, 0.35, 0.45, 0.55, 0.60])
print(f"Raw SOS values:\n{sos_values.tolist()}")
normalized = _percentile_norm(sos_values)
print(f"\nNormalized (percentile):\n{normalized.tolist()}")
print(f"\nResult: 5 teams with SOS=0.35 all get normalized value of {normalized[0]:.4f}")

# Scenario 2: All teams have the same SOS value
print("\n" + "=" * 60)
print("Scenario 2: ALL teams with identical SOS values")
print("-" * 60)
sos_values2 = pd.Series([0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50])
print(f"Raw SOS values:\n{sos_values2.tolist()}")
normalized2 = _percentile_norm(sos_values2)
print(f"\nNormalized (percentile):\n{normalized2.tolist()}")
print(f"\nResult: ALL teams get normalized value of {normalized2[0]:.4f}")

# Scenario 3: Many teams have no games (all get default 0.5)
print("\n" + "=" * 60)
print("Scenario 3: Mix of calculated SOS and default values")
print("-" * 60)
# 20 teams with calculated SOS, 80 teams with default 0.5 (no games)
calculated = [0.35, 0.40, 0.42, 0.45, 0.48, 0.52, 0.55, 0.57, 0.60, 0.65,
              0.30, 0.33, 0.38, 0.43, 0.47, 0.53, 0.58, 0.62, 0.67, 0.70]
defaults = [0.50] * 80  # 80 teams with no games
all_sos = pd.Series(calculated + defaults)
print(f"Total teams: {len(all_sos)}")
print(f"Teams with calculated SOS: {len(calculated)}")
print(f"Teams with default SOS (0.5): {len(defaults)}")

normalized3 = _percentile_norm(all_sos)
print(f"\nSample normalized values:")
print(f"  Team with SOS=0.30: {normalized3[10]:.4f}")
print(f"  Team with SOS=0.40: {normalized3[1]:.4f}")
print(f"  Teams with SOS=0.50 (80 teams): {normalized3[20]:.4f}")
print(f"  Team with SOS=0.60: {normalized3[8]:.4f}")
print(f"  Team with SOS=0.70: {normalized3[19]:.4f}")

# Count how many teams have each normalized value
unique_normalized = normalized3.value_counts().sort_index(ascending=False)
print(f"\nDistribution of normalized values:")
for value, count in unique_normalized.items():
    if count > 1:
        print(f"  {count} teams have normalized SOS = {value:.4f}")

print("\n" + "=" * 60)
print("CONCLUSION:")
print("=" * 60)
print("If many teams have default SOS (0.5) because they played")
print("against unranked opponents or have limited games, they will")
print("ALL get the same normalized SOS value after percentile ranking!")
print("This explains why users see many teams with identical SOS scores.")
print("=" * 60)
