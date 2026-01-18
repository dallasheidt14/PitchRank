"""Check how teams got matched"""
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
supabase = create_client(supabase_url, supabase_key)

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

# Check all aliases
aliases = supabase.table('team_alias_map').select('*').eq('provider_id', provider_id).execute()
print(f'Total aliases: {len(aliases.data)}')

# Check by method
methods = {}
for a in aliases.data:
    m = a.get('match_method', 'unknown')
    methods[m] = methods.get(m, 0) + 1
print(f'Aliases by method: {methods}')

# Check missing teams
missing_ids = ['101', '103', '1134', '132', '390', '393', '871', '925']

print()
print('Checking missing teams:')
for tid in missing_ids:
    # Get the game and master ID
    game = supabase.table('games').select('home_provider_id, home_team_master_id').eq('provider_id', provider_id).eq('home_provider_id', tid).limit(1).execute()
    if game.data:
        master_id = game.data[0]['home_team_master_id']
        
        # Get team info
        team = supabase.table('teams').select('team_name, provider_team_id').eq('team_id_master', master_id).limit(1).execute()
        if team.data:
            t = team.data[0]
            print(f'{tid} -> {t["team_name"]} (provider_team_id: {t["provider_team_id"]})')













