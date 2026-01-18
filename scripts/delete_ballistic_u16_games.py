"""Delete U16 games incorrectly associated with Ballistic United U13"""
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
print("DELETE BALLISTIC U13 vs U16 MISMATCH GAMES")
print("=" * 70)

# The problematic game UIDs
problematic_uids = [
    'modular11:2025-05-31:105:406',
    'modular11:2025-05-03:105:77',
    'modular11:2025-04-05:105:461',
    'modular11:2025-03-22:105:409',
    'modular11:2025-03-15:105:77',
    'modular11:2025-03-09:105:411',
    'modular11:2025-03-02:104:105',
    'modular11:2025-03-01:105:564',
    'modular11:2025-02-22:105:410',
    'modular11:2025-02-08:105:461',
    'modular11:2025-01-19:105:4',
    'modular11:2025-01-18:105:15',
    'modular11:2025-01-12:105:77',
    'modular11:2025-01-11:105:411'
]

print(f"\nFinding games to delete...")
game_ids = []

for game_uid in problematic_uids:
    result = supabase.table('games').select('id, game_uid, game_date').eq('game_uid', game_uid).eq('provider_id', modular11_provider_id).execute()
    
    if result.data:
        for game in result.data:
            game_id = game.get('id')
            if game_id:
                game_ids.append(game_id)
                print(f"  Found: {game_uid} (Date: {game.get('game_date')}, ID: {game_id})")

if not game_ids:
    print("\nNo games found to delete.")
    sys.exit(0)

print(f"\nTotal games to delete: {len(game_ids)}")

# Confirm deletion
print("\n" + "=" * 70)
response = input(f"\n⚠️  Delete {len(game_ids)} age mismatch games? (type 'delete' to confirm): ").strip().upper()

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
        print(f"  ✓ Deleted game {game_id}")
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













