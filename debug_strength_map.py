#!/usr/bin/env python3
"""
Debug script to understand what causes identical SOS values
"""
import pandas as pd
import numpy as np

print("=" * 70)
print("INVESTIGATING: Why do many teams get identical SOS values?")
print("=" * 70)

# Simulate the SOS calculation process
UNRANKED_SOS_BASE = 0.35

print("\n" + "=" * 70)
print("POTENTIAL ROOT CAUSE #1: Opponents not in strength_map")
print("=" * 70)

print("\nScenario: strength_map only includes teams with enough games")
print("If opponents aren't in strength_map, they default to 0.35\n")

# Simulate 10 teams
strength_map = {
    "team_1": 0.60,  # Strong team
    "team_2": 0.55,
    "team_3": 0.50,
    "team_4": 0.45,
    "team_5": 0.40,
    # team_6 through team_10 are NOT in strength_map
    # (maybe they don't have enough games, or are from other regions)
}

# Games played by team_1
games_team1 = pd.DataFrame([
    {"opp_id": "team_2", "w_sos": 1.0},  # In map: 0.55
    {"opp_id": "team_3", "w_sos": 1.0},  # In map: 0.50
])

# Games played by team_2
games_team2 = pd.DataFrame([
    {"opp_id": "team_6", "w_sos": 1.0},  # NOT in map: defaults to 0.35
    {"opp_id": "team_7", "w_sos": 1.0},  # NOT in map: defaults to 0.35
])

# Games played by team_3
games_team3 = pd.DataFrame([
    {"opp_id": "team_8", "w_sos": 1.0},  # NOT in map: defaults to 0.35
    {"opp_id": "team_9", "w_sos": 1.0},  # NOT in map: defaults to 0.35
])

# Games played by team_4
games_team4 = pd.DataFrame([
    {"opp_id": "team_10", "w_sos": 1.0},  # NOT in map: defaults to 0.35
    {"opp_id": "team_6", "w_sos": 1.0},   # NOT in map: defaults to 0.35
])

def calculate_sos(games_df, strength_map_param):
    """Calculate SOS for a team"""
    games_df = games_df.copy()
    games_df["opp_strength"] = games_df["opp_id"].map(
        lambda o: strength_map_param.get(o, UNRANKED_SOS_BASE)
    )
    w_sum = games_df["w_sos"].sum()
    if w_sum <= 0:
        return 0.5
    return np.average(games_df["opp_strength"], weights=games_df["w_sos"])

sos_1 = calculate_sos(games_team1, strength_map)
sos_2 = calculate_sos(games_team2, strength_map)
sos_3 = calculate_sos(games_team3, strength_map)
sos_4 = calculate_sos(games_team4, strength_map)

print(f"Team 1 played team_2 (0.55) and team_3 (0.50)")
print(f"  → SOS = {sos_1:.4f}")
print()
print(f"Team 2 played team_6 (0.35) and team_7 (0.35)")
print(f"  → SOS = {sos_2:.4f}")
print()
print(f"Team 3 played team_8 (0.35) and team_9 (0.35)")
print(f"  → SOS = {sos_3:.4f}  ← IDENTICAL to Team 2!")
print()
print(f"Team 4 played team_10 (0.35) and team_6 (0.35)")
print(f"  → SOS = {sos_4:.4f}  ← IDENTICAL to Teams 2 & 3!")

print("\n" + "-" * 70)
print("⚠️  ROOT CAUSE IDENTIFIED:")
print("-" * 70)
print("Teams 2, 3, and 4 all have IDENTICAL SOS (0.35) because:")
print("  • All their opponents are missing from strength_map")
print("  • All missing opponents default to the same value (0.35)")
print("  • This creates many teams with identical SOS values!")

print("\n" + "=" * 70)
print("POTENTIAL ROOT CAUSE #2: Limited opponent diversity")
print("=" * 70)

print("\nEven if opponents ARE in strength_map, they might have similar strengths\n")

# Scenario: All teams in a league have similar offense/defense
# So their pre-SOS power scores are similar
similar_strength_map = {
    "team_A": 0.50,
    "team_B": 0.51,
    "team_C": 0.49,
    "team_D": 0.50,
    "team_E": 0.52,
    "team_F": 0.48,
}

games_A = pd.DataFrame([
    {"opp_id": "team_B", "w_sos": 1.0},
    {"opp_id": "team_C", "w_sos": 1.0},
])

games_D = pd.DataFrame([
    {"opp_id": "team_E", "w_sos": 1.0},
    {"opp_id": "team_F", "w_sos": 1.0},
])

sos_A = calculate_sos(games_A, similar_strength_map)
sos_D = calculate_sos(games_D, similar_strength_map)

print(f"Team A played team_B (0.51) and team_C (0.49)")
print(f"  → SOS = {sos_A:.4f}")
print()
print(f"Team D played team_E (0.52) and team_F (0.48)")
print(f"  → SOS = {sos_D:.4f}")
print()
print("Both teams have nearly identical SOS because all opponents")
print("have similar strength values (all around 0.50)")

print("\n" + "=" * 70)
print("SUMMARY OF ROOT CAUSES:")
print("=" * 70)
print("1. Opponents not in strength_map → All default to 0.35")
print("2. Opponents with similar strengths → Similar SOS values")
print("3. Teams with no games → All default to 0.50")
print()
print("After percentile normalization within cohorts, teams with")
print("identical raw SOS values will have identical normalized SOS!")
print("=" * 70)
