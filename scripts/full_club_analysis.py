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

SKIP_STATES = set()  # Scan all states (CA/AZ were previously skipped)

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
    """Normalize name to find genuine naming variations.
    
    CONSERVATIVE approach: Normalize suffix/prefix variations to a canonical form
    instead of stripping them. This prevents false matches like:
      - "FC Arkansas" ≠ "Arkansas Soccer Club"  (prefix FC ≠ suffix SC)
      - "FC United Soccer Club" ≠ "United Soccer Club"  (different clubs)
    
    Only matches genuine variations like:
      - "Pride SC" = "Pride Soccer Club"  (same suffix, different abbreviation)
      - "Florida West F.C." = "Florida West FC"  (same suffix, different format)
    """
    n = name.lower().strip()
    
    # Normalize trailing suffix variations to canonical "sc" or "fc"
    # "Soccer Club" / "S.C." → " sc"
    n = re.sub(r'\s+soccer\s+club\s*$', ' sc', n)
    n = re.sub(r'\s+s\.c\.\s*$', ' sc', n)
    
    # "Football Club" / "Futbol Club" / "F.C." → " fc"
    n = re.sub(r'\s+football\s+club\s*$', ' fc', n)
    n = re.sub(r'\s+futbol\s+club\s*$', ' fc', n)
    n = re.sub(r'\s+f\.c\.\s*$', ' fc', n)
    
    # Normalize leading prefix: "FC X" → "fc x" (keep the FC, just lowercase)
    # Do NOT strip it — "FC Dallas" and "Dallas SC" are different clubs
    
    return n.strip()

def fetch_all_teams(client, state_code):
    """Fetch all active teams for a state (both genders) using pagination."""
    all_teams = []
    offset = 0
    page_size = 1000
    
    while True:
        result = client.table('teams').select(
            'team_id_master, team_name, club_name, gender'
        ).eq('state_code', state_code).eq('is_deprecated', False).range(
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
    teams = fetch_all_teams(client, state_code)
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
        "-- Club Name Standardization Fixes (all teams, both genders)",
        "-- Generated automatically by full_club_analysis.py",
        "-- Includes BOTH caps fixes AND naming variations",
        "--",
        "-- Each UPDATE filtered by state_code (applies to both Male and Female)",
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
            lines.append(f"UPDATE teams SET club_name = '{to_esc}' WHERE club_name = '{from_esc}' AND state_code = '{state}';")
            lines.append("")
        lines.append("")
    
    lines.append("COMMIT;")
    return '\n'.join(lines)

def execute_fixes(client, all_fixes, dry_run=True):
    """Apply club name fixes directly via Supabase REST API."""
    if not all_fixes:
        print("No fixes to apply.")
        return 0, 0
    
    if dry_run:
        print(f"\n[DRY RUN] Would apply {len(all_fixes)} club name fixes")
        for fix in all_fixes[:20]:
            print(f"  {fix['state']}: \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
        if len(all_fixes) > 20:
            print(f"  ... and {len(all_fixes) - 20} more")
        return len(all_fixes), 0
    
    print(f"\nApplying {len(all_fixes)} club name fixes...")
    applied = 0
    failed = 0
    
    for fix in all_fixes:
        try:
            result = client.table('teams').update(
                {'club_name': fix['to']}
            ).eq('club_name', fix['from']).eq('state_code', fix['state']).execute()
            applied += 1
            print(f"  ✅ {fix['state']}: \"{fix['from']}\" → \"{fix['to']}\"")
        except Exception as e:
            failed += 1
            print(f"  ❌ {fix['state']}: \"{fix['from']}\" → error: {e}")
    
    print(f"\nApplied: {applied}, Failed: {failed}")
    return applied, failed


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Full club name analysis and fixing')
    parser.add_argument('--execute', action='store_true', help='Apply fixes via Supabase (default: generate SQL only)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be fixed without applying')
    args = parser.parse_args()
    
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Get all states (paginate to ensure we capture every state_code)
    print("Fetching states...")
    all_states = set()
    offset = 0
    page_size = 1000
    while True:
        result = client.table('teams').select('state_code').eq(
            'is_deprecated', False
        ).range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        for t in result.data:
            if t.get('state_code'):
                all_states.add(t['state_code'])
        if len(result.data) < page_size:
            break
        offset += page_size
    states = sorted(all_states - SKIP_STATES)
    
    skip_note = f" (skipping {', '.join(sorted(SKIP_STATES))})" if SKIP_STATES else ""
    print(f"Processing {len(states)} states{skip_note}\n")
    
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
    
    # Generate SQL (always, for audit trail)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'club_name_fixes_male_all_states.sql')
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
    
    # Execute if requested
    if args.execute:
        execute_fixes(client, all_fixes, dry_run=False)
    elif args.dry_run:
        execute_fixes(client, all_fixes, dry_run=True)

if __name__ == '__main__':
    main()
