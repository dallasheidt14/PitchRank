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

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

# Check how many games have this issue - same game_uid but different age groups
print("Checking for age group conflicts in game_uid...\n")

# Get a sample of games from the recent CSV that have game_uid conflicts
import csv
from src.models.game_matcher import GameHistoryMatcher
from src.utils.enhanced_validators import parse_game_date

csv_path = Path('scrapers/modular11_scraper/output/modular11_results_20260116_151234.csv')

conflicts_by_age = {}
total_conflicts = 0

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        game_date_raw = row.get('game_date', '').strip()
        team_id = row.get('team_id', '').strip()
        opponent_id = row.get('opponent_id', '').strip()
        age_group = row.get('age_group', '').strip()
        
        if not game_date_raw or not team_id or not opponent_id:
            continue
        
        try:
            date_obj = parse_game_date(game_date_raw)
            game_date_normalized = date_obj.strftime('%Y-%m-%d')
        except:
            continue
        
        sorted_teams = sorted([team_id, opponent_id])
        game_uid = GameHistoryMatcher.generate_game_uid(
            provider='modular11',
            game_date=game_date_normalized,
            team1_id=sorted_teams[0],
            team2_id=sorted_teams[1]
        )
        
        # Check if this game_uid exists in database
        db_result = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id').eq('game_uid', game_uid).execute()
        
        if db_result.data:
            # Check if the age groups match
            db_game = db_result.data[0]
            home_team = supabase.table('teams').select('age_group').eq('team_id_master', db_game['home_team_master_id']).execute()
            away_team = supabase.table('teams').select('age_group').eq('team_id_master', db_game['away_team_master_id']).execute()
            
            if home_team.data and away_team.data:
                db_age_home = home_team.data[0].get('age_group', '').lower()
                db_age_away = away_team.data[0].get('age_group', '').lower()
                csv_age = age_group.lower()
                
                # Check if ages match
                if csv_age not in [db_age_home, db_age_away]:
                    total_conflicts += 1
                    key = f"{csv_age} vs {db_age_home}/{db_age_away}"
                    conflicts_by_age[key] = conflicts_by_age.get(key, 0) + 1
                    
                    if total_conflicts <= 5:
                        print(f"Conflict: {game_uid}")
                        print(f"  CSV age: {csv_age}, DB ages: {db_age_home}, {db_age_away}")
                        print(f"  CSV teams: {row.get('team_name')} vs {row.get('opponent_name')}")
                        print()

print(f"\nTotal age group conflicts found: {total_conflicts}")
print(f"Breakdown by age mismatch:")
for key, count in conflicts_by_age.items():
    print(f"  {key}: {count}")
