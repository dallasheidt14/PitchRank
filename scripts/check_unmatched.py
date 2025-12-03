"""Check unmatched Modular11 teams"""
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

provider_id = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

print('=== UNMATCHED MODULAR11 U13 TEAMS ===')
print()

# Get games with provider IDs
games = supabase.table('games').select(
    'home_provider_id, away_provider_id, home_team_master_id, away_team_master_id'
).eq('provider_id', provider_id).limit(500).execute()

unmatched_provider_ids = {}

for g in games.data:
    if not g.get('home_team_master_id') and g.get('home_provider_id'):
        pid = str(g['home_provider_id'])
        unmatched_provider_ids[pid] = unmatched_provider_ids.get(pid, 0) + 1
    
    if not g.get('away_team_master_id') and g.get('away_provider_id'):
        pid = str(g['away_provider_id'])
        unmatched_provider_ids[pid] = unmatched_provider_ids.get(pid, 0) + 1

# Now look up team names from the scraped CSV data
# For now just show provider IDs
sorted_teams = sorted(unmatched_provider_ids.items(), key=lambda x: x[1], reverse=True)

print(f'Found {len(sorted_teams)} unique unmatched provider IDs')
print()

# Try to get team names from teams table
print('Games  Provider ID   Team Name (from teams table)')
print('-' * 70)

for pid, count in sorted_teams:
    # Look up in teams table
    team = supabase.table('teams').select('team_name, club_name').eq('provider_team_id', pid).limit(1).execute()
    if team.data:
        name = team.data[0].get('team_name', 'Unknown')
    else:
        name = '(not in teams table - check scrape CSV)'
    print(f'{count:5d}  {pid:<12}  {name}')

