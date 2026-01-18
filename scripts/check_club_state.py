"""Check state codes for teams with a specific club name"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

club_name = "Beach FC (CA)"

# Try variations
variations = [
    "Beach FC (CA)",
    "Beach FC",
    "Beach FC CA",
    "Beach FC(CA)"
]

print("=" * 80)
print(f"CHECKING STATE CODES FOR CLUB: {club_name}")
print("=" * 80)

# Search for all Beach FC teams
result = supabase.table('teams').select(
    'team_id_master, team_name, club_name, state_code, state'
).ilike('club_name', '%Beach FC%').execute()

if not result.data:
    print(f"\n❌ No teams found with club name containing 'Beach FC'")
    sys.exit(1)

teams = result.data
print(f"\n✅ Found {len(teams)} teams with club name containing 'Beach FC'\n")

teams = result.data
print(f"\n✅ Found {len(teams)} teams with club name containing '{club_name}'\n")

# Count teams with and without state codes
teams_with_code = [t for t in teams if t.get('state_code')]
teams_without_code = [t for t in teams if not t.get('state_code')]

print(f"Teams WITH state_code: {len(teams_with_code)}")
print(f"Teams WITHOUT state_code: {len(teams_without_code)}\n")

if teams_with_code:
    print("=" * 80)
    print("TEAMS WITH STATE CODE:")
    print("=" * 80)
    for team in teams_with_code[:20]:  # Show first 20
        print(f"  ✅ {team['team_name']}")
        print(f"     State Code: {team.get('state_code', 'N/A')}")
        print(f"     State: {team.get('state', 'N/A')}")
        print()
    if len(teams_with_code) > 20:
        print(f"  ... and {len(teams_with_code) - 20} more teams with state codes\n")

if teams_without_code:
    print("=" * 80)
    print("TEAMS STILL MISSING STATE CODE:")
    print("=" * 80)
    for team in teams_without_code[:20]:  # Show first 20
        print(f"  ❌ {team['team_name']}")
        print(f"     State Code: {team.get('state_code', 'NULL')}")
        print(f"     State: {team.get('state', 'NULL')}")
        print()
    if len(teams_without_code) > 20:
        print(f"  ... and {len(teams_without_code) - 20} more teams without state codes\n")

# Check for exact match "Beach FC  (CA)" (with two spaces)
exact_match_result = supabase.table('teams').select(
    'team_id_master, team_name, club_name, state_code, state'
).eq('club_name', 'Beach FC  (CA)').execute()

if exact_match_result.data:
    exact_teams = exact_match_result.data
    exact_with_code = [t for t in exact_teams if t.get('state_code')]
    exact_without_code = [t for t in exact_teams if not t.get('state_code')]
    
    print("=" * 80)
    print(f"EXACT MATCH (club_name = 'Beach FC (CA)'):")
    print("=" * 80)
    print(f"Total teams: {len(exact_teams)}")
    print(f"With state_code CA: {len(exact_with_code)}")
    print(f"Without state_code: {len(exact_without_code)}")
    
    if exact_with_code:
        print("\n✅ Teams with state codes:")
        ca_teams = [t for t in exact_with_code if t.get('state_code') == 'CA']
        other_teams = [t for t in exact_with_code if t.get('state_code') != 'CA']
        print(f"  Teams with CA: {len(ca_teams)}")
        for team in ca_teams[:5]:
            print(f"    ✅ {team['team_name']}: {team.get('state_code', 'N/A')}")
        if other_teams:
            print(f"  Teams with other codes: {len(other_teams)}")
            for team in other_teams[:5]:
                print(f"    ⚠️  {team['team_name']}: {team.get('state_code', 'N/A')}")
    
    if exact_without_code:
        print("\n❌ Teams still missing state codes:")
        for team in exact_without_code:
            print(f"  - {team['team_name']}")
else:
    print("\n" + "=" * 80)
    print("No teams found with exact club_name = 'Beach FC (CA)'")
    print("Checking for similar club names...")
    
    # Check what Beach FC club names exist
    all_beach_result = supabase.table('teams').select('club_name').ilike('club_name', '%Beach FC%').execute()
    if all_beach_result.data:
        unique_clubs = set(t['club_name'] for t in all_beach_result.data if t.get('club_name'))
        print(f"\nFound {len(unique_clubs)} unique Beach FC club names:")
        for club in sorted(unique_clubs)[:20]:
            print(f"  - {club}")

print("\n" + "=" * 80)

