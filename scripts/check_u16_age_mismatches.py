"""
Check for age mismatches in U16 Modular11 teams' game history.

This script verifies that U16 teams don't have games against U13 teams
or other incompatible age groups after the import.
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
    print("Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
    sys.exit(1)

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def check_u16_age_mismatches():
    """Check for age mismatches involving U16 Modular11 teams."""
    
    print("=" * 70)
    print("CHECKING U16 AGE MISMATCHES")
    print("=" * 70)
    
    # Get Modular11 provider ID
    provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
    if not provider_result.data:
        print("Error: Modular11 provider not found")
        return
    
    provider_id = provider_result.data['id']
    
    # Get all U16 Modular11 teams
    u16_teams_result = supabase.table('teams').select(
        'team_id_master, team_name, age_group, provider_id'
    ).eq('provider_id', provider_id).eq('age_group', 'u16').execute()
    
    u16_teams = u16_teams_result.data
    print(f"\nFound {len(u16_teams)} U16 Modular11 teams")
    
    if not u16_teams:
        print("No U16 teams found. Nothing to check.")
        return
    
    # Check games for each U16 team
    problematic_games = []
    total_games_checked = 0
    
    for team in u16_teams:
        team_id = team['team_id_master']
        team_name = team['team_name']
        
        # Get all games where this team is home or away
        home_games = supabase.table('games').select(
            'game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score'
        ).eq('home_team_master_id', team_id).execute()
        
        away_games = supabase.table('games').select(
            'game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score'
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
                'team_id_master, team_name, age_group, provider_id'
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
                        problematic_games.append({
                            'u16_team_id': team_id,
                            'u16_team_name': team_name,
                            'opponent_id': opponent_id,
                            'opponent_name': opponent.get('team_name', 'Unknown'),
                            'opponent_age': opponent_age,
                            'age_diff': age_diff,
                            'game_uid': game['game_uid'],
                            'game_date': game.get('game_date', 'Unknown'),
                            'score': f"{game.get('home_score', '?')} - {game.get('away_score', '?')}"
                        })
                except (ValueError, TypeError):
                    # Skip if age can't be parsed
                    continue
    
    # Report results
    print(f"\nTotal games checked: {total_games_checked:,}")
    print(f"Problematic games found: {len(problematic_games)}")
    
    if problematic_games:
        print("\n" + "=" * 70)
        print("AGE MISMATCHES DETECTED:")
        print("=" * 70)
        
        # Group by opponent age
        by_opponent_age = {}
        for game in problematic_games:
            opp_age = game['opponent_age']
            if opp_age not in by_opponent_age:
                by_opponent_age[opp_age] = []
            by_opponent_age[opp_age].append(game)
        
        for opp_age in sorted(by_opponent_age.keys()):
            games = by_opponent_age[opp_age]
            print(f"\nU16 vs {opp_age.upper()} ({len(games)} games):")
            for i, game in enumerate(games[:10], 1):  # Show first 10
                print(f"  {i}. {game['u16_team_name']} vs {game['opponent_name']}")
                print(f"     Date: {game['game_date']}, Score: {game['score']}")
                print(f"     Game UID: {game['game_uid']}")
            if len(games) > 10:
                print(f"     ... and {len(games) - 10} more")
        
        print("\n" + "=" * 70)
        print("SUMMARY:")
        print("=" * 70)
        print(f"Total problematic games: {len(problematic_games)}")
        print(f"Affected U16 teams: {len(set(g['u16_team_id'] for g in problematic_games))}")
        
        # Show breakdown by age difference
        age_diff_counts = {}
        for game in problematic_games:
            diff = game['age_diff']
            age_diff_counts[diff] = age_diff_counts.get(diff, 0) + 1
        
        print("\nBreakdown by age difference:")
        for diff in sorted(age_diff_counts.keys()):
            print(f"  {diff} year(s): {age_diff_counts[diff]} games")
        
        return False  # Found issues
    else:
        print("\n✅ No age mismatches found! All U16 teams have compatible opponents.")
        return True  # No issues

if __name__ == '__main__':
    success = check_u16_age_mismatches()
    sys.exit(0 if success else 1)
