#!/usr/bin/env python3
"""Compare teams in CSV vs teams created"""
import csv
from pathlib import Path
import os
from dotenv import load_dotenv
from supabase import create_client

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
supabase = create_client(supabase_url, supabase_key)

tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

# Get teams from CSV
csv_path = Path('data/raw/tgs/tgs_events_4066_4066_2025-12-11T20-26-36-840795+00-00.csv')
csv_teams = set()
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '')
        if team_id:
            csv_teams.add(team_id)

print(f"Unique teams in CSV: {len(csv_teams)}")
print(f"Total records in CSV: 266 (133 games × 2 perspectives)")

# Get teams that were created during import
created_teams_result = supabase.table('teams').select(
    'provider_team_id, team_name, created_at'
).eq('provider_id', tgs_provider_id).gte(
    'created_at', '2025-12-11T20:29:00'
).lte('created_at', '2025-12-11T20:31:30').execute()

created_team_ids = {t['provider_team_id'] for t in created_teams_result.data if t.get('provider_team_id')}
print(f"\nTeams CREATED during import: {len(created_team_ids)}")

# Get all TGS teams that exist (including pre-existing)
all_tgs_teams_result = supabase.table('teams').select('provider_team_id').eq('provider_id', tgs_provider_id).execute()
all_tgs_team_ids = {t['provider_team_id'] for t in all_tgs_teams_result.data if t.get('provider_team_id')}

# Teams in CSV that already existed
existing_team_ids = csv_teams & (all_tgs_team_ids - created_team_ids)
print(f"Teams in CSV that ALREADY EXISTED: {len(existing_team_ids)}")

# Teams in CSV but not in database (should be 0 if import worked)
missing_teams = csv_teams - all_tgs_team_ids
print(f"Teams in CSV but NOT in database: {len(missing_teams)}")

print(f"\nBreakdown:")
print(f"  CSV teams: {len(csv_teams)}")
print(f"  - Created during import: {len(created_team_ids)}")
print(f"  - Already existed: {len(existing_team_ids)}")
print(f"  - Missing: {len(missing_teams)}")
print(f"\n  Total in database: {len(all_tgs_team_ids)}")

if existing_team_ids:
    print(f"\n\nTeams that already existed ({len(existing_team_ids)}):")
    existing_teams_result = supabase.table('teams').select(
        'provider_team_id, team_name, created_at'
    ).eq('provider_id', tgs_provider_id).in_('provider_team_id', list(existing_team_ids)[:10]).execute()
    for team in existing_teams_result.data:
        print(f"  {team['provider_team_id']:<12} {team['team_name']:<50} Created: {team['created_at'][:10]}")









