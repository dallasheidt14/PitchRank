#!/usr/bin/env python3
"""Check why fuzzy matching didn't link games to Eastside FC ECNL B12"""
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

print("="*70)
print("ANALYZING FUZZY MATCHING ISSUE")
print("="*70)

# Get team info
team_result = supabase.table('teams').select('*').eq('team_id_master', team_uuid).execute()
team = team_result.data[0]

print(f"\nTarget Team:")
print(f"  Name: {team.get('team_name')}")
print(f"  Club: {team.get('club_name')}")
print(f"  Age Group: {team.get('age_group')}")
print(f"  Gender: {team.get('gender')}")
print(f"  Provider: GotSport (ID: {team.get('provider_team_id')})")

# Get TGS provider ID
tgs_provider = supabase.table('providers').select('id').eq('code', 'tgs').execute()
tgs_provider_id = tgs_provider.data[0]['id'] if tgs_provider.data else None

print(f"\nTGS Provider ID: {tgs_provider_id}")

# Find all Eastside teams in CSV
print("\n" + "="*70)
print("Eastside FC teams in CSV file:")
print("="*70)

eastside_teams_in_csv = {}
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_name = row.get('team_name', '').strip()
        team_id = row.get('team_id', '').strip()
        club_name = row.get('club_name', '').strip()
        age_group = row.get('age_group', '').strip()
        gender = row.get('gender', '').strip()
        
        if 'eastside' in team_name.lower() or 'eastside' in (club_name or '').lower():
            key = (team_name, team_id)
            if key not in eastside_teams_in_csv:
                eastside_teams_in_csv[key] = {
                    'team_name': team_name,
                    'team_id': team_id,
                    'club_name': club_name,
                    'age_group': age_group,
                    'gender': gender
                }

for i, (key, team_data) in enumerate(eastside_teams_in_csv.items(), 1):
    print(f"\n{i}. {team_data['team_name']}")
    print(f"   TGS Team ID: {team_data['team_id']}")
    print(f"   Club: {team_data['club_name']}")
    print(f"   Age Group: {team_data['age_group']}")
    print(f"   Gender: {team_data['gender']}")

# Check if any TGS Eastside teams were matched to this GotSport team
print("\n" + "="*70)
print("Checking alias map for TGS Eastside teams:")
print("="*70)

for team_id in [t['team_id'] for t in eastside_teams_in_csv.values()]:
    alias_result = supabase.table('team_alias_map').select('*').eq(
        'provider_id', tgs_provider_id
    ).eq('provider_team_id', team_id).execute()
    
    if alias_result.data:
        for alias in alias_result.data:
            matched_team_id = alias.get('team_id_master')
            matched_team = supabase.table('teams').select('team_name, age_group, gender').eq(
                'team_id_master', matched_team_id
            ).execute()
            
            if matched_team.data:
                matched = matched_team.data[0]
                print(f"\nTGS Team ID {team_id} matched to:")
                print(f"  Team UUID: {matched_team_id}")
                print(f"  Team Name: {matched.get('team_name')}")
                print(f"  Age Group: {matched.get('age_group')}")
                print(f"  Match Method: {alias.get('match_method')}")
                print(f"  Review Status: {alias.get('review_status')}")
                
                if matched_team_id == team_uuid:
                    print(f"  ✅ MATCHED TO TARGET TEAM!")
                else:
                    print(f"  ❌ Matched to different team")

# Check games in database for TGS Eastside teams
print("\n" + "="*70)
print("Checking games in database for TGS Eastside teams:")
print("="*70)

for team_id in [t['team_id'] for t in eastside_teams_in_csv.values()]:
    # Check games by provider ID
    home_games = supabase.table('games').select(
        'game_uid, game_date, home_score, away_score, home_team_master_id'
    ).eq('home_provider_id', team_id).eq('provider_id', tgs_provider_id).limit(5).execute()
    
    away_games = supabase.table('games').select(
        'game_uid, game_date, home_score, away_score, away_team_master_id'
    ).eq('away_provider_id', team_id).eq('provider_id', tgs_provider_id).limit(5).execute()
    
    if home_games.data or away_games.data:
        print(f"\nTGS Team ID {team_id} has games:")
        for game in home_games.data[:3]:
            print(f"  {game.get('game_date')}: home_team_master_id={game.get('home_team_master_id')}")
        for game in away_games.data[:3]:
            print(f"  {game.get('game_date')}: away_team_master_id={game.get('away_team_master_id')}")

print("\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"\nTarget team '{team.get('team_name')}' (GotSport ID: {team.get('provider_team_id')})")
print(f"should have been matched to TGS teams via fuzzy matching if:")
print(f"  1. Team names are similar")
print(f"  2. Age groups match (or are close)")
print(f"  3. Gender matches")
print(f"  4. Club names match")
print(f"\nThe dry run showed 0 games accepted because all were duplicates.")
print(f"This means the games are already in the database.")
print(f"\nThe question is: Are those games linked to the correct team?")







