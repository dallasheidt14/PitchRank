#!/usr/bin/env python3
"""
Explain what PERFORMANCE_K actually does
========================================
PERFORMANCE_K appears TWICE in the v53e code, which is confusing!
"""

print("="*100)
print("WHAT DOES PERFORMANCE_K DO?")
print("="*100)
print()

print("PERFORMANCE_K is used in TWO places:")
print()

print("1. Line 549 - During per-game contribution calculation:")
print("   perf_contrib = PERFORMANCE_K × perf_delta × recency_decay × k_adapt × w_game")
print()
print("   Where:")
print("   - perf_delta = actual_gd - expected_gd")
print("   - expected_gd = PERFORMANCE_GOAL_SCALE × (team_power - opp_power)")
print()

print("2. Line 575 - When adding to final power score:")
print("   powerscore_core = 0.25×OFF + 0.25×DEF + 0.50×SOS + perf_centered × PERFORMANCE_K")
print()

print("="*100)
print("THE CONFUSION: Which one matters?")
print("="*100)
print()

print("The KEY insight is that perf_centered is NORMALIZED (percentile rank).")
print()
print("Process:")
print("1. Calculate per-game contributions: perf_contrib = PERFORMANCE_K × perf_delta × ...")
print("2. Sum to get perf_raw per team")
print("3. Normalize within cohort: perf_centered = rank(perf_raw, pct=True) - 0.5")
print("   → This converts to percentile rank, ranging from -0.5 to +0.5")
print("4. Add to power score: powerscore_core += perf_centered × PERFORMANCE_K")
print()

print("⚠️  CRITICAL: Step 3 (normalization) REMOVES the effect of PERFORMANCE_K from step 1!")
print()
print("Why? Because percentile rank only cares about RELATIVE ORDER, not absolute values.")
print("Whether you multiply perf_delta by 0.15 or 1.5, after normalization you get the same")
print("percentile ranks (just scaled differently).")
print()

print("="*100)
print("THEREFORE: Only the SECOND use of PERFORMANCE_K (line 575) actually matters!")
print("="*100)
print()

print("The first use (line 549) affects the aggregation of per-game contributions, but")
print("the normalization step erases its effect on the final power score.")
print()

print("="*100)
print("WHAT HAPPENS WHEN YOU CHANGE PERFORMANCE_K FROM 0.15 TO 0.17?")
print("="*100)
print()

print("Effect on power score:")
print()

# Calculate the effect
k_old = 0.15
k_new = 0.17

print(f"Current (PERFORMANCE_K = {k_old}):")
print(f"  - Best performing team (perf_centered = +0.5):  gets +{0.5 * k_old:.4f} boost")
print(f"  - Worst performing team (perf_centered = -0.5): gets {-0.5 * k_old:.4f} penalty")
print(f"  - Maximum swing: {k_old:.4f}")
print()

print(f"Proposed (PERFORMANCE_K = {k_new}):")
print(f"  - Best performing team (perf_centered = +0.5):  gets +{0.5 * k_new:.4f} boost")
print(f"  - Worst performing team (perf_centered = -0.5): gets {-0.5 * k_new:.4f} penalty")
print(f"  - Maximum swing: {k_new:.4f}")
print()

increase = k_new - k_old
pct_increase = (k_new / k_old - 1) * 100

print(f"Increase: +{increase:.4f} ({pct_increase:.1f}% more influence)")
print()

print("="*100)
print("WHAT THIS MEANS FOR PRFC vs DYNAMOS")
print("="*100)
print()

print("Hypothetical scenario (we don't have actual perf_centered values):")
print()

# Hypothetical values based on our theory
prfc_perf = -0.10  # Underperforming (inflated power from weak schedule)
dynamos_perf = +0.15  # Overperforming (deflated power from strong schedule)

print(f"Assume PRFC has perf_centered = {prfc_perf:.2f} (underperforming expectations)")
print(f"Assume Dynamos has perf_centered = {dynamos_perf:.2f} (overperforming expectations)")
print()

print(f"Current (PERFORMANCE_K = {k_old}):")
prfc_contrib_old = prfc_perf * k_old
dynamos_contrib_old = dynamos_perf * k_old
gap_old = dynamos_contrib_old - prfc_contrib_old
print(f"  PRFC contribution:    {prfc_contrib_old:+.4f}")
print(f"  Dynamos contribution: {dynamos_contrib_old:+.4f}")
print(f"  Gap (Dynamos - PRFC): {gap_old:+.4f}")
print()

print(f"Proposed (PERFORMANCE_K = {k_new}):")
prfc_contrib_new = prfc_perf * k_new
dynamos_contrib_new = dynamos_perf * k_new
gap_new = dynamos_contrib_new - prfc_contrib_new
print(f"  PRFC contribution:    {prfc_contrib_new:+.4f}")
print(f"  Dynamos contribution: {dynamos_contrib_new:+.4f}")
print(f"  Gap (Dynamos - PRFC): {gap_new:+.4f}")
print()

extra_swing = gap_new - gap_old
print(f"Extra swing in Dynamos' favor: {extra_swing:+.4f}")
print()

# Current gap is 0.000094 in PRFC's favor
current_gap = 0.000094
print(f"Current power score gap: PRFC ahead by {current_gap:.6f}")
print(f"After increasing PERFORMANCE_K: Would swing by {extra_swing:+.6f}")
print()

if extra_swing > current_gap:
    print(f"✓ This would flip the ranking! Dynamos would be ahead by {extra_swing - current_gap:.6f}")
else:
    print(f"✗ Not enough to flip the ranking. PRFC would still be ahead by {current_gap - extra_swing:.6f}")
print()

print("="*100)
print("THE PROBLEM WITH THIS APPROACH")
print("="*100)
print()

print("Increasing PERFORMANCE_K affects ALL teams, not just PRFC and Dynamos!")
print()
print("Effects:")
print("1. Teams that overperform expectations get MORE reward")
print("2. Teams that underperform expectations get MORE penalty")
print("3. This makes the performance metric MORE influential across ALL rankings")
print()

print("Is this desirable?")
print()
print("Pros:")
print("  ✓ Rewards teams that exceed expectations (good!)")
print("  ✓ Penalizes teams that disappoint (good!)")
print("  ✓ Might help correct the double-counting problem")
print()

print("Cons:")
print("  ✗ Not a targeted fix - affects everyone")
print("  ✗ Performance metric might have other purposes (measuring clutch performance, etc.)")
print("  ✗ Might overcorrect in some cases")
print("  ✗ Changes the fundamental balance of the formula")
print()

print("="*100)
print("RECOMMENDATION")
print("="*100)
print()

print("Increasing PERFORMANCE_K from 0.15 to 0.17 is a BLUNT INSTRUMENT.")
print()
print("It would:")
print("  - Make performance matter 13% more across ALL teams")
print("  - Potentially flip close matchups like PRFC vs Dynamos")
print("  - Change the balance of the formula (currently OFF=25%, DEF=25%, SOS=50%, PERF=15%)")
print()

print("Better alternatives:")
print("  1. Accept current system (99% correction is good enough)")
print("  2. Implement opponent-adjusted offense/defense (fixes root cause)")
print("  3. Analyze whether the 0.000094 gap is actually a problem worth fixing")
print()

print("To make an informed decision, you should:")
print("  1. Extract actual perf_centered values for PRFC and Dynamos")
print("  2. Understand WHY they have those performance values")
print("  3. Decide if increasing PERFORMANCE_K would have unintended consequences")
print()
