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

# Check the specific game: Aspire FC (1326) vs GFI Academy South (942) on 11/23/2025
game_uid = 'modular11:2025-11-23:1326:942'

print(f"Checking game: {game_uid}\n")

# Get from database
db_result = supabase.table('games').select('*').eq('game_uid', game_uid).execute()
if db_result.data:
    db_game = db_result.data[0]
    print("✅ Game EXISTS in database:")
    print(f"   home_provider_id={db_game['home_provider_id']}, away_provider_id={db_game['away_provider_id']}")
    print(f"   home_score={db_game['home_score']}, away_score={db_game['away_score']}")
    print(f"   home_team_master_id={db_game.get('home_team_master_id')}")
    print(f"   away_team_master_id={db_game.get('away_team_master_id')}")
else:
    print("❌ Game NOT in database")

# Check CSV
print("\n" + "="*70)
print("Checking CSV:")
print("="*70)

import csv
csv_path = Path('scrapers/modular11_scraper/output/MODU14.csv')

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('team_id', '').strip() == '1326' and row.get('opponent_id', '').strip() == '942' and row.get('game_date', '').strip() == '11/23/2025':
            print("✅ Found in CSV:")
            print(f"   team_id={row['team_id']}, opponent_id={row['opponent_id']}")
            print(f"   goals_for={row['goals_for']}, goals_against={row['goals_against']}")
            print(f"   home_away={row['home_away']}")
            
            # Determine home/away and scores
            if row['home_away'] == 'H':
                # Team 1326 is home
                csv_home_id = '1326'
                csv_away_id = '942'
                csv_home_score = int(row['goals_for'])
                csv_away_score = int(row['goals_against'])
            else:
                # Team 1326 is away
                csv_home_id = '942'
                csv_away_id = '1326'
                csv_home_score = int(row['goals_against'])
                csv_away_score = int(row['goals_for'])
            
            print(f"\n   After perspective transformation:")
            print(f"   home_provider_id={csv_home_id}, away_provider_id={csv_away_id}")
            print(f"   home_score={csv_home_score}, away_score={csv_away_score}")
            
            # Compare with database
            if db_result.data:
                db_game = db_result.data[0]
                scores_match = (
                    db_game['home_provider_id'] == csv_home_id and
                    db_game['away_provider_id'] == csv_away_id and
                    db_game['home_score'] == csv_home_score and
                    db_game['away_score'] == csv_away_score
                )
                
                if scores_match:
                    print(f"\n   ✅ Scores MATCH - this is a duplicate!")
                else:
                    print(f"\n   ❌ Scores DON'T MATCH - this should be a different game!")
                    print(f"   DB: home={db_game['home_provider_id']}, away={db_game['away_provider_id']}, scores={db_game['home_score']}-{db_game['away_score']}")
                    print(f"   CSV: home={csv_home_id}, away={csv_away_id}, scores={csv_home_score}-{csv_away_score}")
            
            break
