import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime, timedelta

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

# Get Modular11 provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
provider_id = provider_result.data[0]['id']

# Check recent games
recent_games = supabase.table('games').select('game_uid, game_date, created_at').eq('provider_id', provider_id).order('created_at', desc=True).limit(10).execute()

print(f'Most recent Modular11 games (last 10):')
for g in recent_games.data:
    print(f"  {g['game_uid']} - {g['game_date']} - {g['created_at']}")

# Check total count
total_result = supabase.table('games').select('game_uid', count='exact').eq('provider_id', provider_id).execute()
print(f'\nTotal Modular11 games in DB: {total_result.count}')

