"""Check ALL Modular11 teams for age mismatches (U13 games with U16 teams, etc.)"""
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
print(f"Modular11 Provider ID: {modular11_provider_id}\n")
print("=" * 70)
print("CHECKING ALL MODULAR11 TEAMS FOR AGE MISMATCHES")
print("=" * 70)

# Get all Modular11 teams
print("\nFetching all Modular11 teams...")
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

# Check each team for age mismatches
problematic_teams = []
total_problematic_games = 0

print("Checking games for each team...")
for i, team in enumerate(all_teams, 1):
    if i % 100 == 0:
        print(f"  Processed {i}/{len(all_teams)} teams...")
    
    team_id = team['team_id_master']
    team_name = team.get('team_name', 'Unknown')
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
    problematic_games = []
    
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
        
        # Check for age mismatch (e.g., U13 vs U16, U14 vs U17, etc.)
        # Extract age numbers
        try:
            team_age_num = int(expected_age.replace('u', '').replace('U', ''))
            opp_age_num = int(opponent_age.replace('u', '').replace('U', ''))
            
            # If age difference is >= 2, it's likely a mismatch
            if abs(team_age_num - opp_age_num) >= 2:
                problematic_games.append({
                    'game': game,
                    'opponent_id': opponent_id,
                    'opponent_name': opponent_team.get('team_name', 'Unknown'),
                    'opponent_age': opponent_age,
                    'age_diff': abs(team_age_num - opp_age_num)
                })
        except (ValueError, AttributeError):
            # Can't parse age, skip
            continue
    
    if problematic_games:
        problematic_teams.append({
            'team': team,
            'problematic_games': problematic_games
        })
        total_problematic_games += len(problematic_games)

print(f"\n✓ Checked {len(all_teams)} teams")
print(f"⚠️  Found {len(problematic_teams)} teams with age mismatches")
print(f"⚠️  Total problematic games: {total_problematic_games}\n")

if problematic_teams:
    print("=" * 70)
    print("DETAILED RESULTS")
    print("=" * 70)
    
    # Group by age difference
    by_age_diff = defaultdict(list)
    for pt in problematic_teams:
        for pg in pt['problematic_games']:
            age_diff = pg['age_diff']
            by_age_diff[age_diff].append({
                'team': pt['team'],
                'game': pg
            })
    
    for age_diff in sorted(by_age_diff.keys(), reverse=True):
        print(f"\n{'=' * 70}")
        print(f"AGE DIFFERENCE: {age_diff} years (e.g., U13 vs U{13+age_diff})")
        print(f"{'=' * 70}")
        
        items = by_age_diff[age_diff]
        print(f"Found {len(items)} problematic games:\n")
        
        for i, item in enumerate(items[:20], 1):  # Show first 20
            team = item['team']
            game_info = item['game']
            game = game_info['game']
            
            print(f"{i}. Team: {team.get('team_name')} ({team.get('age_group')})")
            print(f"   Opponent: {game_info['opponent_name']} ({game_info['opponent_age']})")
            print(f"   Game Date: {game.get('game_date')}")
            print(f"   Game UID: {game.get('game_uid', 'N/A')}")
            print()
        
        if len(items) > 20:
            print(f"   ... and {len(items) - 20} more games\n")
    
    # Summary by team
    print("\n" + "=" * 70)
    print("SUMMARY BY TEAM")
    print("=" * 70)
    for pt in problematic_teams[:30]:  # Show first 30 teams
        team = pt['team']
        print(f"\n{team.get('team_name')} ({team.get('age_group')}): {len(pt['problematic_games'])} problematic games")
    
    if len(problematic_teams) > 30:
        print(f"\n... and {len(problematic_teams) - 30} more teams with issues")
    
    print("\n" + "=" * 70)
    print(f"\nTOTAL: {len(problematic_teams)} teams with {total_problematic_games} problematic games")
    print("=" * 70)
else:
    print("\n✓ No age mismatches found!")

print()
