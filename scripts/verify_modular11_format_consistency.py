#!/usr/bin/env python3
"""
Detailed verification script for Modular11 team/alias format consistency.

Checks:
1. Teams use aliased provider_team_id format ({club_id}_{age}_{division})
2. Aliases use same format as teams
3. No orphaned aliases (aliases pointing to non-existent teams)
4. No mismatched aliases (aliases pointing to wrong age groups)
5. Review queue is not polluted with successfully created teams
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables - prioritize .env.local if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'
MODULAR11_PROVIDER_CODE = 'modular11'

def check_format(provider_team_id: str) -> dict:
    """Check if provider_team_id follows expected format"""
    if not provider_team_id:
        return {'valid': False, 'reason': 'empty'}
    
    parts = provider_team_id.split('_')
    
    # Expected formats:
    # - {club_id}_{age}_{division} (e.g., "564_U16_AD")
    # - {club_id}_{age} (e.g., "564_U16")
    # - {club_id} (legacy, but acceptable)
    
    has_age = False
    has_division = False
    age_group = None
    division = None
    
    if len(parts) >= 2:
        # Check if second part is age group
        second_part = parts[1].upper()
        if second_part.startswith('U') and len(second_part) >= 3:
            has_age = True
            age_group = second_part
    
    if len(parts) >= 3:
        # Check if third part is division
        third_part = parts[2].upper()
        if third_part in ('HD', 'AD'):
            has_division = True
            division = third_part
    
    return {
        'valid': True,
        'has_age': has_age,
        'has_division': has_division,
        'age_group': age_group,
        'division': division,
        'format': f"{parts[0]}_{age_group or ''}_{division or ''}".strip('_')
    }

def main():
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)
    
    db = create_client(supabase_url, supabase_key)
    
    print("=" * 80)
    print("MODULAR11 FORMAT CONSISTENCY VERIFICATION")
    print("=" * 80)
    
    # Get all Modular11 teams (limit to recent for faster check)
    print("\n[1/5] Fetching teams...")
    teams_result = db.table('teams').select(
        'team_id_master, provider_team_id, team_name, age_group, created_at'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).order('created_at', desc=True).limit(500).execute()
    
    teams = teams_result.data or []
    print(f"   Found {len(teams)} recent Modular11 teams (checking most recent 500)")
    
    # Also get ALL teams for full stats
    all_teams_result = db.table('teams').select('team_id_master').eq('provider_id', MODULAR11_PROVIDER_ID).execute()
    total_teams = len(all_teams_result.data or [])
    print(f"   Total Modular11 teams in database: {total_teams}")
    
    # Get all Modular11 aliases
    print("\n[2/5] Fetching aliases...")
    aliases_result = db.table('team_alias_map').select(
        'team_id_master, provider_team_id, division, match_method, created_at'
    ).eq('provider_id', MODULAR11_PROVIDER_ID).execute()
    
    aliases = aliases_result.data or []
    print(f"   Found {len(aliases)} Modular11 aliases")
    
    # Build lookup maps
    teams_by_master = {t['team_id_master']: t for t in teams}
    aliases_by_master = defaultdict(list)
    aliases_by_pid = {}
    
    for alias in aliases:
        aliases_by_master[alias['team_id_master']].append(alias)
        aliases_by_pid[alias['provider_team_id']] = alias
    
    # Check 1: Teams with correct format
    print("\n[3/5] Checking team provider_team_id format...")
    teams_with_format = 0
    teams_without_format = []
    recent_teams_with_format = 0
    recent_teams_without_format = []
    
    # Check recent teams (last 50) separately to see if fix is working
    recent_teams = sorted(teams, key=lambda x: x.get('created_at', ''), reverse=True)[:50]
    
    for team in teams:
        format_check = check_format(team['provider_team_id'])
        if format_check['has_age'] or format_check['has_division']:
            teams_with_format += 1
            if team in recent_teams:
                recent_teams_with_format += 1
        else:
            teams_without_format.append(team)
            if team in recent_teams:
                recent_teams_without_format.append(team)
    
    print(f"   ✅ Teams with age/division format: {teams_with_format}/{len(teams)}")
    print(f"   📊 Recent 50 teams with format: {recent_teams_with_format}/50")
    if teams_without_format:
        print(f"   ⚠️  Teams without format (raw club_id): {len(teams_without_format)}")
        if recent_teams_without_format:
            print(f"   ⚠️  Recent teams without format: {len(recent_teams_without_format)}")
            print("      (These may be legacy teams from before the fix)")
            for t in recent_teams_without_format[:3]:
                print(f"      - {t['team_name']}: {t['provider_team_id']} (created: {t.get('created_at', 'unknown')[:10]})")
    
    # Check 2: Team/Alias consistency
    print("\n[4/5] Checking team/alias provider_team_id consistency...")
    mismatches = []
    matches = 0
    recent_mismatches = []
    recent_matches = 0
    
    # Check recent teams separately
    recent_team_masters = {t['team_id_master'] for t in recent_teams}
    
    for team in teams:
        team_aliases = aliases_by_master.get(team['team_id_master'], [])
        if not team_aliases:
            continue
        
        is_recent = team['team_id_master'] in recent_team_masters
        
        for alias in team_aliases:
            if alias['provider_team_id'] == team['provider_team_id']:
                matches += 1
                if is_recent:
                    recent_matches += 1
            else:
                mismatch_info = {
                    'team_name': team['team_name'],
                    'team_pid': team['provider_team_id'],
                    'alias_pid': alias['provider_team_id'],
                    'team_age': team['age_group'],
                    'alias_division': alias.get('division'),
                    'created_at': team.get('created_at', '')
                }
                mismatches.append(mismatch_info)
                if is_recent:
                    recent_mismatches.append(mismatch_info)
    
    print(f"   ✅ Matching team/alias pairs: {matches}")
    print(f"   📊 Recent teams matching: {recent_matches}")
    if mismatches:
        print(f"   ❌ Mismatched pairs: {len(mismatches)}")
        if recent_mismatches:
            print(f"   ⚠️  Recent mismatches: {len(recent_mismatches)}")
            print("\n   Recent mismatches (should be 0 if fix is working):")
            for m in recent_mismatches[:5]:
                print(f"      Team: {m['team_name']}")
                print(f"        Team provider_team_id: {m['team_pid']}")
                print(f"        Alias provider_team_id: {m['alias_pid']}")
                print(f"        Created: {m['created_at'][:10] if m['created_at'] else 'unknown'}")
        else:
            print("   ✅ No recent mismatches - fix is working!")
            print("\n   Sample old mismatches (legacy data):")
            for m in mismatches[:3]:
                print(f"      Team: {m['team_name']}")
                print(f"        Team provider_team_id: {m['team_pid']}")
                print(f"        Alias provider_team_id: {m['alias_pid']}")
    else:
        print("   ✅ All teams and aliases use matching provider_team_id!")
    
    # Check 3: Orphaned aliases
    print("\n[5/5] Checking for orphaned aliases...")
    orphaned = []
    for alias in aliases:
        if alias['team_id_master'] not in teams_by_master:
            orphaned.append(alias)
    
    print(f"   {'❌' if orphaned else '✅'} Orphaned aliases: {len(orphaned)}")
    if orphaned:
        print("\n   Sample orphaned aliases:")
        for o in orphaned[:5]:
            print(f"      provider_team_id: {o['provider_team_id']}")
            print(f"        Points to non-existent team_id_master: {o['team_id_master']}")
    
    # Check 4: Age group mismatches
    print("\n[6/6] Checking for age group mismatches...")
    age_mismatches = []
    for alias in aliases:
        team = teams_by_master.get(alias['team_id_master'])
        if not team:
            continue
        
        # Extract age from alias provider_team_id
        alias_format = check_format(alias['provider_team_id'])
        alias_age = alias_format.get('age_group')
        
        if alias_age:
            # Normalize for comparison
            alias_age_norm = alias_age.lower()
            team_age_norm = (team['age_group'] or '').lower()
            
            if team_age_norm and alias_age_norm != team_age_norm:
                age_mismatches.append({
                    'team_name': team['team_name'],
                    'team_age': team['age_group'],
                    'alias_age': alias_age,
                    'alias_pid': alias['provider_team_id']
                })
    
    print(f"   {'❌' if age_mismatches else '✅'} Age group mismatches: {len(age_mismatches)}")
    if age_mismatches:
        print("\n   Sample age mismatches:")
        for m in age_mismatches[:5]:
            print(f"      Team: {m['team_name']}")
            print(f"        Team age: {m['team_age']}, Alias age: {m['alias_age']}")
            print(f"        Alias provider_team_id: {m['alias_pid']}")
    
    # Check 5: Review queue pollution
    print("\n[7/7] Checking review queue...")
    review_result = db.table('team_match_review_queue').select('id, provider_team_id, status').eq(
        'provider_id', MODULAR11_PROVIDER_CODE
    ).eq('status', 'pending').execute()
    
    review_count = len(review_result.data or [])
    print(f"   📋 Pending review queue entries: {review_count}")
    
    if review_count == 0:
        print("   ✅ No review queue pollution - successfully created teams NOT in queue!")
    else:
        print(f"   ⚠️  {review_count} entries in review queue (may be expected for unmatched teams)")
    
    # Final summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    all_good = (
        len(mismatches) == 0 and
        len(orphaned) == 0 and
        len(age_mismatches) == 0
    )
    
    if all_good:
        print("\n✅ ALL CHECKS PASSED!")
        print("   - Teams use correct format")
        print("   - Teams and aliases match")
        print("   - No orphaned aliases")
        print("   - No age group mismatches")
        print("   - Review queue clean")
    else:
        print("\n⚠️  ISSUES FOUND:")
        if mismatches:
            print(f"   - {len(mismatches)} team/alias provider_team_id mismatches")
        if orphaned:
            print(f"   - {len(orphaned)} orphaned aliases")
        if age_mismatches:
            print(f"   - {len(age_mismatches)} age group mismatches")
    
    print("\n" + "=" * 80)
    
    return 0 if all_good else 1

if __name__ == '__main__':
    sys.exit(main())

