"""Check how many Modular11 games have unmatched teams"""
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
print("MODULAR11 GAME MATCHING STATUS")
print("=" * 70)

# Get all Modular11 games
games_result = supabase.table('games').select('id, game_uid, home_team_master_id, away_team_master_id').eq('provider_id', modular11_provider_id).execute()

total_games = len(games_result.data)
matched_games = 0
unmatched_games = 0

for game in games_result.data:
    home_id = game.get('home_team_master_id')
    away_id = game.get('away_team_master_id')
    
    if home_id and away_id:
        matched_games += 1
    else:
        unmatched_games += 1

print(f"\nTotal Modular11 games: {total_games:,}")
print(f"  ✓ Matched (both teams): {matched_games:,} ({matched_games/total_games*100:.1f}%)")
print(f"  ✗ Unmatched (NULL team IDs): {unmatched_games:,} ({unmatched_games/total_games*100:.1f}%)")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)

if unmatched_games > 0:
    print(f"\n⚠️  {unmatched_games:,} games have NULL team master IDs.")
    print("   These games were imported but teams were not matched.")
    print("\n   Possible reasons:")
    print("   1. Games were imported before team matching was complete")
    print("   2. Teams failed to match during import")
    print("   3. Age mismatch validation rejected the games")
    print("\n   Solution:")
    print("   - Re-run the import with the current matching system")
    print("   - The new age validation will prevent mismatches")
    print("   - Teams should now match correctly")
else:
    print("\n✓ All games have matched teams!")

print("=" * 70)













