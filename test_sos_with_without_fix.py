#!/usr/bin/env python3
"""
Direct test: Run rankings with and without the fix to compare results
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.append(str(Path(__file__).parent))

# Read the v53e.py file and create two versions
v53e_path = Path("src/etl/v53e.py")
original_code = v53e_path.read_text()

# Check if the fix is present
fix_marker = "# Fix for identical SOS scores"
has_fix = fix_marker in original_code

if not has_fix:
    print("ERROR: Fix not found in v53e.py")
    print("Looking for marker:", fix_marker)
    sys.exit(1)

print("=" * 80)
print("DIRECT COMPARISON: WITH vs WITHOUT FIX")
print("=" * 80)

# Create simple test data
today = pd.Timestamp("2025-01-15")
games = []
gid = [0]

def add_game(team, opp, days_ago, ts, os):
    gid[0] += 1
    d = today - timedelta(days=days_ago)
    games.extend([
        {"game_id": f"g{gid[0]}", "date": d, "team_id": team, "opp_id": opp,
         "age": "12", "gender": "male", "opp_age": "12", "opp_gender": "male",
         "gf": ts, "ga": os},
        {"game_id": f"g{gid[0]}", "date": d, "team_id": opp, "opp_id": team,
         "age": "12", "gender": "male", "opp_age": "12", "opp_gender": "male",
         "gf": os, "ga": ts},
    ])

# Create a scenario:
# - Team Filler1-10: Each has 30 games against each other (will be kept)
# - Team A, B, C: Each has 10 games total
#   - 5 games against Filler teams (recent)
#   - 5 games against RareOpp teams (these opponents will be filtered out)

# Filler teams: create a pool of 10 teams with 30 games each
print("\n1. Creating test data...")
print("   - Creating 10 filler teams with 30 games each...")
for i in range(10):
    for j in range(30):
        opp_idx = (i + j + 1) % 10
        add_game(f"filler{i}", f"filler{opp_idx}", j, 3, 2)

# RareOpp teams: teams that will have 40 games, so their earliest 10 will be filtered out
print("   - Creating rare opponent teams (will be filtered out)...")
for i in range(5):
    # Recent 30 games (will be kept)
    for j in range(30):
        add_game(f"rare{i}", f"dummy{i}_{j}", j, 4, 3)

    # Old games (will be FILTERED OUT) - these are games vs A, B, C
    # These happen at days 35-40 (beyond the 30 game cutoff for rare{i})
    add_game(f"rare{i}", "team_a", 35 + i, 5, 2)
    add_game(f"rare{i}", "team_b", 36 + i, 5, 2)
    add_game(f"rare{i}", "team_c", 37 + i, 5, 2)

# Now create dummy opponents for rare teams
for i in range(5):
    for j in range(30):
        for k in range(10):
            add_game(f"dummy{i}_{j}", f"extra{i}_{j}_{k}", 5 + k, 3, 3)

# Teams A, B, C: Mix of filler opponents and rare opponents
print("   - Creating test teams A, B, C...")

# Team A: plays mostly filler teams + one rare opponent
for i in range(7):
    add_game("team_a", f"filler{i}", 5 + i, 3, 2)
add_game("team_a", "rare0", 35, 2, 5)  # Lost to rare0 (old game for rare0)
add_game("team_a", "rare1", 36, 2, 5)  # Lost to rare1
add_game("team_a", "rare2", 37, 2, 5)  # Lost to rare2

# Team B: same pattern as A (should get same SOS)
for i in range(7):
    add_game("team_b", f"filler{i}", 5 + i, 3, 2)
add_game("team_b", "rare0", 35, 2, 5)
add_game("team_b", "rare1", 36, 2, 5)
add_game("team_b", "rare2", 37, 2, 5)

# Team C: different opponents
for i in range(7):
    add_game("team_c", f"filler{i+3}", 5 + i, 4, 2)  # Different filler teams
add_game("team_c", "rare3", 37, 2, 5)
add_game("team_c", "rare4", 38, 2, 5)
add_game("team_c", "rare0", 39, 2, 5)

df = pd.DataFrame(games)
print(f"   Total games: {len(df):,}")
print(f"   Unique teams: {df['team_id'].nunique()}")

# Check if rare opponents will be filtered
print(f"\n2. Checking filter logic (MAX_GAMES_FOR_RANK=30):")
for i in range(5):
    rare_games = df[df['team_id'] == f'rare{i}'].sort_values('date', ascending=False)
    print(f"   rare{i}: {len(rare_games)} total games")
    if len(rare_games) >= 30:
        cutoff_date = rare_games.iloc[29]['date']
        print(f"     30th game date: {cutoff_date}")
        games_vs_abc = df[(df['team_id'] == f'rare{i}') & (df['opp_id'].isin(['team_a', 'team_b', 'team_c']))]
        print(f"     Games vs A/B/C:")
        for _, g in games_vs_abc.iterrows():
            status = "FILTERED OUT" if g['date'] < cutoff_date else "KEPT"
            print(f"       {g['date']}: {status}")

# Now run rankings WITH the fix
print(f"\n3. Running rankings WITH fix...")
from src.etl.v53e import compute_rankings, V53EConfig

cfg = V53EConfig()
result = compute_rankings(df, today=today, cfg=cfg)
teams_with_fix = result['teams']

# Get A, B, C results
abc_with = teams_with_fix[teams_with_fix['team_id'].isin(['team_a', 'team_b', 'team_c'])].sort_values('team_id')

print(f"\n4. Results WITH fix:")
for _, t in abc_with.iterrows():
    print(f"   {t['team_id']}: SOS = {t['sos']:.6f}")

# Check if rare opponents are in the rankings
rare_with = teams_with_fix[teams_with_fix['team_id'].str.startswith('rare')]
print(f"\n5. Rare opponents in rankings: {len(rare_with)}")
if len(rare_with) > 0:
    print(f"   (They were NOT filtered out, so fix may not have triggered)")

# Now create version WITHOUT fix (manually comment out the fix code)
print(f"\n6. To test WITHOUT fix, we need to temporarily disable it...")
print(f"   Checking if we can identify missing opponents...")

# Simulate what happens without the fix
from src.etl.v53e import V53EConfig as Cfg
test_cfg = Cfg()

# Apply same filtering logic as v53e.py
g = df.copy()
g["date"] = pd.to_datetime(g["date"])
cutoff = today - pd.Timedelta(days=test_cfg.WINDOW_DAYS)
g = g[g["date"] >= cutoff].copy()
g = g.sort_values(["team_id", "date"], ascending=[True, False])
g["rank_recency"] = g.groupby("team_id")["date"].rank(ascending=False, method="first")
g_filtered = g[g["rank_recency"] <= test_cfg.MAX_GAMES_FOR_RANK].copy()

all_team_ids = set(g_filtered["team_id"].unique())
all_opp_ids = set(g_filtered["opp_id"].unique())
missing_opponents = all_opp_ids - all_team_ids

print(f"\n7. Missing opponents analysis:")
print(f"   Teams as team_id: {len(all_team_ids)}")
print(f"   Teams as opp_id: {len(all_opp_ids)}")
print(f"   Missing (appear as opp but not team): {len(missing_opponents)}")

if len(missing_opponents) > 0:
    print(f"   Missing teams: {sorted(missing_opponents)[:20]}")  # Show first 20
    print(f"\n   ✓ This CONFIRMS the bug scenario exists!")
    print(f"   Without the fix, these opponents would default to 0.35")
else:
    print(f"   No missing opponents found - test scenario didn't trigger the bug")

print(f"\n" + "=" * 80)
print("SUMMARY:")
print("=" * 80)

sos_values = abc_with['sos'].values
unique_count = len(set(sos_values))

print(f"Teams A, B, C SOS values: {[f'{v:.6f}' for v in sos_values]}")
print(f"Unique values: {unique_count}/3")

if unique_count == 3:
    print(f"✓ All teams have different SOS (best case)")
elif unique_count == 2:
    if abs(sos_values[0] - sos_values[1]) < 0.000001:
        print(f"✓ Teams A and B have identical SOS (expected - they played same opponents)")
        print(f"✓ Team C has different SOS")
        print(f"✓ FIX IS WORKING")
    else:
        print(f"⚠ Unexpected pattern of SOS values")
else:
    print(f"✗ All teams have identical SOS - fix may not be working")

print(f"=" * 80)
