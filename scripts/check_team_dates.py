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

got_team = supabase.table('teams').select('created_at, team_name').eq('team_id_master', '148edffd-4319-4f21-8b2b-524ad82fb0d3').execute()
tgs_team = supabase.table('teams').select('created_at, team_name').eq('team_id_master', 'e36421e1-d675-47f6-b70e-f417925657bc').execute()

print(f"GotSport team '{got_team.data[0].get('team_name')}' created: {got_team.data[0].get('created_at')}")
print(f"TGS team '{tgs_team.data[0].get('team_name')}' created: {tgs_team.data[0].get('created_at')}")







