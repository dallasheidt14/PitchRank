"""Delete the remaining 16 age mismatch games"""
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
print("DELETE REMAINING AGE MISMATCH GAMES")
print("=" * 70)

# These are the 16 problematic game UIDs from the check
problematic_game_uids = [
    'modular11:2025-04-06:13:371',
    'modular11:2025-05-17:138:371',
    'modular11:2025-03-29:267:45',
    'modular11:2025-02-02:371:490',
    'modular11:2025-11-22:371:459',
    'modular11:2025-03-09:371:459',
    'modular11:2025-06-01:45:565',
    'modular11:2025-11-15:45:565',
]

print(f"\nFound {len(problematic_game_uids)} unique problematic game UIDs")
print("(Some games appear twice because they're counted from both team perspectives)\n")

# Get game IDs from UIDs
print("Looking up game IDs...")
game_ids = []
for game_uid in problematic_game_uids:
    result = supabase.table('games').select('id, game_uid, game_date, home_team_master_id, away_team_master_id').eq('game_uid', game_uid).eq('provider_id', modular11_provider_id).execute()
    if result.data:
        for game in result.data:
            game_id = game.get('id')
            if game_id and game_id not in game_ids:
                game_ids.append(game_id)
                print(f"  Found: {game_uid} (ID: {game_id}, Date: {game.get('game_date')})")

print(f"\nTotal unique games to delete: {len(game_ids)}")

if not game_ids:
    print("\nNo games found to delete.")
    sys.exit(0)

# Confirm deletion
print("\n" + "=" * 70)
response = input(f"\n⚠️  Delete {len(game_ids)} remaining age mismatch games? (type 'delete' to confirm): ").strip().upper()

if response != 'DELETE':
    print("\nDeletion cancelled.")
    sys.exit(0)

# Delete games
print(f"\nDeleting {len(game_ids)} games...")
deleted_count = 0
failed_count = 0

for game_id in game_ids:
    try:
        supabase.table('games').delete().eq('id', game_id).execute()
        deleted_count += 1
    except Exception as e:
        print(f"  ✗ Error deleting game {game_id}: {e}")
        failed_count += 1

print("\n" + "=" * 70)
print("DELETION COMPLETE")
print("=" * 70)
print(f"✓ Successfully deleted: {deleted_count} games")
if failed_count > 0:
    print(f"✗ Failed to delete: {failed_count} games")
print("=" * 70)













