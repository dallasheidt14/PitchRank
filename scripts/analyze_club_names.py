#!/usr/bin/env python3
"""
Analyze club names across all states (Male gender only) and generate SQL fixes.
Skips CA and AZ (already done).

Fixes:
1. Caps issues - same name, different capitalization
2. Naming variations - "Rebels SC" vs "Rebels Soccer Club", etc.
"""

import os
import re
from collections import defaultdict
from supabase import create_client

# Credentials
SUPABASE_URL = "https://pfkrhmprwxtghtpinrot.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBma3JobXByd3h0Z2h0cGlucm90Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE3NDQ3ODQsImV4cCI6MjA3NzMyMDc4NH0.fOl6xuUuRzJhXe6UPHiCveZsviApipnFmcoB2Iz6Jt0"

SKIP_STATES = {'CA', 'AZ'}

# Acronyms to keep uppercase
ACRONYMS = {
    'FC', 'SC', 'SA', 'AC', 'CF', 'CD', 'YSA', 'YSO', 'YSL', 'SL', 'CC', 'AD',
    'AYSO', 'MLS', 'RSL', 'US', 'USA', 'USYS', 'USSF', 'USSSA', 'YFC',
    'LA', 'NY', 'NJ', 'OC', 'DC', 'KC', 'STL', 'DMV', 'BV', 'PSL',
    'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X',
    'AL', 'AK', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN',
    'IA', 'KS', 'KY', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE',
    'NV', 'NH', 'NM', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'AFC', 'CFC', 'SFC', 'VFC', 'PFC', 'RFC', 'BFC', 'GFC', 'HFC', 'MFC', 'TFC', 'WFC',
    'NCFC', 'NAZ', 'LLC', 'INC', 'DBA', 'LTD', 'CORP',
}

# Suffixes to strip for normalization (order matters - longer first)
SUFFIXES_TO_STRIP = [
    ' soccer club',
    ' futbol club', 
    ' football club',
    ' soccer academy',
    ' futbol academy',
    ' football academy',
    ' sc',
    ' fc', 
    ' sa',
    ' ac',
    ' cf',
]

# Prefixes to strip
PREFIXES_TO_STRIP = [
    'fc ',
    'sc ',
    'ac ',
]


def fetch_all_teams(client, state_code):
    """Fetch all Male teams for a state using pagination."""
    all_teams = []
    page_size = 1000
    offset = 0
    
    while True:
        response = client.table('teams').select('id, club_name, state_code').eq(
            'gender', 'Male'
        ).eq(
            'state_code', state_code
        ).range(offset, offset + page_size - 1).execute()
        
        if not response.data:
            break
        all_teams.extend(response.data)
        if len(response.data) < page_size:
            break
        offset += page_size
    
    return all_teams


def normalize_for_naming(name):
    """Normalize a club name to find naming variations."""
    n = name.lower().strip()
    
    # Remove parenthetical state codes
    n = re.sub(r'\s*\([a-z]{2}\)\s*$', '', n)
    
    # Remove periods
    n = n.replace('.', '')
    
    # Strip suffixes
    for suffix in SUFFIXES_TO_STRIP:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
            break
    
    # Strip prefixes
    for prefix in PREFIXES_TO_STRIP:
        if n.startswith(prefix):
            n = n[len(prefix):].strip()
            break
    
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def is_multi_word_all_caps(name):
    """Check if name is a multi-word ALL CAPS name."""
    words = [w for w in name.split() if re.sub(r'[^A-Za-z]', '', w)]
    if len(words) <= 1:
        return False
    
    all_caps_words = 0
    for word in words:
        clean = re.sub(r'[^A-Za-z]', '', word)
        if clean and clean.isupper() and clean.upper() not in ACRONYMS and len(clean) > 2:
            all_caps_words += 1
    
    return all_caps_words >= 2


def score_casing(name):
    """Score how well a name is cased. Higher = better."""
    words = name.split()
    score = 0
    
    for word in words:
        clean = re.sub(r'[^A-Za-z]', '', word)
        if not clean:
            continue
        if clean.upper() in ACRONYMS and clean.isupper():
            score += 2
        elif clean.upper() in ACRONYMS:
            score -= 1
        elif clean.isupper() and len(clean) > 2:
            score -= 2
        elif clean[0].isupper() and (len(clean) == 1 or clean[1:].islower()):
            score += 1
    
    return score


def proper_title_case(name):
    """Convert ALL CAPS name to proper title case."""
    words = name.split()
    result = []
    
    for i, word in enumerate(words):
        suffix = ''
        prefix = ''
        if word and word[-1] in '.,;:!?)':
            suffix = word[-1]
            word = word[:-1]
        if word and word[0] in '(':
            prefix = word[0]
            word = word[1:]
        
        clean = re.sub(r'[^A-Za-z0-9]', '', word)
        
        if clean.upper() in ACRONYMS:
            result.append(prefix + clean.upper() + suffix)
        elif re.match(r'^[A-Za-z]\.[A-Za-z]\.?$', word):
            result.append(prefix + word.upper() + suffix)
        elif word.lower() in ('del', 'de', 'la', 'el', 'los', 'las', 'y', 'the', 'of', 'and', 'at', 'in', 'on', 'for', 'to', 'by') and i > 0:
            result.append(prefix + word.lower() + suffix)
        else:
            result.append(prefix + word.capitalize() + suffix)
    
    return ' '.join(result)


def has_full_suffix(name):
    """Check if name has full suffix like 'Soccer Club'."""
    lower = name.lower()
    return any(lower.endswith(s) for s in [' soccer club', ' futbol club', ' football club', ' soccer academy'])


def analyze_state(client, state_code):
    """Analyze all club names in a state."""
    teams = fetch_all_teams(client, state_code)
    
    if not teams:
        return [], 0
    
    # Count all club names
    name_counts = defaultdict(int)
    for team in teams:
        club = team['club_name']
        if club:
            name_counts[club] += 1
    
    # === PHASE 1: Identify caps fixes ===
    caps_groups = defaultdict(lambda: defaultdict(int))
    for name, count in name_counts.items():
        key = name.lower().strip()
        caps_groups[key][name] = count
    
    caps_map = {}  # from -> to for caps fixes
    
    for lower_name, variations in caps_groups.items():
        if len(variations) > 1:
            # Multiple caps variants - pick best
            scored = [(name, count, score_casing(name)) for name, count in variations.items()]
            scored.sort(key=lambda x: (-x[2], -x[1]))
            canonical = scored[0][0]
            
            if is_multi_word_all_caps(canonical):
                canonical = proper_title_case(canonical)
            
            for variant in variations:
                if variant != canonical:
                    caps_map[variant] = canonical
        else:
            # Single variant - check if ALL CAPS
            name = list(variations.keys())[0]
            if is_multi_word_all_caps(name):
                fixed = proper_title_case(name)
                if fixed != name:
                    caps_map[name] = fixed
    
    # === PHASE 2: Identify naming variations ===
    # Apply caps fixes first to get effective names
    effective_counts = defaultdict(int)
    original_to_effective = {}  # maps original name -> effective name after caps fix
    
    for name, count in name_counts.items():
        effective = caps_map.get(name, name)
        effective_counts[effective] += count
        original_to_effective[name] = effective
    
    # Group by normalized name
    naming_groups = defaultdict(lambda: defaultdict(int))
    for effective, count in effective_counts.items():
        normalized = normalize_for_naming(effective)
        if normalized:
            naming_groups[normalized][effective] = count
    
    naming_map = {}  # from effective -> to canonical
    
    for norm_name, variations in naming_groups.items():
        if len(variations) <= 1:
            continue
        
        # Check if this is truly a naming variation (not just caps)
        unique_lowers = set(v.lower() for v in variations.keys())
        if len(unique_lowers) <= 1:
            continue
        
        # Sort by count
        sorted_variants = sorted(variations.items(), key=lambda x: -x[1])
        best_name, best_count = sorted_variants[0]
        
        # Prefer full-suffix version if it has reasonable count
        for name, count in sorted_variants:
            if has_full_suffix(name) and count >= best_count * 0.2:
                best_name = name
                break
        
        canonical = best_name
        
        for variant in variations:
            if variant != canonical:
                naming_map[variant] = canonical
    
    # === PHASE 3: Collapse chains and generate final fixes ===
    # For each original name, find its final destination
    all_fixes = []
    
    for original_name, count in name_counts.items():
        # Step 1: Apply caps fix if any
        after_caps = caps_map.get(original_name, original_name)
        
        # Step 2: Apply naming fix if any
        final = naming_map.get(after_caps, after_caps)
        
        # If final differs from original, create a fix
        if final != original_name:
            # Determine type
            if original_name.lower() == final.lower():
                fix_type = 'caps'
            else:
                fix_type = 'naming'
            
            all_fixes.append({
                'from': original_name,
                'to': final,
                'count': count,
                'type': fix_type,
                'state': state_code
            })
    
    teams_affected = sum(f['count'] for f in all_fixes)
    return all_fixes, len(teams)


def generate_sql(all_fixes):
    """Generate SQL UPDATE statements."""
    lines = [
        "-- Club Name Standardization Fixes (Male teams only)",
        "-- Generated automatically - excludes CA and AZ (already done)",
        "-- ",
        "-- IMPORTANT: Each UPDATE is filtered by state_code to avoid cross-state conflicts",
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
        
        caps = [f for f in state_fixes if f['type'] == 'caps']
        naming = [f for f in state_fixes if f['type'] == 'naming']
        
        if caps:
            lines.append("-- Capitalization fixes:")
            for fix in sorted(caps, key=lambda x: x['from']):
                lines.append(f"-- \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
                from_escaped = fix['from'].replace("'", "''")
                to_escaped = fix['to'].replace("'", "''")
                lines.append(f"UPDATE teams SET club_name = '{to_escaped}' WHERE club_name = '{from_escaped}' AND state_code = '{state}' AND gender = 'Male';")
                lines.append("")
        
        if naming:
            lines.append("-- Naming variations:")
            for fix in sorted(naming, key=lambda x: x['from']):
                lines.append(f"-- \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
                from_escaped = fix['from'].replace("'", "''")
                to_escaped = fix['to'].replace("'", "''")
                lines.append(f"UPDATE teams SET club_name = '{to_escaped}' WHERE club_name = '{from_escaped}' AND state_code = '{state}' AND gender = 'Male';")
                lines.append("")
        
        lines.append("")
    
    lines.append("COMMIT;")
    return '\n'.join(lines)


def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    print("Fetching distinct states...")
    states_response = client.table('teams').select('state_code').eq('gender', 'Male').execute()
    all_states = set(t['state_code'] for t in states_response.data if t['state_code'])
    states_to_process = sorted(all_states - SKIP_STATES)
    
    print(f"Found {len(all_states)} states total, processing {len(states_to_process)} (skipping CA, AZ)")
    
    all_fixes = []
    summary = {}
    
    for state in states_to_process:
        print(f"Analyzing {state}...")
        fixes, total_teams = analyze_state(client, state)
        all_fixes.extend(fixes)
        
        caps_count = sum(1 for f in fixes if f['type'] == 'caps')
        naming_count = sum(1 for f in fixes if f['type'] == 'naming')
        teams_affected = sum(f['count'] for f in fixes)
        
        if teams_affected > 0:
            summary[state] = {
                'caps_fixes': caps_count,
                'naming_fixes': naming_count,
                'teams_affected': teams_affected,
                'total_teams': total_teams
            }
            print(f"  → {caps_count} caps + {naming_count} naming = {caps_count + naming_count} fixes ({teams_affected} teams)")
        else:
            print(f"  → No fixes needed")
    
    if all_fixes:
        sql = generate_sql(all_fixes)
        output_path = '/Users/pitchrankio-dev/Projects/PitchRank/scripts/club_name_fixes_male_all_states.sql'
        with open(output_path, 'w') as f:
            f.write(sql)
        print(f"\nSQL written to: {output_path}")
    else:
        print("\nNo fixes needed!")
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    total_caps = 0
    total_naming = 0
    total_teams = 0
    
    for state in sorted(summary.keys()):
        s = summary[state]
        print(f"{state}: {s['caps_fixes']} caps + {s['naming_fixes']} naming = {s['caps_fixes'] + s['naming_fixes']} fixes, {s['teams_affected']} teams (of {s['total_teams']})")
        total_caps += s['caps_fixes']
        total_naming += s['naming_fixes']
        total_teams += s['teams_affected']
    
    if summary:
        print("-"*60)
        print(f"TOTAL: {total_caps} caps + {total_naming} naming = {total_caps + total_naming} fixes, {total_teams} teams affected")
    
    return summary, all_fixes


if __name__ == '__main__':
    main()
