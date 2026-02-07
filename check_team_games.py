import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

team_master_id = 'c98a5a90-fe80-4b2f-bf96-91d7bfe18638'
provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

# Get team info
team_result = supabase.table('teams').select('team_name, age_group, gender').eq('team_id_master', team_master_id).execute()
if team_result.data:
    team = team_result.data[0]
    print(f"Team: {team['team_name']} ({team.get('age_group')}, {team.get('gender')})")
else:
    print(f"Team not found: {team_master_id}")

# Get aliases for this team
aliases_result = supabase.table('team_alias_map').select('provider_team_id').eq('team_id_master', team_master_id).eq('provider_id', provider_id).execute()
print(f"\nAliases for this team:")
for alias in aliases_result.data:
    print(f"  - {alias['provider_team_id']}")

# Check games in database for this team
print(f"\nGames in database for this team:")
games_result = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score, home_team_master_id, away_team_master_id').or_(f'home_team_master_id.eq.{team_master_id},away_team_master_id.eq.{team_master_id}').eq('provider_id', provider_id).eq('game_date', '2025-11-23').execute()

print(f"Found {len(games_result.data)} games on 2025-11-23:")
for game in games_result.data:
    print(f"  {game['game_uid']}")
    print(f"    home={game['home_provider_id']}, away={game['away_provider_id']}")
    print(f"    scores={game['home_score']}-{game['away_score']}")
    print()

# Now check CSV for games with this team's provider IDs
print("="*70)
print("Checking CSV for games with this team:")
print("="*70)

import csv
csv_path = Path('scrapers/modular11_scraper/output/MODU14.csv')
provider_ids_to_check = [alias['provider_team_id'] for alias in aliases_result.data]

# Also check base IDs (without suffixes)
base_ids = set()
for alias in aliases_result.data:
    pid = alias['provider_team_id']
    # Remove suffixes like _U14_AD, _U14, _AD
    base = pid.split('_')[0]
    base_ids.add(base)

print(f"Checking provider IDs: {list(provider_ids_to_check)}")
print(f"Checking base IDs: {list(base_ids)}")

csv_games = []
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        game_date = row.get('game_date', '').strip()
        
        # Check if this row is for our team
        if team_id in base_ids or team_id in provider_ids_to_check:
            csv_games.append({
                'team_id': team_id,
                'opponent_id': opponent_id,
                'game_date': game_date,
                'goals_for': row.get('goals_for', ''),
                'goals_against': row.get('goals_against', ''),
                'home_away': row.get('home_away', ''),
                'team_name': row.get('team_name', ''),
                'opponent_name': row.get('opponent_name', '')
            })

print(f"\nFound {len(csv_games)} CSV rows for this team:")
for game in csv_games[:10]:  # Show first 10
    print(f"  {game['team_name']} vs {game['opponent_name']}")
    print(f"    Date: {game['game_date']}, Score: {game['goals_for']}-{game['goals_against']} ({game['home_away']})")
    print(f"    team_id={game['team_id']}, opponent_id={game['opponent_id']}")
    
    # Generate game_uid
    from src.models.game_matcher import GameHistoryMatcher
    sorted_teams = sorted([game['team_id'], game['opponent_id']])
    game_uid = GameHistoryMatcher.generate_game_uid(
        provider='modular11',
        game_date=game['game_date'],
        team1_id=sorted_teams[0],
        team2_id=sorted_teams[1]
    )
    print(f"    game_uid: {game_uid}")
    
    # Check if this game exists
    exists = supabase.table('games').select('game_uid').eq('game_uid', game_uid).execute()
    if exists.data:
        print(f"    ❌ EXISTS in DB")
    else:
        print(f"    ✅ NOT in DB - should be imported")
    print()
