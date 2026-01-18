"""Delete the 3 U13 games incorrectly associated with Ventura County Fusion U16"""
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
print("DELETE VENTURA U13 MISMATCH GAMES")
print("=" * 70)

# The 3 problematic game UIDs
problematic_uids = [
    'modular11:2025-09-27:184:397',
    'modular11:2025-03-30:19:397',
    'modular11:2025-03-09:19:397'
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













