import os
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

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

csv_date = first_game['game_date']  # "11/23/2025"
print(f"CSV date: {csv_date}")

# Convert to DB format
try:
    parsed_date = datetime.strptime(csv_date, '%m/%d/%Y')
    db_date = parsed_date.strftime('%Y-%m-%d')  # "2025-11-23"
    print(f"DB date format: {db_date}")
except:
    print("Date parsing failed")

# Check what's actually in DB
existing = supabase.table('games').select('game_uid, game_date, home_provider_id, away_provider_id, home_score, away_score').eq('provider_id', provider_id).eq('game_date', db_date).limit(5).execute()

print(f"\nGames in DB with date {db_date}:")
for game in existing.data:
    print(f"  {game['game_uid']} - home={game['home_provider_id']}, away={game['away_provider_id']}, scores={game.get('home_score')}-{game.get('away_score')}")

# Check if our specific game exists
if first_game['home_away'].upper() == 'H':
    home_id = first_game['team_id']
    away_id = first_game['opponent_id']
    home_score = int(first_game['goals_for'])
    away_score = int(first_game['goals_against'])
else:
    home_id = first_game['opponent_id']
    away_id = first_game['team_id']
    home_score = int(first_game['goals_against'])
    away_score = int(first_game['goals_for'])

print(f"\nLooking for game: home={home_id}, away={away_id}, scores={home_score}-{away_score}, date={db_date}")

matching = supabase.table('games').select('*').eq('provider_id', provider_id).eq('home_provider_id', home_id).eq('away_provider_id', away_id).eq('game_date', db_date).eq('home_score', home_score).eq('away_score', away_score).execute()

print(f"Exact matches found: {len(matching.data)}")

