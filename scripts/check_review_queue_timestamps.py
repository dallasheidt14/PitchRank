#!/usr/bin/env python3
"""Check exact timestamps of review queue entries"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

db = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

entries = db.table('team_match_review_queue').select('created_at, provider_team_id, provider_team_name').eq(
    'provider_id', 'modular11'
).eq('status', 'pending').order('created_at', desc=True).limit(10).execute()

print("Top 10 review queue entries by timestamp:")
print("=" * 80)
for e in (entries.data or []):
    print(f"{e['created_at']} | {e['provider_team_id']} | {e['provider_team_name']}")

