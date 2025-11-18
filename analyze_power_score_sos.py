#!/usr/bin/env python3
"""
Analyze Power Score vs SOS Weighting
=====================================
This script helps analyze whether the current SOS weighting (50%) is appropriate
by comparing teams with different SOS/offense/defense profiles.

Usage:
    python analyze_power_score_sos.py
"""

import json


def calculate_power_score(sos_norm, offense_norm, defense_norm, perf_centered=0.0,
                          sos_weight=0.50, off_weight=0.25, def_weight=0.25, perf_k=0.15):
    """Calculate power score using the v53e formula"""
    return (
        off_weight * offense_norm +
        def_weight * defense_norm +
        sos_weight * sos_norm +
        perf_centered * perf_k
    )


def analyze_teams(team1_name, team1_data, team2_name, team2_data, custom_weights=None):
    """Compare two teams and show component breakdown"""

    weights = custom_weights or {
        'sos_weight': 0.50,
        'off_weight': 0.25,
        'def_weight': 0.25,
        'perf_k': 0.15
    }

    print("="*100)
    print(f"COMPARING: {team1_name} vs {team2_name}")
    print("="*100)

    # Team 1
    print(f"\n{team1_name}:")
    print(f"  SOS Norm:     {team1_data['sos_norm']:.4f} ({team1_data['sos_norm']*100:.1f}th percentile)")
    print(f"  Offense Norm: {team1_data['offense_norm']:.4f} ({team1_data['offense_norm']*100:.1f}th percentile)")
    print(f"  Defense Norm: {team1_data['defense_norm']:.4f} ({team1_data['defense_norm']*100:.1f}th percentile)")
    print(f"  Actual Power Score: {team1_data['power_score_final']:.6f}")

    # Team 2
    print(f"\n{team2_name}:")
    print(f"  SOS Norm:     {team2_data['sos_norm']:.4f} ({team2_data['sos_norm']*100:.1f}th percentile)")
    print(f"  Offense Norm: {team2_data['offense_norm']:.4f} ({team2_data['offense_norm']*100:.1f}th percentile)")
    print(f"  Defense Norm: {team2_data['defense_norm']:.4f} ({team2_data['defense_norm']*100:.1f}th percentile)")
    print(f"  Actual Power Score: {team2_data['power_score_final']:.6f}")

    # Calculate contributions
    print(f"\n{'COMPONENT BREAKDOWN':^100}")
    print("="*100)

    # SOS
    sos1_contrib = team1_data['sos_norm'] * weights['sos_weight']
    sos2_contrib = team2_data['sos_norm'] * weights['sos_weight']
    print(f"\n1. SOS (Weight: {weights['sos_weight']*100:.0f}%)")
    print(f"   {team1_name:30s}: {team1_data['sos_norm']:.4f} × {weights['sos_weight']:.2f} = {sos1_contrib:.4f}")
    print(f"   {team2_name:30s}: {team2_data['sos_norm']:.4f} × {weights['sos_weight']:.2f} = {sos2_contrib:.4f}")
    sos_diff = sos2_contrib - sos1_contrib
    winner = team2_name if sos_diff > 0 else team1_name
    print(f"   → Advantage: {winner} by {abs(sos_diff):.4f}")

    # Offense
    off1_contrib = team1_data['offense_norm'] * weights['off_weight']
    off2_contrib = team2_data['offense_norm'] * weights['off_weight']
    print(f"\n2. Offense (Weight: {weights['off_weight']*100:.0f}%)")
    print(f"   {team1_name:30s}: {team1_data['offense_norm']:.4f} × {weights['off_weight']:.2f} = {off1_contrib:.4f}")
    print(f"   {team2_name:30s}: {team2_data['offense_norm']:.4f} × {weights['off_weight']:.2f} = {off2_contrib:.4f}")
    off_diff = off1_contrib - off2_contrib
    winner = team1_name if off_diff > 0 else team2_name
    print(f"   → Advantage: {winner} by {abs(off_diff):.4f}")

    # Defense
    def1_contrib = team1_data['defense_norm'] * weights['def_weight']
    def2_contrib = team2_data['defense_norm'] * weights['def_weight']
    print(f"\n3. Defense (Weight: {weights['def_weight']*100:.0f}%)")
    print(f"   {team1_name:30s}: {team1_data['defense_norm']:.4f} × {weights['def_weight']:.2f} = {def1_contrib:.4f}")
    print(f"   {team2_name:30s}: {team2_data['defense_norm']:.4f} × {weights['def_weight']:.2f} = {def2_contrib:.4f}")
    def_diff = def1_contrib - def2_contrib
    winner = team1_name if def_diff > 0 else team2_name
    print(f"   → Advantage: {winner} by {abs(def_diff):.4f}")

    # Total
    total1 = sos1_contrib + off1_contrib + def1_contrib
    total2 = sos2_contrib + off2_contrib + def2_contrib

    print(f"\n{'NET RESULT':^100}")
    print("="*100)
    print(f"{team1_name:30s}: {sos1_contrib:.4f} + {off1_contrib:.4f} + {def1_contrib:.4f} = {total1:.4f}")
    print(f"{team2_name:30s}: {sos2_contrib:.4f} + {off2_contrib:.4f} + {def2_contrib:.4f} = {total2:.4f}")
    print(f"\n{'Final Winner':30s}: {team1_name if total1 > total2 else team2_name} by {abs(total1 - total2):.6f}")

    # Show what SOS weight would be needed to flip the result
    print(f"\n{'SENSITIVITY ANALYSIS':^100}")
    print("="*100)

    # Calculate what SOS weight would make them equal
    # We want: sos_w * (sos2 - sos1) = (1-sos_w) * [(off1-off2) + (def1-def2)] / 2
    # Simplifying: (off1 + def1) - (off2 + def2) = sos_w * [sos2 - sos1] - (1-sos_w) * [(off1-off2) + (def1-def2)]

    sos_delta = team2_data['sos_norm'] - team1_data['sos_norm']
    off_delta = team1_data['offense_norm'] - team2_data['offense_norm']
    def_delta = team1_data['defense_norm'] - team2_data['defense_norm']

    if sos_delta != 0:
        # Find SOS weight that would flip the result
        for test_sos_weight in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
            test_off_weight = (1 - test_sos_weight) / 2
            test_def_weight = (1 - test_sos_weight) / 2

            score1 = (test_sos_weight * team1_data['sos_norm'] +
                     test_off_weight * team1_data['offense_norm'] +
                     test_def_weight * team1_data['defense_norm'])
            score2 = (test_sos_weight * team2_data['sos_norm'] +
                     test_off_weight * team2_data['offense_norm'] +
                     test_def_weight * team2_data['defense_norm'])

            diff = score1 - score2
            winner = team1_name if diff > 0 else team2_name

            print(f"SOS Weight = {test_sos_weight*100:3.0f}% (OFF/DEF = {test_off_weight*100:4.1f}% each): "
                  f"{score1:.4f} vs {score2:.4f} → {winner} by {abs(diff):.6f}")

    print("\n")


def main():
    # PRFC Scottsdale vs Dynamos SC data
    prfc_data = {
        'team_name': 'PRFC Scottsdale 14B Pre-Academy',
        'sos_norm': 0.745094391647912,
        'offense_norm': 0.862994438111424,
        'defense_norm': 0.924490455434377,
        'power_score_final': 0.469726964338811,
        'rank': 109,
        'state_rank': 4
    }

    dynamos_data = {
        'team_name': 'Dynamos SC 14B SC',
        'sos_norm': 0.849912408846438,
        'offense_norm': 0.590158996464718,
        'defense_norm': 0.910145134330495,
        'power_score_final': 0.469632835958009,
        'rank': 111,
        'state_rank': 5
    }

    analyze_teams(
        prfc_data['team_name'], prfc_data,
        dynamos_data['team_name'], dynamos_data
    )

    # Key insight
    print("="*100)
    print("KEY INSIGHT")
    print("="*100)
    print("""
PRFC Scottsdale has a higher power score despite weaker SOS because:

1. OFFENSE DOMINANCE: PRFC's offense (86.3%ile) is 27.3 percentile points better than Dynamos (59.0%ile)
   - This translates to a +0.0682 advantage (27.3% × 0.25 weight)

2. DEFENSIVE EDGE: PRFC's defense (92.5%ile) is 1.4 points better than Dynamos (91.0%ile)
   - This translates to a +0.0036 advantage (1.4% × 0.25 weight)

3. SOS DISADVANTAGE: Dynamos' SOS (85.0%ile) is 10.5 points better than PRFC (74.5%ile)
   - This translates to a +0.0524 advantage for Dynamos (10.5% × 0.50 weight)

NET RESULT: PRFC's offense/defense advantage (+0.0718) > Dynamos' SOS advantage (+0.0524)
            PRFC wins by +0.0194 in the formula

THE ISSUE: PRFC is DOMINATING weaker opponents (high offense/defense scores)
           Dynamos is STRUGGLING against stronger opponents (low offense score)

           The question is: Should dominating weak opponents count more than
           competing respectably against strong opponents?

RECOMMENDATION: Consider increasing SOS weight to 60-70% if you want to further
                penalize teams that play weaker schedules.
    """)


if __name__ == "__main__":
    main()
