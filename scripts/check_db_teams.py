"""Check if teams exist in database"""
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

# Check if these teams exist in DB
test_teams = ['IMG', 'Atlanta United', 'Inter Miami', 'Philadelphia Union', 
              'New York Red Bulls', 'Chicago Fire', 'Orlando City', 
              'Real Colorado', 'Austin FC', 'FC Dallas', 'LA Galaxy',
              'Tampa Bay', 'Weston FC', 'Jacksonville']

print('Checking if teams exist in database (u13, Male):')
for team in test_teams:
    result = supabase.table('teams').select('team_id_master, team_name, club_name').eq(
        'age_group', 'u13'
    ).eq('gender', 'Male').ilike('team_name', f'%{team}%').limit(3).execute()
    
    if result.data:
        for t in result.data:
            print(f'  {team}: FOUND -> {t["team_name"]}')
    else:
        # Try club_name
        result2 = supabase.table('teams').select('team_id_master, team_name, club_name').eq(
            'age_group', 'u13'
        ).eq('gender', 'Male').ilike('club_name', f'%{team}%').limit(3).execute()
        
        if result2.data:
            for t in result2.data:
                print(f'  {team}: FOUND (club) -> {t["team_name"]}')
        else:
            print(f'  {team}: NOT FOUND in u13 Male')

# Count total u13 Male teams
total = supabase.table('teams').select('*', count='exact').eq('age_group', 'u13').eq('gender', 'Male').execute()
print(f'\nTotal u13 Male teams in DB: {total.count}')













