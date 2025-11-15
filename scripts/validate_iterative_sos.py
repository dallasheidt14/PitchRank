#!/usr/bin/env python3
"""
Validation script for iterative SOS implementation.

Compares legacy vs. hybrid iterative SOS to show improvements in:
- SOS variance (reduced "flat SOS" problem)
- Fallback pollution (fewer 0.5 values)
- Coverage gaps (better handling of missing opponents)

Usage:
    python scripts/validate_iterative_sos.py
    python scripts/validate_iterative_sos.py --age 12 --gender male
    python scripts/validate_iterative_sos.py --comparison  # Side-by-side comparison
"""

import sys
import os
import logging
import argparse
import pandas as pd
import numpy as np
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.etl.v53e import compute_rankings, V53EConfig
from src.rankings.data_adapter import fetch_games_for_rankings

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_sos_distribution(teams_df: pd.DataFrame, label: str):
    """Analyze and print SOS distribution statistics."""
    print(f"\n{'=' * 60}")
    print(f"{label}")
    print(f"{'=' * 60}")

    # Overall statistics
    sos_values = teams_df["sos"].dropna()
    print(f"\n📊 Overall SOS Statistics:")
    print(f"   Count:    {len(sos_values):>8,}")
    print(f"   Mean:     {sos_values.mean():>8.4f}")
    print(f"   Std Dev:  {sos_values.std():>8.4f}")
    print(f"   Min:      {sos_values.min():>8.4f}")
    print(f"   25th %ile:{sos_values.quantile(0.25):>8.4f}")
    print(f"   Median:   {sos_values.median():>8.4f}")
    print(f"   75th %ile:{sos_values.quantile(0.75):>8.4f}")
    print(f"   Max:      {sos_values.max():>8.4f}")

    # Check for fallback pollution (values exactly at 0.5)
    exact_half = (sos_values == 0.5).sum()
    near_half = ((sos_values > 0.49) & (sos_values < 0.51)).sum()
    print(f"\n🔍 Fallback Pollution Check:")
    print(f"   Exactly 0.5:      {exact_half:>6,} ({exact_half/len(sos_values)*100:>5.1f}%)")
    print(f"   Near 0.5 (±0.01): {near_half:>6,} ({near_half/len(sos_values)*100:>5.1f}%)")

    # Unique value count
    unique_count = sos_values.nunique()
    print(f"\n🎯 SOS Variance:")
    print(f"   Unique values:    {unique_count:>6,} ({unique_count/len(sos_values)*100:>5.1f}%)")

    # Per-cohort statistics
    print(f"\n📈 Per-Cohort Statistics:")
    cohort_stats = teams_df.groupby(["age", "gender"]).agg({
        "sos": ["count", "mean", "std", "min", "max"]
    }).round(4)
    print(cohort_stats.to_string())

    # Top/Bottom teams by SOS
    print(f"\n🔝 Top 10 Teams by SOS:")
    top_teams = teams_df.nlargest(10, "sos")[["team_id", "age", "gender", "sos", "sos_norm", "powerscore_adj"]]
    print(top_teams.to_string(index=False))

    print(f"\n🔻 Bottom 10 Teams by SOS:")
    bottom_teams = teams_df.nsmallest(10, "sos")[["team_id", "age", "gender", "sos", "sos_norm", "powerscore_adj"]]
    print(bottom_teams.to_string(index=False))


def compare_legacy_vs_iterative(games_df: pd.DataFrame, age_filter=None, gender_filter=None):
    """Compare legacy single-pass SOS vs. hybrid iterative SOS."""

    # Filter games if requested
    if age_filter:
        games_df = games_df[games_df["age"] == str(age_filter)]
    if gender_filter:
        games_df = games_df[games_df["gender"].str.lower() == gender_filter.lower()]

    print(f"\n{'=' * 60}")
    print(f"Comparison: Legacy vs. Iterative SOS")
    print(f"{'=' * 60}")
    print(f"Games: {len(games_df):,}")
    if age_filter:
        print(f"Age filter: {age_filter}")
    if gender_filter:
        print(f"Gender filter: {gender_filter}")

    # Run legacy SOS
    logger.info("Running LEGACY SOS calculation...")
    cfg_legacy = V53EConfig()
    cfg_legacy.ENABLE_ITERATIVE_SOS = False
    result_legacy = compute_rankings(games_df, cfg=cfg_legacy)
    teams_legacy = result_legacy["teams"]

    # Run iterative SOS
    logger.info("\nRunning ITERATIVE SOS calculation...")
    cfg_iterative = V53EConfig()
    cfg_iterative.ENABLE_ITERATIVE_SOS = True
    cfg_iterative.SOS_STRENGTH_ITERATIONS = 3
    result_iterative = compute_rankings(games_df, cfg=cfg_iterative)
    teams_iterative = result_iterative["teams"]

    # Analyze both
    analyze_sos_distribution(teams_legacy, "LEGACY SOS (Single-Pass)")
    analyze_sos_distribution(teams_iterative, "ITERATIVE SOS (3 Passes)")

    # Direct comparison
    print(f"\n{'=' * 60}")
    print(f"IMPROVEMENT SUMMARY")
    print(f"{'=' * 60}")

    legacy_std = teams_legacy["sos"].std()
    iterative_std = teams_iterative["sos"].std()
    std_improvement = ((iterative_std - legacy_std) / legacy_std * 100) if legacy_std > 0 else 0

    legacy_half = (teams_legacy["sos"] == 0.5).sum()
    iterative_half = (teams_iterative["sos"] == 0.5).sum()
    half_reduction = legacy_half - iterative_half

    legacy_unique = teams_legacy["sos"].nunique()
    iterative_unique = teams_iterative["sos"].nunique()
    unique_improvement = iterative_unique - legacy_unique

    print(f"\n📊 Variance Improvement:")
    print(f"   Legacy std:       {legacy_std:.4f}")
    print(f"   Iterative std:    {iterative_std:.4f}")
    print(f"   Change:           {std_improvement:+.1f}%")

    print(f"\n🔍 Fallback Pollution Reduction:")
    print(f"   Legacy 0.5 count:     {legacy_half:>6,}")
    print(f"   Iterative 0.5 count:  {iterative_half:>6,}")
    print(f"   Reduction:            {half_reduction:>6,} ({half_reduction/legacy_half*100:+.1f}%)")

    print(f"\n🎯 Unique Value Increase:")
    print(f"   Legacy unique:    {legacy_unique:>6,}")
    print(f"   Iterative unique: {iterative_unique:>6,}")
    print(f"   Increase:         {unique_improvement:>6,} ({unique_improvement/legacy_unique*100:+.1f}%)")

    # Correlation between legacy and iterative SOS
    merged = teams_legacy[["team_id", "sos"]].merge(
        teams_iterative[["team_id", "sos"]],
        on="team_id",
        suffixes=("_legacy", "_iterative")
    )
    correlation = merged["sos_legacy"].corr(merged["sos_iterative"])
    print(f"\n🔗 Correlation between legacy and iterative SOS: {correlation:.4f}")

    # Teams with biggest changes
    merged["sos_delta"] = (merged["sos_iterative"] - merged["sos_legacy"]).abs()
    merged = merged.merge(teams_iterative[["team_id", "age", "gender"]], on="team_id", how="left")

    print(f"\n📈 Teams with Biggest SOS Changes:")
    top_changes = merged.nlargest(10, "sos_delta")[
        ["team_id", "age", "gender", "sos_legacy", "sos_iterative", "sos_delta"]
    ]
    print(top_changes.to_string(index=False))


async def main():
    parser = argparse.ArgumentParser(description="Validate iterative SOS implementation")
    parser.add_argument("--age", type=int, help="Filter by age group")
    parser.add_argument("--gender", type=str, help="Filter by gender (male/female)")
    parser.add_argument("--comparison", action="store_true", help="Run side-by-side comparison")
    parser.add_argument("--lookback-days", type=int, default=365, help="Lookback window in days")
    args = parser.parse_args()

    # Initialize Supabase client
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment")
        return 1

    supabase: Client = create_client(supabase_url, supabase_key)

    # Fetch games
    logger.info("Fetching games from database...")
    games_df = await fetch_games_for_rankings(
        supabase,
        lookback_days=args.lookback_days
    )

    if games_df.empty:
        logger.error("No games found. Exiting.")
        return 1

    logger.info(f"Loaded {len(games_df):,} games")

    if args.comparison:
        compare_legacy_vs_iterative(games_df, age_filter=args.age, gender_filter=args.gender)
    else:
        # Just run iterative and show results
        cfg = V53EConfig()
        cfg.ENABLE_ITERATIVE_SOS = True
        cfg.SOS_STRENGTH_ITERATIONS = 3

        result = compute_rankings(games_df, cfg=cfg)
        teams = result["teams"]

        analyze_sos_distribution(teams, "Iterative SOS Results")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
