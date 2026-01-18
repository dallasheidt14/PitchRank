"""Investigate and fix U13 games incorrectly associated with U16 teams"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from datetime import datetime

# Load environment variables - same pattern as import script
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_KEY must be set")
    print("Trying alternative method...")
    # Try loading from parent directory
    parent_env = Path('..') / '.env.local'
    if parent_env.exists():
        load_dotenv(parent_env, override=True)
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: Could not load environment variables")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Find the U16 team
team_name = "Ventura County Fusion 2010B MLS"
print(f"Investigating team: {team_name}\n")
print("=" * 70)

# Search for the team
teams_result = supabase.table('teams').select('*').ilike('name', f'%{team_name}%').execute()

if not teams_result.data:
    print("Team not found")
    sys.exit(0)

for team in teams_result.data:
    print(f"\nFound team: {team['name']}")
    print(f"  Team ID: {team['team_id_master']}")
    print(f"  Age Group: {team.get('age_group', 'N/A')}")
    print(f"  Gender: {team.get('gender', 'N/A')}")
    
    team_id = team['team_id_master']
    expected_age = team.get('age_group', '').lower()
    
    # Find all games for this team
    home_games = supabase.table('games').select('*').eq('home_team_master_id', team_id).order('game_date', desc=True).execute()
    away_games = supabase.table('games').select('*').eq('away_team_master_id', team_id).order('game_date', desc=True).execute()
    
    all_games = home_games.data + away_games.data
    all_games.sort(key=lambda x: x.get('game_date', ''), reverse=True)
    
    print(f"\n  Total Games: {len(all_games)}")
    
    # Check for age mismatches
    problematic_games = []
    opponent_ids = set()
    
    for game in all_games:
        game_date = game.get('game_date', 'N/A')
        provider = game.get('provider', 'N/A')
        
        # Get opponent info
        if game.get('home_team_master_id') == team_id:
            opponent_id = game.get('away_team_master_id')
            home_away = "Home"
        else:
            opponent_id = game.get('home_team_master_id')
            home_away = "Away"
        
        if not opponent_id:
            continue
            
        opponent_ids.add(opponent_id)
        
        # Get opponent team info
        opp_result = supabase.table('teams').select('name, age_group, gender').eq('team_id_master', opponent_id).execute()
        if not opp_result.data:
            continue
            
        opponent_team = opp_result.data[0]
        opponent_name = opponent_team.get('name', 'Unknown')
        opponent_age = opponent_team.get('age_group', '').lower()
        
        # Check if opponent is U13 when this team is U16
        if 'u13' in opponent_age and 'u16' in expected_age:
            problematic_games.append({
                'game': game,
                'opponent_id': opponent_id,
                'opponent_name': opponent_name,
                'opponent_age': opponent_age,
                'home_away': home_away,
                'provider': provider
            })
    
    if problematic_games:
        print(f"\n  ⚠️  FOUND {len(problematic_games)} PROBLEMATIC GAMES (U13 opponents for U16 team):")
        print("\n" + "-" * 70)
        
        for i, prob in enumerate(problematic_games, 1):
            game = prob['game']
            print(f"\n  {i}. Game Date: {game.get('game_date')}")
            print(f"     Opponent: {prob['opponent_name']} ({prob['opponent_age']})")
            print(f"     Location: {prob['home_away']}")
            print(f"     Provider: {prob['provider']}")
            print(f"     Game UID: {game.get('game_uid', 'N/A')}")
            print(f"     Game ID: {game.get('id', 'N/A')}")
            
            # Check if this is a Modular11 game
            if prob['provider'] == 'modular11':
                print(f"     ⚠️  This is a Modular11 game - likely incorrectly matched!")
        
        print("\n" + "=" * 70)
        print("\nCHECKING TEAM ALIAS MAP FOR INCORRECT MAPPINGS:")
        print("=" * 70)
        
        # Check team_alias_map for this team
        alias_result = supabase.table('team_alias_map').select('*').eq('team_id_master', team_id).execute()
        
        if alias_result.data:
            print(f"\nFound {len(alias_result.data)} alias mappings for this team:")
            for alias in alias_result.data:
                print(f"  Provider Team ID: {alias.get('provider_team_id')}")
                print(f"  Match Method: {alias.get('match_method')}")
                print(f"  Match Confidence: {alias.get('match_confidence')}")
                print(f"  Division: {alias.get('division', 'N/A')}")
        
        # Check if any of the problematic opponents have aliases that point to this team
        print("\nChecking if U13 opponents are incorrectly mapped to this U16 team...")
        for prob in problematic_games[:5]:  # Check first 5
            opp_id = prob['opponent_id']
            opp_aliases = supabase.table('team_alias_map').select('*').eq('team_id_master', opp_id).execute()
            
            if opp_aliases.data:
                print(f"\n  Opponent: {prob['opponent_name']} (ID: {opp_id})")
                print(f"    Has {len(opp_aliases.data)} alias mappings")
                for alias in opp_aliases.data:
                    print(f"      Provider: {alias.get('provider_id')}, Provider Team ID: {alias.get('provider_team_id')}")
        
        print("\n" + "=" * 70)
        print("\nRECOMMENDATION:")
        print("=" * 70)
        print("1. These games likely have incorrect team associations")
        print("2. The U13 teams may have been incorrectly matched to U16 teams during import")
        print("3. Need to:")
        print("   a. Find the correct U13 teams for these games")
        print("   b. Update the games to use the correct team IDs")
        print("   c. Or delete these incorrectly imported games if they're from Modular11")
        
    else:
        print("\n  ✓ No problematic games found")

print("\n" + "=" * 70)













