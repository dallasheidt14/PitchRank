"""Analyze U16 import results to see why games weren't imported"""
import os
import sys
import csv
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

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
print("ANALYZING U16 IMPORT RESULTS")
print("=" * 70)

# Read CSV and generate game UIDs
csv_path = Path('scrapers/modular11_scraper/output/modular11_u16.csv')
print(f"\nReading CSV: {csv_path}")

csv_game_uids = set()
csv_games_by_uid = {}

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        game_date = row.get('game_date', '')
        team_id = row.get('team_id', '')
        opponent_id = row.get('opponent_id', '')
        
        if game_date and team_id and opponent_id:
            game_uid = f"modular11:{game_date}:{team_id}:{opponent_id}"
            csv_game_uids.add(game_uid)
            if game_uid not in csv_games_by_uid:
                csv_games_by_uid[game_uid] = row

print(f"CSV unique games: {len(csv_game_uids)}")

# Get all Modular11 games from database
print("\nFetching games from database...")
db_game_uids = set()

# Get games in batches
batch_size = 1000
offset = 0
while True:
    result = supabase.table('games').select('game_uid').eq('provider_id', modular11_provider_id).range(offset, offset + batch_size - 1).execute()
    
    if not result.data:
        break
    
    for game in result.data:
        game_uid = game.get('game_uid')
        if game_uid and game_uid.startswith('modular11:'):
            db_game_uids.add(game_uid)
    
    offset += batch_size
    if len(result.data) < batch_size:
        break

print(f"Database Modular11 games: {len(db_game_uids)}")

# Find missing games
missing_uids = csv_game_uids - db_game_uids
print(f"\nMissing games: {len(missing_uids)}")

# Sample some missing games to understand why
print("\nAnalyzing sample of missing games...")
sample_missing = list(missing_uids)[:20]

for game_uid in sample_missing:
    game_data = csv_games_by_uid.get(game_uid, {})
    if game_data:
        print(f"\n  Game UID: {game_uid}")
        print(f"    Date: {game_data.get('game_date')}")
        print(f"    Team: {game_data.get('team_name')} (ID: {game_data.get('team_id')})")
        print(f"    Opponent: {game_data.get('opponent_name')} (ID: {game_data.get('opponent_id')})")
        print(f"    Age: {game_data.get('age_group')}")
        print(f"    Scores: {game_data.get('goals_for')} - {game_data.get('goals_against')}")
        
        # Check if this game might be a duplicate (check reverse perspective)
        reverse_uid = f"modular11:{game_data.get('game_date')}:{game_data.get('opponent_id')}:{game_data.get('team_id')}"
        if reverse_uid in db_game_uids:
            print(f"    ⚠️  Reverse perspective exists in DB: {reverse_uid}")

# Check for games with missing scores
print("\n" + "=" * 70)
print("CHECKING FOR GAMES WITH MISSING SCORES")
print("=" * 70)

missing_scores_count = 0
for game_uid in list(csv_game_uids)[:100]:  # Check first 100
    game_data = csv_games_by_uid.get(game_uid, {})
    goals_for = game_data.get('goals_for', '').strip()
    goals_against = game_data.get('goals_against', '').strip()
    
    if not goals_for and not goals_against:
        missing_scores_count += 1
        if missing_scores_count <= 5:
            print(f"  Game with no scores: {game_uid}")

print(f"\nGames with missing scores (sample of 100): {missing_scores_count}")

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"CSV games: {len(csv_game_uids)}")
print(f"Database games: {len(db_game_uids)}")
print(f"Missing: {len(missing_uids)}")
print(f"\nPossible reasons for missing games:")
print("  1. Duplicate detection (perspective-based duplicates)")
print("  2. Missing scores (validation rejects games with no scores)")
print("  3. Games already imported from previous runs")
print("  4. Validation failures")

print("\n" + "=" * 70)













