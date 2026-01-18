"""
Verify that all U16 Modular11 teams have no U13 games in their game history.
This is a safety check before importing U17 games.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from collections import defaultdict

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

def get_all_teams_paginated():
    """Get all teams with pagination."""
    all_teams = []
    page_size = 1000
    offset = 0
    
    while True:
        result = supabase.table('teams').select('team_id_master, team_name, age_group, gender').range(
            offset, offset + page_size - 1
        ).execute()
        
        if not result.data:
            break
        
        all_teams.extend(result.data)
        
        if len(result.data) < page_size:
            break
        
        offset += page_size
    
    return {t['team_id_master']: t for t in all_teams}

def get_games_for_team_paginated(team_id: str, provider_id: str):
    """Get all games for a team (home and away) with pagination."""
    all_games = []
    page_size = 1000
    
    # Get home games
    offset = 0
    while True:
        result = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score'
        ).eq('home_team_master_id', team_id).eq('provider_id', provider_id).range(
            offset, offset + page_size - 1
        ).execute()
        
        if not result.data:
            break
        
        all_games.extend(result.data)
        
        if len(result.data) < page_size:
            break
        
        offset += page_size
    
    # Get away games
    offset = 0
    while True:
        result = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score'
        ).eq('away_team_master_id', team_id).eq('provider_id', provider_id).range(
            offset, offset + page_size - 1
        ).execute()
        
        if not result.data:
            break
        
        all_games.extend(result.data)
        
        if len(result.data) < page_size:
            break
        
        offset += page_size
    
    return all_games

def main():
    print("=" * 70)
    print("VERIFYING U16 MODULAR11 TEAMS - NO U13 GAMES CHECK")
    print("=" * 70)
    
    # Get Modular11 provider ID
    provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
    if not provider_result.data:
        print("Error: Modular11 provider not found")
        sys.exit(1)
    
    provider_id = provider_result.data['id']
    
    # Get all U16 Modular11 teams
    print("\n1. Fetching all U16 Modular11 teams...")
    u16_teams_result = supabase.table('teams').select(
        'team_id_master, team_name, age_group, gender'
    ).eq('provider_id', provider_id).eq('age_group', 'u16').execute()
    
    u16_teams = u16_teams_result.data
    print(f"   Found {len(u16_teams)} U16 Modular11 teams")
    
    if not u16_teams:
        print("\n✅ No U16 teams found. Nothing to check.")
        return
    
    # Get all teams for lookup (to check opponent ages)
    print("\n2. Loading all teams for age group lookup...")
    all_teams_lookup = get_all_teams_paginated()
    print(f"   Loaded {len(all_teams_lookup)} total teams")
    
    # Check each U16 team's games
    print("\n3. Checking game history for each U16 team...")
    print("-" * 70)
    
    problematic_games = []
    teams_with_issues = []
    total_games_checked = 0
    
    for i, team in enumerate(u16_teams, 1):
        team_id = team['team_id_master']
        team_name = team['team_name']
        
        if i % 10 == 0:
            print(f"   Checking team {i}/{len(u16_teams)}: {team_name[:50]}...")
        
        # Get all games for this team
        games = get_games_for_team_paginated(team_id, provider_id)
        total_games_checked += len(games)
        
        # Check each game for age mismatches
        for game in games:
            home_id = game.get('home_team_master_id')
            away_id = game.get('away_team_master_id')
            
            if not home_id or not away_id:
                continue
            
            # Determine opponent
            opponent_id = away_id if home_id == team_id else home_id
            opponent = all_teams_lookup.get(opponent_id)
            
            if not opponent:
                continue
            
            opponent_age = opponent.get('age_group', '').lower() if opponent.get('age_group') else ''
            
            if not opponent_age:
                continue
            
            # Check for age mismatch (U16 vs U13, or age difference >= 2 years)
            try:
                u16_age_num = 16
                opponent_age_num = int(opponent_age.replace('u', '').replace('U', ''))
                age_diff = abs(u16_age_num - opponent_age_num)
                
                if age_diff >= 2:
                    problematic_games.append({
                        'game_id': game.get('id'),
                        'game_uid': game.get('game_uid'),
                        'game_date': game.get('game_date', 'Unknown'),
                        'u16_team_id': team_id,
                        'u16_team_name': team_name,
                        'opponent_id': opponent_id,
                        'opponent_name': opponent.get('team_name', 'Unknown'),
                        'opponent_age': opponent_age,
                        'age_diff': age_diff,
                        'home_score': game.get('home_score'),
                        'away_score': game.get('away_score')
                    })
                    
                    if team_id not in teams_with_issues:
                        teams_with_issues.append(team_id)
            except (ValueError, TypeError):
                continue
    
    # Report results
    print("\n" + "=" * 70)
    print("VERIFICATION RESULTS")
    print("=" * 70)
    print(f"\nU16 Teams Checked: {len(u16_teams)}")
    print(f"Total Games Checked: {total_games_checked:,}")
    print(f"Teams with Age Mismatch Games: {len(teams_with_issues)}")
    print(f"Total Problematic Games Found: {len(problematic_games)}")
    
    if problematic_games:
        print("\n" + "=" * 70)
        print("❌ PROBLEMATIC GAMES FOUND")
        print("=" * 70)
        
        # Group by team
        games_by_team = defaultdict(list)
        for game in problematic_games:
            games_by_team[game['u16_team_name']].append(game)
        
        print(f"\nFound {len(teams_with_issues)} U16 teams with problematic games:\n")
        
        for team_name, games in sorted(games_by_team.items()):
            print(f"\n{team_name} ({len(games)} problematic game(s)):")
            for game in games:
                print(f"  • Game ID: {game['game_id']}")
                print(f"    Game UID: {game['game_uid']}")
                print(f"    Date: {game['game_date']}")
                print(f"    vs {game['opponent_name']} ({game['opponent_age']}) - Age diff: {game['age_diff']} years")
                print(f"    Score: {game.get('home_score', '?')} - {game.get('away_score', '?')}")
        
        # Export to file
        output_file = "u16_u13_problematic_games.txt"
        with open(output_file, "w") as f:
            f.write("U16 MODULAR11 TEAMS - PROBLEMATIC GAMES (U13 or age diff >= 2 years)\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Total Teams with Issues: {len(teams_with_issues)}\n")
            f.write(f"Total Problematic Games: {len(problematic_games)}\n\n")
            f.write("=" * 70 + "\n\n")
            
            for team_name, games in sorted(games_by_team.items()):
                f.write(f"\n{team_name} ({len(games)} problematic game(s)):\n")
                for game in games:
                    f.write(f"  Game ID: {game['game_id']}\n")
                    f.write(f"  Game UID: {game['game_uid']}\n")
                    f.write(f"  Date: {game['game_date']}\n")
                    f.write(f"  vs {game['opponent_name']} ({game['opponent_age']})\n")
                    f.write(f"  Age Difference: {game['age_diff']} years\n")
                    f.write(f"  Score: {game.get('home_score', '?')} - {game.get('away_score', '?')}\n")
                    f.write("\n")
        
        print(f"\n⚠️  Full report saved to: {output_file}")
        print("\n❌ VERIFICATION FAILED - U16 teams have problematic games!")
        print("   Please review and clean up these games before importing U17.")
        sys.exit(1)
    else:
        print("\n✅ SUCCESS: No problematic games found!")
        print("✅ All U16 Modular11 teams have clean game histories.")
        print("✅ Safe to proceed with U17 import.")
        print("=" * 70)

if __name__ == '__main__':
    main()













