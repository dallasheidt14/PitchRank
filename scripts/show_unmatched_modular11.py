#!/usr/bin/env python3
"""Show Modular11 teams that don't have approved aliases"""
import csv
from collections import defaultdict
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Read the CSV and find teams - track full team names
teams_in_csv = defaultdict(lambda: {'team_names': set(), 'games': 0, 'club': ''})

csv_path = 'scrapers/modular11_scraper/output/modular11_results_20251203_105706.csv'
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '')
        club = row.get('club_name', '')
        team_name = row.get('team_name', '')
        
        teams_in_csv[team_id]['team_names'].add(team_name)
        teams_in_csv[team_id]['club'] = club
        teams_in_csv[team_id]['games'] += 1

# Get approved aliases from DB
supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

result = supabase.table('team_alias_map').select('provider_team_id').eq(
    'provider_id', 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
).eq('review_status', 'approved').execute()
approved_ids = set(r['provider_team_id'] for r in result.data)

# Find unmatched teams
unmatched = []
for team_id, info in teams_in_csv.items():
    if team_id not in approved_ids:
        unmatched.append({
            'id': team_id,
            'club': info['club'],
            'team_names': sorted(info['team_names']),
            'games': info['games']
        })

# Sort by game count (most games first)
unmatched.sort(key=lambda x: -x['games'])

print(f'\nUNMATCHED MODULAR11 TEAMS ({len(unmatched)} teams)')
print(f'These teams have games that were NOT imported')
print('=' * 100)

for t in unmatched[:50]:
    print(f"\nID: {t['id']} | Club: {t['club']} | Games: {t['games']}")
    print(f"   Team Names: {', '.join(t['team_names'])}")

if len(unmatched) > 50:
    print(f'\n... and {len(unmatched) - 50} more teams')

# Summary
total_games = sum(t['games'] for t in unmatched)
print(f'\n' + '=' * 100)
print(f'SUMMARY:')
print(f'   Unmatched teams: {len(unmatched)}')
print(f'   Total game rows not imported: {total_games}')
print(f'   Unique games (approx): {total_games // 2}')

