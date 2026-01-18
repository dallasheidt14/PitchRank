"""Check how many teams have no state information"""
import os
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
    exit(1)

supabase = create_client(supabase_url, supabase_key)

print("Investigating teams with no state information...\n")

# Count total teams
total_result = supabase.table('teams').select('*', count='exact').execute()
total_teams = total_result.count
print(f"Total teams in database: {total_teams:,}")

# Count teams with no state (both state and state_code are NULL)
no_state_result = supabase.table('teams').select(
    '*', 
    count='exact'
).is_('state', 'null').is_('state_code', 'null').execute()
no_state_count = no_state_result.count
print(f"Teams with no state (both state and state_code NULL): {no_state_count:,}")

# Count teams with state but no state_code
has_state_no_code_result = supabase.table('teams').select(
    '*',
    count='exact'
).not_.is_('state', 'null').is_('state_code', 'null').execute()
has_state_no_code_count = has_state_no_code_result.count
print(f"Teams with state but no state_code: {has_state_no_code_count:,}")

# Count teams with state_code but no state
has_code_no_state_result = supabase.table('teams').select(
    '*',
    count='exact'
).is_('state', 'null').not_.is_('state_code', 'null').execute()
has_code_no_state_count = has_code_no_state_result.count
print(f"Teams with state_code but no state: {has_code_no_state_count:,}")

# Count teams with both state and state_code
has_both_result = supabase.table('teams').select(
    '*',
    count='exact'
).not_.is_('state', 'null').not_.is_('state_code', 'null').execute()
has_both_count = has_both_result.count
print(f"Teams with both state and state_code: {has_both_count:,}")

print("\n" + "="*60)
print("Summary:")
print(f"  Teams with complete state info: {has_both_count:,} ({has_both_count/total_teams*100:.1f}%)")
print(f"  Teams missing state entirely: {no_state_count:,} ({no_state_count/total_teams*100:.1f}%)")
print(f"  Teams with partial state info: {has_state_no_code_count + has_code_no_state_count:,} ({(has_state_no_code_count + has_code_no_state_count)/total_teams*100:.1f}%)")

# Get some sample teams with no state
print("\n" + "="*60)
print("Sample teams with no state (first 20):")
print("-" * 60)

sample_result = supabase.table('teams').select(
    'team_id_master, team_name, club_name, age_group, gender, state, state_code'
).is_('state', 'null').is_('state_code', 'null').limit(20).execute()

if sample_result.data:
    for i, team in enumerate(sample_result.data, 1):
        print(f"{i:2d}. {team.get('team_name', 'N/A')[:50]:<50} | {team.get('age_group', 'N/A'):<4} | {team.get('gender', 'N/A')}")
        if team.get('club_name'):
            print(f"    Club: {team.get('club_name')}")
else:
    print("  No teams found with no state")

print("\n" + "="*60)
print("Investigation complete!")












