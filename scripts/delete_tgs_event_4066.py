#!/usr/bin/env python3
"""Delete TGS games from event 4066 that were just imported"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# TGS provider ID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

# Find games imported after the scrape started (around 13:28 UTC)
print("Finding TGS games from event 4066...")
result = supabase.table('games').select('game_uid, created_at, game_date').eq(
    'provider_id', tgs_provider_id
).gte('created_at', '2025-12-11T13:28:00').execute()

if not result.data:
    print("No games found to delete.")
    sys.exit(0)

game_uids = [g['game_uid'] for g in result.data]
print(f"\nFound {len(game_uids)} games to delete")

# Show first few
for g in result.data[:5]:
    print(f"  {g['game_uid']} - {g['game_date']}")

# Auto-confirm (non-interactive)
print("\n" + "=" * 70)
print(f"\n⚠️  Deleting {len(game_uids)} TGS games...")
print("=" * 70)

# Delete in batches
print(f"\nDeleting {len(game_uids)} games...")
delete_batch_size = 100
deleted_count = 0

for i in range(0, len(game_uids), delete_batch_size):
    batch = game_uids[i:i + delete_batch_size]
    try:
        supabase.table('games').delete().in_('game_uid', batch).eq('provider_id', tgs_provider_id).execute()
        deleted_count += len(batch)
        print(f"  Deleted batch {i//delete_batch_size + 1}: {len(batch)} games (total: {deleted_count})")
    except Exception as e:
        print(f"  Error deleting batch {i//delete_batch_size + 1}: {e}")

print(f"\n✅ Deleted {deleted_count} games")

