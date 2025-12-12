"""Check team merge status"""
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

# Team IDs from user
deprecated_team_id = 'a2126cb2-409e-4dce-896f-8928cdfea485'  # North 14B GSA
canonical_team_id = '291aa4d2-d3c9-4d22-aa6b-5f855ff19408'  # 14B GSA

print("=" * 80)
print("CHECKING TEAM MERGE STATUS")
print("=" * 80)

# Check if teams exist
print("\n1. Checking if teams exist:")
print("-" * 80)

deprecated_team = supabase.table('teams').select('team_id_master, team_name, is_deprecated, club_name, age_group, gender').eq('team_id_master', deprecated_team_id).maybe_single().execute()
if deprecated_team.data:
    print(f"✅ Deprecated Team Found:")
    print(f"   ID: {deprecated_team.data['team_id_master']}")
    print(f"   Name: {deprecated_team.data['team_name']}")
    print(f"   Is Deprecated: {deprecated_team.data.get('is_deprecated', False)}")
    print(f"   Club: {deprecated_team.data.get('club_name', 'N/A')}")
    print(f"   Age/Gender: {deprecated_team.data.get('age_group', 'N/A')} {deprecated_team.data.get('gender', 'N/A')}")
else:
    print(f"❌ Deprecated Team NOT FOUND: {deprecated_team_id}")

canonical_team = supabase.table('teams').select('team_id_master, team_name, is_deprecated, club_name, age_group, gender').eq('team_id_master', canonical_team_id).maybe_single().execute()
if canonical_team.data:
    print(f"\n✅ Canonical Team Found:")
    print(f"   ID: {canonical_team.data['team_id_master']}")
    print(f"   Name: {canonical_team.data['team_name']}")
    print(f"   Is Deprecated: {canonical_team.data.get('is_deprecated', False)}")
    print(f"   Club: {canonical_team.data.get('club_name', 'N/A')}")
    print(f"   Age/Gender: {canonical_team.data.get('age_group', 'N/A')} {canonical_team.data.get('gender', 'N/A')}")
else:
    print(f"\n❌ Canonical Team NOT FOUND: {canonical_team_id}")

# Check merge map
print("\n2. Checking team_merge_map:")
print("-" * 80)
merge_map = supabase.table('team_merge_map').select('*').eq('deprecated_team_id', deprecated_team_id).execute()
if merge_map.data:
    print(f"✅ Merge map entry found:")
    for entry in merge_map.data:
        print(f"   Merge ID: {entry['id']}")
        print(f"   Deprecated Team: {entry['deprecated_team_id']}")
        print(f"   Canonical Team: {entry['canonical_team_id']}")
        print(f"   Merged By: {entry.get('merged_by', 'N/A')}")
        print(f"   Merged At: {entry.get('merged_at', 'N/A')}")
        print(f"   Reason: {entry.get('merge_reason', 'N/A')}")
else:
    print(f"❌ NO merge map entry found for deprecated team {deprecated_team_id}")

# Check merge audit
print("\n3. Checking team_merge_audit:")
print("-" * 80)
merge_audit = supabase.table('team_merge_audit').select('*').eq('deprecated_team_id', deprecated_team_id).order('performed_at', desc=True).limit(5).execute()
if merge_audit.data:
    print(f"✅ Found {len(merge_audit.data)} audit entries:")
    for entry in merge_audit.data:
        print(f"   Action: {entry.get('action', 'N/A')}")
        print(f"   Performed By: {entry.get('performed_by', 'N/A')}")
        print(f"   Performed At: {entry.get('performed_at', 'N/A')}")
        print(f"   Games Affected: {entry.get('games_affected', 0)}")
        print(f"   Aliases Updated: {entry.get('aliases_updated', 0)}")
        print(f"   Reverted: {entry.get('reverted_at') is not None}")
        print()
else:
    print(f"❌ NO audit entries found for deprecated team {deprecated_team_id}")

# Check team_alias_map
print("\n4. Checking team_alias_map:")
print("-" * 80)
alias_map = supabase.table('team_alias_map').select('*').eq('team_id_master', deprecated_team_id).limit(5).execute()
if alias_map.data:
    print(f"✅ Found {len(alias_map.data)} alias entries still pointing to deprecated team:")
    for entry in alias_map.data[:3]:
        print(f"   Provider: {entry.get('provider', 'N/A')}")
        print(f"   Provider Team ID: {entry.get('provider_team_id', 'N/A')}")
        print()
else:
    print(f"ℹ️  No alias entries found (or already updated)")

# Check if canonical team has aliases
canonical_aliases = supabase.table('team_alias_map').select('*').eq('team_id_master', canonical_team_id).limit(5).execute()
if canonical_aliases.data:
    print(f"✅ Canonical team has {len(canonical_aliases.data)} alias entries")

# Try to execute merge again to see error
print("\n5. Testing merge function (dry run - will show error if merge exists):")
print("-" * 80)
try:
    result = supabase.rpc('execute_team_merge', {
        'p_deprecated_team_id': deprecated_team_id,
        'p_canonical_team_id': canonical_team_id,
        'p_merged_by': 'test@example.com',
        'p_merge_reason': 'Testing merge status'
    }).execute()
    
    if result.data:
        print(f"Result: {result.data}")
        if isinstance(result.data, dict):
            if result.data.get('success'):
                print("✅ Merge function returned success")
            else:
                print(f"❌ Merge function returned error: {result.data.get('error', 'Unknown error')}")
except Exception as e:
    print(f"❌ Error calling merge function: {e}")

print("\n" + "=" * 80)

