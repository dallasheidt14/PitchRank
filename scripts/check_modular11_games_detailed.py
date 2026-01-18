"""Detailed check of Modular11 games and their team age groups"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

print("=" * 70)
print("DETAILED MODULAR11 GAME ANALYSIS")
print("=" * 70)

# Get all Modular11 games
print("\nFetching Modular11 games...")
games_result = supabase.table('games').select('id, game_uid, game_date, home_team_master_id, away_team_master_id').eq('provider_id', modular11_provider_id).limit(10).execute()

print(f"Total Modular11 games in database: {len(games_result.data)} (showing first 10)")

# Get all teams
all_teams_result = supabase.table('teams').select('team_id_master, age_group, team_name, provider_id').execute()
teams_by_id = {team['team_id_master']: team for team in all_teams_result.data}

# Count by age group (using home team's age group)
age_counts = defaultdict(int)
sample_games = []

for game in games_result.data[:10]:
    home_id = game.get('home_team_master_id')
    away_id = game.get('away_team_master_id')
    
    home_team = teams_by_id.get(home_id)
    away_team = teams_by_id.get(away_id)
    
    home_age = home_team.get('age_group', 'Unknown') if home_team else 'No Team'
    away_age = away_team.get('age_group', 'Unknown') if away_team else 'No Team'
    home_name = home_team.get('team_name', 'Unknown') if home_team else 'No Team'
    away_name = away_team.get('team_name', 'Unknown') if away_team else 'No Team'
    
    sample_games.append({
        'game_uid': game.get('game_uid'),
        'home': f"{home_name} ({home_age})",
        'away': f"{away_name} ({away_age})"
    })
    
    if home_team:
        age_counts[home_age] += 1

print("\nSample games (first 10):")
for game in sample_games:
    print(f"  {game['game_uid']}")
    print(f"    Home: {game['home']}")
    print(f"    Away: {game['away']}")
    print()

print("\nAge group distribution (based on home team):")
for age in sorted(age_counts.keys()):
    print(f"  {age}: {age_counts[age]} games")

# Now get full count
print("\nFetching full count...")
full_games = supabase.table('games').select('home_team_master_id').eq('provider_id', modular11_provider_id).execute()

full_age_counts = defaultdict(int)
for game in full_games.data:
    home_id = game.get('home_team_master_id')
    if home_id and home_id in teams_by_id:
        age = teams_by_id[home_id].get('age_group', 'Unknown')
        full_age_counts[age] += 1

print("\nFull age group distribution:")
for age in sorted(full_age_counts.keys()):
    print(f"  {age}: {full_age_counts[age]:,} games")

print("\n" + "=" * 70)













