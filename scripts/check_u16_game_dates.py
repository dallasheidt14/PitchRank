"""
Check when the problematic U16 vs U13 games were created.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

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

def check_game_dates():
    """Check when problematic games were created."""
    
    # Get Modular11 provider ID
    provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
    if not provider_result.data:
        print("Error: Modular11 provider not found")
        return
    
    provider_id = provider_result.data['id']
    
    # Get all U16 Modular11 teams
    u16_teams_result = supabase.table('teams').select('team_id_master').eq('provider_id', provider_id).eq('age_group', 'u16').execute()
    u16_team_ids = [t['team_id_master'] for t in u16_teams_result.data]
    
    if not u16_team_ids:
        print("No U16 teams found")
        return
    
    # Get all U13 teams (any provider)
    u13_teams_result = supabase.table('teams').select('team_id_master').eq('age_group', 'u13').execute()
    u13_team_ids = [t['team_id_master'] for t in u13_teams_result.data]
    
    # Find games between U16 and U13 teams
    problematic_games = []
    
    # Check games where U16 is home
    for u16_id in u16_team_ids[:10]:  # Sample first 10
        games = supabase.table('games').select(
            'game_uid, game_date, home_team_master_id, away_team_master_id, created_at'
        ).eq('home_team_master_id', u16_id).in_('away_team_master_id', u13_team_ids).limit(5).execute()
        
        problematic_games.extend(games.data)
    
    if problematic_games:
        print(f"Found {len(problematic_games)} sample problematic games")
        print("\nSample game creation dates:")
        for game in problematic_games[:5]:
            created_at = game.get('created_at', 'Unknown')
            print(f"  {game['game_uid']}: created_at = {created_at}")
    
    # Check all problematic games
    all_problematic = []
    for u16_id in u16_team_ids:
        games = supabase.table('games').select(
            'game_uid, created_at'
        ).eq('home_team_master_id', u16_id).in_('away_team_master_id', u13_team_ids).execute()
        all_problematic.extend(games.data)
        
        games2 = supabase.table('games').select(
            'game_uid, created_at'
        ).eq('away_team_master_id', u16_id).in_('home_team_master_id', u13_team_ids).execute()
        all_problematic.extend(games2.data)
    
    if all_problematic:
        print(f"\nTotal problematic games: {len(all_problematic)}")
        # Check if they have created_at
        with_dates = [g for g in all_problematic if g.get('created_at')]
        print(f"Games with created_at: {len(with_dates)}")
        
        if with_dates:
            # Parse dates and find most recent
            dates = []
            for game in with_dates:
                try:
                    dt = datetime.fromisoformat(game['created_at'].replace('Z', '+00:00'))
                    dates.append((dt, game['game_uid']))
                except:
                    pass
            
            if dates:
                dates.sort(reverse=True)
                print(f"\nMost recent problematic game: {dates[0][1]} created at {dates[0][0]}")
                print(f"Oldest problematic game: {dates[-1][1]} created at {dates[-1][0]}")

if __name__ == '__main__':
    check_game_dates()













