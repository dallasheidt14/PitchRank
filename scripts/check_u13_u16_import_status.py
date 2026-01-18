"""Check status of U13 and U16 Modular11 game imports"""
import os
import sys
import csv
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
print("U13 & U16 MODULAR11 GAME IMPORT STATUS")
print("=" * 70)

# Get all Modular11 games
print("\nFetching Modular11 games from database...")
games_result = supabase.table('games').select('id, game_uid, game_date, home_team_master_id, away_team_master_id').eq('provider_id', modular11_provider_id).execute()

print(f"Total Modular11 games in database: {len(games_result.data)}")

# Get all teams to check age groups
print("\nFetching all teams for age group lookup...")
all_teams_result = supabase.table('teams').select('team_id_master, age_group, team_name').execute()
teams_by_id = {team['team_id_master']: team for team in all_teams_result.data}

# Count games by age group
games_by_age = defaultdict(int)
games_with_age_mismatch = []

for game in games_result.data:
    home_id = game.get('home_team_master_id')
    away_id = game.get('away_team_master_id')
    
    home_team = teams_by_id.get(home_id)
    away_team = teams_by_id.get(away_id)
    
    if home_team and away_team:
        home_age = home_team.get('age_group', '').lower()
        away_age = away_team.get('age_group', '').lower()
        
        # Check for age mismatch
        try:
            home_age_num = int(home_age.replace('u', '').replace('U', ''))
            away_age_num = int(away_age.replace('u', '').replace('U', ''))
            
            if abs(home_age_num - away_age_num) >= 2:
                games_with_age_mismatch.append({
                    'game_uid': game.get('game_uid'),
                    'home_team': home_team.get('team_name'),
                    'home_age': home_age,
                    'away_team': away_team.get('team_name'),
                    'away_age': away_age
                })
            else:
                # Use the age group from the game (should be same for both teams)
                age_group = home_age if home_age == away_age else f"{home_age}/{away_age}"
                games_by_age[age_group] += 1
        except (ValueError, AttributeError):
            pass

print("\n" + "=" * 70)
print("GAMES BY AGE GROUP (in database)")
print("=" * 70)
for age in sorted(games_by_age.keys()):
    print(f"  {age.upper()}: {games_by_age[age]:,} games")

if games_with_age_mismatch:
    print(f"\n⚠️  WARNING: {len(games_with_age_mismatch)} games with age mismatches found!")
    print("   These should have been rejected by validation.")
else:
    print(f"\n✓ No age mismatches found in database")

# Check CSV files
print("\n" + "=" * 70)
print("CSV FILE COUNTS")
print("=" * 70)

csv_files = {
    'U13': 'scrapers/modular11_scraper/output/modular11_u13.csv',
    'U16': 'scrapers/modular11_scraper/output/modular11_u16.csv'
}

csv_counts = {}
for age, csv_path in csv_files.items():
    if Path(csv_path).exists():
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Count unique games (by game_uid or match_id)
            unique_games = set()
            for row in rows:
                game_uid = row.get('game_uid') or row.get('match_id')
                if game_uid:
                    unique_games.add(game_uid)
            csv_counts[age] = len(unique_games)
            print(f"  {age}: {len(unique_games):,} unique games in CSV")
    else:
        print(f"  {age}: CSV file not found at {csv_path}")

# Compare
print("\n" + "=" * 70)
print("COMPARISON")
print("=" * 70)

db_u13 = games_by_age.get('u13', 0)
db_u16 = games_by_age.get('u16', 0)

print(f"\nU13 Games:")
print(f"  CSV: {csv_counts.get('U13', 0):,}")
print(f"  Database: {db_u13:,}")
if csv_counts.get('U13', 0) > 0:
    coverage_u13 = (db_u13 / csv_counts['U13']) * 100
    print(f"  Coverage: {coverage_u13:.1f}%")
    if db_u13 < csv_counts['U13']:
        missing_u13 = csv_counts['U13'] - db_u13
        print(f"  ⚠️  Missing: {missing_u13:,} games")

print(f"\nU16 Games:")
print(f"  CSV: {csv_counts.get('U16', 0):,}")
print(f"  Database: {db_u16:,}")
if csv_counts.get('U16', 0) > 0:
    coverage_u16 = (db_u16 / csv_counts['U16']) * 100
    print(f"  Coverage: {coverage_u16:.1f}%")
    if db_u16 < csv_counts['U16']:
        missing_u16 = csv_counts['U16'] - db_u16
        print(f"  ⚠️  Missing: {missing_u16:,} games")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)

if db_u13 < csv_counts.get('U13', 0) or db_u16 < csv_counts.get('U16', 0):
    print("\n⚠️  Not all games are imported yet.")
    print("   Some games may have been rejected due to:")
    print("   - Age mismatches (now prevented by validation)")
    print("   - Duplicate detection")
    print("   - Missing team matches")
    print("\n   Consider re-running imports to catch any games that were")
    print("   previously rejected but should now be accepted.")
else:
    print("\n✓ All games appear to be imported!")

print("=" * 70)













