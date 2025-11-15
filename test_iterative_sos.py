#!/usr/bin/env python3
"""
Test the iterative SOS algorithm to see if it's working correctly
"""
import pandas as pd
import numpy as np
from datetime import timedelta

print("=" * 80)
print("ITERATIVE SOS ALGORITHM TEST")
print("=" * 80)

# Simulate the exact scenario from v53e.py
UNRANKED_SOS_BASE = 0.35
SOS_ITERATIONS = 3
SOS_TRANSITIVITY_LAMBDA = 0.15

today = pd.Timestamp("2025-01-15")

# Create test scenario:
# - Teams A, B, C: Small teams (10 games each, all kept)
# - Teams X, Y, Z: Big teams (40 games each, only last 30 kept)
# - A, B, C all played X, Y, Z in games that are outside X/Y/Z's last 30

games_data = []

# Team X: 40 games (recent 30 against "dummy" opponents)
for i in range(30):
    games_data.extend([
        {"team_id": "X", "opp_id": f"dummy_x_{i}", "w_sos": 1.0, "opp_strength": 0.7},
        {"team_id": f"dummy_x_{i}", "opp_id": "X", "w_sos": 1.0, "opp_strength": None},  # Will be set later
    ])

# Team X: 10 OLD games (vs A, B, C - these will be FILTERED OUT from X's perspective)
for team in ["A", "B", "C"]:
    games_data.extend([
        # From A/B/C's perspective (KEPT - recent games)
        {"team_id": team, "opp_id": "X", "w_sos": 1.0, "opp_strength": None},
        # From X's perspective (FILTERED OUT - old games beyond 30 limit)
        # This row won't exist in g_sos!
    ])

# Team Y: Similar structure
for i in range(30):
    games_data.extend([
        {"team_id": "Y", "opp_id": f"dummy_y_{i}", "w_sos": 1.0, "opp_strength": 0.5},
        {"team_id": f"dummy_y_{i}", "opp_id": "Y", "w_sos": 1.0, "opp_strength": None},
    ])

for team in ["A", "B", "C"]:
    games_data.append({"team_id": team, "opp_id": "Y", "w_sos": 1.0, "opp_strength": None})

# Team Z: Weaker
for i in range(30):
    games_data.extend([
        {"team_id": "Z", "opp_id": f"dummy_z_{i}", "w_sos": 1.0, "opp_strength": 0.3},
        {"team_id": f"dummy_z_{i}", "opp_id": "Z", "w_sos": 1.0, "opp_strength": None},
    ])

for team in ["A", "B", "C"]:
    games_data.append({"team_id": team, "opp_id": "Z", "w_sos": 1.0, "opp_strength": None})

# Teams A, B, C also play some dummy opponents
for team in ["A", "B", "C"]:
    for i in range(7):
        games_data.extend([
            {"team_id": team, "opp_id": f"dummy_{team}_{i}", "w_sos": 1.0, "opp_strength": None},
            {"team_id": f"dummy_{team}_{i}", "opp_id": team, "w_sos": 1.0, "opp_strength": None},
        ])

# Create strength_map (simulating what teams are ranked)
strength_map = {
    # Main teams
    "X": 0.7,
    "Y": 0.5,
    "Z": 0.3,
    "A": 0.45,
    "B": 0.45,
    "C": 0.45,
}

# Dummy opponents
for i in range(30):
    strength_map[f"dummy_x_{i}"] = 0.6
    strength_map[f"dummy_y_{i}"] = 0.4
    strength_map[f"dummy_z_{i}"] = 0.2

for team in ["A", "B", "C"]:
    for i in range(7):
        strength_map[f"dummy_{team}_{i}"] = 0.4

g_sos = pd.DataFrame(games_data)

# Set opponent strengths
g_sos["opp_strength"] = g_sos["opp_id"].map(lambda o: strength_map.get(o, UNRANKED_SOS_BASE))

print("\n1. Initial Setup:")
print(f"   Total game rows: {len(g_sos)}")
print(f"   Unique teams in games: {g_sos['team_id'].nunique()}")

# Check if X appears as team_id
x_as_team = g_sos[g_sos["team_id"] == "X"]
x_as_opp = g_sos[g_sos["opp_id"] == "X"]
print(f"\n2. Team X filtering check:")
print(f"   X appears as team_id: {len(x_as_team)} times")
print(f"   X appears as opp_id: {len(x_as_opp)} times")

# Calculate direct SOS
def avg_weighted(df, col, wcol):
    w = df[wcol].values
    s = w.sum()
    if s <= 0:
        return 0.5
    return float(np.average(df[col].values, weights=w))

direct = (
    g_sos.groupby("team_id", group_keys=False)
    .apply(lambda d: avg_weighted(d, "opp_strength", "w_sos"), include_groups=False)
    .rename("sos_direct")
    .reset_index()
)

sos_curr = direct.rename(columns={"sos_direct": "sos"}).copy()

print(f"\n3. Direct SOS calculated for {len(direct)} teams")
print(f"\n   Direct SOS for teams A, B, C:")
for team in ["A", "B", "C"]:
    if team in direct["team_id"].values:
        sos_val = direct[direct["team_id"] == team]["sos_direct"].iloc[0]
        print(f"     {team}: {sos_val:.6f}")

        # Show what opponents contributed
        team_games = g_sos[g_sos["team_id"] == team]
        print(f"        Opponents: {team_games['opp_id'].tolist()}")
        print(f"        Strengths: {team_games['opp_strength'].tolist()}")

# Now iterate
print(f"\n4. Iterative Refinement ({SOS_ITERATIONS-1} iterations):")
print("   " + "=" * 70)

for iteration in range(max(0, SOS_ITERATIONS - 1)):
    print(f"\n   ITERATION {iteration + 1}:")

    # Build opponent SOS map
    opp_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))

    print(f"     Teams in opp_sos_map: {len(opp_sos_map)}")

    # Check if X, Y, Z are in the map
    for team in ["X", "Y", "Z"]:
        if team in opp_sos_map:
            print(f"       ✓ {team} in map: SOS = {opp_sos_map[team]:.6f}")
        else:
            print(f"       ✗ {team} NOT in map (will default to {UNRANKED_SOS_BASE})")

    # Map opponent SOS
    g_sos["opp_sos"] = g_sos["opp_id"].map(lambda o: opp_sos_map.get(o, UNRANKED_SOS_BASE))

    # Calculate transitive SOS
    trans = (
        g_sos.groupby("team_id", group_keys=False)
        .apply(lambda d: avg_weighted(d, "opp_sos", "w_sos"), include_groups=False)
        .rename("sos_trans")
        .reset_index()
    )

    # Merge and blend
    merged = direct.merge(trans, on="team_id", how="outer").fillna(0.5)
    merged["sos"] = (
        (1 - SOS_TRANSITIVITY_LAMBDA) * merged["sos_direct"]
        + SOS_TRANSITIVITY_LAMBDA * merged["sos_trans"]
    )
    merged["sos"] = merged["sos"].clip(0.0, 1.0)

    # Check convergence
    if iteration > 0:
        old_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))
        changes = []
        for team in ["A", "B", "C"]:
            if team in merged["team_id"].values and team in old_sos_map:
                old = old_sos_map[team]
                new = merged[merged["team_id"] == team]["sos"].iloc[0]
                change = abs(new - old)
                changes.append(change)
                print(f"     {team}: {old:.6f} → {new:.6f} (Δ {change:.6f})")

        max_change = max(changes) if changes else 0
        print(f"     Max change: {max_change:.6f}")

    sos_curr = merged[["team_id", "sos"]]

print(f"\n" + "=" * 80)
print("5. FINAL SOS VALUES:")
print("=" * 80)

for team in ["A", "B", "C"]:
    if team in sos_curr["team_id"].values:
        final_sos = sos_curr[sos_curr["team_id"] == team]["sos"].iloc[0]
        direct_sos = direct[direct["team_id"] == team]["sos_direct"].iloc[0]
        improvement = final_sos - direct_sos

        print(f"{team}: Direct={direct_sos:.6f}, Final={final_sos:.6f}, Δ={improvement:.6f}")

# Check if they're identical
abc_sos = sos_curr[sos_curr["team_id"].isin(["A", "B", "C"])]["sos"].values
unique_sos = len(set(abc_sos))

print(f"\n6. RESULT:")
if unique_sos == 1:
    print(f"   ✗ PROBLEM: All three teams have IDENTICAL SOS = {abc_sos[0]:.6f}")
    print(f"   This suggests the iterative algorithm isn't differentiating them.")
    print(f"\n   Why? Check if:")
    print(f"     1. Their opponents (X, Y, Z) are missing from opp_sos_map")
    print(f"     2. Transitivity weight (15%) is too low")
    print(f"     3. Iterations (3) aren't enough")
else:
    print(f"   ✓ Teams have different SOS values")
    print(f"   Unique values: {unique_sos}")

print("=" * 80)
