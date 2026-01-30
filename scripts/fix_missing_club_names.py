#!/usr/bin/env python3
"""
Fix teams with empty club_name by extracting club from team_name.
Part of Cleany's data hygiene responsibilities.
"""

import os
import sys
import re
import argparse
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Common patterns that indicate where club name ends
AGE_PATTERNS = [
    r'\b[BG]?20\d{2}[BG]?\b',  # B2014, 2014B, 2014, G2016
    r'\bU\d{1,2}[BG]?\b',       # U14, U14B, U16G
    r'\b\d{1,2}[BG]\b',         # 14B, 16G
    r'\b\d{2}/\d{2}\b',         # 14/15
    r'\bBoys\b',
    r'\bGirls\b',
    r'\bMen\b',
    r'\bWomen\b',
]

# Words that are definitely part of team identifier, not club
TEAM_IDENTIFIER_WORDS = [
    'Black', 'Blue', 'Red', 'White', 'Navy', 'Gold', 'Orange', 'Green', 'Purple',
    'Silver', 'Grey', 'Gray', 'Yellow', 'Pink', 'Maroon', 'Teal',
    'Academy', 'Premier', 'Elite', 'Select', 'Development', 'Competitive',
    'North', 'South', 'East', 'West', 'Central',
    'ECNL', 'MLS', 'NPL', 'DPL', 'GA', 'RL',
    'I', 'II', 'III', 'IV', 'V', '1', '2', '3', '4', '5',
]


def extract_club_name(team_name: str) -> str:
    """
    Extract the club name from a team name by finding where the age/identifier starts.
    """
    if not team_name:
        return ''
    
    original = team_name
    
    # Handle names that START with age pattern (e.g., "2014G SYSA Storm")
    # Try to find club name after the age pattern
    leading_age = re.match(r'^[BG]?20\d{2}[BG]?\s+', team_name, re.IGNORECASE)
    if leading_age:
        team_name = team_name[leading_age.end():]
    
    # Find the earliest age pattern match
    earliest_pos = len(team_name)
    for pattern in AGE_PATTERNS:
        match = re.search(pattern, team_name, re.IGNORECASE)
        if match and match.start() < earliest_pos:
            earliest_pos = match.start()
    
    # Take everything before the age pattern
    if earliest_pos > 0 and earliest_pos < len(team_name):
        club = team_name[:earliest_pos].strip()
    else:
        club = team_name
    
    # Clean up trailing identifiers
    club = club.strip(' -–—')
    
    # Remove trailing team identifier words
    words = club.split()
    while words and words[-1] in TEAM_IDENTIFIER_WORDS:
        words.pop()
    
    # Remove trailing numbers (e.g., "Attack 14" → "Attack")
    while words and words[-1].isdigit():
        words.pop()
    
    # Remove trailing single letters that look like age markers
    while words and len(words[-1]) == 1 and words[-1] in 'BGbg':
        words.pop()
    
    club = ' '.join(words).strip(' -–—')
    
    # If club is too short or same as original, return empty
    if len(club) < 2 or club == original:
        return ''
    
    return club


def get_existing_clubs(state_code: str) -> dict:
    """Get existing clubs in a state with team counts."""
    result = supabase.table('teams').select('club_name').eq('state_code', state_code).neq('club_name', '').eq('is_deprecated', False).execute()
    
    clubs = Counter(t['club_name'] for t in result.data if t['club_name'])
    return clubs


def find_matching_club(extracted: str, existing_clubs: dict) -> str:
    """Find best matching existing club for extracted name. VERY CONSERVATIVE matching."""
    if not extracted:
        return ''
    
    # Reject too-short extractions (likely wrong)
    if len(extracted) < 4:
        return ''
    
    # Reject generic terms that shouldn't match
    generic_terms = ['fc', 'sc', 'united', 'city', 'west', 'east', 'north', 'south', 
                     'academy', 'premier', 'elite', 'select', 'blue', 'red', 'white',
                     'black', 'gold', 'green', 'boys', 'girls']
    if extracted.lower() in generic_terms:
        return ''
    
    extracted_lower = extracted.lower()
    
    # Exact match (case-insensitive) - SAFE
    for club in existing_clubs:
        if club.lower() == extracted_lower:
            return club
    
    # Check for AMBIGUOUS matches - multiple clubs start with same prefix
    # e.g., "Legends FC", "Legends FC SD", "Legends FC OC" - can't auto-match!
    matching_clubs = [c for c in existing_clubs if c.lower().startswith(extracted_lower)]
    if len(matching_clubs) > 1:
        # Ambiguous - multiple clubs could match
        return ''
    
    # Check reverse - multiple clubs that extracted starts with
    reverse_matches = [c for c in existing_clubs if extracted_lower.startswith(c.lower())]
    if len(reverse_matches) > 1:
        # Ambiguous
        return ''
    
    # Single match - extracted is START of existing club AND at least 70% of the name
    if len(matching_clubs) == 1:
        club = matching_clubs[0]
        if len(extracted) >= len(club) * 0.7:
            return club
    
    # Single reverse match - existing club is START of extracted AND at least 85% match
    if len(reverse_matches) == 1:
        club = reverse_matches[0]
        if len(club) >= len(extracted) * 0.85:
            return club
    
    # No safe match found - return empty to mark as "new club"
    return ''


def analyze_empty_club_names(state_code: str = None, limit: int = None):
    """Analyze teams with empty club_name."""
    
    print("=" * 70)
    print("EMPTY CLUB NAME ANALYSIS")
    print("=" * 70)
    
    # Build query
    query = supabase.table('teams').select(
        'team_id_master, team_name, state_code, age_group, gender'
    ).eq('club_name', '').eq('is_deprecated', False)
    
    if state_code:
        query = query.eq('state_code', state_code)
    
    # Paginate
    all_teams = []
    offset = 0
    while True:
        result = query.range(offset, offset + 999).execute()
        if not result.data:
            break
        all_teams.extend(result.data)
        offset += 1000
        if len(result.data) < 1000:
            break
        if limit and len(all_teams) >= limit:
            all_teams = all_teams[:limit]
            break
    
    print(f"Teams with empty club_name: {len(all_teams)}")
    
    # Group by state
    by_state = defaultdict(list)
    for t in all_teams:
        by_state[t['state_code']].append(t)
    
    # Analyze each state
    results = {
        'fixable': [],
        'new_clubs': [],
        'unfixable': []
    }
    
    for state, teams in sorted(by_state.items(), key=lambda x: -len(x[1])):
        existing_clubs = get_existing_clubs(state)
        
        for t in teams:
            extracted = extract_club_name(t['team_name'])
            
            if not extracted:
                results['unfixable'].append(t)
                continue
            
            matched = find_matching_club(extracted, existing_clubs)
            
            if matched in existing_clubs:
                results['fixable'].append({
                    **t,
                    'suggested_club': matched,
                    'extracted': extracted
                })
            else:
                results['new_clubs'].append({
                    **t,
                    'suggested_club': matched,
                    'extracted': extracted
                })
    
    print(f"\nResults:")
    print(f"  ✅ Fixable (match existing club): {len(results['fixable'])}")
    print(f"  🆕 New clubs (no match): {len(results['new_clubs'])}")
    print(f"  ❓ Unfixable (can't extract): {len(results['unfixable'])}")
    
    return results


def generate_fix_sql(results: dict, output_path: str = None):
    """Generate SQL to fix club names."""
    
    sql_lines = [
        "-- Fix empty club_name fields",
        "-- Generated by fix_missing_club_names.py",
        f"-- Total fixes: {len(results['fixable'])}",
        ""
    ]
    
    # Group by suggested club
    by_club = defaultdict(list)
    for r in results['fixable']:
        by_club[(r['state_code'], r['suggested_club'])].append(r)
    
    for (state, club), teams in sorted(by_club.items()):
        sql_lines.append(f"-- {state}: {club} ({len(teams)} teams)")
        ids = [f"'{t['team_id_master']}'" for t in teams]
        
        # Batch update
        sql_lines.append(f"UPDATE teams SET club_name = '{club.replace(chr(39), chr(39)+chr(39))}'")
        sql_lines.append(f"WHERE team_id_master IN ({', '.join(ids)});")
        sql_lines.append("")
    
    sql_content = '\n'.join(sql_lines)
    
    if output_path:
        with open(output_path, 'w') as f:
            f.write(sql_content)
        print(f"\nSQL written to: {output_path}")
    
    return sql_content


def execute_fixes(results: dict, dry_run: bool = True):
    """Execute fixes directly via Supabase."""
    
    if dry_run:
        print("\n[DRY RUN] Would fix:")
    else:
        print("\nExecuting fixes...")
    
    fixed = 0
    failed = 0
    
    for r in results['fixable']:
        if dry_run:
            print(f"  {r['team_name'][:40]} → {r['suggested_club']}")
            fixed += 1
        else:
            try:
                supabase.table('teams').update({
                    'club_name': r['suggested_club']
                }).eq('team_id_master', r['team_id_master']).execute()
                fixed += 1
            except Exception as e:
                print(f"  ❌ Failed: {r['team_name']}: {e}")
                failed += 1
    
    print(f"\n{'Would fix' if dry_run else 'Fixed'}: {fixed}")
    if failed:
        print(f"Failed: {failed}")
    
    return fixed, failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fix missing club names')
    parser.add_argument('--state', help='Filter by state code')
    parser.add_argument('--limit', type=int, help='Limit teams to analyze')
    parser.add_argument('--sql', help='Output SQL file path')
    parser.add_argument('--execute', action='store_true', help='Execute fixes (default: dry-run)')
    parser.add_argument('--show-samples', action='store_true', help='Show sample extractions')
    
    args = parser.parse_args()
    
    results = analyze_empty_club_names(args.state, args.limit)
    
    if args.show_samples:
        print("\n" + "=" * 70)
        print("SAMPLE EXTRACTIONS")
        print("=" * 70)
        
        print("\n✅ Fixable (first 20):")
        for r in results['fixable'][:20]:
            print(f"  {r['team_name'][:50]}")
            print(f"    → extracted: '{r['extracted']}' → matched: '{r['suggested_club']}'")
        
        print("\n🆕 New clubs (first 10):")
        for r in results['new_clubs'][:10]:
            print(f"  {r['team_name'][:50]}")
            print(f"    → new club: '{r['suggested_club']}'")
        
        print("\n❓ Unfixable (first 10):")
        for r in results['unfixable'][:10]:
            print(f"  {r['team_name']}")
    
    if args.sql:
        generate_fix_sql(results, args.sql)
    
    if args.execute or not args.sql:
        execute_fixes(results, dry_run=not args.execute)
