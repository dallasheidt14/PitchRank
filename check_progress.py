#!/usr/bin/env python3
"""Check import progress"""
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get gotsport provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
provider_id = provider_result.data['id']

# Count teams
teams_result = supabase.table('teams').select('team_id_master', count='exact').eq('provider_id', provider_id).limit(1).execute()
team_count = teams_result.count if hasattr(teams_result, 'count') else 0

# Count direct ID mappings
mappings_result = supabase.table('team_alias_map').select('id', count='exact').eq('provider_id', provider_id).eq('match_method', 'direct_id').limit(1).execute()
mapping_count = mappings_result.count if hasattr(mappings_result, 'count') else 0

expected = 87166
progress_pct = (team_count / expected * 100) if expected > 0 else 0
remaining = expected - team_count

print(f"\n📊 Import Progress:")
print(f"  Teams imported: {team_count:,} / {expected:,} ({progress_pct:.1f}%)")
print(f"  Direct ID mappings: {mapping_count:,}")
print(f"  Remaining: {remaining:,} teams")
print(f"\nStatus: {'✅ Complete' if team_count >= expected else '⏳ In Progress' if team_count > 0 else '❌ Not Started'}")





