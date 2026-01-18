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

# Check the specific game: modular11:2025-09-06:14:249
game_uid = 'modular11:2025-09-06:14:249'

print(f"Checking game_uid: {game_uid}\n")

# Get ALL games with this game_uid
result = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score, created_at').eq('game_uid', game_uid).execute()

print(f"Found {len(result.data)} game(s) with this game_uid:")
for game in result.data:
    print(f"  home={game['home_provider_id']}, away={game['away_provider_id']}")
    print(f"  scores={game['home_score']}-{game['away_score']}")
    print(f"  date={game['game_date']}")
    print(f"  created_at={game['created_at']}")
    print()

# Also check by composite key components
print("="*70)
print("Checking by team IDs and date:")
print("="*70)

result2 = supabase.table('games').select('game_uid, home_provider_id, away_provider_id, game_date, home_score, away_score').eq('provider_id', provider_id).eq('game_date', '2025-09-06').or_('home_provider_id.eq.14,away_provider_id.eq.14').or_('home_provider_id.eq.249,away_provider_id.eq.249').execute()

print(f"Found {len(result2.data)} games on 2025-09-06 involving teams 14 or 249:")
for game in result2.data:
    print(f"  game_uid={game['game_uid']}")
    print(f"  home={game['home_provider_id']}, away={game['away_provider_id']}")
    print(f"  scores={game['home_score']}-{game['away_score']}")
    print()

# Check CSV
print("="*70)
print("Checking CSV for this game:")
print("="*70)

import csv
csv_path = Path('scrapers/modular11_scraper/output/modular11_results_20260116_151234.csv')

with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('game_date', '').strip() == '9/6/2025' or row.get('game_date', '').strip() == '09/06/2025':
            team_id = row.get('team_id', '').strip()
            opponent_id = row.get('opponent_id', '').strip()
            if (team_id == '14' and opponent_id == '249') or (team_id == '249' and opponent_id == '14'):
                print(f"CSV row:")
                print(f"  team_id={team_id}, opponent_id={opponent_id}")
                print(f"  goals_for={row['goals_for']}, goals_against={row['goals_against']}")
                print(f"  home_away={row['home_away']}")
                print(f"  team_name={row.get('team_name', '')}")
                print(f"  opponent_name={row.get('opponent_name', '')}")
                print()
