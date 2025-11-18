#!/usr/bin/env python3
"""
CRITICAL ANALYSIS: Real perf_centered values reveal the truth
"""

print("="*100)
print("ACTUAL DATA FROM DATABASE")
print("="*100)
print()

# Actual data from query
prfc = {
    'name': 'PRFC Scottsdale 14B Pre-Academy',
    'power_score_final': 0.469726964338811,
    'powerscore_core': 0.854049026070565,
    'sos_norm': 0.745094391647912,
    'offense_norm': 0.862994438111424,
    'defense_norm': 0.924490455434377,
    'perf_centered': 0.230870712401055,  # POSITIVE!
    'perf_raw': 0.0264968297350826,
    'rank': 109
}

dynamos = {
    'name': 'Dynamos SC 14B SC',
    'power_score_final': 0.469632835958009,
    'powerscore_core': 0.853877883560017,
    'sos_norm': 0.849912408846438,
    'offense_norm': 0.590158996464718,
    'defense_norm': 0.910145134330495,
    'perf_centered': 0.358970976253298,  # EVEN MORE POSITIVE!
    'perf_raw': 0.048943343341493,
    'rank': 111
}

print("PRFC Scottsdale:")
print(f"  perf_centered: {prfc['perf_centered']:+.4f} (OVERPERFORMING!)")
print(f"  powerscore_core: {prfc['powerscore_core']:.6f}")
print(f"  power_score_final: {prfc['power_score_final']:.6f}")
print()

print("Dynamos SC:")
print(f"  perf_centered: {dynamos['perf_centered']:+.4f} (OVERPERFORMING EVEN MORE!)")
print(f"  powerscore_core: {dynamos['powerscore_core']:.6f}")
print(f"  power_score_final: {dynamos['power_score_final']:.6f}")
print()

print("="*100)
print("VERIFICATION: Recalculate powerscore_core from components")
print("="*100)
print()

PERFORMANCE_K = 0.15

prfc_calc = (
    0.25 * prfc['offense_norm'] +
    0.25 * prfc['defense_norm'] +
    0.50 * prfc['sos_norm'] +
    prfc['perf_centered'] * PERFORMANCE_K
)

dynamos_calc = (
    0.25 * dynamos['offense_norm'] +
    0.25 * dynamos['defense_norm'] +
    0.50 * dynamos['sos_norm'] +
    dynamos['perf_centered'] * PERFORMANCE_K
)

print(f"PRFC calculated: {prfc_calc:.6f}")
print(f"PRFC actual:     {prfc['powerscore_core']:.6f}")
print(f"Match: {abs(prfc_calc - prfc['powerscore_core']) < 0.00001}")
print()

print(f"Dynamos calculated: {dynamos_calc:.6f}")
print(f"Dynamos actual:     {dynamos['powerscore_core']:.6f}")
print(f"Match: {abs(dynamos_calc - dynamos['powerscore_core']) < 0.00001}")
print()

print("="*100)
print("THE SHOCKING TRUTH")
print("="*100)
print()

print("❌ MY PREDICTION WAS WRONG!")
print()
print("I predicted:")
print("  - PRFC would have NEGATIVE performance (underperforming inflated expectations)")
print("  - Dynamos would have POSITIVE performance (overperforming deflated expectations)")
print()
print("Reality:")
print(f"  - PRFC has POSITIVE performance: {prfc['perf_centered']:+.4f}")
print(f"  - Dynamos has EVEN MORE POSITIVE performance: {dynamos['perf_centered']:+.4f}")
print()

print("="*100)
print("BREAKDOWN: Where does each component come from?")
print("="*100)
print()

# Calculate contributions
prfc_off = 0.25 * prfc['offense_norm']
prfc_def = 0.25 * prfc['defense_norm']
prfc_sos = 0.50 * prfc['sos_norm']
prfc_perf = prfc['perf_centered'] * PERFORMANCE_K

dynamos_off = 0.25 * dynamos['offense_norm']
dynamos_def = 0.25 * dynamos['defense_norm']
dynamos_sos = 0.50 * dynamos['sos_norm']
dynamos_perf = dynamos['perf_centered'] * PERFORMANCE_K

print("PRFC Scottsdale contributions:")
print(f"  Offense:     {prfc['offense_norm']:.4f} × 0.25 = {prfc_off:.6f}")
print(f"  Defense:     {prfc['defense_norm']:.4f} × 0.25 = {prfc_def:.6f}")
print(f"  SOS:         {prfc['sos_norm']:.4f} × 0.50 = {prfc_sos:.6f}")
print(f"  Performance: {prfc['perf_centered']:+.4f} × 0.15 = {prfc_perf:+.6f}")
print(f"  Total:                                  {prfc_off + prfc_def + prfc_sos + prfc_perf:.6f}")
print()

print("Dynamos SC contributions:")
print(f"  Offense:     {dynamos['offense_norm']:.4f} × 0.25 = {dynamos_off:.6f}")
print(f"  Defense:     {dynamos['defense_norm']:.4f} × 0.25 = {dynamos_def:.6f}")
print(f"  SOS:         {dynamos['sos_norm']:.4f} × 0.50 = {dynamos_sos:.6f}")
print(f"  Performance: {dynamos['perf_centered']:+.4f} × 0.15 = {dynamos_perf:+.6f}")
print(f"  Total:                                  {dynamos_off + dynamos_def + dynamos_sos + dynamos_perf:.6f}")
print()

print("="*100)
print("COMPONENT-BY-COMPONENT COMPARISON")
print("="*100)
print()

off_diff = prfc_off - dynamos_off
def_diff = prfc_def - dynamos_def
sos_diff = prfc_sos - dynamos_sos
perf_diff = prfc_perf - dynamos_perf
total_diff = off_diff + def_diff + sos_diff + perf_diff

print(f"Offense:     PRFC {prfc_off:.6f} vs Dynamos {dynamos_off:.6f} = {off_diff:+.6f} (PRFC ahead)")
print(f"Defense:     PRFC {prfc_def:.6f} vs Dynamos {dynamos_def:.6f} = {def_diff:+.6f} (PRFC ahead)")
print(f"SOS:         PRFC {prfc_sos:.6f} vs Dynamos {dynamos_sos:.6f} = {sos_diff:+.6f} (Dynamos ahead)")
print(f"Performance: PRFC {prfc_perf:+.6f} vs Dynamos {dynamos_perf:+.6f} = {perf_diff:+.6f} (Dynamos ahead)")
print("-"*100)
print(f"TOTAL:                                                    = {total_diff:+.6f} (PRFC ahead)")
print()

print("="*100)
print("THE DOUBLE-COUNTING PROBLEM IS REAL")
print("="*100)
print()

# Calculate without performance
prfc_base = prfc_off + prfc_def + prfc_sos
dynamos_base = dynamos_off + dynamos_def + dynamos_sos
base_gap = prfc_base - dynamos_base

print("WITHOUT performance metric (OFF + DEF + SOS only):")
print(f"  PRFC:    {prfc_base:.6f}")
print(f"  Dynamos: {dynamos_base:.6f}")
print(f"  Gap:     {base_gap:+.6f} (PRFC ahead) ← THIS IS THE DOUBLE-COUNTING PROBLEM")
print()

print("WITH performance metric:")
print(f"  PRFC:    {prfc_base + prfc_perf:.6f}")
print(f"  Dynamos: {dynamos_base + dynamos_perf:.6f}")
print(f"  Gap:     {total_diff:+.6f} (PRFC ahead) ← Performance reduced gap but didn't eliminate it")
print()

performance_correction = perf_diff  # How much performance helped Dynamos
print(f"Performance correction: {performance_correction:+.6f} in Dynamos' favor")
print(f"Remaining gap:          {total_diff:+.6f} in PRFC's favor")
print()

correction_pct = abs(performance_correction / base_gap) * 100
print(f"Performance corrected {correction_pct:.1f}% of the double-counting problem")
print(f"BUT only because Dynamos happens to be overperforming MORE than PRFC")
print(f"This is NOT a systematic correction for schedule strength!")
print()

print("="*100)
print("WHAT THIS MEANS")
print("="*100)
print()

print("1. BOTH teams are overperforming expectations:")
print(f"   - PRFC:    {prfc['perf_centered']:+.4f} (winning by more than expected)")
print(f"   - Dynamos: {dynamos['perf_centered']:+.4f} (winning by even more than expected)")
print()

print("2. Performance metric is NOT correcting for double-counting:")
print("   - It's NOT that PRFC is underperforming inflated expectations")
print("   - It's NOT that Dynamos is overperforming deflated expectations")
print("   - Both are just having good seasons relative to their pre-calculated power")
print()

print("3. The gap closed from +0.0194 to +0.0001 by COINCIDENCE:")
print("   - Dynamos happens to be overperforming more (+0.3590 vs +0.2309)")
print("   - This gives them a +0.0193 performance boost over PRFC")
print("   - Which almost exactly cancels out the +0.0194 double-counting gap")
print("   - But this is LUCK, not systematic correction!")
print()

print("4. The double-counting problem IS REAL:")
print(f"   - PRFC's weak schedule (SOS {prfc['sos_norm']:.3f}) inflates their offense ({prfc['offense_norm']:.3f})")
print(f"   - Dynamos' strong schedule (SOS {dynamos['sos_norm']:.3f}) deflates their offense ({dynamos['offense_norm']:.3f})")
print(f"   - The offense/defense advantage (+{off_diff + def_diff:.4f}) overcomes SOS advantage ({sos_diff:+.4f})")
print(f"   - Net double-counting effect: {base_gap:+.6f}")
print()

print("="*100)
print("CONCLUSION")
print("="*100)
print()

print("❌ The system is NOT systematically correcting for double-counting")
print("❌ Both teams happen to be overperforming, masking the problem")
print("❌ In this specific case, it worked out (gap reduced to 0.0001)")
print("✓  But in other cases, the double-counting would still be present")
print()

print("THE USER WAS RIGHT TO BE CONCERNED!")
print()

print("Options:")
print("1. Implement opponent-adjusted offense/defense (fixes root cause)")
print("2. Increase SOS weight from 50% to 60-65%")
print("3. Accept that close matchups will sometimes go the wrong way")
