"""Investigate root cause of remaining age mismatches"""
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
print("INVESTIGATING AGE MISMATCH ROOT CAUSE")
print("=" * 70)

# The problematic teams from the check
problematic_teams = [
    "Achilles FC U16",
    "Sacramento Republic FC U16",
    "Achilles FC",
    "Sacramento Republic FC"
]

print("\nInvestigating problematic teams...\n")

# Check each problematic team
for team_name_search in problematic_teams:
    print("=" * 70)
    print(f"TEAM: {team_name_search}")
    print("=" * 70)
    
    # Find teams matching this name
    teams_result = supabase.table('teams').select('*').ilike('team_name', f'%{team_name_search}%').execute()
    
    if not teams_result.data:
        print(f"  No teams found matching '{team_name_search}'")
        continue
    
    for team in teams_result.data:
        team_id = team['team_id_master']
        team_name = team.get('team_name', 'Unknown')
        age_group = team.get('age_group', 'N/A')
        gender = team.get('gender', 'N/A')
        provider_id = team.get('provider_id')
        provider_team_id = team.get('provider_team_id', 'N/A')
        
        print(f"\n  Found: {team_name}")
        print(f"    Team ID: {team_id}")
        print(f"    Age Group: {age_group}")
        print(f"    Gender: {gender}")
        print(f"    Provider ID: {provider_id}")
        print(f"    Provider Team ID: {provider_team_id}")
        
        # Check if this is a Modular11 team
        is_modular11 = (provider_id == modular11_provider_id)
        print(f"    Is Modular11: {is_modular11}")
        
        # Check alias mappings
        if is_modular11 and provider_team_id:
            alias_result = supabase.table('team_alias_map').select('*').eq('provider_id', modular11_provider_id).eq('provider_team_id', provider_team_id).execute()
            if alias_result.data:
                print(f"    Alias Mappings: {len(alias_result.data)}")
                for alias in alias_result.data:
                    print(f"      - Match Method: {alias.get('match_method')}")
                    print(f"      - Review Status: {alias.get('review_status')}")
                    print(f"      - Division: {alias.get('division', 'N/A')}")
                    print(f"      - Confidence: {alias.get('match_confidence', 'N/A')}")
            else:
                print(f"    ⚠️  No alias mappings found!")
        
        # Check games for this team
        home_games = supabase.table('games').select('game_uid, game_date, away_team_master_id').eq('home_team_master_id', team_id).eq('provider_id', modular11_provider_id).limit(5).execute()
        away_games = supabase.table('games').select('game_uid, game_date, home_team_master_id').eq('away_team_master_id', team_id).eq('provider_id', modular11_provider_id).limit(5).execute()
        
        print(f"    Recent Games: {len(home_games.data)} home, {len(away_games.data)} away")
        
        # Check for age mismatches in recent games
        all_games = home_games.data + away_games.data
        for game in all_games[:3]:  # Check first 3
            if game.get('away_team_master_id'):
                opp_id = game.get('away_team_master_id')
            else:
                opp_id = game.get('home_team_master_id')
            
            if opp_id:
                opp_result = supabase.table('teams').select('team_name, age_group').eq('team_id_master', opp_id).execute()
                if opp_result.data:
                    opp = opp_result.data[0]
                    opp_age = opp.get('age_group', '').lower()
                    team_age = age_group.lower()
                    
                    # Check for age mismatch
                    try:
                        team_age_num = int(team_age.replace('u', '').replace('U', ''))
                        opp_age_num = int(opp_age.replace('u', '').replace('U', ''))
                        if abs(team_age_num - opp_age_num) >= 2:
                            print(f"      ⚠️  AGE MISMATCH: vs {opp.get('team_name')} ({opp_age}) on {game.get('game_date')}")
                    except (ValueError, AttributeError):
                        pass

# Check for "Achilles" teams specifically (might be name confusion)
print("\n" + "=" * 70)
print("CHECKING FOR 'ACHILLES' TEAM NAME CONFUSION")
print("=" * 70)

achilles_teams = supabase.table('teams').select('*').ilike('team_name', '%achilles%').execute()
print(f"\nFound {len(achilles_teams.data)} teams with 'Achilles' in name:")

for team in achilles_teams.data:
    print(f"\n  {team.get('team_name')}")
    print(f"    Age: {team.get('age_group')}, Provider Team ID: {team.get('provider_team_id')}")
    
    # Check if this team has "13" in the name but is marked as U16
    team_name = team.get('team_name', '').lower()
    age_group = team.get('age_group', '').lower()
    
    if '13' in team_name and 'u16' in age_group:
        print(f"    ⚠️  POTENTIAL ISSUE: Team name contains '13' but age_group is U16!")
    if '16' in team_name and 'u13' in age_group:
        print(f"    ⚠️  POTENTIAL ISSUE: Team name contains '16' but age_group is U13!")

# Check Sacramento Republic teams
print("\n" + "=" * 70)
print("CHECKING FOR 'SACRAMENTO REPUBLIC' TEAM NAME CONFUSION")
print("=" * 70)

sac_teams = supabase.table('teams').select('*').ilike('team_name', '%sacramento%republic%').execute()
print(f"\nFound {len(sac_teams.data)} teams with 'Sacramento Republic' in name:")

for team in sac_teams.data:
    print(f"\n  {team.get('team_name')}")
    print(f"    Age: {team.get('age_group')}, Provider Team ID: {team.get('provider_team_id')}")
    
    team_name = team.get('team_name', '').lower()
    age_group = team.get('age_group', '').lower()
    
    if '13' in team_name and 'u16' in age_group:
        print(f"    ⚠️  POTENTIAL ISSUE: Team name contains '13' but age_group is U16!")
    if '16' in team_name and 'u13' in age_group:
        print(f"    ⚠️  POTENTIAL ISSUE: Team name contains '16' but age_group is U13!")

print("\n" + "=" * 70)
print("ANALYSIS COMPLETE")
print("=" * 70)

