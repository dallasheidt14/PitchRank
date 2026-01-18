"""Delete U16 Modular11 games that were just imported"""
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
    print("Loaded .env.local")
else:
    load_dotenv()
    print("Loaded .env")

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase: Client = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
if not provider_result.data:
    print("ERROR: Modular11 provider not found")
    sys.exit(1)
provider_id = provider_result.data['id']

# Parse arguments
parser = argparse.ArgumentParser(description='Delete recent Modular11 games')
parser.add_argument('--yes', action='store_true', help='Auto-confirm deletion without prompt')
args = parser.parse_args()

print("=" * 80)
print("DELETING MODULAR11 GAMES FROM LAST 30 MINUTES")
print("=" * 80)

# Get all Modular11 games imported in the last 30 minutes
cutoff_time = (datetime.utcnow() - timedelta(minutes=30)).isoformat() + 'Z'
print(f"\nFinding Modular11 games imported after: {cutoff_time}")

# Query for recent games
existing_games = []
offset = 0
batch_size = 1000

while True:
    try:
        result = supabase.table('games').select(
            'game_uid, created_at, game_date, home_team_master_id, away_team_master_id'
        ).eq('provider_id', provider_id).gte('created_at', cutoff_time).order(
            'created_at', desc=True
        ).range(offset, offset + batch_size - 1).execute()
        
        if not result.data:
            break
        
        existing_games.extend([g['game_uid'] for g in result.data])
        print(f"  Found {len(existing_games)} games so far...")
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size
        
    except Exception as e:
        print(f"  Error fetching games: {e}")
        break

print(f"\nFound {len(existing_games)} recent Modular11 games to delete")

if not existing_games:
    print("\n✅ No recent Modular11 games found in database. Nothing to delete.")
    sys.exit(0)

# Confirm deletion
print("\n" + "=" * 80)
print("⚠️  WARNING: About to delete the following:")
print("=" * 80)
print(f"  - {len(existing_games)} games from 'games' table")
print(f"  - Related quarantine games")
print(f"  - Related validation errors")
print(f"  - Related scrape logs")
print("\nThis action cannot be undone!")
if args.yes:
    print("\n✅ Auto-confirming deletion (--yes flag provided)")
    response = 'DELETE'
else:
    response = input("\nType 'DELETE' to confirm: ")

if response != 'DELETE':
    print("\n❌ Deletion cancelled.")
    sys.exit(0)

print("\n" + "=" * 80)
print("DELETING GAMES...")
print("=" * 80)

# Delete in smaller batches (Supabase .in_() limit is ~100-200)
delete_batch_size = 100
deleted_count = 0
for i in range(0, len(existing_games), delete_batch_size):
    batch = existing_games[i:i + delete_batch_size]
    try:
        # Delete games
        result = supabase.table('games').delete().in_('game_uid', batch).eq('provider_id', provider_id).execute()
        deleted_count += len(batch)
        print(f"  Deleted batch {i//delete_batch_size + 1}: {len(batch)} games (total: {deleted_count})")
    except Exception as e:
        print(f"  Error deleting batch {i//delete_batch_size + 1}: {e}")
        # Try deleting one by one as fallback
        for uid in batch:
            try:
                supabase.table('games').delete().eq('game_uid', uid).eq('provider_id', provider_id).execute()
                deleted_count += 1
            except:
                pass

print(f"\n✅ Deleted {deleted_count} games from 'games' table")

# Delete related quarantine games (in batches)
quarantine_deleted = 0
for i in range(0, len(existing_games), delete_batch_size):
    batch = existing_games[i:i + delete_batch_size]
    try:
        supabase.table('quarantine_games').delete().in_('game_uid', batch).execute()
        quarantine_deleted += len(batch)
    except Exception as e:
        pass
if quarantine_deleted > 0:
    print(f"✅ Deleted {quarantine_deleted} quarantine games")

# Delete related validation errors (in batches)
validation_deleted = 0
for i in range(0, len(existing_games), delete_batch_size):
    batch = existing_games[i:i + delete_batch_size]
    try:
        supabase.table('validation_errors').delete().in_('game_uid', batch).execute()
        validation_deleted += len(batch)
    except Exception as e:
        pass
if validation_deleted > 0:
    print(f"✅ Deleted {validation_deleted} validation errors")

# Delete related scrape logs (if any)
try:
    # Get scrape request IDs for these games
    scrape_logs = supabase.table('team_scrape_log').select('id').eq('provider_id', provider_id).execute()
    if scrape_logs.data:
        log_ids = [log['id'] for log in scrape_logs.data]
        supabase.table('team_scrape_log').delete().in_('id', log_ids).execute()
        print(f"✅ Cleaned up scrape logs")
except Exception as e:
    print(f"⚠️  Error cleaning scrape logs: {e}")

print("\n" + "=" * 80)
print("✅ DELETION COMPLETE")
print("=" * 80)
print(f"\nDeleted {deleted_count} Modular11 games from the database.")
print("\nYou can now re-import with the fixed matching logic:")
print("  python scripts/import_games_enhanced.py scrapers/modular11_scraper/output/modular11_u16.csv modular11")

