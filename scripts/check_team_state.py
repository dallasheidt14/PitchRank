"""Check if a team has state_code in database"""
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

team_id = '13d101b3-51a1-4d78-a359-635db250520b'  # TFA-AV G2014

result = supabase.table('teams').select('team_id_master, team_name, state_code, state, club_name, age_group, gender').eq('team_id_master', team_id).single().execute()

print(f"Team: {result.data['team_name']}")
print(f"State Code: {result.data['state_code']}")
print(f"State (full name): {result.data['state']}")
print(f"Club: {result.data['club_name']}")
print(f"Age Group: {result.data['age_group']}")
print(f"Gender: {result.data['gender']}")

# Also check rankings_view
ranking_result = supabase.table('rankings_view').select('team_id_master, state').eq('team_id_master', team_id).execute()
if ranking_result.data and len(ranking_result.data) > 0:
    print(f"\nIn rankings_view:")
    print(f"  State: {ranking_result.data[0].get('state')}")
else:
    print("\nNot found in rankings_view")

# Check state_rankings_view
state_ranking_result = supabase.table('state_rankings_view').select('team_id_master, state').eq('team_id_master', team_id).execute()
if state_ranking_result.data and len(state_ranking_result.data) > 0:
    print(f"\nIn state_rankings_view:")
    print(f"  State: {state_ranking_result.data[0].get('state')}")
else:
    print("\nNot found in state_rankings_view")

