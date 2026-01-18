"""Delete all Modular11 games with age mismatches (e.g., U13 vs U16)"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (or SUPABASE_KEY) must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
providers_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not providers_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

modular11_provider_id = providers_result.data[0]['id']

print("=" * 70)
print("DELETE ALL MODULAR11 AGE MISMATCH GAMES")
print("=" * 70)
print(f"\nModular11 Provider ID: {modular11_provider_id}\n")

# Get all Modular11 teams
print("Fetching all Modular11 teams...")
all_teams = []
page_size = 1000
offset = 0

while True:
    result = supabase.table('teams').select('team_id_master, team_name, age_group, gender').eq('provider_id', modular11_provider_id).range(offset, offset + page_size - 1).execute()
    
    if not result.data:
        break
    
    all_teams.extend(result.data)
    offset += page_size
    
    if len(result.data) < page_size:
        break

print(f"Found {len(all_teams)} Modular11 teams\n")

# Collect all problematic games
problematic_game_ids = []
problematic_game_uids = []

print("Identifying problematic games...")
for i, team in enumerate(all_teams, 1):
    if i % 100 == 0:
        print(f"  Processed {i}/{len(all_teams)} teams...")
    
    team_id = team['team_id_master']
    expected_age = team.get('age_group', '').lower()
    
    if not expected_age:
        continue
    
    # Get Modular11 games for this team
    home_games = supabase.table('games').select('*').eq('home_team_master_id', team_id).eq('provider_id', modular11_provider_id).execute()
    away_games = supabase.table('games').select('*').eq('away_team_master_id', team_id).eq('provider_id', modular11_provider_id).execute()
    
    all_games = home_games.data + away_games.data
    
    if not all_games:
        continue
    
    # Check for age mismatches
    for game in all_games:
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
        opponent_age = opponent_team.get('age_group', '').lower()
        
        # Check for age mismatch (age difference >= 2)
        try:
            team_age_num = int(expected_age.replace('u', '').replace('U', ''))
            opp_age_num = int(opponent_age.replace('u', '').replace('U', ''))
            
            # If age difference is >= 2, it's likely a mismatch
            if abs(team_age_num - opp_age_num) >= 2:
                game_id = game.get('id')
                game_uid = game.get('game_uid', 'N/A')
                
                if game_id and game_id not in problematic_game_ids:
                    problematic_game_ids.append(game_id)
                    problematic_game_uids.append(game_uid)
        except (ValueError, AttributeError):
            # Can't parse age, skip
            continue

print(f"\n✓ Found {len(problematic_game_ids)} problematic games to delete\n")

if not problematic_game_ids:
    print("No problematic games found. Exiting.")
    sys.exit(0)

# Show summary
print("=" * 70)
print("GAMES TO BE DELETED")
print("=" * 70)
print(f"Total games: {len(problematic_game_ids)}")
print(f"\nFirst 10 game UIDs:")
for uid in problematic_game_uids[:10]:
    print(f"  - {uid}")
if len(problematic_game_uids) > 10:
    print(f"  ... and {len(problematic_game_uids) - 10} more")

# Confirm deletion
print("\n" + "=" * 70)
response = input(f"\n⚠️  Are you sure you want to DELETE {len(problematic_game_ids)} games? (type 'DELETE' or 'delete' to confirm): ").strip().upper()

if response != 'DELETE':
    print("\nDeletion cancelled.")
    sys.exit(0)

# Delete games in batches
print(f"\nDeleting {len(problematic_game_ids)} games in batches of 100...")
deleted_count = 0
failed_count = 0

batch_size = 100
for i in range(0, len(problematic_game_ids), batch_size):
    batch = problematic_game_ids[i:i + batch_size]
    
    try:
        # Delete batch
        for game_id in batch:
            try:
                supabase.table('games').delete().eq('id', game_id).execute()
                deleted_count += 1
            except Exception as e:
                print(f"  ✗ Error deleting game {game_id}: {e}")
                failed_count += 1
        
        if (i + batch_size) % 500 == 0 or i + batch_size >= len(problematic_game_ids):
            print(f"  Progress: {deleted_count}/{len(problematic_game_ids)} deleted...")
    
    except Exception as e:
        print(f"  ✗ Error deleting batch: {e}")
        failed_count += len(batch)

print("\n" + "=" * 70)
print("DELETION COMPLETE")
print("=" * 70)
print(f"✓ Successfully deleted: {deleted_count} games")
if failed_count > 0:
    print(f"✗ Failed to delete: {failed_count} games")
print("=" * 70)

