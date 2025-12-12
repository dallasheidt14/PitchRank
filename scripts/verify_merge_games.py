"""Verify that games are being resolved correctly after merge"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

supabase = create_client(supabase_url, supabase_key)

# Team IDs from user
deprecated_team_id = 'a2126cb2-409e-4dce-896f-8928cdfea485'  # North 14B GSA
canonical_team_id = '291aa4d2-d3c9-4d22-aa6b-5f855ff19408'  # 14B GSA

print("=" * 80)
print("VERIFYING MERGE GAME RESOLUTION")
print("=" * 80)

# Check games directly referencing deprecated team
print("\n1. Games directly referencing deprecated team:")
print("-" * 80)
games_deprecated = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id, home_score, away_score, game_date').or_(f'home_team_master_id.eq.{deprecated_team_id},away_team_master_id.eq.{deprecated_team_id}').execute()
if games_deprecated.data:
    print(f"Found {len(games_deprecated.data)} games:")
    for game in games_deprecated.data:
        print(f"  Game {game['game_uid']}: {game['home_team_master_id']} vs {game['away_team_master_id']} on {game.get('game_date', 'N/A')}")
else:
    print("No games found")

# Check games for canonical team
print("\n2. Games directly referencing canonical team:")
print("-" * 80)
games_canonical = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id, home_score, away_score, game_date').or_(f'home_team_master_id.eq.{canonical_team_id},away_team_master_id.eq.{canonical_team_id}').execute()
if games_canonical.data:
    print(f"Found {len(games_canonical.data)} games:")
    for game in games_canonical.data[:5]:
        print(f"  Game {game['game_uid']}: {game['home_team_master_id']} vs {game['away_team_master_id']} on {game.get('game_date', 'N/A')}")
    if len(games_canonical.data) > 5:
        print(f"  ... and {len(games_canonical.data) - 5} more")
else:
    print("No games found")

# Test resolve_team_id function
print("\n3. Testing resolve_team_id function:")
print("-" * 80)
try:
    result = supabase.rpc('resolve_team_id', {'p_team_id': deprecated_team_id}).execute()
    resolved_id = result.data
    print(f"resolve_team_id('{deprecated_team_id}') = {resolved_id}")
    if resolved_id == canonical_team_id:
        print("✅ Function correctly resolves to canonical team")
    else:
        print(f"❌ Expected {canonical_team_id}, got {resolved_id}")
except Exception as e:
    print(f"❌ Error calling resolve_team_id: {e}")

# Check rankings_view for canonical team
print("\n4. Checking rankings_view for canonical team:")
print("-" * 80)
rankings = supabase.table('rankings_view').select('team_id_master, team_name, total_games_played, games_played, wins, losses, power_score_final').eq('team_id_master', canonical_team_id).execute()
if rankings.data:
    for r in rankings.data:
        print(f"✅ Found in rankings_view:")
        print(f"   Team: {r['team_name']}")
        print(f"   Total Games (all): {r.get('total_games_played', 0)}")
        print(f"   Games (capped): {r.get('games_played', 0)}")
        print(f"   Wins: {r.get('wins', 0)}")
        print(f"   Losses: {r.get('losses', 0)}")
        print(f"   Power Score: {r.get('power_score_final', 'N/A')}")
else:
    print("❌ Not found in rankings_view")

# Check if deprecated team appears in rankings_view (should not)
print("\n5. Checking if deprecated team appears in rankings_view (should NOT):")
print("-" * 80)
deprecated_in_view = supabase.table('rankings_view').select('team_id_master, team_name').eq('team_id_master', deprecated_team_id).execute()
if deprecated_in_view.data:
    print(f"❌ PROBLEM: Deprecated team still appears in rankings_view!")
    for r in deprecated_in_view.data:
        print(f"   {r['team_name']} (ID: {r['team_id_master']})")
else:
    print("✅ Deprecated team correctly excluded from rankings_view")

# Check rankings_full table
print("\n6. Checking rankings_full table:")
print("-" * 80)
rankings_full = supabase.table('rankings_full').select('team_id, games_played, wins, losses, power_score_final').eq('team_id', canonical_team_id).execute()
if rankings_full.data:
    for r in rankings_full.data:
        print(f"✅ Found in rankings_full:")
        print(f"   Games Played: {r.get('games_played', 0)}")
        print(f"   Wins: {r.get('wins', 0)}")
        print(f"   Losses: {r.get('losses', 0)}")
        print(f"   Power Score: {r.get('power_score_final', 'N/A')}")
else:
    print("❌ Not found in rankings_full (rankings may need recalculation)")

# Check deprecated team in rankings_full (should not exist or be ignored)
deprecated_full = supabase.table('rankings_full').select('team_id, games_played').eq('team_id', deprecated_team_id).execute()
if deprecated_full.data:
    print(f"\n⚠️  Deprecated team still has entry in rankings_full:")
    for r in deprecated_full.data:
        print(f"   Games: {r.get('games_played', 0)}")
    print("   Note: This is OK - rankings_full may not filter deprecated teams")
else:
    print("\n✅ Deprecated team not in rankings_full (or filtered out)")

print("\n" + "=" * 80)
print("SUMMARY:")
print("=" * 80)
print(f"- Deprecated team games: {len(games_deprecated.data) if games_deprecated.data else 0}")
print(f"- Canonical team games: {len(games_canonical.data) if games_canonical.data else 0}")
print(f"- Total games that should be counted: {len(games_deprecated.data) + len(games_canonical.data) if games_deprecated.data and games_canonical.data else (games_deprecated.data and len(games_deprecated.data)) or (games_canonical.data and len(games_canonical.data)) or 0}")
if rankings.data:
    print(f"- Rankings_view shows {rankings.data[0].get('total_games_played', 0)} total games for canonical team")
    expected_total = len(games_deprecated.data) + len(games_canonical.data) if games_deprecated.data and games_canonical.data else (games_deprecated.data and len(games_deprecated.data)) or (games_canonical.data and len(games_canonical.data)) or 0
    if rankings.data[0].get('total_games_played', 0) != expected_total:
        print(f"⚠️  MISMATCH: Rankings show {rankings.data[0].get('total_games_played', 0)} games but should show {expected_total}")
        print("   Rankings may need to be recalculated!")

