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

# Read first few games from CSV
csv_path = Path('scrapers/modular11_scraper/output/MODU14.csv')
games_to_check = []
with open(csv_path, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 5:
            break
        games_to_check.append(row)

print(f"Checking {len(games_to_check)} games from CSV:\n")

for game in games_to_check:
    team_id = game['team_id']
    opponent_id = game['opponent_id']
    
    # Check if teams have master IDs
    team_aliases = supabase.table('team_alias_map').select('team_id_master').eq('provider_id', provider_id).in_('provider_team_id', [f"{team_id}_U14_AD", f"{team_id}_U14_HD", f"{team_id}_U14", team_id]).execute()
    opponent_aliases = supabase.table('team_alias_map').select('team_id_master').eq('provider_id', provider_id).in_('provider_team_id', [f"{opponent_id}_U14_AD", f"{opponent_id}_U14_HD", f"{opponent_id}_U14", opponent_id]).execute()
    
    team_master_id = team_aliases.data[0]['team_id_master'] if team_aliases.data else None
    opponent_master_id = opponent_aliases.data[0]['team_id_master'] if opponent_aliases.data else None
    
    print(f"Game: {game['team_name']} vs {game['opponent_name']}")
    print(f"  team_id={team_id}, opponent_id={opponent_id}")
    print(f"  team_master_id={team_master_id}")
    print(f"  opponent_master_id={opponent_master_id}")
    
    if not team_master_id or not opponent_master_id:
        print(f"  ⚠️  MISSING MASTER ID!")
    print()

