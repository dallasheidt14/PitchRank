#!/usr/bin/env python3
"""Verify Modular11 games were imported with correct age groups"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

# Check ALL modular11 games
print('Fetching all Modular11 games...')
all_games = []
offset = 0
while True:
    result = supabase.table('games').select(
        'game_uid, game_date, home_team_master_id, away_team_master_id'
    ).eq('provider_id', provider_id).range(offset, offset + 999).execute()
    if not result.data:
        break
    all_games.extend(result.data)
    offset += 1000
    if len(result.data) < 1000:
        break

print(f'Found {len(all_games)} Modular11 games')
result = type('obj', (object,), {'data': all_games})()

print('VERIFYING MODULAR11 IMPORTED GAMES')
print('=' * 100)
print('Checking if teams were matched to correct age groups...\n')

mismatches = 0
correct = 0

for g in result.data:
    home_id = g['home_team_master_id']
    away_id = g['away_team_master_id']
    
    if not home_id or not away_id:
        continue
    
    # Get team info
    team = supabase.table('teams').select('team_name, age_group').eq('team_id_master', home_id).limit(1).execute()
    opp = supabase.table('teams').select('team_name, age_group').eq('team_id_master', away_id).limit(1).execute()
    
    team_name = team.data[0]['team_name'] if team.data else 'Unknown'
    team_age = team.data[0]['age_group'] if team.data else '?'
    opp_name = opp.data[0]['team_name'] if opp.data else 'Unknown'
    opp_age = opp.data[0]['age_group'] if opp.data else '?'
    
    # Check if ages match
    if team_age.lower() == opp_age.lower():
        status = "✅"
        correct += 1
    else:
        status = "⚠️ AGE MISMATCH"
        mismatches += 1
        print(f"{g['game_date']}: {status}")
        print(f"   Team: {team_name} (age: {team_age})")
        print(f"   Opp:  {opp_name} (age: {opp_age})")
        print()

print('=' * 100)
print(f'RESULTS: {correct} correct, {mismatches} age mismatches')

if mismatches == 0:
    print('\n✅ ALL GOOD! Games appear to be matched to correct age groups.')
else:
    print('\n⚠️ WARNING: Some games may have age group mismatches!')

# Also count total modular11 games
total = supabase.table('games').select('game_uid', count='exact').eq('provider_id', provider_id).execute()
print(f'\nTotal Modular11 games in database: {total.count}')

