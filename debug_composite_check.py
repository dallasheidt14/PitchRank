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

# Check the game that failed: modular11:2025-11-23:1348:456
game_uid = 'modular11:2025-11-23:1348:456'

print(f"Checking game_uid: {game_uid}\n")

# Get all games with this game_uid
result = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('game_uid', game_uid).execute()

print(f"Found {len(result.data)} games with this game_uid:")
for game in result.data:
    print(f"  home={game['home_provider_id']}, away={game['away_provider_id']}")
    print(f"  scores={game['home_score']}-{game['away_score']}")
    print()

# Now check CSV for this game
import csv
csv_path = Path('scrapers/modular11_scraper/output/MODU14.csv')

print("Checking CSV for games with team 1348 or 456 on 2025-11-23:")
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('game_date', '').strip() == '11/23/2025':
            team_id = row.get('team_id', '').strip()
            opponent_id = row.get('opponent_id', '').strip()
            if team_id in ['1348', '456'] or opponent_id in ['1348', '456']:
                print(f"\nCSV row:")
                print(f"  team_id={team_id}, opponent_id={opponent_id}")
                print(f"  goals_for={row['goals_for']}, goals_against={row['goals_against']}")
                print(f"  home_away={row['home_away']}")
                
                # Determine home/away
                if row['home_away'] == 'H':
                    csv_home_id = team_id
                    csv_away_id = opponent_id
                    csv_home_score = int(row['goals_for'])
                    csv_away_score = int(row['goals_against'])
                else:
                    csv_home_id = opponent_id
                    csv_away_id = team_id
                    csv_home_score = int(row['goals_against'])
                    csv_away_score = int(row['goals_for'])
                
                print(f"  After transform: home={csv_home_id}, away={csv_away_id}, scores={csv_home_score}-{csv_away_score}")
                
                # Check if this matches any DB game
                for db_game in result.data:
                    if (db_game['home_provider_id'] == csv_home_id and 
                        db_game['away_provider_id'] == csv_away_id and
                        db_game['home_score'] == csv_home_score and
                        db_game['away_score'] == csv_away_score):
                        print(f"  ✅ MATCHES DB game (composite key match)")
                    else:
                        print(f"  ❌ Different scores - would be new game but game_uid conflict!")
