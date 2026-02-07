#!/usr/bin/env python3
"""Update specific Modular11 alias from 'import' to 'direct_id'"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

modular11_provider_id = supabase.table('providers').select('id').eq('code', 'modular11').execute().data[0]['id']

print("=" * 80)
print("UPDATING SPECIFIC ALIAS: 456_U14_AD")
print("=" * 80)

# Check current status
print("\n1. Current alias status:")
alias_result = supabase.table('team_alias_map').select(
    'id, provider_team_id, match_method, team_id_master'
).eq('provider_id', modular11_provider_id).eq('provider_team_id', '456_U14_AD').execute()

if not alias_result.data:
    print("   ❌ Alias '456_U14_AD' not found!")
    sys.exit(1)

alias = alias_result.data[0]
team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', alias['team_id_master']).execute()
team_name = team_info.data[0]['team_name'] if team_info.data else 'Unknown'

print(f"   Provider Team ID: {alias['provider_team_id']}")
print(f"   Match Method: {alias['match_method']}")
print(f"   Team: {team_name}")
print(f"   Master ID: {alias['team_id_master']}")

# Update to direct_id
print("\n2. Updating match_method to 'direct_id'...")
try:
    result = supabase.table('team_alias_map').update({
        'match_method': 'direct_id'
    }).eq('id', alias['id']).execute()
    
    if result.data:
        updated_alias = result.data[0]
        print(f"   ✅ Updated successfully!")
        print(f"   New match_method: {updated_alias['match_method']}")
    else:
        print("   ❌ Update failed - no data returned")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# Verify
print("\n3. Verifying update:")
verify_result = supabase.table('team_alias_map').select(
    'provider_team_id, match_method'
).eq('provider_id', modular11_provider_id).eq('provider_team_id', '456_U14_AD').execute()

if verify_result.data:
    print(f"   ✅ Verified: match_method = {verify_result.data[0]['match_method']}")
else:
    print("   ❌ Verification failed")

print("\n" + "=" * 80)
print("NOTE: This fixes the alias, but the games that were already imported")
print("with incorrect matches will need to be fixed separately.")
print("=" * 80)



