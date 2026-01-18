"""
Delete all U16 vs U13 age mismatch games from the database.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_KEY must be set")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def delete_age_mismatch_games():
    """Delete all U16 vs U13 age mismatch games."""
    
    print("=" * 70)
    print("DELETING U16 vs U13 AGE MISMATCH GAMES")
    print("=" * 70)
    
    # Get Modular11 provider ID
    provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
    if not provider_result.data:
        print("Error: Modular11 provider not found")
        return
    
    provider_id = provider_result.data['id']
    
    # Get all U16 Modular11 teams
    u16_teams_result = supabase.table('teams').select(
        'team_id_master, team_name, age_group'
    ).eq('provider_id', provider_id).eq('age_group', 'u16').execute()
    
    u16_teams = u16_teams_result.data
    print(f"\nFound {len(u16_teams)} U16 Modular11 teams")
    
    if not u16_teams:
        print("No U16 teams found.")
        return
    
    # Collect all problematic game UIDs
    print("\nCollecting problematic games...")
    problematic_game_uids = []
    total_games_checked = 0
    
    for team in u16_teams:
        team_id = team['team_id_master']
        team_name = team['team_name']
        
        # Get all games where this team is home or away
        home_games = supabase.table('games').select(
            'game_uid, game_date, home_team_master_id, away_team_master_id'
        ).eq('home_team_master_id', team_id).execute()
        
        away_games = supabase.table('games').select(
            'game_uid, game_date, home_team_master_id, away_team_master_id'
        ).eq('away_team_master_id', team_id).execute()
        
        all_games = home_games.data + away_games.data
        total_games_checked += len(all_games)
        
        # Check each game for age mismatch
        for game in all_games:
            home_id = game['home_team_master_id']
            away_id = game['away_team_master_id']
            
            # Get opponent team details
            opponent_id = away_id if home_id == team_id else home_id
            
            opponent_result = supabase.table('teams').select(
                'team_id_master, team_name, age_group'
            ).eq('team_id_master', opponent_id).single().execute()
            
            if not opponent_result.data:
                continue
            
            opponent = opponent_result.data
            opponent_age = opponent.get('age_group', '').lower()
            
            # Check for age mismatch (U16 vs U13, or age difference >= 2 years)
            if opponent_age:
                try:
                    u16_age_num = 16
                    opponent_age_num = int(opponent_age.replace('u', ''))
                    age_diff = abs(u16_age_num - opponent_age_num)
                    
                    if age_diff >= 2:
                        problematic_game_uids.append(game['game_uid'])
                except (ValueError, TypeError):
                    # Skip if age can't be parsed
                    continue
    
    print(f"Total games checked: {total_games_checked:,}")
    print(f"Problematic games found: {len(problematic_game_uids)}")
    
    if not problematic_game_uids:
        print("\nNo problematic games found to delete.")
        return
    
    # Remove duplicates
    problematic_game_uids = list(set(problematic_game_uids))
    print(f"Unique problematic games: {len(problematic_game_uids)}")
    
    # Confirm deletion
    print(f"\n⚠️  WARNING: About to delete {len(problematic_game_uids)} games")
    print("These are U16 teams playing against U13 teams (3-year age difference)")
    response = input("\nType 'DELETE' to confirm: ")
    
    if response != 'DELETE':
        print("Deletion cancelled.")
        return
    
    # Delete games in batches (Supabase has limits)
    print(f"\nDeleting {len(problematic_game_uids)} games in batches...")
    batch_size = 100
    deleted_count = 0
    failed_count = 0
    
    for i in range(0, len(problematic_game_uids), batch_size):
        batch = problematic_game_uids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(problematic_game_uids) + batch_size - 1) // batch_size
        
        print(f"  Deleting batch {batch_num}/{total_batches} ({len(batch)} games)...")
        
        try:
            # Delete from games table
            result = supabase.table('games').delete().in_('game_uid', batch).execute()
            deleted_count += len(batch)
            print(f"    ✓ Deleted {len(batch)} games")
        except Exception as e:
            print(f"    ✗ Error deleting batch: {e}")
            failed_count += len(batch)
    
    # Also clean up related records
    print("\nCleaning up related records...")
    
    # Delete from quarantine_games
    try:
        quarantine_result = supabase.table('quarantine_games').delete().in_('game_uid', problematic_game_uids).execute()
        print(f"  ✓ Cleaned up quarantine_games")
    except Exception as e:
        print(f"  ⚠ Could not clean quarantine_games: {e}")
    
    # Delete from validation_errors
    try:
        validation_result = supabase.table('validation_errors').delete().in_('game_uid', problematic_game_uids).execute()
        print(f"  ✓ Cleaned up validation_errors")
    except Exception as e:
        print(f"  ⚠ Could not clean validation_errors: {e}")
    
    # Summary
    print("\n" + "=" * 70)
    print("DELETION SUMMARY")
    print("=" * 70)
    print(f"Total problematic games found: {len(problematic_game_uids)}")
    print(f"Successfully deleted: {deleted_count}")
    print(f"Failed to delete: {failed_count}")
    print("\n✅ Deletion complete!")
    print("=" * 70)

if __name__ == '__main__':
    delete_age_mismatch_games()













