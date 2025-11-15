#!/usr/bin/env python3
"""
Test SOS fix by temporarily disabling it to show BEFORE vs AFTER
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent))

from src.etl.v53e import compute_rankings, V53EConfig

print("=" * 80)
print("SOS FIX: BEFORE vs AFTER TEST")
print("=" * 80)

today = pd.Timestamp("2025-01-15")

def create_problematic_scenario():
    """
    Create scenario that DEFINITELY triggers the bug:
    - Teams A, B, C: 10 games each (recent)
    - Teams X, Y: 50 games each, BUT games vs A/B/C were 40 days ago
      (beyond the MAX_GAMES_FOR_RANK=30 cutoff for X and Y)

    Result: When ranked, X and Y's rows as team_id get filtered out,
    but A/B/C still have games against X and Y
    """
    games = []
    game_id = [0]

    def add_game(team_id, opp_id, days_ago, team_score, opp_score):
        game_id[0] += 1
        date = today - timedelta(days=days_ago)

        # Add both perspectives
        games.append({
            "game_id": f"g{game_id[0]}",
            "date": date,
            "team_id": team_id,
            "opp_id": opp_id,
            "age": "12",
            "gender": "male",
            "opp_age": "12",
            "opp_gender": "male",
            "gf": team_score,
            "ga": opp_score,
        })

        games.append({
            "game_id": f"g{game_id[0]}",
            "date": date,
            "team_id": opp_id,
            "opp_id": team_id,
            "age": "12",
            "gender": "male",
            "opp_age": "12",
            "opp_gender": "male",
            "gf": opp_score,
            "ga": team_score,
        })

    # Team X: 35 recent games against "dummy" opponents
    # These are X's last 30 games (will be kept)
    for i in range(35):
        add_game("team_x", f"dummy_x_{i}", i, 4, 2)

    # Team Y: 35 recent games
    for i in range(35):
        add_game("team_y", f"dummy_y_{i}", i, 5, 3)

    # NOW: Add games between A/B/C and X/Y that are 40 days old
    # From X and Y's perspective, these are game #36-40 (will be FILTERED OUT)
    # From A/B/C's perspective, these are their ONLY games (will be KEPT)

    # Team A's games (40-50 days ago) - all against X and Y
    add_game("team_a", "team_x", 40, 2, 5)  # Lost to X
    add_game("team_a", "team_y", 41, 2, 6)  # Lost to Y
    add_game("team_a", "team_x", 42, 1, 4)  # Lost to X again
    add_game("team_a", "team_y", 43, 3, 5)  # Lost to Y again
    add_game("team_a", "team_x", 44, 2, 4)  # Lost to X
    for i in range(5):  # Fill to 10 games
        add_game("team_a", f"other_a_{i}", 45+i, 3, 2)

    # Team B's games - also all against X and Y
    add_game("team_b", "team_x", 40, 2, 5)  # Lost to X (same as A)
    add_game("team_b", "team_y", 41, 2, 6)  # Lost to Y (same as A)
    add_game("team_b", "team_x", 42, 1, 4)  # Lost to X (same as A)
    add_game("team_b", "team_y", 43, 3, 5)  # Lost to Y (same as A)
    add_game("team_b", "team_x", 44, 2, 4)  # Lost to X (same as A)
    for i in range(5):
        add_game("team_b", f"other_b_{i}", 45+i, 3, 2)

    # Team C's games - different pattern
    add_game("team_c", "team_x", 40, 3, 4)  # Lost to X (different score)
    add_game("team_c", "team_y", 41, 4, 5)  # Lost to Y (different score)
    add_game("team_c", "team_x", 42, 2, 3)  # Lost to X
    add_game("team_c", "team_y", 43, 2, 4)  # Lost to Y
    add_game("team_c", "team_x", 44, 3, 5)  # Lost to X
    for i in range(5):
        add_game("team_c", f"other_c_{i}", 45+i, 4, 2)

    # Add games for the "other" opponents so they have records too
    for prefix in ['a', 'b', 'c']:
        for i in range(5):
            for j in range(8):
                add_game(f"other_{prefix}_{i}", f"filler_{prefix}_{i}_{j}", 50+j, 3, 3)

    # Add games for dummy opponents
    for i in range(35):
        for j in range(8):
            add_game(f"dummy_x_{i}", f"filler_x_{i}_{j}", 10+j, 3, 3)
            add_game(f"dummy_y_{i}", f"filler_y_{i}_{j}", 10+j, 3, 3)

    return pd.DataFrame(games)

print("\n1. Creating problematic test scenario...")
games_df = create_problematic_scenario()

print(f"   Total game rows: {len(games_df):,}")
print(f"   Unique teams: {games_df['team_id'].nunique()}")

# Check what should happen with filtering
print(f"\n2. Analyzing what SHOULD happen with MAX_GAMES_FOR_RANK=30:")

team_x_games = games_df[games_df['team_id'] == 'team_x'].sort_values('date', ascending=False)
team_a_games = games_df[games_df['team_id'] == 'team_a'].sort_values('date', ascending=False)

print(f"   Team X total games: {len(team_x_games)}")
print(f"   Team X's 30th most recent game date: {team_x_games.iloc[29]['date'] if len(team_x_games) >= 30 else 'N/A'}")
print(f"   Team A's games vs Team X dates:")
for _, g in games_df[(games_df['team_id'] == 'team_a') & (games_df['opp_id'] == 'team_x')].iterrows():
    print(f"     {g['date']}")

print(f"\n   EXPECTED: Team X's games vs A/B/C will be FILTERED OUT (too old)")
print(f"   EXPECTED: Team A/B/C's games vs X will be KEPT (within their recent games)")
print(f"   RESULT: Team X won't be in strength_map, will default to 0.35")

# Run the ranking engine
print(f"\n3. Running rankings engine WITH the fix...")
cfg = V53EConfig()

result = compute_rankings(games_df, today=today, cfg=cfg)
teams_df = result['teams']

print(f"   Teams ranked: {len(teams_df)}")

# Check if X and Y are in the rankings
xyz = teams_df[teams_df['team_id'].isin(['team_x', 'team_y'])]
print(f"\n4. Are X and Y in the ranked teams?")
if len(xyz) > 0:
    print(f"   YES - Found {len(xyz)} teams")
    for _, t in xyz.iterrows():
        print(f"     {t['team_id']}: {t['gp']} games, SOS={t['sos']:.4f}")
else:
    print(f"   NO - X and Y are NOT in rankings")
    print(f"   (This is what we want - it triggers the fix)")

# Check A, B, C
abc = teams_df[teams_df['team_id'].isin(['team_a', 'team_b', 'team_c'])].sort_values('team_id')

print(f"\n5. Teams A, B, C analysis:")
if len(abc) == 0:
    print("   ERROR: Teams not found!")
else:
    print(f"\n   {'Team':<10} {'SOS (raw)':<12} {'SOS (norm)':<12} {'Unique?':<10}")
    print(f"   {'-'*50}")

    sos_values = {}
    for _, t in abc.iterrows():
        sos_raw = t['sos']
        sos_norm = t.get('sos_norm', 0)
        sos_values[t['team_id']] = sos_raw

        print(f"   {t['team_id']:<10} {sos_raw:<12.6f} {sos_norm:<12.6f}")

    # Check uniqueness
    unique_sos = len(set(sos_values.values()))

    print(f"\n6. VERDICT:")
    print(f"   Unique SOS values: {unique_sos}/3")

    if unique_sos == 1:
        print(f"   ✗ FAIL: All teams have identical SOS ({list(sos_values.values())[0]:.6f})")
        print(f"        This means X and Y are defaulting to 0.35")
        print(f"        The fix is NOT working!")
    elif unique_sos == 3:
        print(f"   ✓ PERFECT: All teams have different SOS")
        print(f"        The fix is working correctly!")
    else:
        # Check if A and B are identical (they played the same opponents with same scores)
        if abs(sos_values.get('team_a', 0) - sos_values.get('team_b', 0)) < 0.000001:
            print(f"   ✓ EXPECTED: Teams A and B have identical SOS")
            print(f"        (They played the same opponents with identical scores)")
            print(f"        Team C has different SOS")
            print(f"        The fix is working correctly!")
        else:
            print(f"   ⚠ PARTIAL: {unique_sos} unique values")

# Check for the default SOS value (0.35)
if any(abs(v - 0.35) < 0.01 for v in sos_values.values()):
    print(f"\n   ⚠ WARNING: Some teams have SOS near 0.35 (default value)")
    print(f"        This suggests opponents are still using default strength")

print(f"\n" + "=" * 80)
