"""Check if we have all U16 games from the import"""
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
print("CHECKING U16 GAME COUNT")
print("=" * 70)

# Count U16 games in CSV
csv_path = Path('scrapers/modular11_scraper/output/modular11_u16.csv')
if not csv_path.exists():
    print(f"\nError: CSV file not found: {csv_path}")
    sys.exit(1)

print(f"\nReading CSV: {csv_path}")
csv_games = []
unique_game_uids = set()

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        # Generate game_uid (same way as the import does)
        game_date = row.get('game_date', '')
        team_id = row.get('team_id', '')
        opponent_id = row.get('opponent_id', '')
        
        if game_date and team_id and opponent_id:
            # Create game_uid (perspective-based, so each game appears twice)
            game_uid = f"modular11:{game_date}:{team_id}:{opponent_id}"
            unique_game_uids.add(game_uid)
            csv_games.append(row)

print(f"Total rows in CSV: {len(csv_games)}")
print(f"Unique games (deduplicated): {len(unique_game_uids)}")

# Count U16 games in database
print(f"\nCounting U16 games in database...")

# Get all U16 Modular11 teams
u16_teams_result = supabase.table('teams').select('team_id_master').eq('provider_id', modular11_provider_id).ilike('age_group', '%u16%').execute()

u16_team_ids = [t['team_id_master'] for t in u16_teams_result.data]
print(f"Found {len(u16_team_ids)} U16 Modular11 teams in database")

# Count games where U16 teams are involved
if u16_team_ids:
    # Count home games
    home_games_result = supabase.table('games').select('game_uid', count='exact').eq('provider_id', modular11_provider_id).in_('home_team_master_id', u16_team_ids).execute()
    home_count = home_games_result.count if hasattr(home_games_result, 'count') else len(home_games_result.data) if home_games_result.data else 0
    
    # Count away games
    away_games_result = supabase.table('games').select('game_uid', count='exact').eq('provider_id', modular11_provider_id).in_('away_team_master_id', u16_team_ids).execute()
    away_count = away_games_result.count if hasattr(away_games_result, 'count') else len(away_games_result.data) if away_games_result.data else 0
    
    # Get unique game UIDs (games appear twice - once as home, once as away)
    all_game_uids = set()
    if home_games_result.data:
        for g in home_games_result.data:
            all_game_uids.add(g.get('game_uid'))
    if away_games_result.data:
        for g in away_games_result.data:
            all_game_uids.add(g.get('game_uid'))
    
    print(f"\nDatabase U16 games:")
    print(f"  Home games: {home_count}")
    print(f"  Away games: {away_count}")
    print(f"  Unique games: {len(all_game_uids)}")
else:
    print("\n⚠️  No U16 teams found in database!")
    all_game_uids = set()

# Compare
print("\n" + "=" * 70)
print("COMPARISON")
print("=" * 70)
print(f"CSV unique games: {len(unique_game_uids)}")
print(f"Database unique games: {len(all_game_uids)}")

if len(all_game_uids) < len(unique_game_uids):
    missing = len(unique_game_uids) - len(all_game_uids)
    print(f"\n⚠️  Missing {missing} games in database")
    print("   This could be due to:")
    print("   - Age mismatch games that were deleted")
    print("   - Games that failed to import")
    print("   - Duplicate detection")
    
    # Check if missing games are the ones we deleted
    print("\n   Recommendation: Re-import U16 games to ensure all valid games are present")
else:
    print(f"\n✓ Database has {len(all_game_uids)} games")
    if len(all_game_uids) == len(unique_game_uids):
        print("   Perfect match! All games are in the database.")
    else:
        print(f"   Database has {len(all_game_uids) - len(unique_game_uids)} more games than CSV")
        print("   (This is normal - could be from previous imports or perspective duplicates)")

print("\n" + "=" * 70)













