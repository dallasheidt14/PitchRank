#!/usr/bin/env python3
"""
Diagnose SOS compression issue in rankings.

This script checks if the global min-max scaling of sos_norm
is compressing the effective contribution of SOS to PowerScore.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()


def analyze_sos_compression():
    """Analyze SOS normalization compression per cohort."""

    # Connect to Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: Missing SUPABASE_URL or SUPABASE_KEY")
        return

    client = create_client(supabase_url, supabase_key)

    # Fetch rankings data
    print("Fetching rankings data...")
    result = client.table('rankings_full').select(
        'team_id, age_group, gender, sos_norm, off_norm, def_norm, '
        'powerscore_core, powerscore_adj, rank_in_cohort, games_played, status'
    ).eq('status', 'Active').execute()

    if not result.data:
        print("No active rankings found")
        return

    df = pd.DataFrame(result.data)
    print(f"Loaded {len(df):,} active teams\n")

    # Analyze per cohort
    print("=" * 80)
    print("SOS COMPRESSION ANALYSIS BY COHORT")
    print("=" * 80)
    print(f"{'Cohort':<15} {'Teams':>6} {'SOS Range':>12} {'OFF Range':>12} {'DEF Range':>12} {'SOS Contrib':>12}")
    print("-" * 80)

    issues = []

    for (age, gender), cohort in df.groupby(['age_group', 'gender']):
        if len(cohort) < 5:
            continue

        sos_min = cohort['sos_norm'].min()
        sos_max = cohort['sos_norm'].max()
        sos_range = sos_max - sos_min

        off_min = cohort['off_norm'].min()
        off_max = cohort['off_norm'].max()
        off_range = off_max - off_min

        def_min = cohort['def_norm'].min()
        def_max = cohort['def_norm'].max()
        def_range = def_max - def_min

        # Effective contribution to PowerScore spread
        # SOS has 50% weight, OFF/DEF have 25% each
        sos_contrib = sos_range * 0.50
        off_contrib = off_range * 0.25
        def_contrib = def_range * 0.25
        total_contrib = sos_contrib + off_contrib + def_contrib

        # SOS should be ~50% of total contribution
        sos_pct = (sos_contrib / total_contrib * 100) if total_contrib > 0 else 0

        cohort_name = f"U{age} {gender[:1].upper()}"

        flag = ""
        if sos_pct < 40:
            flag = " ⚠️ LOW"
            issues.append((cohort_name, sos_pct, sos_range))

        print(f"{cohort_name:<15} {len(cohort):>6} {sos_range:>11.3f}  {off_range:>11.3f}  {def_range:>11.3f}  {sos_pct:>10.1f}%{flag}")

    print("-" * 80)

    # Check for anomalies: teams with low SOS rank but high overall rank
    print("\n" + "=" * 80)
    print("ANOMALY CHECK: Teams with Low SOS but High Rank")
    print("=" * 80)

    for (age, gender), cohort in df.groupby(['age_group', 'gender']):
        if len(cohort) < 20:
            continue

        cohort = cohort.copy()
        # Calculate SOS rank within cohort
        cohort['sos_rank'] = cohort['sos_norm'].rank(ascending=False, method='min')
        cohort['overall_rank'] = cohort['rank_in_cohort']

        total_teams = len(cohort)

        # Find teams in top 10% overall but bottom 30% SOS
        top_overall = total_teams * 0.10
        bottom_sos = total_teams * 0.70  # rank > 70th percentile = weak SOS

        anomalies = cohort[
            (cohort['overall_rank'] <= top_overall) &
            (cohort['sos_rank'] > bottom_sos)
        ]

        if len(anomalies) > 0:
            cohort_name = f"U{age} {gender[:1].upper()}"
            print(f"\n{cohort_name} ({total_teams} teams):")
            for _, row in anomalies.iterrows():
                print(f"  Rank #{int(row['overall_rank'])}: "
                      f"SOS rank {int(row['sos_rank'])}/{total_teams} "
                      f"(sos_norm={row['sos_norm']:.3f}, "
                      f"off={row['off_norm']:.3f}, def={row['def_norm']:.3f})")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if issues:
        print(f"\n⚠️  {len(issues)} cohorts have SOS contributing < 40% to ranking spread:")
        for cohort_name, sos_pct, sos_range in sorted(issues, key=lambda x: x[1]):
            print(f"   {cohort_name}: SOS contributes {sos_pct:.1f}% (range={sos_range:.3f})")

        print("\n🔧 RECOMMENDED FIX:")
        print("   Change sos_norm to be normalized WITHIN each cohort (age+gender),")
        print("   not globally. This ensures SOS has full [0,1] range in each cohort.")
    else:
        print("✅ SOS contribution looks healthy across all cohorts")


if __name__ == '__main__':
    analyze_sos_compression()
