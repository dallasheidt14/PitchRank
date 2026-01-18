"""Fix U13 games incorrectly associated with U16 teams from Modular11 import"""
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

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set in .env or .env.local")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']
print(f"Modular11 Provider ID: {modular11_provider_id}\n")

# Find the U16 team
team_name = "Ventura County Fusion 2010B MLS"
print(f"Investigating team: {team_name}\n")
print("=" * 70)

# Search for the team
teams_result = supabase.table('teams').select('*').ilike('team_name', f'%{team_name}%').execute()

if not teams_result.data:
    print("Team not found")
    sys.exit(0)

team = teams_result.data[0]
team_id = team['team_id_master']
expected_age = team.get('age_group', '').lower()

print(f"Found team: {team.get('team_name', 'Unknown')}")
print(f"  Team ID: {team_id}")
print(f"  Age Group: {expected_age}")
print(f"  Gender: {team.get('gender', 'N/A')}\n")

# Find all Modular11 games for this team
print("Finding all Modular11 games for this team...")
home_games = supabase.table('games').select('*').eq('home_team_master_id', team_id).eq('provider_id', modular11_provider_id).order('game_date', desc=True).execute()
away_games = supabase.table('games').select('*').eq('away_team_master_id', team_id).eq('provider_id', modular11_provider_id).order('game_date', desc=True).execute()

all_games = home_games.data + away_games.data
all_games.sort(key=lambda x: x.get('game_date', ''), reverse=True)

print(f"Found {len(all_games)} Modular11 games\n")

# Check for age mismatches
problematic_games = []

for game in all_games:
    game_date = game.get('game_date', 'N/A')
    
    # Get opponent info
    if game.get('home_team_master_id') == team_id:
        opponent_id = game.get('away_team_master_id')
    else:
        opponent_id = game.get('home_team_master_id')
    
    if not opponent_id:
        continue
    
    # Get opponent team info
    opp_result = supabase.table('teams').select('team_name, age_group, gender').eq('team_id_master', opponent_id).execute()
    if not opp_result.data:
        continue
    
    opponent_team = opp_result.data[0]
    opponent_name = opponent_team.get('team_name', 'Unknown')
    opponent_age = opponent_team.get('age_group', '').lower()
    
    # Check if opponent is U13 when this team is U16
    if 'u13' in opponent_age and 'u16' in expected_age:
        problematic_games.append({
            'game': game,
            'opponent_id': opponent_id,
            'opponent_name': opponent_name,
            'opponent_age': opponent_age
        })

if not problematic_games:
    print("✓ No problematic games found")
    sys.exit(0)

print(f"⚠️  FOUND {len(problematic_games)} PROBLEMATIC GAMES (U13 opponents for U16 team):\n")
print("=" * 70)

for i, prob in enumerate(problematic_games, 1):
    game = prob['game']
    print(f"\n{i}. Game Date: {game.get('game_date')}")
    print(f"   Opponent: {prob['opponent_name']} ({prob['opponent_age']})")
    print(f"   Game UID: {game.get('game_uid', 'N/A')}")
    print(f"   Game ID: {game.get('id', 'N/A')}")

print("\n" + "=" * 70)
print("\nANALYSIS:")
print("=" * 70)
print("These games have U13 teams incorrectly associated with a U16 team.")
print("This likely happened during the Modular11 import when:")
print("1. U13 teams were incorrectly matched to U16 teams")
print("2. Or the games have incorrect team associations")
print("\nSOLUTION OPTIONS:")
print("1. Delete these incorrectly imported games (safest)")
print("2. Find the correct U13 teams and update the games")
print("3. Check team_alias_map for incorrect mappings")

# Ask user what to do
print("\n" + "=" * 70)
response = input("\nDo you want to DELETE these problematic games? (yes/no): ").strip().lower()

if response == 'yes':
    print("\nDeleting problematic games...")
    deleted_count = 0
    
    for prob in problematic_games:
        game = prob['game']
        game_id = game.get('id')
        
        if game_id:
            try:
                # Delete the game
                supabase.table('games').delete().eq('id', game_id).execute()
                deleted_count += 1
                print(f"  ✓ Deleted game {game.get('game_uid', game_id)}")
            except Exception as e:
                print(f"  ✗ Error deleting game {game_id}: {e}")
    
    print(f"\n✓ Deleted {deleted_count} problematic games")
else:
    print("\nNo games deleted. Please review and fix manually.")

print("\n" + "=" * 70)

