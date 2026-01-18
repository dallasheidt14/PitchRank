"""
Check how many teams were actually created during the most recent TGS import.
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

# Get the most recent build_id from build_logs
build_logs = supabase.table('build_logs').select('build_id, completed_at, started_at').eq(
    'provider_id', provider_id
).eq('stage', 'game_import').order('id', desc=True).limit(5).execute()

if not build_logs.data:
    print("❌ No build logs found")
    sys.exit(1)

print(f"\n📊 Recent imports:")
for i, log in enumerate(build_logs.data[:5]):
    build_id = log['build_id']
    build_time = log.get('completed_at') or log.get('started_at')
    print(f"   {i+1}. Build ID: {build_id}, Completed: {build_time}")

# Use the most recent one
build_id = build_logs.data[0]['build_id']
build_time = build_logs.data[0].get('completed_at') or build_logs.data[0].get('started_at')
print(f"\n📊 Using most recent import build_id: {build_id}")
print(f"   Completed at: {build_time}")

# Parse build time to get a time window (check teams created in the last 24 hours)
# Actually, let's check the last 2 hours to catch today's import
if build_time:
    build_dt = datetime.fromisoformat(build_time.replace('Z', '+00:00'))
    # Check last 2 hours instead of 24
    start_time = (datetime.now() - timedelta(hours=2)).isoformat()
    end_time = (datetime.now() + timedelta(minutes=5)).isoformat()
else:
    # Fallback: use last 2 hours
    end_time = datetime.now().isoformat()
    start_time = (datetime.now() - timedelta(hours=2)).isoformat()

print(f"\n🔍 Checking teams created between {start_time} and {end_time}")

# Method 1: Count team_alias_map entries with match_method='import' created during this window
alias_imports = supabase.table('team_alias_map').select(
    'id, team_id_master, provider_team_id, created_at', count='exact'
).eq('provider_id', provider_id).eq(
    'match_method', 'import'
).gte('created_at', start_time).lte('created_at', end_time).execute()

print(f"\n📈 Method 1: team_alias_map entries with match_method='import'")
print(f"   Count: {alias_imports.count if hasattr(alias_imports, 'count') else len(alias_imports.data)}")
print(f"   Sample entries:")
for entry in alias_imports.data[:10]:
    print(f"     - Provider ID: {entry['provider_team_id']} -> Master: {entry['team_id_master']} (created: {entry['created_at']})")

# Method 2: Count unique team_id_master values from those imports
if alias_imports.data:
    unique_teams = set(entry['team_id_master'] for entry in alias_imports.data)
    print(f"\n📈 Method 2: Unique teams created (from alias map)")
    print(f"   Unique team count: {len(unique_teams)}")

# Method 3: Check teams table for recently created teams
teams_recent = supabase.table('teams').select(
    'team_id_master, team_name, club_name, age_group, gender, created_at', count='exact'
).gte('created_at', start_time).lte('created_at', end_time).execute()

print(f"\n📈 Method 3: Teams table entries created in time window")
print(f"   Count: {teams_recent.count if hasattr(teams_recent, 'count') else len(teams_recent.data)}")
print(f"   Sample teams:")
for team in teams_recent.data[:10]:
    print(f"     - {team['team_name']} ({team['age_group']}, {team['gender']}) - {team['club_name']}")

# Method 4: Check team_alias_map for ALL 'import' entries (not time-filtered)
all_imports = supabase.table('team_alias_map').select(
    'id', count='exact'
).eq('provider_id', provider_id).eq('match_method', 'import').execute()

print(f"\n📈 Method 4: ALL team_alias_map entries with match_method='import' (all time)")
print(f"   Total count: {all_imports.count if hasattr(all_imports, 'count') else len(all_imports.data)}")

# Method 5: Check how many unique teams are referenced in the most recent games
recent_games = supabase.table('games').select(
    'home_team_master_id, away_team_master_id'
).eq('provider_id', provider_id).order('created_at', desc=True).limit(1000).execute()

if recent_games.data:
    unique_game_teams = set()
    for game in recent_games.data:
        if game.get('home_team_master_id'):
            unique_game_teams.add(game['home_team_master_id'])
        if game.get('away_team_master_id'):
            unique_game_teams.add(game['away_team_master_id'])
    
    print(f"\n📈 Method 5: Unique teams in most recent 1000 games")
    print(f"   Unique team count: {len(unique_game_teams)}")
    
    # Check how many of these teams were created recently
    if unique_game_teams:
        teams_list = list(unique_game_teams)[:100]  # Limit to 100 for query
        teams_info = supabase.table('teams').select(
            'team_id_master, created_at'
        ).in_('team_id_master', teams_list).execute()
        
        recent_count = sum(1 for t in teams_info.data 
                          if t.get('created_at') and 
                          start_time <= t['created_at'] <= end_time)
        print(f"   Teams created in time window: {recent_count}")

print("\n" + "="*80)
print("SUMMARY")
print("="*80)
print(f"Most likely teams created: {alias_imports.count if hasattr(alias_imports, 'count') else len(alias_imports.data)}")
print(f"Unique teams created: {len(unique_teams) if alias_imports.data else 0}")

