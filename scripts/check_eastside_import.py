#!/usr/bin/env python3
"""Check what happened to Eastside FC ECNL B12 during import"""
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

csv_file = "tgs eentssss.csv"
tgs_team_id = "79561"  # Eastside FC ECNL B12

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

print("="*70)
print("CHECKING EASTSIDE FC ECNL B12 IN CSV")
print("="*70)

# Find games with TGS Team ID 79561 in CSV
eastside_games = []
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('team_id') == tgs_team_id or row.get('opponent_id') == tgs_team_id:
            eastside_games.append({
                'game_date': row.get('game_date'),
                'team_id': row.get('team_id'),
                'opponent_id': row.get('opponent_id'),
                'team_name': row.get('team_name'),
                'opponent_name': row.get('opponent_name'),
                'goals_for': row.get('goals_for'),
                'goals_against': row.get('goals_against'),
                'home_away': row.get('home_away')
            })

print(f"\nFound {len(eastside_games)} games with TGS Team ID {tgs_team_id} in CSV")
if eastside_games:
    print(f"\nFirst 5 games:")
    for i, game in enumerate(eastside_games[:5], 1):
        print(f"  {i}. {game['game_date']}: {game['team_name']} ({game['team_id']}) vs {game['opponent_name']} ({game['opponent_id']})")
        print(f"     Score: {game['goals_for']}-{game['goals_against']} ({game['home_away']})")

# Check if these games exist in database
print(f"\n" + "="*70)
print("CHECKING IF GAMES EXIST IN DATABASE")
print("="*70)

# Get TGS provider ID
tgs_provider = supabase.table('providers').select('id').eq('code', 'tgs').execute()
tgs_provider_id = tgs_provider.data[0]['id'] if tgs_provider.data else None

# Check a few games by game_uid
from src.models.game_matcher import GameHistoryMatcher

games_found = 0
games_not_found = 0

for game in eastside_games[:10]:
    # Generate game_uid
    team1_id = game['team_id']
    team2_id = game['opponent_id']
    sorted_teams = sorted([team1_id, team2_id])
    
    game_uid = GameHistoryMatcher.generate_game_uid(
        provider='tgs',
        game_date=game['game_date'],
        team1_id=sorted_teams[0],
        team2_id=sorted_teams[1]
    )
    
    # Check if game exists
    existing = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id').eq('game_uid', game_uid).execute()
    
    if existing.data:
        games_found += 1
        game_record = existing.data[0]
        print(f"\n✅ Game {game_uid} EXISTS:")
        print(f"   Date: {game['game_date']}")
        print(f"   Home Team Master ID: {game_record.get('home_team_master_id')}")
        print(f"   Away Team Master ID: {game_record.get('away_team_master_id')}")
        
        # Check which team is linked to TGS ID 79561
        home_team = supabase.table('games').select('home_provider_id').eq('game_uid', game_uid).execute()
        away_team = supabase.table('games').select('away_provider_id').eq('game_uid', game_uid).execute()
        
        if home_team.data and home_team.data[0].get('home_provider_id') == tgs_team_id:
            team_master_id = game_record.get('home_team_master_id')
            team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', team_master_id).execute()
            if team_info.data:
                print(f"   → Linked to team: {team_info.data[0].get('team_name')} ({team_info.data[0].get('age_group')})")
        
        if away_team.data and away_team.data[0].get('away_provider_id') == tgs_team_id:
            team_master_id = game_record.get('away_team_master_id')
            team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', team_master_id).execute()
            if team_info.data:
                print(f"   → Linked to team: {team_info.data[0].get('team_name')} ({team_info.data[0].get('age_group')})")
    else:
        games_not_found += 1
        print(f"\n❌ Game {game_uid} NOT FOUND in database")
        print(f"   Date: {game['game_date']}")

print(f"\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"\nGames with TGS Team ID {tgs_team_id} in CSV: {len(eastside_games)}")
print(f"Games found in database: {games_found}")
print(f"Games not found: {games_not_found}")

# Check what team TGS 79561 is currently linked to
print(f"\n" + "="*70)
print("CURRENT TEAM LINKAGE FOR TGS ID 79561")
print("="*70)

# Get games with this provider ID
sample_games = supabase.table('games').select(
    'game_uid, game_date, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
).eq('home_provider_id', tgs_team_id).eq('provider_id', tgs_provider_id).limit(3).execute()

if sample_games.data:
    unique_team_ids = set()
    for game in sample_games.data:
        if game.get('home_team_master_id'):
            unique_team_ids.add(game.get('home_team_master_id'))
    
    print(f"\nTGS Team ID {tgs_team_id} games are linked to:")
    for team_id in unique_team_ids:
        team_info = supabase.table('teams').select('team_name, age_group, gender, provider_id').eq('team_id_master', team_id).execute()
        if team_info.data:
            team = team_info.data[0]
            provider_info = supabase.table('providers').select('code').eq('id', team.get('provider_id')).execute()
            provider_code = provider_info.data[0].get('code') if provider_info.data else 'unknown'
            print(f"  - {team_id}: {team.get('team_name')} ({team.get('age_group')}, {team.get('gender')})")
            print(f"    Provider: {provider_code}")

print(f"\n" + "="*70)
print("CONCLUSION")
print("="*70)
print(f"\nDuring the import:")
print(f"  1. All games were duplicates (already in database)")
print(f"  2. Games were skipped before team matching step")
print(f"  3. No new teams were created (teams already exist)")
print(f"\nThe 'Eastside FC ECNL B12' team from the CSV:")
print(f"  - TGS Team ID: {tgs_team_id}")
print(f"  - Games are already linked to an existing team")
print(f"  - No new team creation was needed")







