"""Investigate Team 1 fuzzy match"""
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

master_team_id = 'f13aa463-60cd-4d2b-91dc-a06a071d336d'

print("="*80)
print("INVESTIGATING TEAM 1: Sporting California Perris G09")
print("="*80)

# Get master team details
result = supabase.table('teams').select('*').eq('team_id_master', master_team_id).execute()
team = result.data[0] if result.data else None

if team:
    print(f"\nMaster Team Details:")
    print(f"  Team Name: {team.get('team_name')}")
    print(f"  Club Name: {team.get('club_name')}")
    print(f"  Age Group: {team.get('age_group')}")
    print(f"  Gender: {team.get('gender')}")
    print(f"  Provider Team ID: {team.get('provider_team_id')}")
    print(f"  Provider ID: {team.get('provider_id')}")
    print(f"  Created At: {team.get('created_at')}")
    
    # Check games
    print(f"\nGames for this team:")
    games = supabase.table('games').select('event_name, game_date').or_(
        f'home_team_master_id.eq.{master_team_id},away_team_master_id.eq.{master_team_id}'
    ).order('game_date', desc=True).limit(10).execute()
    
    print(f"  Found {len(games.data)} games")
    events = set()
    for g in games.data:
        events.add(g.get('event_name'))
        print(f"    Event: {g.get('event_name')}, Date: {g.get('game_date')}")
    
    print(f"\n  Unique Events: {sorted(events)}")
    
    # Check alias map
    print(f"\nAlias Map Entries:")
    aliases = supabase.table('team_alias_map').select('*').eq('team_id_master', master_team_id).execute()
    print(f"  Found {len(aliases.data)} alias entries")
    for alias in aliases.data:
        print(f"    Provider ID: {alias.get('provider_id')}")
        print(f"    Provider Team ID: {alias.get('provider_team_id')}")
        print(f"    Match Method: {alias.get('match_method')}")
        print(f"    Created At: {alias.get('created_at')}")









