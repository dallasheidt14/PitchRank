"""Audit the 11 teams that were incorrectly matched to see what happened after re-import"""
import os
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client
import csv

# Load environment
env_local = Path('.env.local')
load_dotenv(env_local if env_local.exists() else None, override=True)

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY')
)

# TGS provider ID
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'

# The 11 teams that were incorrectly matched
incorrect_teams = [
    {'provider_team_id': '95276', 'team_name': 'Sporting CA USA ECNL RL S.Cal G08/07'},
    {'provider_team_id': '118267', 'team_name': 'Legends FC San Diego ECNL RL S.Cal G08/07'},
    {'provider_team_id': '95277', 'team_name': 'Sporting CA USA ECNL RL S.Cal G09'},
    {'provider_team_id': '89524', 'team_name': 'SLAMMERS FC ECNL RL S.Cal G09'},
    {'provider_team_id': '95278', 'team_name': 'Sporting CA USA ECNL RL S.Cal G10'},
    {'provider_team_id': '95099', 'team_name': 'San Diego Surf ECNL RL S.Cal G11'},
    {'provider_team_id': '108106', 'team_name': 'Rebels SC ECNL RL S.Cal G11'},
    {'provider_team_id': '118268', 'team_name': 'Legends FC San Diego ECNL RL S.Cal G11'},
    {'provider_team_id': '95276', 'team_name': 'Sporting CA USA ECNL RL S.Cal G12'},
    {'provider_team_id': '95275', 'team_name': 'So Cal Blues SC ECNL RL SoCal G12'},
    {'provider_team_id': '108107', 'team_name': 'Sporting CA USA ECNL RL S.Cal G13'},
]

# Read CSV to get actual team IDs
csv_file = Path('data/raw/tgs/tgs_events_3953_3953_2025-12-12T17-48-39-608611+00-00.csv')
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    csv_rows = list(reader)

# Build map of team names to IDs
team_name_to_id = {}
for row in csv_rows:
    team_name = row.get('team_name')
    team_id = row.get('team_id')
    if team_name and team_id:
        if team_name not in team_name_to_id:
            team_name_to_id[team_name] = team_id

print("="*80)
print("AUDITING 11 FIXED TEAMS")
print("="*80)

# Get the actual team IDs from CSV
teams_to_check = []
for team_info in incorrect_teams:
    team_name = team_info['team_name']
    team_id = team_name_to_id.get(team_name)
    if team_id:
        teams_to_check.append({
            'team_id': team_id,
            'team_name': team_name
        })

print(f"\nFound {len(teams_to_check)} teams to check\n")

for i, team in enumerate(teams_to_check, 1):
    team_id = team['team_id']
    team_name = team['team_name']
    
    print(f"{'='*80}")
    print(f"TEAM {i}/11: {team_name}")
    print(f"{'='*80}")
    print(f"TGS Team ID: {team_id}")
    
    # Check alias map
    alias_result = supabase.table('team_alias_map').select('*').eq(
        'provider_id', tgs_provider_id
    ).eq('provider_team_id', team_id).execute()
    
    if alias_result.data:
        alias = alias_result.data[0]
        print(f"\n✅ Alias Found:")
        print(f"  Match Method: {alias.get('match_method')}")
        print(f"  Match Confidence: {alias.get('match_confidence')}")
        print(f"  Review Status: {alias.get('review_status')}")
        print(f"  Created At: {alias.get('created_at')}")
        print(f"  Team ID Master: {alias.get('team_id_master')}")
        
        # Get master team
        master_result = supabase.table('teams').select('*').eq(
            'team_id_master', alias.get('team_id_master')
        ).execute()
        
        if master_result.data:
            master = master_result.data[0]
            print(f"\n✅ Master Team:")
            print(f"  Team Name: {master.get('team_name')}")
            print(f"  Club Name: {master.get('club_name')}")
            print(f"  Age Group: {master.get('age_group')}")
            print(f"  Gender: {master.get('gender')}")
            print(f"  Provider Team ID: {master.get('provider_team_id')}")
            
            # Check if this is a direct ID match
            if master.get('provider_team_id') == team_id:
                print(f"\n✅ DIRECT ID MATCH: Master team's provider_team_id matches")
            else:
                print(f"\n⚠️  FUZZY MATCH: Master team's provider_team_id ({master.get('provider_team_id')}) != TGS ID ({team_id})")
                
                # Check for league mismatch
                provider_upper = team_name.upper()
                master_upper = master.get('team_name', '').upper()
                
                provider_has_ecnl_rl = 'ECNL' in provider_upper and ('RL' in provider_upper or 'ECRL' in provider_upper)
                master_has_ecnl_only = 'ECNL' in master_upper and 'RL' not in master_upper and 'ECRL' not in master_upper
                master_has_ecrl = 'ECRL' in master_upper or ('RL' in master_upper and 'ECNL' not in master_upper)
                
                if provider_has_ecnl_rl and (master_has_ecnl_only or master_has_ecrl):
                    print(f"\n❌ STILL INCORRECT: League mismatch detected!")
                    print(f"   Provider: ECNL RL")
                    print(f"   Master: {'ECNL' if master_has_ecnl_only else 'ECRL/RL'}")
        else:
            print(f"\n❌ Master team not found!")
    else:
        print(f"\n❌ NO ALIAS FOUND")
        print(f"   This team was not matched during re-import")
        print(f"   It should have been created as a new team")
        
        # Check if there are any games for this team from event 3953
        # We need to check games that reference this team_id
        # But games use master team IDs, so we need to find games by event and check team names
        
        # Get games from event 3953
        games_result = supabase.table('games').select('game_uid, home_team_master_id, away_team_master_id').eq(
            'event_name', 'Event 3953'
        ).limit(1000).execute()
        
        # Check if any games reference teams with this name pattern
        # This is approximate - we'd need to check team names
        print(f"   Checking if games exist for this team...")
        
        # Check if team exists in teams table with this provider_team_id
        team_exists = supabase.table('teams').select('team_id_master, team_name').eq(
            'provider_id', tgs_provider_id
        ).eq('provider_team_id', team_id).execute()
        
        if team_exists.data:
            print(f"   ⚠️  Team exists in teams table but no alias!")
            for t in team_exists.data:
                print(f"      Team ID: {t.get('team_id_master')}")
                print(f"      Team Name: {t.get('team_name')}")
        else:
            print(f"   Team does not exist in teams table")
            print(f"   This team should have been created but wasn't")

print(f"\n{'='*80}")
print("AUDIT COMPLETE")
print(f"{'='*80}")









