#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from supabase import create_client
from pathlib import Path

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

team_uuid = 'e36421e1-d675-47f6-b70e-f417925657bc'
team = supabase.table('teams').select('*').eq('team_id_master', team_uuid).execute()

print('Team that TGS 79561 games are linked to:')
print(f"  Name: {team.data[0].get('team_name')}")
print(f"  Club: {team.data[0].get('club_name')}")
print(f"  Age Group: {team.data[0].get('age_group')}")
print(f"  Gender: {team.data[0].get('gender')}")
print(f"  Provider ID: {team.data[0].get('provider_id')}")
print(f"  Provider Team ID: {team.data[0].get('provider_team_id')}")

# Check if this team has a TGS alias
tgs_provider = supabase.table('providers').select('id').eq('code', 'tgs').execute()
tgs_provider_id = tgs_provider.data[0]['id'] if tgs_provider.data else None

aliases = supabase.table('team_alias_map').select('*').eq('team_id_master', team_uuid).eq('provider_id', tgs_provider_id).execute()
print(f"\nTGS aliases for this team:")
if aliases.data:
    for alias in aliases.data:
        print(f"  TGS Team ID: {alias.get('provider_team_id')}, Method: {alias.get('match_method')}")
else:
    print("  None")







