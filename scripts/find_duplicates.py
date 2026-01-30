#!/usr/bin/env python3
"""
Find duplicate teams using the normalizer.
Checks aliases for AD/HD/EA division markers to avoid false positives.
"""

import os
import sys
import argparse
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from supabase import create_client
from team_name_normalizer import parse_team_name, teams_match, ALIAS_DIVISION_SUFFIXES
from collections import defaultdict

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))


def get_alias_division(team_id: str) -> str:
    """Check team's aliases for division suffixes (AD, HD, EA, etc.)"""
    aliases = supabase.table('team_alias_map').select('provider_team_id').eq('team_id_master', team_id).execute()
    
    for a in aliases.data or []:
        pid = (a.get('provider_team_id') or '').lower()
        for suffix in ALIAS_DIVISION_SUFFIXES:
            if pid.endswith(suffix):
                return suffix.strip('_').upper()
    return None


def pick_canonical(teams: list) -> tuple:
    """
    Pick which team should be canonical (kept) vs deprecated (merged).
    
    Priority:
    1. Team with club name in team_name (more complete)
    2. Title Case over ALL CAPS
    3. First one if tie
    
    Returns: (canonical_team, deprecated_teams)
    """
    def score_team(t):
        name = t['name']
        club = t['club'] or ''
        score = 0
        
        # Prefer team_name that contains club name
        if club and club.lower() in name.lower():
            score += 100
        
        # Prefer Title Case over ALL CAPS
        if name != name.upper():
            score += 10
        
        # Prefer longer names (more complete)
        score += len(name) / 100
        
        return score
    
    sorted_teams = sorted(teams, key=score_team, reverse=True)
    canonical = sorted_teams[0]
    deprecated = sorted_teams[1:]
    
    return canonical, deprecated


def find_duplicates(state_code: str, gender: str, age_group: str, output_sql: bool = False):
    """Find potential duplicates for a given cohort."""
    
    print(f'Fetching {age_group} {gender} {state_code} teams...')
    
    # Build age filter
    age_num = age_group.lower().replace('u', '')
    
    teams = supabase.table('teams').select(
        'team_id_master, team_name, club_name, state_code, age_group, gender'
    ).eq('state_code', state_code).eq('gender', gender).eq('is_deprecated', False).or_(
        f'age_group.eq.{age_num},age_group.eq.u{age_num},age_group.eq.U{age_num}'
    ).execute()
    
    print(f'Found {len(teams.data)} teams\n')
    
    # Parse and group by FULL normalized form
    groups = defaultdict(list)
    for t in teams.data:
        parsed = parse_team_name(t['team_name'], t['club_name'])
        key = parsed['normalized'] or 'UNPARSED'
        groups[key].append({
            'id': t['team_id_master'],
            'name': t['team_name'],
            'club': t['club_name'],
            'parsed': parsed
        })
    
    # Find duplicates
    exact_dupes = []
    alias_division_conflicts = []
    
    for key, group in groups.items():
        unique_ids = list(set(t['id'] for t in group))
        if len(unique_ids) < 2:
            continue
        
        # Check aliases for division markers
        divisions = {}
        for t in group:
            div = get_alias_division(t['id'])
            divisions[t['id']] = div
        
        # If all have same division (or no division), it's a real duplicate
        unique_divs = set(d for d in divisions.values() if d)
        
        if len(unique_divs) > 1:
            # Different divisions - NOT a duplicate
            alias_division_conflicts.append({
                'key': key,
                'teams': group,
                'divisions': divisions
            })
        else:
            # No division conflict - check if true dupe
            if len(unique_ids) > 1:
                canonical, deprecated = pick_canonical(group)
                exact_dupes.append({
                    'key': key,
                    'teams': group,
                    'divisions': divisions,
                    'canonical': canonical,
                    'deprecated': deprecated
                })
    
    # Print results
    print('=' * 60)
    print('EXACT DUPLICATES (safe to merge)')
    print('=' * 60)
    
    if not exact_dupes:
        print('\n  ✅ None found!')
    else:
        for d in exact_dupes:
            canonical = d['canonical']
            print(f"\n🔴 {canonical['club']} | {d['key']}")
            print(f"   ✅ KEEP: [{canonical['id'][:8]}] {canonical['name']}")
            for t in d['deprecated']:
                print(f"   ❌ MERGE: [{t['id'][:8]}] {t['name']}")
    
    print('\n')
    print('=' * 60)
    print('⚠️  SAME NAME BUT DIFFERENT DIVISIONS (AD/HD/EA)')
    print('    DO NOT auto-merge - need manual review')
    print('=' * 60)
    
    if not alias_division_conflicts:
        print('\n  None found')
    else:
        for d in alias_division_conflicts:
            print(f"\n⚠️  {d['key']}")
            for t in d['teams']:
                div = d['divisions'].get(t['id'], '-')
                print(f"   [{t['id'][:8]}] {t['name']} → division: {div}")
    
    print('\n')
    print('=' * 60)
    print('SUMMARY')
    print('=' * 60)
    print(f'Total teams: {len(teams.data)}')
    print(f'Exact duplicates (safe): {len(exact_dupes)}')
    print(f'Division conflicts (manual): {len(alias_division_conflicts)}')
    
    # Output SQL if requested
    if output_sql and exact_dupes:
        print('\n')
        print('=' * 60)
        print('MERGE SQL')
        print('=' * 60)
        print('-- Run these in Supabase SQL Editor')
        print(f'-- {state_code} {gender} {age_group} duplicates')
        print()
        
        for d in exact_dupes:
            canonical = d['canonical']
            print(f"-- {canonical['club']} | {canonical['name']}")
            for dep in d['deprecated']:
                print(f"SELECT execute_team_merge(")
                print(f"    '{dep['id']}'::uuid,  -- deprecated: {dep['name']}")
                print(f"    '{canonical['id']}'::uuid,  -- canonical: {canonical['name']}")
                print(f"    'pitchrank-bot',")
                print(f"    'Auto-merge: duplicate team'")
                print(f");")
                print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Find duplicate teams')
    parser.add_argument('--state', required=True, help='State code (e.g., NY)')
    parser.add_argument('--gender', required=True, choices=['Male', 'Female'])
    parser.add_argument('--age', required=True, help='Age group (e.g., U16)')
    parser.add_argument('--sql', action='store_true', help='Output merge SQL')
    
    args = parser.parse_args()
    find_duplicates(args.state, args.gender, args.age, args.sql)
