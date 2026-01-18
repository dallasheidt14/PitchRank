"""
Re-import U16 games and immediately verify age validation is working.
Logs any cross-age games that slip through with their game IDs.
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
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

# Track game count before import
games_before_import = set()

def get_game_count_before_import(provider_id: str) -> set:
    """Get all Modular11 game UIDs before import."""
    result = supabase.table('games').select('game_uid, id').eq('provider_id', provider_id).execute()
    return {game['game_uid'] for game in result.data}

def check_for_age_mismatches(provider_id: str):
    """Check for any U16 vs U13 games immediately after import."""
    
    print("\n" + "=" * 70)
    print("IMMEDIATE AGE MISMATCH CHECK")
    print("=" * 70)
    
    # Get all teams for lookup (paginated to handle >1000 teams)
    print("Fetching all teams for age group lookup...")
    all_teams_lookup = {}
    page_size = 1000
    offset = 0
    
    while True:
        teams_result = supabase.table('teams').select('team_id_master, team_name, age_group').range(
            offset, offset + page_size - 1
        ).execute()
        
        if not teams_result.data:
            break
        
        for team in teams_result.data:
            all_teams_lookup[team['team_id_master']] = team
        
        if len(teams_result.data) < page_size:
            break
        
        offset += page_size
        print(f"  Loaded {len(all_teams_lookup)} teams so far...")
    
    print(f"Loaded {len(all_teams_lookup)} total teams for lookup")
    
    # Get all Modular11 games (including newly inserted ones) - paginated
    print("Fetching all Modular11 games...")
    all_games = []
    page_size = 1000
    offset = 0
    
    while True:
        games_result = supabase.table('games').select(
            'id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score'
        ).eq('provider_id', provider_id).range(offset, offset + page_size - 1).execute()
        
        if not games_result.data:
            break
        
        all_games.extend(games_result.data)
        
        if len(games_result.data) < page_size:
            break
        
        offset += page_size
        print(f"  Loaded {len(all_games)} games so far...")
    
    print(f"Found {len(all_games)} total Modular11 games")
    
    # Find problematic games (U16 vs any age with difference >= 2 years)
    problematic_games = []
    
    for game in all_games:
        home_id = game.get('home_team_master_id')
        away_id = game.get('away_team_master_id')
        
        if not home_id or not away_id:
            continue
        
        home_team = all_teams_lookup.get(home_id)
        away_team = all_teams_lookup.get(away_id)
        
        if not home_team or not away_team:
            continue
        
        home_age = home_team.get('age_group', '').lower() if home_team.get('age_group') else ''
        away_age = away_team.get('age_group', '').lower() if away_team.get('age_group') else ''
        
        if not home_age or not away_age:
            continue
        
        # Check for age mismatch (difference >= 2 years)
        try:
            home_age_num = int(home_age.replace('u', '').replace('U', ''))
            away_age_num = int(away_age.replace('u', '').replace('U', ''))
            age_diff = abs(home_age_num - away_age_num)
            
            if age_diff >= 2:
                # Check if this is a newly inserted game (not in games_before_import)
                is_new = game['game_uid'] not in games_before_import
                
                problematic_games.append({
                    'game_id': game.get('id'),  # Database ID
                    'game_uid': game['game_uid'],
                    'game_date': game.get('game_date', 'Unknown'),
                    'home_team_name': home_team.get('team_name', 'Unknown'),
                    'home_age': home_age,
                    'away_team_name': away_team.get('team_name', 'Unknown'),
                    'away_age': away_age,
                    'age_diff': age_diff,
                    'score': f"{game.get('home_score', '?')} - {game.get('away_score', '?')}",
                    'is_newly_inserted': is_new
                })
                
                # IMMEDIATELY LOG if this is a newly inserted cross-age game
                if is_new:
                    print(f"\n❌ IMMEDIATE ALERT: Cross-age game detected!")
                    print(f"   Game ID: {game.get('id')}")
                    print(f"   Game UID: {game['game_uid']}")
                    print(f"   Date: {game.get('game_date', 'Unknown')}")
                    print(f"   {home_team.get('team_name')} ({home_age}) vs {away_team.get('team_name')} ({away_age})")
                    print(f"   Age Difference: {age_diff} years")
        except (ValueError, TypeError):
            continue
    
    return problematic_games

def main():
    """Run import and check for age mismatches."""
    
    csv_file = "scrapers/modular11_scraper/output/modular11_u16.csv"
    
    if not os.path.exists(csv_file):
        print(f"Error: CSV file not found: {csv_file}")
        sys.exit(1)
    
    # Get Modular11 provider ID
    provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
    if not provider_result.data:
        print("Error: Modular11 provider not found")
        sys.exit(1)
    
    provider_id = provider_result.data['id']
    
    print("=" * 70)
    print("RE-IMPORTING U16 GAMES WITH AGE VALIDATION CHECK")
    print("=" * 70)
    print(f"\nCSV File: {csv_file}")
    
    # Get game count BEFORE import
    print("\nGetting game count before import...")
    global games_before_import
    games_before_import = get_game_count_before_import(provider_id)
    print(f"Games in database before import: {len(games_before_import)}")
    
    print("\nRunning import...")
    print("-" * 70)
    
    # Run the import (positional arguments: file, provider)
    result = subprocess.run(
        [
            sys.executable,
            "scripts/import_games_enhanced.py",
            csv_file,
            "modular11"
        ],
        capture_output=True,
        text=True
    )
    
    # Print import output
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode != 0:
        print(f"\n⚠️  Import failed with exit code {result.returncode}")
        return
    
    print("\n" + "-" * 70)
    print("Import completed. Checking for age mismatches...")
    
    # Immediately check for age mismatches
    problematic_games = check_for_age_mismatches(provider_id)
    
    # Separate newly inserted vs existing problematic games
    newly_inserted_problematic = [g for g in problematic_games if g.get('is_newly_inserted', False)]
    existing_problematic = [g for g in problematic_games if not g.get('is_newly_inserted', False)]
    
    if newly_inserted_problematic:
        print(f"\n❌ CRITICAL: Found {len(newly_inserted_problematic)} NEWLY INSERTED age mismatch games!")
        print("\n" + "=" * 70)
        print("NEWLY INSERTED PROBLEMATIC GAME IDs (IMMEDIATE ALERT):")
        print("=" * 70)
        for i, game in enumerate(newly_inserted_problematic, 1):
            print(f"\n{i}. Game ID (DB): {game['game_id']}")
            print(f"   Game UID: {game['game_uid']}")
            print(f"   Date: {game['game_date']}")
            print(f"   {game['home_team_name']} ({game['home_age']}) vs {game['away_team_name']} ({game['away_age']})")
            print(f"   Age Difference: {game['age_diff']} years")
            print(f"   Score: {game['score']}")
        
        # Export to file with game IDs
        with open("age_mismatch_games_after_import.txt", "w") as f:
            f.write("AGE MISMATCH GAMES FOUND AFTER U16 IMPORT\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"NEWLY INSERTED PROBLEMATIC GAMES: {len(newly_inserted_problematic)}\n")
            f.write(f"EXISTING PROBLEMATIC GAMES: {len(existing_problematic)}\n\n")
            f.write("=" * 70 + "\n")
            f.write("NEWLY INSERTED GAMES (IMMEDIATE ALERT):\n")
            f.write("=" * 70 + "\n\n")
            for game in newly_inserted_problematic:
                f.write(f"Game ID (DB): {game['game_id']}\n")
                f.write(f"Game UID: {game['game_uid']}\n")
                f.write(f"Date: {game['game_date']}\n")
                f.write(f"Home: {game['home_team_name']} ({game['home_age']})\n")
                f.write(f"Away: {game['away_team_name']} ({game['away_age']})\n")
                f.write(f"Age Difference: {game['age_diff']} years\n")
                f.write(f"Score: {game['score']}\n")
                f.write("\n")
        
        print(f"\n⚠️  Game IDs logged to: age_mismatch_games_after_import.txt")
        print("\n❌ AGE VALIDATION FAILED - Cross-age games were inserted!")
        print(f"❌ {len(newly_inserted_problematic)} newly inserted games with age mismatches detected!")
        sys.exit(1)
    else:
        print("\n✅ SUCCESS: Zero newly inserted age mismatch games found!")
        if existing_problematic:
            print(f"⚠️  Note: {len(existing_problematic)} existing problematic games found (from previous imports)")
            print("   These are not newly inserted, so validation is working correctly.")
        else:
            print("✅ No age mismatches found at all!")
        print("✅ Age validation is working correctly.")
        print("=" * 70)

if __name__ == '__main__':
    main()

