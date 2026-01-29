#!/usr/bin/env python3
"""
Full club name analysis - finds BOTH caps issues AND naming variations.
Generates SQL for all states (Male only), excluding CA and AZ.
"""

import os
import re
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

SKIP_STATES = {'CA', 'AZ'}

# Acronyms to keep uppercase
ACRONYMS = {
    'FC', 'SC', 'SA', 'AC', 'CF', 'CD', 'YSA', 'YSO', 'YSL', 'SL', 'CC', 'AD',
    'AYSO', 'MLS', 'RSL', 'US', 'USA', 'USYS', 'USSF', 'ECNL', 'GA', 'MLS',
    'LA', 'NY', 'NJ', 'OC', 'DC', 'KC', 'STL', 'ATL', 'PHX',
    'AL', 'AK', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN',
    'IA', 'KS', 'KY', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE',
    'NV', 'NH', 'NM', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'AFC', 'CFC', 'SFC', 'VFC', 'PFC', 'LAFC', 'NYCFC', 'NCFC'
}

def proper_case(name):
    """Convert to proper title case, preserving acronyms."""
    words = name.split()
    result = []
    for i, word in enumerate(words):
        upper = word.upper()
        # Check for acronyms
        if upper in ACRONYMS:
            result.append(upper)
        # Lowercase articles/prepositions (except first word)
        elif word.lower() in ('del', 'de', 'la', 'el', 'los', 'y', 'the', 'of', 'and', 'at', 'in') and i > 0:
            result.append(word.lower())
        # F.C. -> FC
        elif re.match(r'^[A-Za-z]\.[A-Za-z]\.?$', word):
            result.append(word.upper().replace('.', ''))
        else:
            result.append(word.capitalize())
    return ' '.join(result)

def normalize_for_grouping(name):
    """Normalize name to find naming variations (SC vs Soccer Club etc)."""
    n = name.lower().strip()
    # Remove common suffixes for grouping
    n = re.sub(r'\s+soccer\s+club\s*$', '', n)
    n = re.sub(r'\s+futbol\s+club\s*$', '', n)
    n = re.sub(r'\s+football\s+club\s*$', '', n)
    n = re.sub(r'\s+sc\s*$', '', n)
    n = re.sub(r'\s+fc\s*$', '', n)
    n = re.sub(r'\s+f\.c\.\s*$', '', n)
    n = re.sub(r'\s+s\.c\.\s*$', '', n)
    # Remove leading FC
    n = re.sub(r'^fc\s+', '', n)
    return n.strip()

def fetch_all_male_teams(client, state_code):
    """Fetch all Male teams for a state using pagination."""
    all_teams = []
    offset = 0
    page_size = 1000
    
    while True:
        result = client.table('teams').select(
            'team_id_master, team_name, club_name'
        ).eq('gender', 'Male').eq('state_code', state_code).range(
            offset, offset + page_size - 1
        ).execute()
        
        if not result.data:
            break
        all_teams.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    
    return all_teams

def analyze_state(client, state_code):
    """Analyze club names in a state, return fixes needed."""
    teams = fetch_all_male_teams(client, state_code)
    if not teams:
        return [], 0
    
    # Count club names
    club_counts = defaultdict(int)
    for team in teams:
        club = team.get('club_name')
        if club:
            club_counts[club] += 1
    
    fixes = []
    processed = set()
    
    # 1. Find caps issues (same lowercase, different case)
    by_lower = defaultdict(list)
    for club in club_counts:
        by_lower[club.lower()].append(club)
    
    for lower, variants in by_lower.items():
        if len(variants) > 1:
            # Pick majority, or proper case if tied
            sorted_v = sorted(variants, key=lambda x: -club_counts[x])
            winner = sorted_v[0]
            # Apply proper case
            winner = proper_case(winner)
            
            for variant in variants:
                if variant != winner:
                    fixes.append({
                        'from': variant,
                        'to': winner,
                        'count': club_counts[variant],
                        'type': 'CAPS',
                        'state': state_code
                    })
                    processed.add(variant)
                    processed.add(winner)
    
    # 2. Find naming variations (SC vs Soccer Club etc)
    by_normalized = defaultdict(list)
    for club in club_counts:
        if club not in processed:
            norm = normalize_for_grouping(club)
            by_normalized[norm].append(club)
    
    for norm, variants in by_normalized.items():
        if len(variants) > 1:
            # Pick majority
            sorted_v = sorted(variants, key=lambda x: -club_counts[x])
            winner = sorted_v[0]
            
            for variant in sorted_v[1:]:
                fixes.append({
                    'from': variant,
                    'to': winner,
                    'count': club_counts[variant],
                    'type': 'NAMING',
                    'state': state_code
                })
    
    return fixes, len(teams)

def generate_sql(all_fixes):
    """Generate SQL UPDATE statements."""
    lines = [
        "-- Club Name Standardization Fixes (Male teams only)",
        "-- Generated automatically - excludes CA and AZ (already done)",
        "-- Includes BOTH caps fixes AND naming variations",
        "--",
        "-- IMPORTANT: Each UPDATE filtered by state_code AND gender='Male'",
        "",
        "BEGIN;",
        ""
    ]
    
    by_state = defaultdict(list)
    for fix in all_fixes:
        by_state[fix['state']].append(fix)
    
    for state in sorted(by_state.keys()):
        state_fixes = by_state[state]
        lines.append(f"-- ========== {state} ==========")
        
        for fix in sorted(state_fixes, key=lambda x: (-x['count'], x['from'])):
            from_esc = fix['from'].replace("'", "''")
            to_esc = fix['to'].replace("'", "''")
            lines.append(f"-- [{fix['type']}] \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
            lines.append(f"UPDATE teams SET club_name = '{to_esc}' WHERE club_name = '{from_esc}' AND state_code = '{state}' AND gender = 'Male';")
            lines.append("")
        lines.append("")
    
    lines.append("COMMIT;")
    return '\n'.join(lines)

def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Get all states
    print("Fetching states...")
    result = client.table('teams').select('state_code').eq('gender', 'Male').execute()
    all_states = set(t['state_code'] for t in result.data if t['state_code'])
    states = sorted(all_states - SKIP_STATES)
    
    print(f"Processing {len(states)} states (skipping CA, AZ)\n")
    
    all_fixes = []
    summary = {}
    
    for state in states:
        print(f"Analyzing {state}...", end=" ")
        fixes, total = analyze_state(client, state)
        all_fixes.extend(fixes)
        
        if fixes:
            affected = sum(f['count'] for f in fixes)
            caps = sum(1 for f in fixes if f['type'] == 'CAPS')
            naming = sum(1 for f in fixes if f['type'] == 'NAMING')
            summary[state] = {'caps': caps, 'naming': naming, 'affected': affected, 'total': total}
            print(f"{caps} caps, {naming} naming ({affected} teams)")
        else:
            print("clean")
    
    # Generate SQL
    output_path = '/Users/pitchrankio-dev/Projects/PitchRank/scripts/club_name_fixes_male_all_states.sql'
    sql = generate_sql(all_fixes)
    with open(output_path, 'w') as f:
        f.write(sql)
    
    print(f"\n{'='*60}")
    print("SUMMARY")
    print('='*60)
    
    total_fixes = len(all_fixes)
    total_affected = sum(f['count'] for f in all_fixes)
    total_caps = sum(1 for f in all_fixes if f['type'] == 'CAPS')
    total_naming = sum(1 for f in all_fixes if f['type'] == 'NAMING')
    
    for state in sorted(summary.keys()):
        s = summary[state]
        print(f"  {state}: {s['caps']} caps + {s['naming']} naming = {s['affected']} teams affected")
    
    print('-'*60)
    print(f"TOTAL: {total_fixes} fixes ({total_caps} caps + {total_naming} naming)")
    print(f"       {total_affected} teams will be updated")
    print(f"\nSQL written to: {output_path}")

if __name__ == '__main__':
    main()
