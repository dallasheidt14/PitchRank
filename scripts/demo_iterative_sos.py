#!/usr/bin/env python3
"""
Demo script showing iterative SOS improvements using synthetic data.

This script creates realistic youth soccer game data and demonstrates
the improvements from the hybrid iterative SOS system.
"""

import sys
import logging
import pandas as pd
import numpy as np
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.etl.v53e import compute_rankings, V53EConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_synthetic_games(n_teams=50, n_games_per_team=15):
    """
    Create synthetic game data with realistic structure:
    - Strong teams play weaker opponents
    - Some teams are unconnected (isolated cohorts)
    - Variable game counts per team
    """
    np.random.seed(42)

    games = []
    game_id = 1

    # Create teams with different strength levels
    teams = [f"team_{i:03d}" for i in range(n_teams)]

    # Assign true strengths (hidden - used only for simulation)
    true_strengths = np.random.beta(2, 5, n_teams)  # Skewed toward weaker teams

    # Create age groups and genders
    ages = np.random.choice([10, 11, 12, 13, 14], n_teams)
    genders = np.random.choice(['male', 'female'], n_teams)

    team_info = {
        teams[i]: {
            'strength': true_strengths[i],
            'age': ages[i],
            'gender': genders[i]
        }
        for i in range(n_teams)
    }

    # Generate games
    for i, team_a in enumerate(teams):
        n_games = np.random.randint(8, n_games_per_team + 1)

        for _ in range(n_games):
            # Strong teams more likely to play weaker opponents (realistic scheduling)
            if team_info[team_a]['strength'] > 0.6:
                # Strong team - play any opponent
                team_b = np.random.choice([t for t in teams if t != team_a])
            else:
                # Weak team - more likely to play similar strength
                similar_strength_teams = [
                    t for t in teams
                    if t != team_a and abs(team_info[t]['strength'] - team_info[team_a]['strength']) < 0.3
                ]
                if similar_strength_teams:
                    team_b = np.random.choice(similar_strength_teams)
                else:
                    team_b = np.random.choice([t for t in teams if t != team_a])

            # Simulate game outcome based on true strengths
            strength_diff = team_info[team_a]['strength'] - team_info[team_b]['strength']
            expected_goals_a = 2.0 + strength_diff * 3.0
            expected_goals_b = 2.0 - strength_diff * 3.0

            goals_a = max(0, int(np.random.poisson(max(0.5, expected_goals_a))))
            goals_b = max(0, int(np.random.poisson(max(0.5, expected_goals_b))))

            # Create game date (spread over last 365 days)
            days_ago = np.random.randint(0, 365)
            game_date = pd.Timestamp('2024-11-15') - pd.Timedelta(days=days_ago)

            # Add both perspectives (team A's view and team B's view)
            games.append({
                'game_id': game_id,
                'date': game_date,
                'team_id': team_a,
                'opp_id': team_b,
                'age': str(team_info[team_a]['age']),
                'gender': team_info[team_a]['gender'],
                'opp_age': str(team_info[team_b]['age']),
                'opp_gender': team_info[team_b]['gender'],
                'gf': goals_a,
                'ga': goals_b,
            })

            games.append({
                'game_id': game_id,
                'date': game_date,
                'team_id': team_b,
                'opp_id': team_a,
                'age': str(team_info[team_b]['age']),
                'gender': team_info[team_b]['gender'],
                'opp_age': str(team_info[team_a]['age']),
                'opp_gender': team_info[team_a]['gender'],
                'gf': goals_b,
                'ga': goals_a,
            })

            game_id += 1

    df = pd.DataFrame(games)
    logger.info(f"Created {len(df)} game records ({len(df)//2} games, {n_teams} teams)")
    return df, team_info


def analyze_sos_results(teams_df, label, team_info=None):
    """Analyze and print SOS results"""
    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"{'='*70}")

    sos_values = teams_df["sos"].dropna()

    print(f"\n📊 SOS Statistics:")
    print(f"   Teams:      {len(sos_values):>8,}")
    print(f"   Mean:       {sos_values.mean():>8.4f}")
    print(f"   Std Dev:    {sos_values.std():>8.4f}")
    print(f"   Min:        {sos_values.min():>8.4f}")
    print(f"   Median:     {sos_values.median():>8.4f}")
    print(f"   Max:        {sos_values.max():>8.4f}")

    # Fallback pollution
    exact_half = (sos_values == 0.5).sum()
    near_half = ((sos_values > 0.49) & (sos_values < 0.51)).sum()

    print(f"\n🔍 Fallback Pollution:")
    print(f"   Exactly 0.5:      {exact_half:>6,} ({exact_half/len(sos_values)*100:>5.1f}%)")
    print(f"   Near 0.5 (±0.01): {near_half:>6,} ({near_half/len(sos_values)*100:>5.1f}%)")

    # Variance
    unique_count = sos_values.nunique()
    print(f"\n🎯 SOS Variance:")
    print(f"   Unique values:    {unique_count:>6,} ({unique_count/len(sos_values)*100:>5.1f}%)")

    # Top teams
    print(f"\n🔝 Top 10 Teams by SOS:")
    top_teams = teams_df.nlargest(10, "sos")[["team_id", "age", "gender", "sos", "powerscore_adj"]]
    for idx, row in top_teams.iterrows():
        true_str = f" (true: {team_info[row['team_id']]['strength']:.3f})" if team_info else ""
        print(f"   {row['team_id']}: SOS={row['sos']:.4f}, Power={row['powerscore_adj']:.4f}{true_str}")


def main():
    print("\n" + "="*70)
    print("ITERATIVE SOS DEMONSTRATION")
    print("="*70)

    # Create synthetic data
    games_df, team_info = create_synthetic_games(n_teams=100, n_games_per_team=20)

    # Run LEGACY SOS
    print("\n🔄 Running LEGACY SOS calculation...")
    cfg_legacy = V53EConfig()
    cfg_legacy.ENABLE_ITERATIVE_SOS = False
    result_legacy = compute_rankings(games_df, cfg=cfg_legacy)
    teams_legacy = result_legacy["teams"]

    # Run ITERATIVE SOS
    print("\n\n🔄 Running ITERATIVE SOS calculation (3 iterations)...")
    cfg_iterative = V53EConfig()
    cfg_iterative.ENABLE_ITERATIVE_SOS = True
    cfg_iterative.SOS_STRENGTH_ITERATIONS = 3
    result_iterative = compute_rankings(games_df, cfg=cfg_iterative)
    teams_iterative = result_iterative["teams"]

    # Analyze both
    analyze_sos_results(teams_legacy, "LEGACY SOS (Single-Pass)", team_info)
    analyze_sos_results(teams_iterative, "ITERATIVE SOS (3 Passes)", team_info)

    # Comparison
    print(f"\n{'='*70}")
    print("IMPROVEMENT SUMMARY")
    print(f"{'='*70}")

    legacy_std = teams_legacy["sos"].std()
    iterative_std = teams_iterative["sos"].std()
    std_improvement = ((iterative_std - legacy_std) / legacy_std * 100) if legacy_std > 0 else 0

    legacy_half = (teams_legacy["sos"] == 0.5).sum()
    iterative_half = (teams_iterative["sos"] == 0.5).sum()

    legacy_unique = teams_legacy["sos"].nunique()
    iterative_unique = teams_iterative["sos"].nunique()

    print(f"\n📊 Variance Improvement:")
    print(f"   Legacy std:       {legacy_std:.4f}")
    print(f"   Iterative std:    {iterative_std:.4f}")
    print(f"   Change:           {std_improvement:+.1f}%")

    print(f"\n🔍 Fallback Pollution Reduction:")
    print(f"   Legacy 0.5 count:     {legacy_half:>6,}")
    print(f"   Iterative 0.5 count:  {iterative_half:>6,}")

    print(f"\n🎯 Unique Value Increase:")
    print(f"   Legacy unique:    {legacy_unique:>6,}")
    print(f"   Iterative unique: {iterative_unique:>6,}")

    print(f"\n✅ DEMONSTRATION COMPLETE\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
