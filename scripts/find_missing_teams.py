#!/usr/bin/env python3
"""Find which teams are missing and why"""
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
csv_teams = {}
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '')
        team_name = row.get('team_name', '')
        if team_id:
            csv_teams[team_id] = team_name

print(f"Unique teams in CSV: {len(csv_teams)}")

# Get teams that exist in database
all_tgs_teams_result = supabase.table('teams').select('provider_team_id').eq('provider_id', tgs_provider_id).execute()
db_team_ids = {t['provider_team_id'] for t in all_tgs_teams_result.data if t.get('provider_team_id')}

# Find missing teams
missing_team_ids = set(csv_teams.keys()) - db_team_ids
print(f"Teams in CSV but NOT in database: {len(missing_team_ids)}")

if missing_team_ids:
    print(f"\nMissing teams:")
    for team_id in sorted(missing_team_ids):
        print(f"  {team_id:<12} {csv_teams.get(team_id, 'Unknown')}")
    
    # Check if these teams are in imported games
    print(f"\nChecking if missing teams appear in imported games...")
    games_result = supabase.table('games').select(
        'game_uid, home_team_master_id, away_team_master_id'
    ).eq('provider_id', tgs_provider_id).gte(
        'created_at', '2025-12-11T13:35:00'
    ).execute()
    
    # Get team IDs from games
    game_team_ids = set()
    for game in games_result.data:
        if game.get('home_team_master_id'):
            game_team_ids.add(game['home_team_master_id'])
        if game.get('away_team_master_id'):
            game_team_ids.add(game['away_team_master_id'])
    
    # Get provider team IDs for these master teams
    if game_team_ids:
        teams_in_games_result = supabase.table('teams').select(
            'team_id_master, provider_team_id'
        ).eq('provider_id', tgs_provider_id).in_('team_id_master', list(game_team_ids)[:100]).execute()
        
        teams_in_games = {t['provider_team_id'] for t in teams_in_games_result.data if t.get('provider_team_id')}
        
        missing_in_games = missing_team_ids & teams_in_games
        missing_not_in_games = missing_team_ids - teams_in_games
        
        print(f"\n  Missing teams that ARE in imported games: {len(missing_in_games)}")
        print(f"  Missing teams NOT in imported games: {len(missing_not_in_games)}")
        
        if missing_not_in_games:
            print(f"\n  These teams are likely in quarantined games (28 games were quarantined)")
            print(f"  Teams not in imported games:")
            for team_id in sorted(missing_not_in_games):
                print(f"    {team_id:<12} {csv_teams.get(team_id, 'Unknown')}")
