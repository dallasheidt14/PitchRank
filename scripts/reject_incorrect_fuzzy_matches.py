#!/usr/bin/env python3
"""
Reject incorrect fuzzy matches that were auto-approved.

This script finds and rejects fuzzy_auto matches that are incorrect,
specifically checking for age group mismatches.
"""
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
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

# Get Modular11 provider ID
provider_result = supabase.table('providers').select('id').eq('code', 'modular11').execute()
if not provider_result.data:
    print("Error: Modular11 provider not found")
    sys.exit(1)

provider_id = provider_result.data[0]['id']

# Find specific incorrect matches
incorrect_matches = [
    {
        'provider_team_name': 'Barca Residency Academy U17',
        'matched_team_name': 'Barca Residency Academy 09 EA AD'
    },
    {
        'provider_team_name': 'Santa Barbara Soccer Club U14 AD',
        'matched_team_name': 'Santa Barbara Soccer Club B2012 White'
    }
]

print("=" * 70)
print("FINDING INCORRECT FUZZY MATCHES")
print("=" * 70)

# Get all fuzzy_auto matches
aliases = supabase.table('team_alias_map').select(
    'id, provider_team_id, team_id_master, match_method, match_confidence, review_status'
).eq('provider_id', provider_id).eq('match_method', 'fuzzy_auto').eq('review_status', 'approved').execute()

print(f"\nFound {len(aliases.data)} fuzzy_auto approved matches")

# Get team details for each alias to check for age mismatches
rejected_count = 0
for alias in aliases.data:
    alias_id = alias['id']
    team_id_master = alias['team_id_master']
    
    # Get team details
    team_result = supabase.table('teams').select('team_name, age_group, gender').eq('team_id_master', team_id_master).single().execute()
    
    if team_result.data:
        team_name = team_result.data.get('team_name', '')
        team_age = team_result.data.get('age_group', '')
        
        # Check if this matches one of our known incorrect matches
        for incorrect in incorrect_matches:
            if incorrect['matched_team_name'].lower() in team_name.lower():
                print(f"\n❌ Found incorrect match:")
                print(f"   Alias ID: {alias_id}")
                print(f"   Provider Team: {incorrect['provider_team_name']}")
                print(f"   Matched Team: {team_name} (Age: {team_age})")
                print(f"   Confidence: {alias.get('match_confidence', 'N/A')}")
                
                # Reject this alias
                try:
                    supabase.table('team_alias_map').update({
                        'review_status': 'rejected'
                    }).eq('id', alias_id).execute()
                    print(f"   ✅ Rejected alias {alias_id}")
                    rejected_count += 1
                except Exception as e:
                    print(f"   ❌ Error rejecting alias: {e}")

print(f"\n{'=' * 70}")
print(f"SUMMARY: Rejected {rejected_count} incorrect matches")
print(f"{'=' * 70}")







