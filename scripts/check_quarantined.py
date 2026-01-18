#!/usr/bin/env python3
"""Check what games were quarantined and why"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

result = supabase.table('quarantine_games').select(
    'reason_code, error_details, raw_data, created_at'
).gte('created_at', '2025-12-11T13:35:00').order('created_at', desc=False).limit(10).execute()

print(f"Found {len(result.data)} quarantined games (showing first 10):\n")
print("=" * 80)

for i, game in enumerate(result.data, 1):
    print(f"\nGame {i}:")
    print(f"  Reason: {game.get('reason_code', 'N/A')}")
    error = game.get('error_details', 'N/A')
    if error and len(error) > 200:
        error = error[:200] + "..."
    print(f"  Error: {error}")
    
    raw = game.get('raw_data', {})
    if isinstance(raw, dict):
        print(f"  Team: {raw.get('team_name', 'N/A')}")
        print(f"  Opponent: {raw.get('opponent_name', 'N/A')}")
        print(f"  Date: {raw.get('game_date', 'N/A')}")
    print("-" * 80)

