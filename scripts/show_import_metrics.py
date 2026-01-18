"""Show detailed metrics from the latest import"""
import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Initialize Supabase client
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get the latest build log for modular11
result = supabase.table('build_logs').select('*').eq('stage', 'game_import').order('started_at', desc=True).limit(1).execute()

if not result.data:
    print("No build logs found")
    sys.exit(0)

log = result.data[0]

print("=" * 70)
print("LATEST IMPORT METRICS")
print("=" * 70)
print(f"\nBuild ID: {log.get('build_id')}")
print(f"Started: {log.get('started_at')}")
print(f"Completed: {log.get('completed_at')}")
print(f"Provider ID: {log.get('provider_id')}")

# Print basic stats
print(f"\nRecords Processed: {log.get('records_processed', 0):,}")
print(f"Records Succeeded: {log.get('records_succeeded', 0):,}")
print(f"Records Failed: {log.get('records_failed', 0):,}")

# Print detailed metrics if available
metrics = log.get('metrics', {})
if metrics:
    print("\n" + "=" * 70)
    print("DETAILED METRICS")
    print("=" * 70)
    print(json.dumps(metrics, indent=2))

# Print errors if any
errors = log.get('errors', [])
if errors:
    print("\n" + "=" * 70)
    print("ERRORS")
    print("=" * 70)
    for i, error in enumerate(errors[:10], 1):
        print(f"{i}. {error}")
    if len(errors) > 10:
        print(f"... and {len(errors) - 10} more errors")

print("\n" + "=" * 70)

