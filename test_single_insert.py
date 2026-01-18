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

# Transform game
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

# Convert date
csv_date = first_game['game_date']
parsed_date = datetime.strptime(csv_date, '%m/%d/%Y')
db_date = parsed_date.strftime('%Y-%m-%d')

# Try to insert this exact game
test_record = {
    'game_uid': f"modular11:{db_date}:{home_provider_id}:{away_provider_id}",
    'provider_id': provider_id,
    'home_provider_id': home_provider_id,
    'away_provider_id': away_provider_id,
    'home_score': home_score,
    'away_score': away_score,
    'game_date': db_date,
    'result': first_game['result'],
    'competition': first_game.get('competition'),
    'division_name': first_game.get('division_name'),
    'event_name': first_game.get('event_name'),
    'venue': first_game.get('venue'),
    'source_url': first_game.get('source_url'),
    'scraped_at': first_game.get('scraped_at'),
    'is_immutable': True
}

print(f"Attempting to insert game:")
print(f"  game_uid: {test_record['game_uid']}")
print(f"  home_provider_id: {test_record['home_provider_id']}")
print(f"  away_provider_id: {test_record['away_provider_id']}")
print(f"  home_score: {test_record['home_score']}")
print(f"  away_score: {test_record['away_score']}")
print(f"  game_date: {test_record['game_date']}")

try:
    result = supabase.table('games').insert(test_record, returning='minimal').execute()
    print(f"\n✅ SUCCESS: Game inserted!")
except Exception as e:
    print(f"\n❌ ERROR: {type(e).__name__}")
    print(f"   Message: {str(e)}")
    error_str = str(e).lower()
    if 'duplicate' in error_str or 'unique' in error_str or '23505' in error_str:
        print("   → This is a duplicate key violation")
    else:
        print("   → This is NOT a duplicate key violation - different error!")

