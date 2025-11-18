#!/usr/bin/env python3
"""
Test Opponent-Adjusted Offense/Defense Metrics
==============================================
This script demonstrates the double-counting problem and shows how
opponent-adjusted metrics would change team rankings.

The current system calculates offense/defense as raw goals scored/allowed,
which means teams playing weak schedules get inflated offense/defense scores.

This script shows:
1. Current system (raw offense/defense)
2. Proposed system (opponent-adjusted offense/defense)
3. Impact on rankings
"""

import numpy as np


def calculate_power_score(offense, defense, sos,
                          off_weight=0.25, def_weight=0.25, sos_weight=0.50):
    """Calculate power score"""
    return off_weight * offense + def_weight * defense + sos_weight * sos


def adjust_for_opponent_strength(raw_value, opponent_sos, baseline_sos=0.50):
    """
    Adjust a metric for opponent strength.

    If you score X goals against weak opponents (SOS < 0.50),
    your adjusted score should be lower.

    If you score X goals against strong opponents (SOS > 0.50),
    your adjusted score should be higher.

    Formula: adjusted = raw × (baseline / opponent_sos)

    Example:
    - Score 3 goals against weak opponents (SOS 0.40) → adjusted = 3 × (0.50/0.40) = 3.75 (penalized)
      Wait, that's backwards. Let me fix this.

    Actually, if you score against WEAK opponents, you should get LESS credit.
    If you score against STRONG opponents, you should get MORE credit.

    So: adjusted = raw × (opponent_sos / baseline)

    Example:
    - Score 3 goals against weak opponents (SOS 0.40) → adjusted = 3 × (0.40/0.50) = 2.4 (penalized)
    - Score 2 goals against strong opponents (SOS 0.80) → adjusted = 2 × (0.80/0.50) = 3.2 (rewarded)
    """
    if opponent_sos == 0:
        return raw_value
    return raw_value * (opponent_sos / baseline_sos)


def main():
    print("="*100)
    print("DOUBLE-COUNTING PROBLEM DEMONSTRATION")
    print("="*100)
    print()
    print("Problem: Offense and defense are NOT adjusted for opponent strength.")
    print("This means teams playing weak schedules get inflated offense/defense scores.")
    print()

    # PRFC Scottsdale data
    prfc = {
        'name': 'PRFC Scottsdale 14B Pre-Academy',
        'sos_norm': 0.745,
        'offense_norm': 0.863,
        'defense_norm': 0.925,
        'power_score': 0.469727,
        'rank': 109,
    }

    # Dynamos SC data
    dynamos = {
        'name': 'Dynamos SC 14B SC',
        'sos_norm': 0.850,
        'offense_norm': 0.590,
        'defense_norm': 0.910,
        'power_score': 0.469633,
        'rank': 111,
    }

    print("="*100)
    print("CURRENT SYSTEM (Raw Offense/Defense)")
    print("="*100)
    print()

    print(f"{prfc['name']:40s} (Rank #{prfc['rank']})")
    print(f"  SOS:     {prfc['sos_norm']:.3f} (74.5th percentile)")
    print(f"  Offense: {prfc['offense_norm']:.3f} (86.3rd percentile) ← HIGH because playing weak teams")
    print(f"  Defense: {prfc['defense_norm']:.3f} (92.5th percentile) ← HIGH because playing weak teams")
    prfc_current = calculate_power_score(prfc['offense_norm'], prfc['defense_norm'], prfc['sos_norm'])
    print(f"  Power Score: {prfc_current:.6f}")
    print()

    print(f"{dynamos['name']:40s} (Rank #{dynamos['rank']})")
    print(f"  SOS:     {dynamos['sos_norm']:.3f} (85.0th percentile)")
    print(f"  Offense: {dynamos['offense_norm']:.3f} (59.0th percentile) ← LOW because playing strong teams")
    print(f"  Defense: {dynamos['defense_norm']:.3f} (91.0th percentile)")
    dynamos_current = calculate_power_score(dynamos['offense_norm'], dynamos['defense_norm'], dynamos['sos_norm'])
    print(f"  Power Score: {dynamos_current:.6f}")
    print()

    print(f"Winner: {prfc['name']} by {prfc_current - dynamos_current:.6f}")
    print()

    print("="*100)
    print("THE PROBLEM")
    print("="*100)
    print()
    print("PRFC's high offense (0.863) is inflated because they play weak opponents (SOS 0.745).")
    print("Dynamos' low offense (0.590) is deflated because they play strong opponents (SOS 0.850).")
    print()
    print("Scoring 2 goals against elite teams might be MORE impressive than scoring 3 against weak teams,")
    print("but the current system doesn't account for this!")
    print()

    print("="*100)
    print("PROPOSED SOLUTION: Opponent-Adjusted Offense/Defense")
    print("="*100)
    print()
    print("Adjust offense/defense based on opponent strength:")
    print("  adjusted_offense = raw_offense × (opponent_sos / 0.50)")
    print("  adjusted_defense = raw_defense × (opponent_sos / 0.50)")
    print()
    print("This way:")
    print("  - High offense against weak opponents → PENALIZED (adjusted down)")
    print("  - High offense against strong opponents → REWARDED (adjusted up)")
    print()

    # Adjust for opponent strength
    # Since PRFC plays weaker opponents (0.745), their offense should be adjusted DOWN
    # Since Dynamos plays stronger opponents (0.850), their offense should be adjusted UP

    baseline_sos = 0.50

    prfc_off_adjusted = adjust_for_opponent_strength(prfc['offense_norm'], prfc['sos_norm'], baseline_sos)
    prfc_def_adjusted = adjust_for_opponent_strength(prfc['defense_norm'], prfc['sos_norm'], baseline_sos)

    dynamos_off_adjusted = adjust_for_opponent_strength(dynamos['offense_norm'], dynamos['sos_norm'], baseline_sos)
    dynamos_def_adjusted = adjust_for_opponent_strength(dynamos['defense_norm'], dynamos['sos_norm'], baseline_sos)

    # Renormalize to 0-1 range (simple min-max normalization between the two teams)
    all_off = [prfc_off_adjusted, dynamos_off_adjusted]
    all_def = [prfc_def_adjusted, dynamos_def_adjusted]

    off_min, off_max = min(all_off), max(all_off)
    def_min, def_max = min(all_def), max(all_def)

    if off_max > off_min:
        prfc_off_norm = (prfc_off_adjusted - off_min) / (off_max - off_min)
        dynamos_off_norm = (dynamos_off_adjusted - off_min) / (off_max - off_min)
    else:
        prfc_off_norm = 0.5
        dynamos_off_norm = 0.5

    if def_max > def_min:
        prfc_def_norm = (prfc_def_adjusted - def_min) / (def_max - def_min)
        dynamos_def_norm = (dynamos_def_adjusted - def_min) / (def_max - def_min)
    else:
        prfc_def_norm = 0.5
        dynamos_def_norm = 0.5

    print(f"{prfc['name']:40s}")
    print(f"  Opponent SOS: {prfc['sos_norm']:.3f} (weaker than average)")
    print(f"  Raw Offense:  {prfc['offense_norm']:.3f} → Adjusted: {prfc_off_adjusted:.3f} → Normalized: {prfc_off_norm:.3f}")
    print(f"  Raw Defense:  {prfc['defense_norm']:.3f} → Adjusted: {prfc_def_adjusted:.3f} → Normalized: {prfc_def_norm:.3f}")
    prfc_adjusted = calculate_power_score(prfc_off_norm, prfc_def_norm, prfc['sos_norm'])
    print(f"  Power Score: {prfc_adjusted:.6f} (was {prfc_current:.6f}, change: {prfc_adjusted - prfc_current:+.6f})")
    print()

    print(f"{dynamos['name']:40s}")
    print(f"  Opponent SOS: {dynamos['sos_norm']:.3f} (stronger than average)")
    print(f"  Raw Offense:  {dynamos['offense_norm']:.3f} → Adjusted: {dynamos_off_adjusted:.3f} → Normalized: {dynamos_off_norm:.3f}")
    print(f"  Raw Defense:  {dynamos['defense_norm']:.3f} → Adjusted: {dynamos_def_adjusted:.3f} → Normalized: {dynamos_def_norm:.3f}")
    dynamos_adjusted = calculate_power_score(dynamos_off_norm, dynamos_def_norm, dynamos['sos_norm'])
    print(f"  Power Score: {dynamos_adjusted:.6f} (was {dynamos_current:.6f}, change: {dynamos_adjusted - dynamos_current:+.6f})")
    print()

    if prfc_adjusted > dynamos_adjusted:
        winner = prfc['name']
        diff = prfc_adjusted - dynamos_adjusted
    else:
        winner = dynamos['name']
        diff = dynamos_adjusted - prfc_adjusted

    print(f"Winner: {winner} by {diff:.6f}")
    print()

    print("="*100)
    print("IMPACT ANALYSIS")
    print("="*100)
    print()

    swing = (dynamos_adjusted - prfc_adjusted) - (dynamos_current - prfc_current)
    print(f"Adjustment swing: {swing:+.6f} in favor of Dynamos")
    print()

    if dynamos_adjusted > prfc_adjusted:
        print("✓ With opponent-adjusted metrics, Dynamos SC would rank HIGHER than PRFC Scottsdale")
        print("  (as expected, since they play a tougher schedule)")
    else:
        print("✗ Even with opponent-adjusted metrics, PRFC still ranks higher")
        print("  (but the gap is reduced)")
    print()

    print("="*100)
    print("CONCLUSION")
    print("="*100)
    print()
    print("The current system has a double-counting problem:")
    print("1. Teams playing weak schedules get INFLATED offense/defense scores")
    print("2. They pay a SOS penalty, but it's NOT ENOUGH to offset the inflation")
    print("3. Net result: dominating weak opponents is rewarded more than competing against strong ones")
    print()
    print("RECOMMENDATION:")
    print("- Implement opponent-adjusted offense/defense metrics")
    print("- OR increase SOS weight from 50% to 60-65%")
    print("- OR remove raw offense/defense from power score entirely")
    print()


if __name__ == "__main__":
    main()
