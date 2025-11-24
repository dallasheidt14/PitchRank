#!/usr/bin/env python3
"""
v54 Validation Script for PitchRank Rankings Engine

Run this inside your project environment. This script validates:
1. PowerScore bounds
2. SOS distribution
3. Anchor scaling correctness
4. Performance distribution sanity
5. Sample-size fairness
6. Cross-age scaling behavior
7. Rank volatility (optional if previous snapshot exists)
"""
import pandas as pd
import numpy as np
import sys
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path("data/validation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RANKINGS_FILE = OUTPUT_DIR / f"rankings_after_v54_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
OUTPUT_STATS = OUTPUT_DIR / f"v54_validation_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# Anchor mapping used by v54
ANCHORS = {
    10: 0.400,
    11: 0.475,
    12: 0.550,
    13: 0.625,
    14: 0.700,
    15: 0.775,
    16: 0.850,
    17: 0.925,
    18: 1.000,
    19: 1.000,
}

# ---------------------------------------------------------------------------
# LOAD DATA FROM SUPABASE
# ---------------------------------------------------------------------------
def fetch_rankings_from_supabase():
    """Fetch all rankings from Supabase rankings_full table"""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    
    supabase = create_client(supabase_url, supabase_key)
    
    print("📥 Fetching rankings from Supabase...")
    
    # Fetch all rankings with pagination
    all_rankings = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('rankings_full').select(
            'team_id, age_group, gender, power_score_final, '
            'sos_norm, off_norm, def_norm, perf_centered, '
            'games_played, sample_flag, powerscore_adj, powerscore_ml, '
            'rank_in_cohort, status'
        ).range(offset, offset + page_size - 1).execute()
        
        if not result.data:
            break
        
        all_rankings.extend(result.data)
        
        if len(result.data) < page_size:
            break
        
        offset += page_size
        if offset % 10000 == 0:
            print(f"  Fetched {offset:,} rankings...")
    
    print(f"✅ Fetched {len(all_rankings):,} total rankings")
    
    df = pd.DataFrame(all_rankings)
    
    # Use power_score_final, fallback to powerscore_ml or powerscore_adj
    if 'power_score_final' in df.columns:
        df['power_score_final'] = df['power_score_final'].fillna(
            df.get('powerscore_ml', pd.Series())).fillna(
            df.get('powerscore_adj', pd.Series()))
    
    return df

# ---------------------------------------------------------------------------
# VALIDATION FUNCTIONS
# ---------------------------------------------------------------------------
def validate_power_score_bounds(df):
    """1. CHECK POWER SCORE BOUNDS (must be 0–1)"""
    out_of_bounds = df[(df["power_score_final"] < 0) | (df["power_score_final"] > 1)]
    return out_of_bounds

def validate_sos_distribution(df):
    """2. CHECK SOS DISTRIBUTION"""
    sos_stats = df["sos_norm"].describe()
    return sos_stats

def validate_anchor_scaling(df):
    """3. CHECK ANCHOR SCALING BY AGE"""
    # Extract numeric age
    df["age_num"] = df["age_group"].str.extract(r"(\d+)").astype(int)
    
    anchor_checks = (
        df.groupby("age_num")["power_score_final"].max()
          .reset_index()
          .rename(columns={"power_score_final": "max_ps"})
    )
    anchor_checks["expected_ceiling"] = anchor_checks["age_num"].map(ANCHORS)
    anchor_checks["over_ceiling"] = anchor_checks["max_ps"] > anchor_checks["expected_ceiling"]
    
    return anchor_checks

def validate_performance_distribution(df):
    """4. PERFORMANCE DISTRIBUTION"""
    perf_extreme = df[df["perf_centered"].abs() > 0.4]
    perf_stats = df["perf_centered"].describe()
    return perf_stats, perf_extreme

def validate_sample_fairness(df):
    """5. SAMPLE SIZE FAIRNESS (LOW_SAMPLE shrink check)"""
    low = df[df["sample_flag"] == "LOW_SAMPLE"]
    ok = df[df["sample_flag"] == "OK"]
    
    low_sos_std = low["sos_norm"].std() if len(low) > 0 else np.nan
    ok_sos_std = ok["sos_norm"].std() if len(ok) > 0 else np.nan
    
    return low_sos_std, ok_sos_std, len(low), len(ok)

def validate_cross_age_scaling(df):
    """6. CROSS-AGE SCALING CHECK (anchor curve monotonicity)"""
    if "age_num" not in df.columns:
        df["age_num"] = df["age_group"].str.extract(r"(\d+)").astype(int)
    
    # For each age, compute mean PowerScore
    age_curve = df.groupby("age_num")["power_score_final"].agg(['mean', 'min', 'max', 'count'])
    return age_curve

def print_validation_report(df, out_of_bounds, sos_stats, anchor_checks, 
                           perf_stats, perf_extreme, low_sos_std, ok_sos_std,
                           low_count, ok_count, age_curve):
    """Print human-readable validation report"""
    print("\n" + "=" * 60)
    print("V54 COMPREHENSIVE VALIDATION SUMMARY")
    print("=" * 60)
    
    print(f"\n📊 Total Teams Validated: {len(df):,}")
    print(f"   Age Groups: {sorted(df['age_num'].unique()) if 'age_num' in df.columns else 'N/A'}")
    
    # 1. PowerScore Bounds
    print(f"\n1️⃣  PowerScore Bounds Check:")
    print(f"   Teams with PowerScore > 1 or < 0: {len(out_of_bounds)}")
    if len(out_of_bounds) > 0:
        print("   ⚠️  OUT OF BOUNDS TEAMS:")
        print(out_of_bounds[["team_id", "age_group", "power_score_final"]].head(10).to_string())
    else:
        print("   ✅ All PowerScore values within [0, 1] bounds")
    
    # 2. SOS Distribution
    print(f"\n2️⃣  SOS Distribution:")
    print(f"   Mean: {sos_stats['mean']:.4f}")
    print(f"   Std:  {sos_stats['std']:.4f}")
    print(f"   Min:  {sos_stats['min']:.4f}")
    print(f"   Max:  {sos_stats['max']:.4f}")
    
    # 3. Anchor Scaling
    print(f"\n3️⃣  Anchor Scaling Check:")
    print(anchor_checks.to_string())
    over_ceiling = anchor_checks[anchor_checks["over_ceiling"]]
    if len(over_ceiling) > 0:
        print(f"   ⚠️  {len(over_ceiling)} age groups exceed expected anchor ceiling")
    else:
        print("   ✅ All age groups respect anchor ceilings")
    
    # 4. Performance Distribution
    print(f"\n4️⃣  Performance Distribution:")
    print(f"   Mean: {perf_stats['mean']:.4f}")
    print(f"   Std:  {perf_stats['std']:.4f}")
    print(f"   Min:  {perf_stats['min']:.4f}")
    print(f"   Max:  {perf_stats['max']:.4f}")
    print(f"   Extreme performance count (|perf_centered| > 0.4): {len(perf_extreme)} teams ({len(perf_extreme)/len(df)*100:.1f}%)")
    
    # 5. Sample Size Fairness
    print(f"\n5️⃣  Sample Size Fairness:")
    print(f"   LOW_SAMPLE teams: {low_count:,}")
    print(f"   LOW_SAMPLE SOS std: {low_sos_std:.4f}")
    print(f"   OK teams: {ok_count:,}")
    print(f"   OK SOS std: {ok_sos_std:.4f}")
    if not np.isnan(low_sos_std) and not np.isnan(ok_sos_std):
        if low_sos_std < ok_sos_std:
            print("   ✅ LOW_SAMPLE has lower variance (proper shrinkage)")
        else:
            print("   ⚠️  LOW_SAMPLE variance not reduced as expected")
    
    # 6. Cross-age Scaling
    print(f"\n6️⃣  Cross-Age Anchor Curve (mean PowerScore per age):")
    print(age_curve.to_string())
    
    # Check monotonicity
    if len(age_curve) > 1:
        means = age_curve['mean'].sort_index()
        is_monotonic = all(means.iloc[i] <= means.iloc[i+1] for i in range(len(means)-1))
        if is_monotonic:
            print("   ✅ Anchor curve is monotonic (increasing with age)")
        else:
            print("   ⚠️  Anchor curve is NOT monotonic")
    
    print("\n" + "=" * 60)

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    try:
        # Fetch data
        df = fetch_rankings_from_supabase()
        
        if df.empty:
            print("❌ No rankings data found")
            return
        
        # Ensure required columns exist
        required_cols = [
            "team_id", "age_group", "gender", "power_score_final",
            "sos_norm", "off_norm", "def_norm", "perf_centered",
            "games_played", "sample_flag"
        ]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Extract numeric age
        df["age_num"] = df["age_group"].str.extract(r"(\d+)").astype(int)
        
        # Run validations
        print("\n🔍 Running validations...")
        
        out_of_bounds = validate_power_score_bounds(df)
        sos_stats = validate_sos_distribution(df)
        anchor_checks = validate_anchor_scaling(df)
        perf_stats, perf_extreme = validate_performance_distribution(df)
        low_sos_std, ok_sos_std, low_count, ok_count = validate_sample_fairness(df)
        age_curve = validate_cross_age_scaling(df)
        
        # Print report
        print_validation_report(df, out_of_bounds, sos_stats, anchor_checks,
                               perf_stats, perf_extreme, low_sos_std, ok_sos_std,
                               low_count, ok_count, age_curve)
        
        # Export data
        print(f"\n💾 Exporting rankings to {RANKINGS_FILE}...")
        df.to_csv(RANKINGS_FILE, index=False)
        print(f"✅ Exported {len(df):,} rankings")
        
        # Export summary stats
        summary = {
            "num_teams": len(df),
            "num_out_of_bounds": len(out_of_bounds),
            "sos_mean": sos_stats["mean"],
            "sos_std": sos_stats["std"],
            "sos_min": sos_stats["min"],
            "sos_max": sos_stats["max"],
            "perf_mean": perf_stats["mean"],
            "perf_std": perf_stats["std"],
            "perf_extreme_count": len(perf_extreme),
            "perf_extreme_pct": len(perf_extreme) / len(df) * 100 if len(df) > 0 else 0,
            "low_sample_count": low_count,
            "low_sample_sos_std": low_sos_std,
            "ok_sample_count": ok_count,
            "ok_sample_sos_std": ok_sos_std,
        }
        summary_df = pd.DataFrame([summary])
        summary_df.to_csv(OUTPUT_STATS, index=False)
        print(f"✅ Exported validation stats to {OUTPUT_STATS}")
        
        print("\n✅ Validation complete!")
        
    except Exception as e:
        print(f"\n❌ Error during validation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

