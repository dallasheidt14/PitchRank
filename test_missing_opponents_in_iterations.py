#!/usr/bin/env python3
"""
Test what happens when opponents are TRULY missing from sos_curr
This simulates the real bug scenario
"""
import pandas as pd
import numpy as np

print("=" * 80)
print("TEST: Missing Opponents in Iterative SOS")
print("=" * 80)

UNRANKED_SOS_BASE = 0.35
SOS_ITERATIONS = 3
SOS_TRANSITIVITY_LAMBDA = 0.15

# Scenario:
# - Teams A, B, C have 10 games each
# - They play against opponents that DON'T appear as team_id
#   (because those opponents were filtered out)

games_data = []

# Team A plays opponents that won't be in sos_curr
for opp in ["filtered_1", "filtered_2", "filtered_3"]:
    games_data.append({
        "team_id": "A",
        "opp_id": opp,
        "w_sos": 1.0,
    })

# Team B plays DIFFERENT filtered opponents
for opp in ["filtered_4", "filtered_5", "filtered_6"]:
    games_data.append({
        "team_id": "B",
        "opp_id": opp,
        "w_sos": 1.0,
    })

# Team C plays yet DIFFERENT filtered opponents
for opp in ["filtered_7", "filtered_8", "filtered_9"]:
    games_data.append({
        "team_id": "C",
        "opp_id": opp,
        "w_sos": 1.0,
    })

g_sos = pd.DataFrame(games_data)

# strength_map has SOME estimates for the filtered opponents
# (simulating my fix that estimates strength)
strength_map = {
    "A": 0.5,
    "B": 0.5,
    "C": 0.5,
    # Filtered opponents have DIFFERENT estimated strengths
    "filtered_1": 0.7,  # Strong
    "filtered_2": 0.6,
    "filtered_3": 0.8,
    "filtered_4": 0.4,  # Weak
    "filtered_5": 0.3,
    "filtered_6": 0.35,
    "filtered_7": 0.55,  # Medium
    "filtered_8": 0.5,
    "filtered_9": 0.52,
}

g_sos["opp_strength"] = g_sos["opp_id"].map(lambda o: strength_map.get(o, UNRANKED_SOS_BASE))

def avg_weighted(df, col, wcol):
    w = df[wcol].values
    s = w.sum()
    if s <= 0:
        return 0.5
    return float(np.average(df[col].values, weights=w))

# Calculate direct SOS
direct = (
    g_sos.groupby("team_id", group_keys=False)
    .apply(lambda d: avg_weighted(d, "opp_strength", "w_sos"), include_groups=False)
    .rename("sos_direct")
    .reset_index()
)

print("\n1. Direct SOS (uses estimated opponent strength):")
print("   " + "=" * 70)
for _, row in direct.iterrows():
    print(f"   {row['team_id']}: {row['sos_direct']:.6f}")

# Notice: All different! Because we estimated opponent strengths

sos_curr = direct.rename(columns={"sos_direct": "sos"}).copy()

print("\n2. Teams in sos_curr: ", sos_curr["team_id"].tolist())
print("   Filtered opponents in sos_curr: ", [o for o in strength_map.keys() if o.startswith("filtered") and o in sos_curr["team_id"].values])
print("   → NONE! Filtered opponents aren't in sos_curr!")

# Now iterate
print("\n3. Iterative Refinement (WITHOUT fix for missing opponent SOS):")
print("   " + "=" * 70)

for iteration in range(max(0, SOS_ITERATIONS - 1)):
    print(f"\n   ITERATION {iteration + 1}:")

    # Build opponent SOS map (CURRENT CODE)
    opp_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))

    print(f"     Teams in opp_sos_map: {opp_sos_map.keys()}")

    # Check filtered opponents
    print(f"     Checking filtered opponents:")
    for opp in ["filtered_1", "filtered_4", "filtered_7"]:
        if opp in opp_sos_map:
            print(f"       ✓ {opp} in map: SOS = {opp_sos_map[opp]:.6f}")
        else:
            print(f"       ✗ {opp} NOT in map (will default to {UNRANKED_SOS_BASE})")

    # Map opponent SOS (defaults to 0.35 for ALL filtered opponents!)
    g_sos["opp_sos"] = g_sos["opp_id"].map(lambda o: opp_sos_map.get(o, UNRANKED_SOS_BASE))

    # Calculate transitive SOS
    trans = (
        g_sos.groupby("team_id", group_keys=False)
        .apply(lambda d: avg_weighted(d, "opp_sos", "w_sos"), include_groups=False)
        .rename("sos_trans")
        .reset_index()
    )

    print(f"\n     Transitive SOS:")
    for _, row in trans.iterrows():
        print(f"       {row['team_id']}: {row['sos_trans']:.6f}")

    # All 0.35! Because all opponents defaulted

    # Merge and blend
    merged = direct.merge(trans, on="team_id", how="outer").fillna(0.5)
    merged["sos"] = (
        (1 - SOS_TRANSITIVITY_LAMBDA) * merged["sos_direct"]
        + SOS_TRANSITIVITY_LAMBDA * merged["sos_trans"]
    )
    merged["sos"] = merged["sos"].clip(0.0, 1.0)

    print(f"\n     Blended SOS (85% direct + 15% transitive):")
    for _, row in merged.iterrows():
        direct_val = row.get("sos_direct", 0)
        trans_val = row.get("sos_trans", 0)
        final_val = row["sos"]
        print(f"       {row['team_id']}: 85%×{direct_val:.4f} + 15%×{trans_val:.4f} = {final_val:.6f}")

    sos_curr = merged[["team_id", "sos"]]

print("\n" + "=" * 80)
print("4. FINAL RESULT (WITHOUT fix):")
print("=" * 80)

for _, row in sos_curr.iterrows():
    direct_val = direct[direct["team_id"] == row["team_id"]]["sos_direct"].iloc[0]
    print(f"{row['team_id']}: Direct={direct_val:.6f} → Final={row['sos']:.6f} (Δ {row['sos']-direct_val:.6f})")

# Calculate convergence
final_values = sos_curr["sos"].values
value_range = final_values.max() - final_values.min()

print(f"\n5. ANALYSIS:")
print(f"   Initial range (direct SOS): {direct['sos_direct'].max() - direct['sos_direct'].min():.6f}")
print(f"   Final range (after iterations): {value_range:.6f}")
print(f"   Convergence: Values moved CLOSER together!")
print()
print("   WHY? Because transitivity defaulted all opponents to 0.35,")
print("   pulling all SOS values toward the same number!")

print("\n" + "=" * 80)
print("6. NOW TEST WITH FIX (estimate opponent SOS):")
print("=" * 80)

# Reset
sos_curr = direct.rename(columns={"sos_direct": "sos"}).copy()

for iteration in range(max(0, SOS_ITERATIONS - 1)):
    print(f"\n   ITERATION {iteration + 1} (WITH FIX):")

    # Build opponent SOS map
    opp_sos_map = dict(zip(sos_curr["team_id"], sos_curr["sos"]))

    # FIX: Add missing opponents with estimated SOS
    missing_opps = set(g_sos["opp_id"].unique()) - set(opp_sos_map.keys())

    if missing_opps:
        print(f"     Found {len(missing_opps)} missing opponents")
        print(f"     Estimating their SOS...")

        for opp in missing_opps:
            # Estimate: Use their strength as proxy for SOS
            estimated_sos = strength_map.get(opp, UNRANKED_SOS_BASE)
            opp_sos_map[opp] = estimated_sos
            print(f"       {opp}: estimated SOS = {estimated_sos:.4f}")

    # Map opponent SOS (now includes estimates!)
    g_sos["opp_sos"] = g_sos["opp_id"].map(lambda o: opp_sos_map.get(o, UNRANKED_SOS_BASE))

    # Calculate transitive SOS
    trans = (
        g_sos.groupby("team_id", group_keys=False)
        .apply(lambda d: avg_weighted(d, "opp_sos", "w_sos"), include_groups=False)
        .rename("sos_trans")
        .reset_index()
    )

    print(f"\n     Transitive SOS (WITH estimates):")
    for _, row in trans.iterrows():
        print(f"       {row['team_id']}: {row['sos_trans']:.6f}")

    # Merge and blend
    merged = direct.merge(trans, on="team_id", how="outer").fillna(0.5)
    merged["sos"] = (
        (1 - SOS_TRANSITIVITY_LAMBDA) * merged["sos_direct"]
        + SOS_TRANSITIVITY_LAMBDA * merged["sos_trans"]
    )
    merged["sos"] = merged["sos"].clip(0.0, 1.0)

    sos_curr = merged[["team_id", "sos"]]

print("\n" + "=" * 80)
print("7. FINAL RESULT (WITH fix):")
print("=" * 80)

for _, row in sos_curr.iterrows():
    direct_val = direct[direct["team_id"] == row["team_id"]]["sos_direct"].iloc[0]
    print(f"{row['team_id']}: Direct={direct_val:.6f} → Final={row['sos']:.6f} (Δ {row['sos']-direct_val:.6f})")

final_values_fixed = sos_curr["sos"].values
value_range_fixed = final_values_fixed.max() - final_values_fixed.min()

print(f"\n8. COMPARISON:")
print(f"   WITHOUT fix: Final range = {value_range:.6f}")
print(f"   WITH fix: Final range = {value_range_fixed:.6f}")

if value_range_fixed > value_range:
    print(f"   ✓ FIX HELPS! Values are more spread out ({value_range_fixed/value_range:.2f}x wider)")
else:
    print(f"   ✗ Fix doesn't help much")

print("=" * 80)
