#!/usr/bin/env python3
"""Debug why team matching is failing for RSL-AZ Holiday Classic"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
import json

load_dotenv()

supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Get provider UUID
provider_result = supabase.table('providers').select('id').eq('code', 'gotsport').single().execute()
provider_id = provider_result.data['id']
print(f"GotSport provider_id: {provider_id}")

# Check a sample team from the scraped games
sample_team_id = '79991'
print(f"\nChecking team_id: {sample_team_id}")

# Check alias map
alias_result = supabase.table('team_alias_map').select('*').eq('provider_id', provider_id).eq('provider_team_id', sample_team_id).execute()
print(f"Alias map entries: {len(alias_result.data)}")
if alias_result.data:
    for entry in alias_result.data:
        print(f"  - team_id_master: {entry['team_id_master']}, match_method: {entry.get('match_method')}, review_status: {entry.get('review_status')}")

# Check teams table
teams_result = supabase.table('teams').select('team_id_master, team_name, provider_team_id, provider_id').eq('provider_team_id', sample_team_id).execute()
print(f"\nTeams table entries: {len(teams_result.data)}")
if teams_result.data:
    for team in teams_result.data:
        print(f"  - team_id_master: {team['team_id_master']}, team_name: {team['team_name']}, provider_id: {team.get('provider_id')}")

# Check if team exists by name (fuzzy)
fuzzy_result = supabase.table('teams').select('team_id_master, team_name, provider_team_id').ilike('team_name', '%Arizona Soccer Club%').limit(5).execute()
print(f"\nFuzzy matches by name: {len(fuzzy_result.data)}")
for team in fuzzy_result.data:
    print(f"  - {team['team_name']} (provider_team_id: {team.get('provider_team_id')})")








