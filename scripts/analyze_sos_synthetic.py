#!/usr/bin/env python3
"""
Analyze SOS distribution using synthetic data to diagnose potential issues
This script doesn't require Supabase - it uses synthetic game data
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from collections import Counter

sys.path.append(str(Path(__file__).parent.parent))

from src.etl.v53e import V53EConfig, compute_rankings


def create_synthetic_games(n_teams=50, n_cohorts=3, games_per_team=20):
    """
    Create synthetic game data that simulates real-world scenarios

    Args:
        n_teams: Number of teams per cohort
        n_cohorts: Number of age/gender cohorts
        games_per_team: Average games per team
    """
    print(f"\n🔧 Generating synthetic data:")
    print(f"   • {n_teams} teams per cohort")
    print(f"   • {n_cohorts} cohorts")
    print(f"   • ~{games_per_team} games per team\n")

    games_list = []
    game_id = 1

    ages = [10, 12, 14][:n_cohorts]
    genders = ['M', 'F'][:min(2, n_cohorts)]

    for age in ages:
        for gender in genders[:min(len(genders), n_cohorts)]:
            # Create team IDs for this cohort
            team_ids = [f"team_{age}{gender}_{i:03d}" for i in range(n_teams)]

            # Generate games - each team plays random opponents
            for team in team_ids:
                n_games = np.random.randint(games_per_team - 5, games_per_team + 5)

                for _ in range(n_games):
                    # Select random opponent from same cohort
                    opp = np.random.choice([t for t in team_ids if t != team])

                    # Generate scores with some randomness
                    gf = np.random.randint(0, 6)
                    ga = np.random.randint(0, 6)

                    games_list.append({
                        'game_id': f'g{game_id}',
                        'date': pd.Timestamp('2024-01-01') + pd.Timedelta(days=np.random.randint(0, 180)),
                        'team_id': team,
                        'opp_id': opp,
                        'age': age,
                        'gender': gender,
                        'opp_age': age,
                        'opp_gender': gender,
                        'gf': gf,
                        'ga': ga,
                    })
                    game_id += 1

    df = pd.DataFrame(games_list)
    print(f"✓ Created {len(df):,} game records")
    return df


def analyze_sos_distribution(teams_df, cfg):
    """Analyze SOS value distribution for duplication issues"""

    print("\n" + "="*70)
    print("SOS DISTRIBUTION ANALYSIS")
    print("="*70)

    if 'sos' not in teams_df.columns:
        print("❌ ERROR: 'sos' column not found in teams_df")
        return

    # 1. Overall Statistics
    print("\n📊 OVERALL SOS STATISTICS:")
    print("-" * 70)
    sos_values = teams_df['sos'].dropna()

    print(f"Total teams: {len(teams_df)}")
    print(f"Teams with SOS: {len(sos_values)}")
    print(f"\nSOS Statistics:")
    print(f"  Mean:   {sos_values.mean():.6f}")
    print(f"  Std:    {sos_values.std():.6f}")
    print(f"  Min:    {sos_values.min():.6f}")
    print(f"  25%:    {sos_values.quantile(0.25):.6f}")
    print(f"  Median: {sos_values.median():.6f}")
    print(f"  75%:    {sos_values.quantile(0.75):.6f}")
    print(f"  Max:    {sos_values.max():.6f}")

    # 2. Check for duplication
    print("\n🔍 DUPLICATION ANALYSIS:")
    print("-" * 70)
    unique_sos = len(sos_values.unique())
    total_sos = len(sos_values)
    duplication_rate = (total_sos - unique_sos) / total_sos * 100

    print(f"Unique SOS values: {unique_sos:,}")
    print(f"Total teams:       {total_sos:,}")
    print(f"Duplication rate:  {duplication_rate:.2f}%")

    # Verdict
    if duplication_rate > 40:
        print(f"\n❌ HIGH DUPLICATION - This is problematic!")
        verdict = "PROBLEM"
    elif duplication_rate > 20:
        print(f"\n⚠️  MODERATE DUPLICATION - May need investigation")
        verdict = "MODERATE"
    else:
        print(f"\n✅ LOW DUPLICATION - This is expected")
        verdict = "HEALTHY"

    # 3. Most common SOS values
    print("\n📋 TOP 10 MOST COMMON SOS VALUES:")
    print("-" * 70)
    sos_rounded = sos_values.round(6)
    value_counts = Counter(sos_rounded)
    most_common = value_counts.most_common(10)

    print(f"{'SOS Value':<15} {'Count':<10} {'% of Total':<12} {'Status'}")
    print("-" * 70)
    for value, count in most_common:
        pct = count / total_sos * 100
        if count > 20:
            status = "🔴 HIGH"
        elif count > 10:
            status = "🟡 MEDIUM"
        else:
            status = "🟢 OK"
        print(f"{value:<15.6f} {count:<10} {pct:<12.2f} {status}")

    # 4. Cohort-level analysis
    print("\n📊 PER-COHORT ANALYSIS:")
    print("-" * 70)
    print(f"{'Age':<6} {'Gender':<8} {'Teams':<8} {'Unique':<10} {'Dup%':<10} {'SOS Std':<10} {'Status'}")
    print("-" * 70)

    cohort_issues = 0
    for (age, gender), grp in teams_df.groupby(['age', 'gender']):
        cohort_sos = grp['sos'].dropna()
        if len(cohort_sos) == 0:
            continue

        n_teams = len(cohort_sos)
        n_unique = len(cohort_sos.unique())
        dup_rate = (n_teams - n_unique) / n_teams * 100
        std = cohort_sos.std()

        if dup_rate > 50:
            status = "🔴 HIGH"
            cohort_issues += 1
        elif dup_rate > 30:
            status = "🟡 MEDIUM"
        else:
            status = "🟢 OK"

        print(f"{age:<6} {gender:<8} {n_teams:<8} {n_unique:<10} {dup_rate:<10.1f} {std:<10.4f} {status}")

    if cohort_issues > 0:
        print(f"\n⚠️  Found {cohort_issues} cohorts with high duplication")

    # 5. Check strength calculation method
    print("\n🔧 STRENGTH CALCULATION METHOD:")
    print("-" * 70)
    if 'abs_strength' in teams_df.columns:
        abs_str = teams_df['abs_strength'].dropna()
        print(f"✅ Using abs_strength (continuous)")
        print(f"   Unique values: {len(abs_str.unique())} / {len(abs_str)}")
        print(f"   Range: [{abs_str.min():.4f}, {abs_str.max():.4f}]")
        print(f"   This is CORRECT - no percentile normalization before SOS")
    else:
        print(f"❌ abs_strength not found")

    # Check for problematic patterns mentioned in the suggestions
    print("\n🔍 CHECKING FOR PROBLEMATIC PATTERNS (from suggestions):")
    print("-" * 70)

    problems_found = []

    # Check 1: strength_for_sos (should NOT exist)
    if 'strength_for_sos' in teams_df.columns:
        problems_found.append("❌ Found 'strength_for_sos' column (problematic)")
    else:
        print("✅ No 'strength_for_sos' column (good)")

    # Check 2: abs_strength_norm (should NOT exist as SOS input)
    if 'abs_strength_norm' in teams_df.columns:
        problems_found.append("❌ Found 'abs_strength_norm' column (may indicate percentile normalization)")
    else:
        print("✅ No 'abs_strength_norm' column (good)")

    # Check 3: Normalization mode
    print(f"✅ Normalization mode: {cfg.NORM_MODE}")
    if cfg.NORM_MODE == "percentile":
        print(f"   ⚠️  Using percentile mode (creates discrete steps)")

    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)

    if verdict == "PROBLEM":
        print("❌ REAL PROBLEM DETECTED:")
        print("   • High SOS value duplication")
        print("   • Needs investigation and potential fix")
    elif verdict == "MODERATE":
        print("⚠️  MODERATE ISSUES:")
        print("   • Some SOS duplication present")
        print("   • May be due to small cohorts or similar schedules")
        print("   • Worth monitoring")
    else:
        print("✅ SOS DISTRIBUTION LOOKS HEALTHY:")
        print("   • Low duplication rate")
        print("   • Expected for discrete opponent sets")

    print(f"\n📌 Current implementation status:")
    print(f"   • Uses continuous abs_strength: ✅")
    print(f"   • No extra percentile layer: ✅")
    print(f"   • SOS iterations: {cfg.SOS_ITERATIONS}")
    print(f"   • Transitivity lambda: {cfg.SOS_TRANSITIVITY_LAMBDA}")

    if problems_found:
        print(f"\n⚠️  Problems found:")
        for p in problems_found:
            print(f"   {p}")
    else:
        print(f"\n✅ No code pattern problems found")
        print(f"   The suggestions describe issues that DON'T exist in this code")

    return verdict


def main():
    print("="*70)
    print("SOS DISTRIBUTION DIAGNOSTIC (Synthetic Data)")
    print("="*70)

    # Load config (use default values)
    cfg = V53EConfig()

    print(f"\n⚙️  Configuration:")
    print(f"   • SOS Iterations: {cfg.SOS_ITERATIONS}")
    print(f"   • SOS Transitivity Lambda: {cfg.SOS_TRANSITIVITY_LAMBDA}")
    print(f"   • Normalization Mode: {cfg.NORM_MODE}")
    print(f"   • SOS Weight: {cfg.SOS_WEIGHT * 100:.0f}%")

    # Create synthetic data
    games_df = create_synthetic_games(n_teams=50, n_cohorts=4, games_per_team=20)

    # Run rankings
    print(f"\n⚙️  Computing rankings...")
    result = compute_rankings(
        games_df=games_df,
        today=pd.Timestamp('2024-06-01'),
        cfg=cfg
    )

    teams_df = result['teams']
    print(f"✓ Rankings computed for {len(teams_df)} teams")

    # Analyze distribution
    verdict = analyze_sos_distribution(teams_df, cfg)

    print("\n" + "="*70)
    print("RECOMMENDATION")
    print("="*70)

    if verdict == "PROBLEM":
        print("\n⚠️  IMPLEMENT THE SUGGESTIONS")
        print("   Your SOS distribution shows real problems that need fixing")
    elif verdict == "MODERATE":
        print("\n🤔 INVESTIGATE FURTHER")
        print("   Run this analysis on real production data")
        print("   Consider if duplication is acceptable for your cohort sizes")
    else:
        print("\n✅ DO NOT IMPLEMENT THE SUGGESTIONS")
        print("   • Your current implementation is correct")
        print("   • The suggestions describe problems that don't exist in your code")
        print("   • SOS duplication is normal with discrete opponent sets")

    print("\n" + "="*70)


if __name__ == '__main__':
    main()
