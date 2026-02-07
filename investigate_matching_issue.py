#!/usr/bin/env python3
"""Investigate why team 456 matched to wrong team"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

modular11_provider_id = supabase.table('providers').select('id').eq('code', 'modular11').execute().data[0]['id']

print("=" * 80)
print("INVESTIGATING MATCHING ISSUE")
print("=" * 80)

# Check when the alias was created
print("\n1. Alias creation times:")
aliases = supabase.table('team_alias_map').select(
    'provider_team_id, team_id_master, created_at, match_method'
).eq('provider_id', modular11_provider_id).like('provider_team_id', '456_U%').execute()

for alias in aliases.data:
    team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', alias['team_id_master']).execute()
    team_name = team_info.data[0]['team_name'] if team_info.data else 'Unknown'
    print(f"   {alias['provider_team_id']} -> {team_name} (created: {alias['created_at']})")

# Check when the games were imported
print("\n2. Game import times:")
from src.models.game_matcher import GameHistoryMatcher
from src.utils.enhanced_validators import parse_game_date

test_games = [
    {'date': '1/10/2026', 'team_id': '456', 'opponent_id': '1350'},
    {'date': '1/11/2026', 'team_id': '456', 'opponent_id': '913'},
]

for game in test_games:
    try:
        date_obj = parse_game_date(game['date'])
        game_date_normalized = date_obj.strftime('%Y-%m-%d')
    except ValueError:
        game_date_normalized = game['date']
    
    game_uid = GameHistoryMatcher.generate_game_uid(
        provider='modular11',
        game_date=game_date_normalized,
        team1_id=game['team_id'],
        team2_id=game['opponent_id']
    )
    
    game_result = supabase.table('games').select(
        'game_uid, created_at, home_provider_id, home_team_master_id'
    ).eq('provider_id', modular11_provider_id).eq('game_uid', game_uid).execute()
    
    if game_result.data:
        g = game_result.data[0]
        matched_team = supabase.table('teams').select('team_name, age_group').eq('team_id_master', g['home_team_master_id']).execute()
        team_name = matched_team.data[0]['team_name'] if matched_team.data else 'Unknown'
        print(f"   {game_uid}")
        print(f"      Created: {g['created_at']}")
        print(f"      Matched to: {team_name}")

# Check if there's a fallback match happening
print("\n3. Checking what happens if we query for '456' directly:")
# Simulate what the matcher would do - check cache first
print("   The matcher should try in order:")
print("   1. 456_U14_AD (with age_group=U14, division=AD)")
print("   2. 456_U14 (with age_group=U14)")
print("   3. 456_AD (with division=AD)")
print("   4. 456 (base ID)")

# Check what would match for each
for try_id in ['456_U14_AD', '456_U14', '456_AD', '456']:
    alias_check = supabase.table('team_alias_map').select(
        'provider_team_id, team_id_master, match_method, review_status'
    ).eq('provider_id', modular11_provider_id).eq('provider_team_id', try_id).eq('review_status', 'approved').execute()
    
    if alias_check.data:
        team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', alias_check.data[0]['team_id_master']).execute()
        team_name = team_info.data[0]['team_name'] if team_info.data else 'Unknown'
        print(f"   {try_id}: ✅ Found -> {team_name}")
    else:
        print(f"   {try_id}: ❌ Not found")

print("\n" + "=" * 80)
print("CONCLUSION:")
print("The matcher SHOULD match '456_U14_AD' first, but the games were matched")
print("to U13 teams. This suggests either:")
print("1. The games were imported before the alias existed")
print("2. The age_group validation failed and it fell back to a wrong match")
print("3. There's a bug in the matcher's priority logic")
print("=" * 80)



