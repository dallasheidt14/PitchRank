"""Check ALL Modular11 teams for age mismatches"""
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
print("CHECKING ALL MODULAR11 TEAMS FOR AGE MISMATCHES")
print("=" * 70)

# Get all Modular11 teams
print("\nFetching all Modular11 teams...")
teams_result = supabase.table('teams').select('team_id_master, team_name, age_group, gender, provider_team_id').eq('provider_id', modular11_provider_id).execute()

if not teams_result.data:
    print("No Modular11 teams found")
    sys.exit(0)

print(f"Found {len(teams_result.data)} Modular11 teams")

# Get all Modular11 games
print("\nFetching all Modular11 games...")
games_result = supabase.table('games').select('id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score').eq('provider_id', modular11_provider_id).execute()

print(f"Found {len(games_result.data)} Modular11 games")

# Build team lookup
teams_by_id = {team['team_id_master']: team for team in teams_result.data}

# Check for age mismatches
print("\nAnalyzing age mismatches...")
problematic_teams = defaultdict(list)
problematic_games = []

for game in games_result.data:
    home_id = game.get('home_team_master_id')
    away_id = game.get('away_team_master_id')
    
    home_team = teams_by_id.get(home_id)
    away_team = teams_by_id.get(away_id)
    
    if not home_team or not away_team:
        continue
    
    home_age = home_team.get('age_group', '').lower()
    away_age = away_team.get('age_group', '').lower()
    
    try:
        home_age_num = int(home_age.replace('u', '').replace('U', ''))
        away_age_num = int(away_age.replace('u', '').replace('U', ''))
        
        # Age mismatch if difference >= 2 years
        if abs(home_age_num - away_age_num) >= 2:
            problematic_games.append({
                'game_id': game.get('id'),
                'game_uid': game.get('game_uid'),
                'game_date': game.get('game_date'),
                'home_team': home_team.get('team_name'),
                'home_age': home_age,
                'away_team': away_team.get('team_name'),
                'away_age': away_age,
                'age_diff': abs(home_age_num - away_age_num)
            })
            
            # Track by team
            problematic_teams[home_team.get('team_name')].append({
                'date': game.get('game_date'),
                'opponent': away_team.get('team_name'),
                'opp_age': away_age,
                'game_uid': game.get('game_uid')
            })
            problematic_teams[away_team.get('team_name')].append({
                'date': game.get('game_date'),
                'opponent': home_team.get('team_name'),
                'opp_age': home_age,
                'game_uid': game.get('game_uid')
            })
    except (ValueError, AttributeError):
        pass

print("\n" + "=" * 70)
print("AGE MISMATCH SUMMARY")
print("=" * 70)
print(f"\nTotal problematic games: {len(problematic_games)}")
print(f"Total teams affected: {len(problematic_teams)}")

# Group by age difference
age_diff_counts = defaultdict(int)
for game in problematic_games:
    age_diff_counts[game['age_diff']] += 1

print(f"\nAge differences:")
for diff in sorted(age_diff_counts.keys()):
    print(f"  {diff} year(s): {age_diff_counts[diff]} games")

# Show top 10 most affected teams
print(f"\nTop 10 most affected teams:")
sorted_teams = sorted(problematic_teams.items(), key=lambda x: len(x[1]), reverse=True)
for team_name, games in sorted_teams[:10]:
    print(f"  {team_name}: {len(games)} problematic games")

# Show sample problematic games
print(f"\nSample problematic games (first 10):")
for game in problematic_games[:10]:
    print(f"  {game['game_date']}: {game['home_team']} ({game['home_age']}) vs {game['away_team']} ({game['away_age']})")
    print(f"    Game UID: {game['game_uid']}")
    print(f"    Age difference: {game['age_diff']} years")

print("\n" + "=" * 70)
print("RECOMMENDATION")
print("=" * 70)
print(f"\nFound {len(problematic_games)} games with age mismatches across {len(problematic_teams)} teams.")
print(f"\nThese games should be deleted to maintain data integrity.")
print(f"\nWould you like to:")
print(f"  1. Delete all {len(problematic_games)} problematic games")
print(f"  2. Export list of game UIDs for review")
print(f"  3. Show detailed breakdown by team")
print("=" * 70)













