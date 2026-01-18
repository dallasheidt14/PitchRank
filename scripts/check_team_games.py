#!/usr/bin/env python3
"""Check if a team should have games from TGS import"""
import sys
from pathlib import Path
import os
import csv
from dotenv import load_dotenv
from supabase import create_client

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

team_uuid = "148edffd-4319-4f21-8b2b-524ad82fb0d3"
csv_file = "tgs eentssss.csv"

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

print(f"Checking team: {team_uuid}\n")

# Get team info
team_result = supabase.table('teams').select('*').eq('team_id_master', team_uuid).execute()
if not team_result.data:
    print("Team not found!")
    sys.exit(1)

team = team_result.data[0]
provider_team_id = team.get('provider_team_id')
provider_id = team.get('provider_id')

print(f"Team: {team.get('team_name')}")
print(f"Provider Team ID: {provider_team_id}")
print(f"Provider ID: {provider_id}\n")

# Get provider code
provider_result = supabase.table('providers').select('code').eq('id', provider_id).execute()
provider_code = provider_result.data[0].get('code') if provider_result.data else None
print(f"Provider Code: {provider_code}\n")

# Check CSV for this team ID
print("="*60)
print("Checking CSV file for this team...")
print("="*60)

team_ids_in_csv = set()
opponent_ids_in_csv = set()
games_with_team = []

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        
        if team_id:
            team_ids_in_csv.add(team_id)
        if opponent_id:
            opponent_ids_in_csv.add(opponent_id)
        
        if team_id == provider_team_id or opponent_id == provider_team_id:
            games_with_team.append({
                'game_date': row.get('game_date'),
                'team_id': team_id,
                'opponent_id': opponent_id,
                'team_name': row.get('team_name'),
                'opponent_name': row.get('opponent_name'),
                'goals_for': row.get('goals_for'),
                'goals_against': row.get('goals_against'),
                'home_away': row.get('home_away')
            })

print(f"\nTotal unique team IDs in CSV: {len(team_ids_in_csv)}")
print(f"Team ID {provider_team_id} found in CSV: {provider_team_id in team_ids_in_csv or provider_team_id in opponent_ids_in_csv}")
print(f"Games with this team ID: {len(games_with_team)}")

if games_with_team:
    print(f"\nFirst 10 games with team ID {provider_team_id}:")
    for i, game in enumerate(games_with_team[:10], 1):
        print(f"\n  {i}. Date: {game['game_date']}")
        print(f"     {game['team_name']} ({game['team_id']}) vs {game['opponent_name']} ({game['opponent_id']})")
        print(f"     Score: {game['goals_for']}-{game['goals_against']} ({game['home_away']})")

# Check database for games with this provider team ID
print("\n" + "="*60)
print("Checking database for games with this provider team ID...")
print("="*60)

# Check games table by provider IDs
home_games = supabase.table('games').select(
    'game_uid, game_date, home_score, away_score, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
).eq('home_provider_id', provider_team_id).eq('provider_id', provider_id).limit(10).execute()

away_games = supabase.table('games').select(
    'game_uid, game_date, home_score, away_score, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
).eq('away_provider_id', provider_team_id).eq('provider_id', provider_id).limit(10).execute()

print(f"\nGames in database with home_provider_id={provider_team_id}: {len(home_games.data)}")
if home_games.data:
    for game in home_games.data[:5]:
        print(f"  {game.get('game_date')}: {game.get('home_score')}-{game.get('away_score')}")
        print(f"    home_team_master_id: {game.get('home_team_master_id')}")
        print(f"    Expected: {team_uuid}")
        if game.get('home_team_master_id') != team_uuid:
            print(f"    ⚠️ MISMATCH!")

print(f"\nGames in database with away_provider_id={provider_team_id}: {len(away_games.data)}")
if away_games.data:
    for game in away_games.data[:5]:
        print(f"  {game.get('game_date')}: {game.get('home_score')}-{game.get('away_score')}")
        print(f"    away_team_master_id: {game.get('away_team_master_id')}")
        print(f"    Expected: {team_uuid}")
        if game.get('away_team_master_id') != team_uuid:
            print(f"    ⚠️ MISMATCH!")

# Check alias map
print("\n" + "="*60)
print("Checking alias map...")
print("="*60)

alias_result = supabase.table('team_alias_map').select('*').eq('provider_id', provider_id).eq('provider_team_id', provider_team_id).execute()
if alias_result.data:
    for alias in alias_result.data:
        print(f"\nAlias mapping:")
        print(f"  provider_team_id: {alias.get('provider_team_id')}")
        print(f"  team_id_master: {alias.get('team_id_master')}")
        print(f"  match_method: {alias.get('match_method')}")
        print(f"  review_status: {alias.get('review_status')}")
        if alias.get('team_id_master') != team_uuid:
            print(f"  ⚠️ MISMATCH! Expected {team_uuid}")
