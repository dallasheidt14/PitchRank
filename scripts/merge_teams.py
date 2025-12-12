"""Merge two teams - deprecated team into canonical team"""
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
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

def merge_teams(deprecated_team_id: str, canonical_team_id: str, merged_by: str = "script", merge_reason: str = None):
    """Merge deprecated team into canonical team."""
    print(f"Merging teams:")
    print(f"  Deprecated Team: {deprecated_team_id}")
    print(f"  Canonical Team: {canonical_team_id}")
    print()
    
    # Check if teams exist
    deprecated_team = supabase.table('teams').select('team_id_master, team_name, club_name, age_group, gender, is_deprecated').eq('team_id_master', deprecated_team_id).maybe_single().execute()
    canonical_team = supabase.table('teams').select('team_id_master, team_name, club_name, age_group, gender, is_deprecated').eq('team_id_master', canonical_team_id).maybe_single().execute()
    
    if not deprecated_team.data:
        print(f"❌ Error: Deprecated team {deprecated_team_id} not found")
        return False
    
    if not canonical_team.data:
        print(f"❌ Error: Canonical team {canonical_team_id} not found")
        return False
    
    print("Team Information:")
    print(f"  Deprecated: {deprecated_team.data['team_name']} ({deprecated_team.data.get('club_name', 'N/A')}) - {deprecated_team.data.get('age_group', 'N/A')} {deprecated_team.data.get('gender', 'N/A')}")
    print(f"  Canonical: {canonical_team.data['team_name']} ({canonical_team.data.get('club_name', 'N/A')}) - {canonical_team.data.get('age_group', 'N/A')} {canonical_team.data.get('gender', 'N/A')}")
    print()
    
    if deprecated_team.data.get('is_deprecated'):
        print(f"⚠️  Warning: Deprecated team is already marked as deprecated")
    
    if canonical_team.data.get('is_deprecated'):
        print(f"❌ Error: Cannot merge into a deprecated team!")
        return False
    
    # Execute merge
    try:
        result = supabase.rpc('execute_team_merge', {
            'p_deprecated_team_id': deprecated_team_id,
            'p_canonical_team_id': canonical_team_id,
            'p_merged_by': merged_by,
            'p_merge_reason': merge_reason or None
        }).execute()
        
        if result.data:
            if isinstance(result.data, dict):
                if result.data.get('success'):
                    print(f"✅ Successfully merged teams!")
                    print(f"   Merge ID: {result.data.get('merge_id', 'N/A')}")
                    print(f"   Games affected: {result.data.get('games_affected', 'N/A')}")
                    print(f"   Aliases updated: {result.data.get('aliases_updated', 'N/A')}")
                    return True
                else:
                    print(f"❌ Merge failed: {result.data.get('error', 'Unknown error')}")
                    return False
            else:
                print(f"✅ Successfully merged teams! Merge ID: {result.data}")
                return True
        else:
            print(f"❌ Merge failed: No data returned")
            return False
            
    except Exception as e:
        print(f"❌ Error executing merge: {e}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python scripts/merge_teams.py <deprecated_team_id> <canonical_team_id> [merged_by] [reason]")
        print("\nExample:")
        print("  python scripts/merge_teams.py ec7b21f9-ef74-441a-94b9-ce70d5d39343 78748e84-900b-4b52-943d-c47687cda27a")
        sys.exit(1)
    
    deprecated_id = sys.argv[1]
    canonical_id = sys.argv[2]
    merged_by = sys.argv[3] if len(sys.argv) > 3 else "script"
    reason = sys.argv[4] if len(sys.argv) > 4 else None
    
    success = merge_teams(deprecated_id, canonical_id, merged_by, reason)
    sys.exit(0 if success else 1)

