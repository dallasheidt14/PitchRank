#!/usr/bin/env python3
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
modular11_provider_id = supabase.table('providers').select('id').eq('code', 'modular11').execute().data[0]['id']

result = supabase.table('team_alias_map').select('provider_team_id, match_method').eq('provider_id', modular11_provider_id).eq('provider_team_id', '456_U14_AD').execute()

if result.data:
    print(f"Alias: {result.data[0]['provider_team_id']}")
    print(f"Match Method: {result.data[0]['match_method']}")
    if result.data[0]['match_method'] == 'direct_id':
        print("✅ Successfully updated!")
    else:
        print("❌ Still has wrong match_method")
else:
    print("❌ Alias not found")

