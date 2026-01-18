#!/usr/bin/env python3
"""Check why TGS Team ID 79561 didn't match to GotSport team"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv
from supabase import create_client

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

target_team_uuid = "148edffd-4319-4f21-8b2b-524ad82fb0d3"  # GotSport Eastside FC ECNL B12
tgs_team_id = "79561"  # TGS Eastside FC ECNL B12

# Initialize Supabase
supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

print("="*70)
print("CHECKING TGS ALIAS MATCHING")
print("="*70)

# Get TGS provider ID
tgs_provider = supabase.table('providers').select('id').eq('code', 'tgs').execute()
tgs_provider_id = tgs_provider.data[0]['id'] if tgs_provider.data else None

# Get target team info
target_team = supabase.table('teams').select('*').eq('team_id_master', target_team_uuid).execute()
if not target_team.data:
    print("Target team not found!")
    sys.exit(1)

target_team_data = target_team.data[0]

print(f"\nTarget Team (GotSport):")
print(f"  UUID: {target_team_uuid}")
print(f"  Name: {target_team_data.get('team_name')}")
print(f"  Club: {target_team_data.get('club_name')}")
print(f"  Age Group: {target_team_data.get('age_group')}")
print(f"  Gender: {target_team_data.get('gender')}")
print(f"  Provider Team ID: {target_team_data.get('provider_team_id')}")

# Check if TGS Team ID 79561 has an alias
print(f"\n" + "="*70)
print(f"Checking alias map for TGS Team ID {tgs_team_id}:")
print("="*70)

alias_result = supabase.table('team_alias_map').select('*').eq(
    'provider_id', tgs_provider_id
).eq('provider_team_id', tgs_team_id).execute()

if alias_result.data:
    for alias in alias_result.data:
        matched_team_id = alias.get('team_id_master')
        matched_team = supabase.table('teams').select('*').eq(
            'team_id_master', matched_team_id
        ).execute()
        
        if matched_team.data:
            matched = matched_team.data[0]
            print(f"\n✅ TGS Team ID {tgs_team_id} HAS an alias:")
            print(f"   Matched to Team UUID: {matched_team_id}")
            print(f"   Team Name: {matched.get('team_name')}")
            print(f"   Club: {matched.get('club_name')}")
            print(f"   Age Group: {matched.get('age_group')}")
            print(f"   Gender: {matched.get('gender')}")
            print(f"   Match Method: {alias.get('match_method')}")
            print(f"   Review Status: {alias.get('review_status')}")
            print(f"   Confidence: {alias.get('confidence')}")
            
            if matched_team_id == target_team_uuid:
                print(f"\n   ✅ CORRECTLY MATCHED to target team!")
            else:
                print(f"\n   ❌ Matched to DIFFERENT team!")
                print(f"   Expected: {target_team_uuid} ({target_team_data.get('team_name')})")
                print(f"   Got: {matched_team_id} ({matched.get('team_name')})")
else:
    print(f"\n❌ TGS Team ID {tgs_team_id} has NO alias mapping!")
    print(f"   This means it was never matched during import.")
    print(f"   It should have been fuzzy matched to:")
    print(f"   - Team: {target_team_data.get('team_name')}")
    print(f"   - Club: {target_team_data.get('club_name')}")
    print(f"   - Age Group: {target_team_data.get('age_group')}")
    print(f"   - Gender: {target_team_data.get('gender')}")

# Check what team TGS ID 79561's games are linked to
print(f"\n" + "="*70)
print(f"Checking which team TGS ID {tgs_team_id}'s games are linked to:")
print("="*70)

home_games = supabase.table('games').select(
    'game_uid, game_date, home_team_master_id'
).eq('home_provider_id', tgs_team_id).eq('provider_id', tgs_provider_id).limit(3).execute()

away_games = supabase.table('games').select(
    'game_uid, game_date, away_team_master_id'
).eq('away_provider_id', tgs_team_id).eq('provider_id', tgs_provider_id).limit(3).execute()

if home_games.data:
    unique_team_ids = set([g.get('home_team_master_id') for g in home_games.data])
    print(f"\nHome games linked to team IDs: {unique_team_ids}")
    for team_id in unique_team_ids:
        if team_id:
            team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', team_id).execute()
            if team_info.data:
                print(f"  - {team_id}: {team_info.data[0].get('team_name')} ({team_info.data[0].get('age_group')})")

if away_games.data:
    unique_team_ids = set([g.get('away_team_master_id') for g in away_games.data])
    print(f"\nAway games linked to team IDs: {unique_team_ids}")
    for team_id in unique_team_ids:
        if team_id:
            team_info = supabase.table('teams').select('team_name, age_group').eq('team_id_master', team_id).execute()
            if team_info.data:
                print(f"  - {team_id}: {team_info.data[0].get('team_name')} ({team_info.data[0].get('age_group')})")

# Summary
print(f"\n" + "="*70)
print("SUMMARY")
print("="*70)
print(f"\nTGS Team ID {tgs_team_id} ('Eastside FC ECNL B12'):")
if alias_result.data:
    print(f"  ✅ Has alias mapping")
    matched_team_id = alias_result.data[0].get('team_id_master')
    if matched_team_id == target_team_uuid:
        print(f"  ✅ Correctly matched to GotSport team")
    else:
        print(f"  ❌ Matched to wrong team (UUID: {matched_team_id})")
        print(f"  ❌ Should be matched to: {target_team_uuid}")
else:
    print(f"  ❌ NO alias mapping exists")
    print(f"  ❌ This means fuzzy matching failed or wasn't attempted")
    print(f"  ❌ Games may be linked to a different team or not imported")

print(f"\nWithout an alias mapping, the system cannot:")
print(f"  1. Direct match TGS Team ID {tgs_team_id} to GotSport team")
print(f"  2. Link games from TGS import to the correct GotSport team")
print(f"  3. Merge data from both providers for the same team")







