"""Audit a specific team to see how it was matched"""
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

import random

# Get random teams from event 3953 CSV
csv_file = Path('data/raw/tgs/tgs_events_3953_3953_2025-12-12T17-48-39-608611+00-00.csv')
with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    all_rows = list(reader)

# Get unique teams (by team_id)
unique_teams = {}
for row in all_rows:
    team_id = row.get('team_id')
    if team_id and team_id not in unique_teams:
        unique_teams[team_id] = row

# Randomly select 5 teams
selected_teams = random.sample(list(unique_teams.values()), min(5, len(unique_teams)))

print("="*80)
print("AUDITING 10 RANDOM TEAMS FROM EVENT 3953")
print("="*80)

# Randomly select 10 teams
selected_teams = random.sample(list(unique_teams.values()), min(10, len(unique_teams)))

for i, csv_row in enumerate(selected_teams, 1):
    team_name = csv_row.get('team_name')
    team_id_tgs = csv_row.get('team_id')
    age_group = csv_row.get('age_group')
    gender = csv_row.get('gender')
    club_name = csv_row.get('club_name')
    
    print(f"\n{'='*80}")
    print(f"TEAM {i}/10")
    print(f"{'='*80}")
    print(f"\nFrom CSV (Event 3953):")
    print(f"  Team Name: {team_name}")
    print(f"  TGS Team ID: {team_id_tgs}")
    print(f"  Age Group: {age_group}")
    print(f"  Gender: {gender}")
    print(f"  Club Name: {club_name}")
    
    # Check team_alias_map
    alias_result = supabase.table('team_alias_map').select('*').eq(
        'provider_id', tgs_provider_id
    ).eq('provider_team_id', team_id_tgs).execute()
    
    if alias_result.data:
        alias = alias_result.data[0]
        team_id_master = alias.get('team_id_master')
        
        print(f"\n✅ Alias Found:")
        print(f"  Match Method: {alias.get('match_method')}")
        print(f"  Match Confidence: {alias.get('match_confidence')}")
        print(f"  Review Status: {alias.get('review_status')}")
        print(f"  Team ID Master: {team_id_master}")
        print(f"  Created At: {alias.get('created_at')}")
        
        # Get the master team details
        team_result = supabase.table('teams').select('*').eq(
            'team_id_master', team_id_master
        ).execute()
        
        if team_result.data:
            team = team_result.data[0]
            print(f"\n✅ Master Team Found:")
            print(f"  Team Name: {team.get('team_name')}")
            print(f"  Club Name: {team.get('club_name')}")
            print(f"  Age Group: {team.get('age_group')}")
            print(f"  Gender: {team.get('gender')}")
            print(f"  Provider Team ID: {team.get('provider_team_id')}")
            
            # Check if this team has a TGS provider_team_id
            if team.get('provider_team_id') == team_id_tgs:
                print(f"\n✅ DIRECT ID MATCH: Master team's provider_team_id ({team.get('provider_team_id')}) matches TGS team ID ({team_id_tgs})")
            else:
                print(f"\n⚠️  NO DIRECT ID MATCH: Master team's provider_team_id ({team.get('provider_team_id')}) != TGS team ID ({team_id_tgs})")
            
            # Verify age_group and gender match
            age_match = team.get('age_group', '').lower() == age_group.lower() if age_group else False
            gender_match = team.get('gender', '').lower() == gender.lower() if gender else False
            
            if age_match and gender_match:
                print(f"✅ Age Group & Gender Match")
            else:
                print(f"⚠️  Mismatch - CSV: age_group={age_group}, gender={gender} | DB: age_group={team.get('age_group')}, gender={team.get('gender')}")
        else:
            print(f"\n❌ Master team not found!")
    else:
        print(f"\n❌ No alias entry found for TGS team ID: {team_id_tgs}")

print(f"\n{'='*80}")
print("AUDIT COMPLETE")
print(f"{'='*80}")

