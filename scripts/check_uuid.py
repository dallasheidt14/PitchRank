#!/usr/bin/env python3
"""Check what a UUID refers to in the database"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
from supabase import create_client

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

uuid_to_check = "148edffd-4319-4f21-8b2b-524ad82fb0d3"

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

print(f"Checking UUID: {uuid_to_check}\n")

# Check teams table
print("1. Checking teams table (team_id_master)...")
try:
    team_result = supabase.table('teams').select('*').eq('team_id_master', uuid_to_check).execute()
    if team_result.data:
        print(f"   ✅ Found team:")
        team = team_result.data[0]
        print(f"      Team Name: {team.get('team_name')}")
        print(f"      Club Name: {team.get('club_name')}")
        print(f"      Age Group: {team.get('age_group')}")
        print(f"      Gender: {team.get('gender')}")
        print(f"      Provider ID: {team.get('provider_id')}")
        print(f"      Provider Team ID: {team.get('provider_team_id')}")
        print(f"      State Code: {team.get('state_code')}")
        print(f"      Created At: {team.get('created_at')}")
    else:
        print("   ❌ Not found in teams table")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Check games table (home_team_master_id)
print("\n2. Checking games table (home_team_master_id)...")
try:
    home_games = supabase.table('games').select('game_uid, game_date, home_score, away_score').eq('home_team_master_id', uuid_to_check).limit(5).execute()
    if home_games.data:
        print(f"   ✅ Found {len(home_games.data)} games (showing first 5)")
        for game in home_games.data[:5]:
            print(f"      {game.get('game_date')}: {game.get('home_score')}-{game.get('away_score')} ({game.get('game_uid')})")
    else:
        print("   ❌ Not found in games table (home team)")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Check games table (away_team_master_id)
print("\n3. Checking games table (away_team_master_id)...")
try:
    away_games = supabase.table('games').select('game_uid, game_date, home_score, away_score').eq('away_team_master_id', uuid_to_check).limit(5).execute()
    if away_games.data:
        print(f"   ✅ Found {len(away_games.data)} games (showing first 5)")
        for game in away_games.data[:5]:
            print(f"      {game.get('game_date')}: {game.get('home_score')}-{game.get('away_score')} ({game.get('game_uid')})")
    else:
        print("   ❌ Not found in games table (away team)")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Check team_alias_map
print("\n4. Checking team_alias_map...")
try:
    alias_result = supabase.table('team_alias_map').select('*').eq('team_id_master', uuid_to_check).execute()
    if alias_result.data:
        print(f"   ✅ Found {len(alias_result.data)} alias mappings:")
        for alias in alias_result.data:
            print(f"      Provider Team ID: {alias.get('provider_team_id')}")
            print(f"      Match Method: {alias.get('match_method')}")
            print(f"      Review Status: {alias.get('review_status')}")
            print(f"      Confidence: {alias.get('confidence')}")
    else:
        print("   ❌ Not found in team_alias_map")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Check rankings
print("\n5. Checking rankings_view...")
try:
    ranking_result = supabase.table('rankings_view').select('*').eq('team_id_master', uuid_to_check).execute()
    if ranking_result.data:
        print(f"   ✅ Found ranking:")
        ranking = ranking_result.data[0]
        print(f"      Power Score: {ranking.get('power_score')}")
        print(f"      Rank: {ranking.get('rank')}")
        print(f"      Wins: {ranking.get('wins')}")
        print(f"      Losses: {ranking.get('losses')}")
        print(f"      Draws: {ranking.get('draws')}")
    else:
        print("   ❌ Not found in rankings_view")
except Exception as e:
    print(f"   ❌ Error: {e}")

# Check providers table
print("\n6. Checking providers table...")
try:
    provider_result = supabase.table('providers').select('*').eq('id', uuid_to_check).execute()
    if provider_result.data:
        print(f"   ✅ Found provider:")
        provider = provider_result.data[0]
        print(f"      Code: {provider.get('code')}")
        print(f"      Name: {provider.get('name')}")
    else:
        print("   ❌ Not found in providers table")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "="*60)







