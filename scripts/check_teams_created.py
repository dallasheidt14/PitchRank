#!/usr/bin/env python3
"""Check how many teams were created vs matched during TGS event 4066 import"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# TGS provider ID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

# Get games imported after 13:35:00
games_result = supabase.table('games').select(
    'home_team_master_id, away_team_master_id, created_at'
).eq('provider_id', tgs_provider_id).gte(
    'created_at', '2025-12-11T13:35:00'
).execute()

if not games_result.data:
    print("No games found.")
    sys.exit(0)

# Get the earliest game creation time
earliest_game_time = min(g['created_at'] for g in games_result.data)
print(f"Earliest game import time: {earliest_game_time}")
print("=" * 80)

# Collect unique team IDs from the games
team_ids = set()
for game in games_result.data:
    if game.get('home_team_master_id'):
        team_ids.add(game['home_team_master_id'])
    if game.get('away_team_master_id'):
        team_ids.add(game['away_team_master_id'])

print(f"\nFound {len(team_ids)} unique teams in imported games\n")

# Check when each team was created
teams_created = []
teams_existing = []

for team_id_master in sorted(team_ids):
    # Get TGS team info
    tgs_team_result = supabase.table('teams').select(
        'team_id_master, team_name, provider_team_id, created_at, updated_at'
    ).eq('team_id_master', team_id_master).eq('provider_id', tgs_provider_id).execute()
    
    if tgs_team_result.data:
        tgs_team = tgs_team_result.data[0]
        created_at = tgs_team.get('created_at', '')
        
        # Check if team was created around the import time (within 5 minutes before earliest game)
        import_time = datetime.fromisoformat(earliest_game_time.replace('Z', '+00:00'))
        team_created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        
        # If team was created within 10 minutes before the first game, consider it created during import
        time_diff = (import_time - team_created_time).total_seconds()
        
        if time_diff >= 0 and time_diff <= 600:  # Created within 10 minutes before import
            teams_created.append({
                'team_id': team_id_master,
                'team_name': tgs_team.get('team_name', ''),
                'provider_team_id': tgs_team.get('provider_team_id', ''),
                'created_at': created_at
            })
        else:
            teams_existing.append({
                'team_id': team_id_master,
                'team_name': tgs_team.get('team_name', ''),
                'provider_team_id': tgs_team.get('provider_team_id', ''),
                'created_at': created_at
            })

print(f"Teams CREATED during import: {len(teams_created)}")
print(f"Teams that ALREADY EXISTED: {len(teams_existing)}")
print(f"\nTotal unique teams: {len(team_ids)}")
print(f"  (59 teams matched means {59} unique teams were involved)")

if teams_created:
    print(f"\n\nTeams Created During Import ({len(teams_created)}):")
    print("-" * 80)
    for team in sorted(teams_created, key=lambda x: x['team_name']):
        print(f"  {team['provider_team_id']:<12} {team['team_name']:<50} Created: {team['created_at']}")

if teams_existing:
    print(f"\n\nTeams That Already Existed ({len(teams_existing)}):")
    print("-" * 80)
    for team in sorted(teams_existing, key=lambda x: x['team_name']):
        print(f"  {team['provider_team_id']:<12} {team['team_name']:<50} Created: {team['created_at']}")









