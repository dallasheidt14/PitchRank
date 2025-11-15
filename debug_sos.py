#!/usr/bin/env python3
"""
Debug script to check SOS calculation logic
"""
import pandas as pd
import numpy as np

# Simulate the issue: What happens when opponents aren't in strength_map?

print("=" * 60)
print("DEBUGGING SOS CALCULATION")
print("=" * 60)

# Scenario: 5 teams (A, B, C, D, E)
# Teams A, B, C have games and are being ranked
# Teams D, E are opponents but don't have enough games to be ranked

# Create strength_map (only includes teams being ranked)
strength_map = {
    "team_A": 0.6,
    "team_B": 0.5,
    "team_C": 0.4,
    # Note: team_D and team_E are NOT in strength_map
}

# Games data
games = [
    {"team_id": "team_A", "opp_id": "team_B", "w_sos": 1.0},
    {"team_id": "team_A", "opp_id": "team_C", "w_sos": 1.0},

    {"team_id": "team_B", "opp_id": "team_D", "w_sos": 1.0},  # D not in strength_map!
    {"team_id": "team_B", "opp_id": "team_E", "w_sos": 1.0},  # E not in strength_map!

    {"team_id": "team_C", "opp_id": "team_D", "w_sos": 1.0},  # D not in strength_map!
    {"team_id": "team_C", "opp_id": "team_E", "w_sos": 1.0},  # E not in strength_map!
]

g_sos = pd.DataFrame(games)

UNRANKED_SOS_BASE = 0.35

# This is what the code does (line 477):
g_sos["opp_strength"] = g_sos["opp_id"].map(lambda o: strength_map.get(o, UNRANKED_SOS_BASE))

print("\nGames with opponent strengths:")
print(g_sos)

# Calculate SOS for each team
def _avg_weighted(df: pd.DataFrame, col: str, wcol: str) -> float:
    w = df[wcol].values
    s = w.sum()
    if s <= 0:
        return 0.5
    return float(np.average(df[col].values, weights=w))

direct = (
    g_sos.groupby("team_id").apply(lambda d: _avg_weighted(d, "opp_strength", "w_sos"))
    .rename("sos_direct").reset_index()
)

print("\n" + "=" * 60)
print("CALCULATED SOS VALUES:")
print("=" * 60)
print(direct)
print()
print("Team A played B (0.5) and C (0.4) → SOS = (0.5 + 0.4) / 2 = 0.45")
print("Team B played D (0.35) and E (0.35) → SOS = (0.35 + 0.35) / 2 = 0.35")
print("Team C played D (0.35) and E (0.35) → SOS = (0.35 + 0.35) / 2 = 0.35")
print()
print("⚠️  PROBLEM: Teams B and C have IDENTICAL SOS (0.35)")
print("    because their opponents (D and E) aren't in strength_map!")
print()
print("If many teams play against opponents that aren't being ranked,")
print("they will all get the same default SOS value!")
print("=" * 60)
