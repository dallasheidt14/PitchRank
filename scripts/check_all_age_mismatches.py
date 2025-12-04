#!/usr/bin/env python3
"""Check ALL teams for age group mismatches (with pagination)"""
import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Load .env.local
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
client = create_client(supabase_url, supabase_key)

CURRENT_YEAR = 2025

def extract_birth_year(team_name):
    match = re.search(r'\b(20\d{2})\b', team_name)
    if match:
        year = int(match.group(1))
        if 2005 <= year <= 2018:
            return year
    return None

def calculate_age_group(birth_year):
    age = CURRENT_YEAR - birth_year + 1
    if 7 <= age <= 19:
        return f'u{age}'
    return None

print('=' * 70)
print('CHECKING ALL TEAMS FOR AGE GROUP MISMATCHES')
print('=' * 70)
print()
print('Fetching ALL teams with pagination...')

all_teams = []
offset = 0
batch_size = 1000

while True:
    result = client.table('teams').select('team_id_master, team_name, age_group').range(offset, offset + batch_size - 1).execute()
    if not result.data:
        break
    all_teams.extend(result.data)
    print(f'  Fetched {len(all_teams)} teams...')
    if len(result.data) < batch_size:
        break
    offset += batch_size

print()
print(f'Total teams in database: {len(all_teams)}')
print()

# Find mismatches
mismatches = []
for team in all_teams:
    team_name = team.get('team_name', '')
    current_age_group = (team.get('age_group') or '').lower()
    birth_year = extract_birth_year(team_name)
    if birth_year:
        expected = calculate_age_group(birth_year)
        if expected and expected != current_age_group:
            mismatches.append({
                'id': team['team_id_master'],
                'name': team_name,
                'current': current_age_group,
                'expected': expected,
                'birth_year': birth_year
            })

print('=' * 70)
print(f'TOTAL MISMATCHES FOUND: {len(mismatches)}')
print('=' * 70)
print()

if mismatches:
    print('Sample mismatches (first 50):')
    print('-' * 80)
    print(f"{'Team Name':<47} {'Current':>8} {'Expected':>8} {'Birth':>6}")
    print('-' * 80)
    
    for m in mismatches[:50]:
        name = m['name'][:45] if len(m['name']) <= 45 else m['name'][:43] + '..'
        print(f"{name:<47} {m['current']:>8} {m['expected']:>8} {m['birth_year']:>6}")
    
    if len(mismatches) > 50:
        print(f'... and {len(mismatches) - 50} more teams')
    
    print()
    print('To fix all these, update fix_team_age_groups.py to use pagination.')

