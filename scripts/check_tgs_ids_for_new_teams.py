"""
Check if all newly created teams have TGS IDs stored in team_alias_map.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

supabase: Client = create_client(supabase_url, supabase_key)

# Get TGS provider ID
providers = supabase.table('providers').select('id, code').eq('code', 'tgs').execute()
if not providers.data:
    print("❌ TGS provider not found")
    sys.exit(1)

provider_id = providers.data[0]['id']
print(f"✅ Found TGS provider: {provider_id}")

# Check teams created in the last 2 hours (from the recent import)
start_time = (datetime.now() - timedelta(hours=2)).isoformat()
end_time = (datetime.now() + timedelta(minutes=5)).isoformat()

print(f"\n🔍 Checking teams created between {start_time} and {end_time}")

# Get all team_alias_map entries with match_method='import' created recently
alias_imports = supabase.table('team_alias_map').select(
    'id, provider_team_id, team_id_master, created_at'
).eq('provider_id', provider_id).eq(
    'match_method', 'import'
).gte('created_at', start_time).lte('created_at', end_time).execute()

print(f"\n📊 Found {len(alias_imports.data)} team_alias_map entries with match_method='import'")

# Check how many have provider_team_id
teams_with_id = [a for a in alias_imports.data if a.get('provider_team_id')]
teams_without_id = [a for a in alias_imports.data if not a.get('provider_team_id')]

print(f"\n✅ Teams WITH TGS provider_team_id: {len(teams_with_id)}")
print(f"❌ Teams WITHOUT TGS provider_team_id: {len(teams_without_id)}")

if teams_without_id:
    print(f"\n⚠️  Sample teams missing TGS IDs:")
    for team in teams_without_id[:10]:
        print(f"   - Master ID: {team['team_id_master']}, Created: {team['created_at']}")

# Get unique teams
unique_teams = set(entry['team_id_master'] for entry in alias_imports.data if entry.get('team_id_master'))
print(f"\n📈 Unique teams created: {len(unique_teams)}")

# Check if we can look up team details
if teams_with_id:
    print(f"\n✅ Sample teams WITH TGS IDs:")
    for team in teams_with_id[:10]:
        # Try to get team details
        team_info = supabase.table('teams').select(
            'team_id_master, team_name, club_name, age_group, gender'
        ).eq('team_id_master', team['team_id_master']).execute()
        
        if team_info.data:
            team_data = team_info.data[0]
            print(f"   - TGS ID: {team['provider_team_id']} -> {team_data['team_name']} ({team_data['age_group']}, {team_data['gender']}) - {team_data.get('club_name', 'N/A')}")
        else:
            print(f"   - TGS ID: {team['provider_team_id']} -> Master ID: {team['team_id_master']} (team not found in teams table)")

# Check if there are any teams in the teams table that don't have alias entries
print(f"\n🔍 Checking for orphaned teams (in teams table but no alias entry)...")
# This would require a more complex query, but let's at least verify the relationship

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Total alias entries: {len(alias_imports.data)}")
print(f"Teams WITH TGS provider_team_id: {len(teams_with_id)} ({len(teams_with_id)/len(alias_imports.data)*100:.1f}%)")
print(f"Teams WITHOUT TGS provider_team_id: {len(teams_without_id)} ({len(teams_without_id)/len(alias_imports.data)*100:.1f}%)")
print(f"Unique teams: {len(unique_teams)}")

if len(teams_without_id) == 0:
    print("\n✅ All teams have TGS IDs!")
else:
    print(f"\n⚠️  {len(teams_without_id)} teams are missing TGS IDs")









