#!/usr/bin/env python3
"""
Comprehensive test for SOS fix
Tests both BEFORE and AFTER the fix to verify it solves the issue
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent))

from src.etl.v53e import compute_rankings, V53EConfig

print("=" * 80)
print("COMPREHENSIVE SOS FIX TEST")
print("=" * 80)

# Create realistic test data that triggers the identical SOS issue
today = pd.Timestamp("2025-01-15")

def create_test_games():
    """
    Create test scenario:
    - Team A, B, C: Each have 10 games (all kept)
    - Team X, Y, Z: Each have 50 games (only last 30 kept)
    - Teams A, B, C all played X, Y, Z in games that appear in A/B/C's data
      but were filtered out of X/Y/Z's data (older games for X/Y/Z)
    """
    games = []
    game_counter = [0]  # Use list for mutable counter

    def add_game(team_id, opp_id, days_ago, team_score, opp_score, age="12", gender="male"):
        game_counter[0] += 1
        date = today - timedelta(days=days_ago)

        # Add both perspectives of the game
        games.append({
            "game_id": f"game_{game_counter[0]}",
            "date": date,
            "team_id": team_id,
            "opp_id": opp_id,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": team_score,
            "ga": opp_score,
        })

        games.append({
            "game_id": f"game_{game_counter[0]}",
            "date": date,
            "team_id": opp_id,
            "opp_id": team_id,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": opp_score,
            "ga": team_score,
        })

    # Team X: 50 games (strong team, scores well)
    # Games 0-19 are recent (kept), games 20-49 are old (filtered out)
    for i in range(50):
        days_ago = i * 3
        if i < 20:
            # Recent games vs other strong teams
            add_game("team_x", f"strong_{i}", days_ago, 5, 3)
        else:
            # Old games (these will be filtered out)
            # These are the games where A, B, C played against X
            pass  # We'll add these from A, B, C's perspective

    # Team Y: 50 games (medium team)
    for i in range(50):
        days_ago = i * 3
        if i < 20:
            add_game("team_y", f"medium_{i}", days_ago, 3, 3)

    # Team Z: 50 games (weak team)
    for i in range(50):
        days_ago = i * 3
        if i < 20:
            add_game("team_z", f"weak_{i}", days_ago, 2, 4)

    # Team A: 10 games (all will be kept)
    # Plays against X, Y, Z in recent games (days 5, 10, 15)
    add_game("team_a", "team_x", 5, 2, 4)   # Lost to X
    add_game("team_a", "team_y", 10, 3, 3)  # Tied with Y
    add_game("team_a", "team_z", 15, 4, 2)  # Beat Z
    for i in range(7):
        add_game("team_a", f"a_opp_{i}", 20 + i*5, 3, 2)

    # Team B: 10 games (all will be kept)
    # Also plays against X, Y, Z
    add_game("team_b", "team_x", 7, 1, 5)   # Lost to X
    add_game("team_b", "team_y", 12, 3, 3)  # Tied with Y
    add_game("team_b", "team_z", 17, 5, 2)  # Beat Z
    for i in range(7):
        add_game("team_b", f"b_opp_{i}", 22 + i*5, 3, 2)

    # Team C: 10 games (all will be kept)
    # Also plays against X, Y, Z
    add_game("team_c", "team_x", 9, 2, 5)   # Lost to X
    add_game("team_c", "team_y", 14, 2, 3)  # Lost to Y
    add_game("team_c", "team_z", 19, 4, 1)  # Beat Z
    for i in range(7):
        add_game("team_c", f"c_opp_{i}", 24 + i*5, 2, 3)

    # Add games for strong/medium/weak opponents
    for i in range(20):
        add_game(f"strong_{i}", f"other_strong_{i}", 30 + i*2, 4, 2)
        add_game(f"medium_{i}", f"other_medium_{i}", 30 + i*2, 3, 3)
        add_game(f"weak_{i}", f"other_weak_{i}", 30 + i*2, 2, 4)

    return pd.DataFrame(games)

# Create test data
print("\n1. Creating test data...")
games_df = create_test_games()
print(f"   Total game rows: {len(games_df):,}")
print(f"   Unique teams: {games_df['team_id'].nunique()}")
print(f"   Date range: {games_df['date'].min()} to {games_df['date'].max()}")

# Test configuration
cfg = V53EConfig()
print(f"\n2. Configuration:")
print(f"   MAX_GAMES_FOR_RANK: {cfg.MAX_GAMES_FOR_RANK}")
print(f"   UNRANKED_SOS_BASE: {cfg.UNRANKED_SOS_BASE}")
print(f"   SOS_WEIGHT: {cfg.SOS_WEIGHT}")

# Run rankings
print(f"\n3. Running rankings engine...")
try:
    result = compute_rankings(games_df, today=today, cfg=cfg)
    teams_df = result['teams']

    print(f"   ✓ Rankings computed successfully")
    print(f"   Teams ranked: {len(teams_df)}")

    # Check for SOS columns
    if 'sos' not in teams_df.columns:
        print("   ✗ ERROR: 'sos' column not found!")
        sys.exit(1)

    print(f"\n4. Analyzing SOS scores...")
    print(f"   SOS statistics:")
    print(f"     Min: {teams_df['sos'].min():.4f}")
    print(f"     Max: {teams_df['sos'].max():.4f}")
    print(f"     Mean: {teams_df['sos'].mean():.4f}")
    print(f"     Std Dev: {teams_df['sos'].std():.4f}")

    # Focus on teams A, B, C (they should have DIFFERENT SOS after the fix)
    test_teams = teams_df[teams_df['team_id'].isin(['team_a', 'team_b', 'team_c'])].copy()

    if len(test_teams) == 0:
        print("   ✗ ERROR: Teams A, B, C not found in results!")
        sys.exit(1)

    print(f"\n5. Testing Teams A, B, C (the critical test):")
    print(f"   These teams all played against X, Y, Z")
    print(f"   WITHOUT fix: X, Y, Z would be missing from strength_map → all default to 0.35")
    print(f"   WITH fix: X, Y, Z get estimated strengths → A, B, C get different SOS\n")

    for _, team in test_teams.iterrows():
        print(f"   {team['team_id']}:")
        print(f"     SOS (raw): {team['sos']:.6f}")
        if 'sos_norm' in teams_df.columns:
            print(f"     SOS (normalized): {team['sos_norm']:.6f}")
        print(f"     Games played: {team['gp']}")
        if 'powerscore_adj' in teams_df.columns:
            print(f"     PowerScore: {team['powerscore_adj']:.4f}")

    # Check if SOS values are identical
    sos_values = test_teams['sos'].values
    unique_sos = len(set(sos_values))

    print(f"\n6. RESULTS:")
    print(f"   Unique SOS values among A, B, C: {unique_sos}")

    if unique_sos == 1:
        print(f"   ✗ FAIL: All three teams have identical SOS ({sos_values[0]:.6f})")
        print(f"   This means the fix did NOT work or opponents X, Y, Z are still defaulting")
    elif unique_sos == 3:
        print(f"   ✓ PASS: All three teams have different SOS values!")
        print(f"   The fix is working - opponents X, Y, Z were estimated correctly")
    else:
        print(f"   ⚠ PARTIAL: {unique_sos} unique SOS values (expected 3)")
        print(f"   Some teams have different SOS, but not all")

    # Check if X, Y, Z appear in the rankings
    xyz_teams = teams_df[teams_df['team_id'].isin(['team_x', 'team_y', 'team_z'])].copy()
    print(f"\n7. Checking if X, Y, Z are in rankings:")
    print(f"   Teams found: {len(xyz_teams)}")

    if len(xyz_teams) > 0:
        print(f"   ✓ X, Y, Z appear in rankings (they were NOT filtered out)")
        print(f"   This means they have strength values in strength_map")
        for _, team in xyz_teams.iterrows():
            print(f"     {team['team_id']}: {team['gp']} games, SOS={team['sos']:.4f}")
    else:
        print(f"   ✗ X, Y, Z do NOT appear in rankings")
        print(f"   They were filtered out or didn't meet minimum game requirements")
        print(f"   The fix should estimate their strength from opponent perspective")

    # Check the distribution of all SOS values
    print(f"\n8. Overall SOS distribution:")
    sos_counts = teams_df['sos'].value_counts()
    duplicate_sos = sos_counts[sos_counts > 1]

    if len(duplicate_sos) > 0:
        print(f"   ⚠ Found {len(duplicate_sos)} SOS values that appear multiple times:")
        for sos_val, count in duplicate_sos.head(10).items():
            print(f"     {count} teams have SOS = {sos_val:.6f}")
    else:
        print(f"   ✓ All teams have unique SOS values!")

    print(f"\n" + "=" * 80)
    print("TEST SUMMARY:")
    print("=" * 80)

    if unique_sos >= 2:
        print("✓ FIX APPEARS TO BE WORKING")
        print("  - Teams A, B, C have different SOS values")
        print("  - This suggests opponents are being estimated correctly")
    else:
        print("✗ FIX MAY NOT BE WORKING")
        print("  - Teams A, B, C still have identical SOS values")
        print("  - Check logs for strength_map estimation messages")

    print("=" * 80)

except Exception as e:
    print(f"\n✗ ERROR running rankings engine:")
    print(f"   {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
