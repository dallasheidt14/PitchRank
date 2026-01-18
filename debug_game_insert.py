import os
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

# Get Modular11 provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
provider_id = provider_result.data[0]['id']

# Read first game from CSV
csv_path = Path('scrapers/modular11_scraper/output/MODU14.csv')
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    first_game = next(reader)

print("First game from CSV:")
print(f"  team_id: {first_game['team_id']}")
print(f"  opponent_id: {first_game['opponent_id']}")
print(f"  game_date: {first_game['game_date']}")
print(f"  goals_for: {first_game['goals_for']}")
print(f"  goals_against: {first_game['goals_against']}")
print(f"  home_away: {first_game['home_away']}")

# Determine home/away provider IDs
if first_game['home_away'].upper() == 'H':
    home_provider_id = first_game['team_id']
    away_provider_id = first_game['opponent_id']
    home_score = int(first_game['goals_for'])
    away_score = int(first_game['goals_against'])
else:
    home_provider_id = first_game['opponent_id']
    away_provider_id = first_game['team_id']
    home_score = int(first_game['goals_against'])
    away_score = int(first_game['goals_for'])

print(f"\nAfter transformation:")
print(f"  home_provider_id: {home_provider_id}")
print(f"  away_provider_id: {away_provider_id}")
print(f"  home_score: {home_score}")
print(f"  away_score: {away_score}")
print(f"  game_date: {first_game['game_date']}")

# Check if this game exists in DB
existing = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('provider_id', provider_id).eq('home_provider_id', home_provider_id).eq('away_provider_id', away_provider_id).eq('game_date', first_game['game_date']).execute()

print(f"\nExisting games in DB with same provider_ids and date: {len(existing.data)}")
for game in existing.data:
    print(f"  {game['game_uid']} - home_score: {game.get('home_score')}, away_score: {game.get('away_score')}")

# Check with scores
existing_with_scores = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('provider_id', provider_id).eq('home_provider_id', home_provider_id).eq('away_provider_id', away_provider_id).eq('game_date', first_game['game_date']).eq('home_score', home_score).eq('away_score', away_score).execute()

print(f"\nExisting games with same scores: {len(existing_with_scores.data)}")
for game in existing_with_scores.data:
    print(f"  {game['game_uid']}")

