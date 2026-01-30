#!/usr/bin/env python3
"""
Run duplicate finder and execute merges for all age groups, states, and genders.
Creates a summary tracker for weekly runs.
"""

import os
import sys
import json
import re
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from supabase import create_client
from team_name_normalizer import parse_team_name, ALIAS_DIVISION_SUFFIXES
from collections import defaultdict

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# All states + DC
ALL_STATES = ['AK', 'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', 'GA', 'HI', 
              'IA', 'ID', 'IL', 'IN', 'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MI', 'MN', 
              'MO', 'MS', 'MT', 'NC', 'ND', 'NE', 'NH', 'NJ', 'NM', 'NV', 'NY', 'OH', 
              'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VA', 'VT', 'WA', 
              'WI', 'WV', 'WY']

ALL_AGE_GROUPS = ['U10', 'U11', 'U12', 'U13', 'U14', 'U15', 'U16', 'U17', 'U18', 'U19']
ALL_GENDERS = ['Male', 'Female']


def get_alias_division(team_id: str) -> str:
    """Check team's aliases for division suffixes (AD, HD, EA, etc.)"""
    try:
        aliases = supabase.table('team_alias_map').select('provider_team_id').eq('team_id_master', team_id).execute()
        for a in aliases.data or []:
            pid = (a.get('provider_team_id') or '').lower()
            for suffix in ALIAS_DIVISION_SUFFIXES:
                if pid.endswith(suffix):
                    return suffix.strip('_').upper()
    except:
        pass
    return None


def pick_canonical(teams: list) -> tuple:
    """Pick which team should be canonical vs deprecated."""
    def score_team(t):
        name = t['name']
        club = t['club'] or ''
        score = 0
        if club and club.lower() in name.lower():
            score += 100
        if name != name.upper():
            score += 10
        score += len(name) / 100
        return score
    
    sorted_teams = sorted(teams, key=score_team, reverse=True)
    return sorted_teams[0], sorted_teams[1:]


def find_duplicates_for_cohort(state: str, gender: str, age_group: str):
    """Find duplicates for a specific cohort."""
    age_num = age_group.lower().replace('u', '')
    
    try:
        teams = supabase.table('teams').select(
            'team_id_master, team_name, club_name'
        ).eq('state_code', state).eq('gender', gender).eq('is_deprecated', False).or_(
            f'age_group.eq.{age_num},age_group.eq.u{age_num},age_group.eq.U{age_num}'
        ).execute()
    except Exception as e:
        return [], 0
    
    if not teams.data:
        return [], 0
    
    # Group by normalized name
    groups = defaultdict(list)
    for t in teams.data:
        parsed = parse_team_name(t['team_name'], t['club_name'])
        key = parsed['normalized'] or 'UNPARSED'
        groups[key].append({
            'id': t['team_id_master'],
            'name': t['team_name'],
            'club': t['club_name']
        })
    
    # Find duplicates
    duplicates = []
    for key, group in groups.items():
        unique_ids = list(set(t['id'] for t in group))
        if len(unique_ids) < 2:
            continue
        
        # Check for division conflicts
        divisions = {t['id']: get_alias_division(t['id']) for t in group}
        unique_divs = set(d for d in divisions.values() if d)
        
        if len(unique_divs) > 1:
            # Different divisions - skip
            continue
        
        canonical, deprecated = pick_canonical(group)
        for dep in deprecated:
            duplicates.append({
                'deprecated_id': dep['id'],
                'deprecated_name': dep['name'],
                'canonical_id': canonical['id'],
                'canonical_name': canonical['name'],
                'club': canonical['club']
            })
    
    return duplicates, len(teams.data)


def execute_merge(deprecated_id: str, canonical_id: str) -> dict:
    """Execute a single merge and return result."""
    try:
        result = supabase.rpc('execute_team_merge', {
            'p_deprecated_team_id': deprecated_id,
            'p_canonical_team_id': canonical_id,
            'p_merged_by': 'pitchrank-bot',
            'p_merge_reason': 'Auto-merge: duplicate team (weekly scan)'
        }).execute()
        
        # Parse the response (handles the JSON parsing quirk)
        if result.data:
            if isinstance(result.data, dict):
                return result.data
            # Try to extract from error details
            return {'success': True}
        return {'success': False, 'error': 'No response'}
    except Exception as e:
        error_str = str(e)
        # Check if it actually succeeded despite the error
        if '"success": true' in error_str or "'success': True" in error_str:
            return {'success': True}
        return {'success': False, 'error': error_str[:100]}


def run_all_merges(dry_run=False):
    """Run duplicate detection and merges for all cohorts."""
    
    print("=" * 70)
    print("PITCHRANK DUPLICATE TEAM MERGER")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print()
    
    # Results tracking
    results = {
        'run_date': datetime.now().isoformat(),
        'dry_run': dry_run,
        'by_state': defaultdict(lambda: {'teams': 0, 'duplicates': 0, 'merged': 0}),
        'by_gender': defaultdict(lambda: {'teams': 0, 'duplicates': 0, 'merged': 0}),
        'by_age': defaultdict(lambda: {'teams': 0, 'duplicates': 0, 'merged': 0}),
        'total_teams': 0,
        'total_duplicates': 0,
        'total_merged': 0,
        'failed_merges': []
    }
    
    all_merges = []
    
    # Scan all cohorts
    for gender in ALL_GENDERS:
        print(f"\n{'='*70}")
        print(f"SCANNING {gender.upper()}")
        print(f"{'='*70}")
        
        for age in ALL_AGE_GROUPS:
            print(f"\n  {age}:", end=" ", flush=True)
            age_dupes = 0
            age_teams = 0
            
            for state in ALL_STATES:
                duplicates, team_count = find_duplicates_for_cohort(state, gender, age)
                
                results['by_state'][state]['teams'] += team_count
                results['by_state'][state]['duplicates'] += len(duplicates)
                results['by_gender'][gender]['teams'] += team_count
                results['by_gender'][gender]['duplicates'] += len(duplicates)
                results['by_age'][age]['teams'] += team_count
                results['by_age'][age]['duplicates'] += len(duplicates)
                results['total_teams'] += team_count
                results['total_duplicates'] += len(duplicates)
                
                age_dupes += len(duplicates)
                age_teams += team_count
                
                for d in duplicates:
                    d['state'] = state
                    d['gender'] = gender
                    d['age'] = age
                    all_merges.append(d)
            
            print(f"{age_dupes} dupes / {age_teams} teams")
    
    print(f"\n{'='*70}")
    print(f"SCAN COMPLETE: {results['total_duplicates']} duplicates found in {results['total_teams']} teams")
    print(f"{'='*70}")
    
    if dry_run:
        print("\n[DRY RUN - No merges executed]")
    elif all_merges:
        print(f"\nExecuting {len(all_merges)} merges...")
        
        for i, merge in enumerate(all_merges):
            result = execute_merge(merge['deprecated_id'], merge['canonical_id'])
            
            if result.get('success'):
                results['total_merged'] += 1
                results['by_state'][merge['state']]['merged'] += 1
                results['by_gender'][merge['gender']]['merged'] += 1
                results['by_age'][merge['age']]['merged'] += 1
                print(f"  ✓ {i+1}/{len(all_merges)}: {merge['club']} - {merge['deprecated_name'][:30]}")
            else:
                results['failed_merges'].append({
                    **merge,
                    'error': result.get('error', 'Unknown')
                })
                print(f"  ✗ {i+1}/{len(all_merges)}: {merge['deprecated_name'][:30]} - {result.get('error', 'Unknown')[:50]}")
        
        print(f"\nMerges complete: {results['total_merged']} succeeded, {len(results['failed_merges'])} failed")
    
    # Convert defaultdicts to regular dicts for JSON
    results['by_state'] = dict(results['by_state'])
    results['by_gender'] = dict(results['by_gender'])
    results['by_age'] = dict(results['by_age'])
    
    return results


def save_tracker(results: dict):
    """Save results to tracker file."""
    tracker_path = '/Users/pitchrankio-dev/Projects/PitchRank/scripts/merges/merge_tracker.json'
    
    # Load existing tracker or create new
    if os.path.exists(tracker_path):
        with open(tracker_path, 'r') as f:
            tracker = json.load(f)
    else:
        tracker = {'runs': []}
    
    # Add this run
    tracker['runs'].append(results)
    tracker['last_run'] = results['run_date']
    
    # Save
    with open(tracker_path, 'w') as f:
        json.dump(tracker, f, indent=2)
    
    print(f"\nTracker saved to: {tracker_path}")
    
    # Also save a human-readable summary
    summary_path = '/Users/pitchrankio-dev/Projects/PitchRank/scripts/merges/MERGE_SUMMARY.md'
    with open(summary_path, 'w') as f:
        f.write(f"# Team Merge Summary\n\n")
        f.write(f"**Last Run:** {results['run_date']}\n\n")
        f.write(f"## Totals\n\n")
        f.write(f"| Metric | Count |\n")
        f.write(f"|--------|-------|\n")
        f.write(f"| Teams Scanned | {results['total_teams']:,} |\n")
        f.write(f"| Duplicates Found | {results['total_duplicates']:,} |\n")
        f.write(f"| Merges Executed | {results['total_merged']:,} |\n")
        f.write(f"| Failed Merges | {len(results['failed_merges']):,} |\n\n")
        
        f.write(f"## By State\n\n")
        f.write(f"| State | Teams | Dupes | Merged |\n")
        f.write(f"|-------|-------|-------|--------|\n")
        for state in sorted(results['by_state'].keys()):
            s = results['by_state'][state]
            if s['teams'] > 0:
                f.write(f"| {state} | {s['teams']:,} | {s['duplicates']} | {s['merged']} |\n")
        
        f.write(f"\n## By Gender\n\n")
        f.write(f"| Gender | Teams | Dupes | Merged |\n")
        f.write(f"|--------|-------|-------|--------|\n")
        for gender in results['by_gender']:
            g = results['by_gender'][gender]
            f.write(f"| {gender} | {g['teams']:,} | {g['duplicates']} | {g['merged']} |\n")
        
        f.write(f"\n## By Age Group\n\n")
        f.write(f"| Age | Teams | Dupes | Merged |\n")
        f.write(f"|-----|-------|-------|--------|\n")
        for age in ALL_AGE_GROUPS:
            if age in results['by_age']:
                a = results['by_age'][age]
                f.write(f"| {age} | {a['teams']:,} | {a['duplicates']} | {a['merged']} |\n")
    
    print(f"Summary saved to: {summary_path}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Run all team merges')
    parser.add_argument('--dry-run', action='store_true', help='Scan only, do not execute merges')
    args = parser.parse_args()
    
    results = run_all_merges(dry_run=args.dry_run)
    save_tracker(results)
    
    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)
