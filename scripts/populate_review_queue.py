"""Populate the team_match_review_queue with unmatched Modular11 teams"""
import os
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
provider_code = 'modular11'

print('=== POPULATING REVIEW QUEUE ===')
print()

# Get unmatched provider IDs from games
games = supabase.table('games').select(
    'home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
).eq('provider_id', provider_id).limit(500).execute()

unmatched_provider_ids = set()

for g in games.data:
    if not g.get('home_team_master_id') and g.get('home_provider_id'):
        unmatched_provider_ids.add(str(g['home_provider_id']))
    
    if not g.get('away_team_master_id') and g.get('away_provider_id'):
        unmatched_provider_ids.add(str(g['away_provider_id']))

print(f'Found {len(unmatched_provider_ids)} unmatched provider IDs')

# Load team names from scraped CSV
csv_path = Path('scrapers/modular11_scraper/output/modular11_u13.csv')
if not csv_path.exists():
    print(f'ERROR: CSV not found at {csv_path}')
    exit(1)

df = pd.read_csv(csv_path)

# Create team_id to info mapping
team_map = {}
for _, row in df.iterrows():
    tid = str(row['team_id'])
    if tid not in team_map:
        team_map[tid] = {
            'team_name': row.get('team_name', row.get('club_name', 'Unknown')),
            'club_name': row.get('club_name', ''),
            'age_group': row.get('age_group', ''),
        }

print(f'Loaded {len(team_map)} teams from CSV')
print()

# Add each to review queue
added = 0
skipped = 0

for pid in unmatched_provider_ids:
    team_info = team_map.get(pid, {})
    team_name = team_info.get('team_name', f'Unknown (ID: {pid})')
    
    # Check if already in queue
    existing = supabase.table('team_match_review_queue').select('id').eq(
        'provider_id', provider_code
    ).eq('provider_team_id', pid).eq('status', 'pending').execute()
    
    if existing.data:
        skipped += 1
        continue
    
    # Insert into queue (DB constraint: confidence_score >= 0.75)
    # We use 0.75 for "no automatic match found - needs manual review"
    try:
        supabase.table('team_match_review_queue').insert({
            'provider_id': provider_code,
            'provider_team_id': pid,
            'provider_team_name': team_name,
            'suggested_master_team_id': None,
            'confidence_score': 0.75,  # Minimum allowed, means "no match found"
            'match_details': {
                'age_group': team_info.get('age_group', 'U13'),
                'club_name': team_info.get('club_name', ''),
                'match_method': 'manual_queue'
            },
            'status': 'pending'
        }).execute()
        added += 1
        print(f'  Added: {team_name} (ID: {pid})')
    except Exception as e:
        print(f'  ERROR adding {team_name}: {e}')

print()
print(f'=== DONE ===')
print(f'Added to queue: {added}')
print(f'Already in queue: {skipped}')

