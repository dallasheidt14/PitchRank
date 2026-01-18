#!/usr/bin/env python3
"""Verify Modular11 import format consistency"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'

def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    db = create_client(supabase_url, supabase_key)
    
    print("=" * 70)
    print("VERIFYING MODULAR11 IMPORT FORMAT CONSISTENCY")
    print("=" * 70)
    
    # Get recent teams (created in last hour)
    teams_result = db.table('teams').select(
        'team_id_master, provider_team_id, team_name, age_group, created_at'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).order('created_at', desc=True).limit(20).execute()
    
    if not teams_result.data:
        print("No recent Modular11 teams found")
        return
    
    print(f"\nFound {len(teams_result.data)} recent teams")
    print("\n" + "-" * 70)
    print("SAMPLE TEAMS:")
    print("-" * 70)
    
    mismatches = []
    correct_format = []
    
    for team in teams_result.data[:10]:
        team_pid = team['provider_team_id']
        team_name = team['team_name']
        age_group = team['age_group']
        
        print(f"\nTeam: {team_name}")
        print(f"  provider_team_id: {team_pid}")
        print(f"  age_group: {age_group}")
        
        # Check if format matches expected pattern: {club_id}_{age}_{division}
        has_age = '_U' in team_pid.upper() or team_pid.upper().endswith('_U13') or team_pid.upper().endswith('_U14') or team_pid.upper().endswith('_U15') or team_pid.upper().endswith('_U16') or team_pid.upper().endswith('_U17')
        has_division = team_pid.upper().endswith('_HD') or team_pid.upper().endswith('_AD')
        
        if has_age or has_division:
            correct_format.append(team)
            print(f"  ✅ Format: Has age/division suffix")
        else:
            print(f"  ⚠️  Format: No age/division suffix (raw club_id)")
        
        # Check alias consistency
        alias_result = db.table('team_alias_map').select('provider_team_id, division').eq(
            'team_id_master', team['team_id_master']
        ).eq('provider_id', MODULAR11_PROVIDER_ID).execute()
        
        if alias_result.data:
            alias_pid = alias_result.data[0]['provider_team_id']
            alias_div = alias_result.data[0].get('division')
            
            print(f"  Alias provider_team_id: {alias_pid}")
            print(f"  Alias division: {alias_div}")
            
            if alias_pid != team_pid:
                mismatches.append({
                    'team_name': team_name,
                    'team_pid': team_pid,
                    'alias_pid': alias_pid
                })
                print(f"  ❌ MISMATCH: Team and alias use different provider_team_id!")
            else:
                print(f"  ✅ MATCH: Team and alias use same provider_team_id")
        else:
            print(f"  ⚠️  No alias found for this team")
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if mismatches:
        print(f"\n❌ Found {len(mismatches)} teams with mismatched provider_team_id:")
        for m in mismatches[:5]:
            print(f"  - {m['team_name']}")
            print(f"    Team: {m['team_pid']}")
            print(f"    Alias: {m['alias_pid']}")
    else:
        print("\n✅ All teams and aliases use matching provider_team_id format!")
    
    print(f"\n✅ Teams with correct format (age/division suffix): {len(correct_format)}/{len(teams_result.data[:10])}")
    
    # Check review queue
    review_result = db.table('team_match_review_queue').select('id').eq(
        'provider_id', 'modular11'
    ).eq('status', 'pending').execute()
    
    print(f"\n📋 Review Queue Entries: {len(review_result.data or [])}")
    if len(review_result.data or []) == 0:
        print("  ✅ No review queue pollution - successfully created teams NOT in queue!")
    else:
        print(f"  ⚠️  {len(review_result.data)} entries in review queue")

if __name__ == '__main__':
    main()







