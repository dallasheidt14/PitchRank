#!/usr/bin/env python3
"""Update Modular11 aliases from 'import' to 'direct_id' for proper Tier 1 matching"""
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
print("FIXING MODULAR11 ALIASES: import -> direct_id")
print("=" * 80)

# Find all Modular11 aliases with match_method='import' that have provider_team_id (not fuzzy matches)
print("\n1. Finding aliases with match_method='import'...")
aliases_result = supabase.table('team_alias_map').select(
    'id, provider_team_id, team_id_master, match_method, match_confidence'
).eq('provider_id', modular11_provider_id).eq('match_method', 'import').execute()

print(f"Found {len(aliases_result.data)} aliases with match_method='import'")

# Filter to only those that look like direct IDs (have numeric provider_team_id or suffixed format)
direct_id_aliases = []
for alias in aliases_result.data:
    provider_team_id = str(alias['provider_team_id'])
    # Check if it looks like a direct ID (numeric or numeric with suffix like "456_U14_AD")
    if provider_team_id.replace('_', '').replace('-', '').isdigit() or \
       any(provider_team_id.startswith(str(i)) for i in range(10)):
        direct_id_aliases.append(alias)

print(f"Found {len(direct_id_aliases)} aliases that look like direct IDs")

# Show what will be updated
print("\n2. Aliases to update (first 10):")
for alias in direct_id_aliases[:10]:
    team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', alias['team_id_master']).execute()
    team_name = team_info.data[0]['team_name'] if team_info.data else 'Unknown'
    print(f"   {alias['provider_team_id']} -> {team_name} (confidence: {alias['match_confidence']})")

if len(direct_id_aliases) > 10:
    print(f"   ... and {len(direct_id_aliases) - 10} more")

# Ask for confirmation
print(f"\n3. Ready to update {len(direct_id_aliases)} aliases from 'import' to 'direct_id'")
response = input("   Proceed? (yes/no): ")

if response.lower() != 'yes':
    print("   Cancelled.")
    sys.exit(0)

# Update aliases
print("\n4. Updating aliases...")
updated_count = 0
failed_count = 0

for alias in direct_id_aliases:
    try:
        result = supabase.table('team_alias_map').update({
            'match_method': 'direct_id'
        }).eq('id', alias['id']).execute()
        
        if result.data:
            updated_count += 1
        else:
            failed_count += 1
            print(f"   Failed to update {alias['provider_team_id']}")
    except Exception as e:
        failed_count += 1
        print(f"   Error updating {alias['provider_team_id']}: {e}")

print(f"\n✅ Updated {updated_count} aliases")
if failed_count > 0:
    print(f"❌ Failed to update {failed_count} aliases")

# Verify the specific alias we care about
print("\n5. Verifying fix for '456_U14_AD':")
verify_result = supabase.table('team_alias_map').select(
    'provider_team_id, match_method, team_id_master'
).eq('provider_id', modular11_provider_id).eq('provider_team_id', '456_U14_AD').execute()

if verify_result.data:
    alias = verify_result.data[0]
    team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', alias['team_id_master']).execute()
    team_name = team_info.data[0]['team_name'] if team_info.data else 'Unknown'
    print(f"   ✅ {alias['provider_team_id']} -> {team_name}")
    print(f"   Match method: {alias['match_method']} (should be 'direct_id')")
else:
    print("   ❌ Alias not found!")

print("\n" + "=" * 80)
print("NOTE: You may need to re-import the games for them to match correctly.")
print("The games that were incorrectly matched will need to be updated manually")
print("or re-imported after deleting the incorrect matches.")
print("=" * 80)



