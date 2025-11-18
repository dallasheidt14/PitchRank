#!/usr/bin/env python3
"""Check if ML layer (Layer 13) is correcting for the double-counting problem"""

# PRFC Scottsdale vs Dynamos data from the user
teams = [
    {
        "team_name": "PRFC Scottsdale 14B Pre-Academy",
        "rank_in_cohort_final": 109,
        "power_score_final": 0.469726964338811,
        "sos_norm": 0.745094391647912,
        "offense_norm": 0.862994438111424,
        "defense_norm": 0.924490455434377,
    },
    {
        "team_name": "Dynamos SC 14B SC",
        "rank_in_cohort_final": 111,
        "power_score_final": 0.469632835958009,
        "sos_norm": 0.849912408846438,
        "offense_norm": 0.590158996464718,
        "defense_norm": 0.910145134330495,
    },
]

print("="*100)
print("ML LAYER (LAYER 13) IMPACT ANALYSIS")
print("="*100)
print()

# Check if the data has ML layer columns
# The user provided: power_score_final, sos_norm, offense_norm, defense_norm
# In the codebase:
# - v53e produces: powerscore_core, powerscore_adj, rank_in_cohort
# - ML layer produces: powerscore_ml, ml_overperf, ml_norm, rank_in_cohort_ml

print("Data provided by user:")
print("- power_score_final (likely = powerscore_ml or powerscore_adj)")
print("- rank_in_cohort_final (likely = rank_in_cohort_ml or rank_in_cohort)")
print()

# Calculate what v53e core power score should be
for team in teams:
    name = team["team_name"]

    # Calculate v53e core power score
    powerscore_core = (
        0.25 * team["offense_norm"] +
        0.25 * team["defense_norm"] +
        0.50 * team["sos_norm"]
        # Note: We don't have perf_centered, so this is approximate
    )

    power_score_final = team["power_score_final"]
    difference = power_score_final - powerscore_core

    print(f"{name}")
    print(f"  Calculated powerscore_core (OFF+DEF+SOS): {powerscore_core:.6f}")
    print(f"  Provided power_score_final:               {power_score_final:.6f}")
    print(f"  Difference:                               {difference:+.6f}")
    print()

    if abs(difference) > 0.001:
        print(f"  → Significant difference! This could be:")
        print(f"     1. Performance metric contribution (perf_centered × 0.15)")
        print(f"     2. ML layer adjustment (ml_norm × alpha)")
        print(f"     3. Provisional multiplier")
        print(f"     4. Anchor scaling")
    else:
        print(f"  → Minimal difference, likely just missing performance metric")
    print()

print("="*100)
print("KEY FINDINGS")
print("="*100)
print()

prfc_core = 0.25 * teams[0]["offense_norm"] + 0.25 * teams[0]["defense_norm"] + 0.50 * teams[0]["sos_norm"]
dynamos_core = 0.25 * teams[1]["offense_norm"] + 0.25 * teams[1]["defense_norm"] + 0.50 * teams[1]["sos_norm"]

print(f"PRFC powerscore_core (OFF+DEF+SOS):    {prfc_core:.6f}")
print(f"Dynamos powerscore_core (OFF+DEF+SOS): {dynamos_core:.6f}")
print(f"Difference:                            {prfc_core - dynamos_core:+.6f} (PRFC ahead)")
print()

print(f"PRFC power_score_final:    {teams[0]['power_score_final']:.6f}")
print(f"Dynamos power_score_final: {teams[1]['power_score_final']:.6f}")
print(f"Difference:                {teams[0]['power_score_final'] - teams[1]['power_score_final']:+.6f} (PRFC ahead)")
print()

# Check if ML layer would have corrected this
prfc_adjustment = teams[0]['power_score_final'] - prfc_core
dynamos_adjustment = teams[1]['power_score_final'] - dynamos_core

print("Adjustments from core to final:")
print(f"  PRFC:    {prfc_adjustment:+.6f}")
print(f"  Dynamos: {dynamos_adjustment:+.6f}")
print(f"  Net swing: {(dynamos_adjustment - prfc_adjustment):+.6f}")
print()

if abs(dynamos_adjustment - prfc_adjustment) < 0.0001:
    print("✗ ML layer did NOT significantly adjust the rankings")
    print("  → The double-counting problem is NOT being corrected by ML")
    print("  → PRFC still ranks higher despite weaker schedule")
else:
    swing_in_dynamos_favor = (dynamos_adjustment - prfc_adjustment)
    if swing_in_dynamos_favor > 0:
        print(f"✓ ML layer adjusted in Dynamos' favor by {swing_in_dynamos_favor:+.6f}")
        print("  → ML layer IS attempting to correct for the double-counting")
        if teams[0]['power_score_final'] > teams[1]['power_score_final']:
            print("  → But it's NOT ENOUGH - PRFC still ranks higher")
    else:
        print(f"✗ ML layer adjusted in PRFC's favor by {-swing_in_dynamos_favor:+.6f}")
        print("  → ML layer is making the problem WORSE")

print()
print("="*100)
print("CONCLUSION")
print("="*100)
print()
print("The 'power_score_final' values suggest that the system is NOT using ML layer")
print("(Layer 13), or the ML layer is not correcting for the double-counting problem.")
print()
print("The difference between calculated core and provided final is likely just the")
print("performance metric (perf_centered × 0.15), which we don't have data for.")
print()
print("RECOMMENDATION:")
print("1. Check if rankings are using Layer 13 (powerscore_ml) or v53e only (powerscore_adj)")
print("2. If using Layer 13, the ML layer is not sufficient to correct the double-counting")
print("3. If using v53e only, the double-counting problem is definitely present")
print()
print("Either way, implementing opponent-adjusted offense/defense would be the")
print("most principled solution to eliminate the double-counting at its source.")
