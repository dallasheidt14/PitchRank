"""Check what happened during U16 import"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

print("=" * 70)
print("CHECKING U16 IMPORT STATUS")
print("=" * 70)

# Check all Modular11 games (not just U16)
print("\nChecking all Modular11 games in database...")
all_games_result = supabase.table('games').select('game_uid', count='exact').eq('provider_id', modular11_provider_id).execute()
total_modular11_games = all_games_result.count if hasattr(all_games_result, 'count') else len(all_games_result.data) if all_games_result.data else 0

print(f"Total Modular11 games in database: {total_modular11_games}")

# Check games by age group (by looking at team age groups)
print("\nChecking games by team age groups...")

# Get all Modular11 teams with their age groups
teams_result = supabase.table('teams').select('team_id_master, age_group').eq('provider_id', modular11_provider_id).execute()

team_age_map = {}
for team in teams_result.data:
    team_id = team['team_id_master']
    age_group = team.get('age_group', '').lower()
    team_age_map[team_id] = age_group

# Count games by age group
age_group_counts = {}
for team_id, age_group in team_age_map.items():
    # Count home games
    home_games = supabase.table('games').select('game_uid').eq('provider_id', modular11_provider_id).eq('home_team_master_id', team_id).limit(1000).execute()
    # Count away games
    away_games = supabase.table('games').select('game_uid').eq('provider_id', modular11_provider_id).eq('away_team_master_id', team_id).limit(1000).execute()
    
    # Collect unique game UIDs
    game_uids = set()
    if home_games.data:
        for g in home_games.data:
            game_uids.add(g.get('game_uid'))
    if away_games.data:
        for g in away_games.data:
            game_uids.add(g.get('game_uid'))
    
    if game_uids:
        if age_group not in age_group_counts:
            age_group_counts[age_group] = set()
        age_group_counts[age_group].update(game_uids)

print("\nGames by age group:")
for age in sorted(age_group_counts.keys()):
    count = len(age_group_counts[age])
    print(f"  {age.upper()}: {count} unique games")

# Check if U16 games were imported but then deleted
print("\n" + "=" * 70)
print("ANALYSIS")
print("=" * 70)

u16_count = len(age_group_counts.get('u16', set()))
print(f"\nU16 games currently in database: {u16_count}")

if u16_count < 1000:
    print("\n⚠️  Very few U16 games in database!")
    print("   Possible reasons:")
    print("   1. U16 import was never fully completed")
    print("   2. Most games were marked as duplicates")
    print("   3. Games failed validation")
    print("   4. Games were deleted during cleanup")
    print("\n   Recommendation: Re-import U16 games to ensure all valid games are present")
else:
    print(f"\n✓ U16 games are in database ({u16_count} games)")

print("\n" + "=" * 70)













