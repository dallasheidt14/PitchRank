#!/usr/bin/env python3
"""Analyze Female teams for club name standardization."""

import os
import re
import json
from collections import defaultdict
from supabase import create_client

# Load credentials
SUPABASE_URL = "https://pfkrhmprwxtghtpinrot.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBma3JobXByd3h0Z2h0cGlucm90Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjE3NDQ3ODQsImV4cCI6MjA3NzMyMDc4NH0.fOl6xuUuRzJhXe6UPHiCveZsviApipnFmcoB2Iz6Jt0"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def fetch_all_female_teams():
    """Fetch all Female teams using pagination."""
    all_teams = []
    offset = 0
    batch_size = 1000
    
    while True:
        response = supabase.table("teams").select("id, club_name, state_code, age_group").eq("gender", "Female").range(offset, offset + batch_size - 1).execute()
        batch = response.data
        if not batch:
            break
        all_teams.extend(batch)
        print(f"Fetched {len(batch)} teams (offset {offset})")
        if len(batch) < batch_size:
            break
        offset += batch_size
    
    return all_teams

def normalize_for_comparison(name):
    """Normalize name for finding variations (lowercase, no punctuation)."""
    # Remove punctuation and extra spaces
    normalized = re.sub(r'[.\-\(\)]', ' ', name.lower())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized

def expand_abbreviations(name):
    """Expand common abbreviations for comparison."""
    expanded = name.lower()
    # Expand common abbreviations
    expanded = re.sub(r'\bsc\b', 'soccer club', expanded)
    expanded = re.sub(r'\bfc\b', 'futbol club', expanded)
    expanded = re.sub(r'\bsa\b', 'soccer academy', expanded)
    expanded = re.sub(r'\bfa\b', 'futbol academy', expanded)
    # Remove extra spaces
    expanded = re.sub(r'\s+', ' ', expanded).strip()
    return expanded

def get_base_name(name):
    """Get base name by removing suffixes for grouping similar clubs."""
    base = name.lower().strip()
    # Remove common suffixes
    base = re.sub(r'\s+(soccer club|sc|futbol club|fc|soccer academy|sa|futbol academy|fa|soccer|united)$', '', base)
    base = re.sub(r'\s+(soccer club|sc|futbol club|fc|soccer academy|sa|futbol academy|fa|soccer|united)$', '', base)  # Run twice for "United Soccer Club"
    base = re.sub(r'\s+', ' ', base).strip()
    return base

def is_caps_issue(name):
    """Check if name has ALL CAPS issues."""
    words = name.split()
    # Acronyms to ignore (2-3 letter words that are OK to be caps)
    acronyms = {'FC', 'SC', 'SA', 'FA', 'USA', 'AC', 'CF', 'CD', 'OC', 'VC', 'LA', 'NY', 'TX', 'AZ', 'CA', 'FL', 'GA', 'NC', 'TN', 'VA', 'MD', 'OH', 'PA', 'NJ', 'CT', 'MA', 'CO', 'UT', 'NV', 'WA', 'OR', 'MN', 'WI', 'MI', 'IL', 'IN', 'KY', 'AL', 'MS', 'AR', 'MO', 'IA', 'KS', 'NE', 'SD', 'ND', 'MT', 'WY', 'ID', 'NM', 'HI', 'AK', 'VT', 'NH', 'ME', 'RI', 'DE', 'WV', 'OK', 'LA', 'CLW', 'TPA', 'RSL', 'ECNL', 'MLS', 'USSF', 'US', 'CCV', 'DKSC', 'GPS', 'CDA', 'NTH', 'PDA', 'TSC', 'VSA', 'MVLA', 'AYSO', 'NTX', 'STX', 'PPA', 'STL', 'KC', 'DC', 'SJ', 'PFC', 'III', 'II', 'IV', 'CFC', 'NCFC', 'SFC', 'ASC', 'NSC', 'CASL', 'BRYC', 'VYS'}
    
    for word in words:
        # Skip short words and acronyms
        if len(word) <= 3 and word.upper() in acronyms:
            continue
        # Skip Roman numerals
        if re.match(r'^[IVX]+$', word):
            continue
        # Check if word is all caps and longer than 3 letters
        if len(word) > 3 and word.isupper():
            return True
    return False

def fix_caps(name):
    """Fix capitalization issues while preserving acronyms."""
    # Known acronyms to preserve
    acronyms = {'FC', 'SC', 'SA', 'FA', 'USA', 'AC', 'CF', 'CD', 'OC', 'VC', 'LA', 'NY', 'TX', 'AZ', 'CA', 'FL', 'GA', 'NC', 'TN', 'VA', 'MD', 'OH', 'PA', 'NJ', 'CT', 'MA', 'CO', 'UT', 'NV', 'WA', 'OR', 'MN', 'WI', 'MI', 'IL', 'IN', 'KY', 'AL', 'MS', 'AR', 'MO', 'IA', 'KS', 'NE', 'SD', 'ND', 'MT', 'WY', 'ID', 'NM', 'HI', 'AK', 'VT', 'NH', 'ME', 'RI', 'DE', 'WV', 'OK', 'LA', 'CLW', 'TPA', 'RSL', 'ECNL', 'MLS', 'USSF', 'US', 'CCV', 'DKSC', 'GPS', 'CDA', 'NTH', 'PDA', 'TSC', 'VSA', 'MVLA', 'AYSO', 'NTX', 'STX', 'PPA', 'STL', 'KC', 'DC', 'SJ', 'PFC', 'III', 'II', 'IV', 'CFC', 'NCFC', 'SFC', 'ASC', 'NSC', 'CASL', 'BRYC', 'VYS'}
    
    words = name.split()
    fixed_words = []
    
    for word in words:
        upper_word = word.upper()
        if upper_word in acronyms:
            fixed_words.append(upper_word)
        elif re.match(r'^[IVX]+$', word.upper()):
            fixed_words.append(word.upper())
        else:
            fixed_words.append(word.title())
    
    return ' '.join(fixed_words)

def analyze_teams(teams):
    """Analyze teams and find standardization issues."""
    # Group by state
    by_state = defaultdict(list)
    for team in teams:
        by_state[team['state_code']].append(team)
    
    fixes = []
    
    for state, state_teams in sorted(by_state.items()):
        # Group clubs by normalized base name to find variations
        club_groups = defaultdict(list)
        for team in state_teams:
            club = team['club_name']
            # Create a key that groups similar names
            base = get_base_name(club)
            club_groups[base].append(team)
        
        # Analyze each group
        for base_name, group_teams in club_groups.items():
            # Count each exact club name variation
            name_counts = defaultdict(int)
            for team in group_teams:
                name_counts[team['club_name']] += 1
            
            # If only one variation, check for caps issues
            if len(name_counts) == 1:
                club_name = list(name_counts.keys())[0]
                if is_caps_issue(club_name):
                    fixed = fix_caps(club_name)
                    if fixed != club_name:
                        fixes.append({
                            'type': 'CAPS',
                            'state': state,
                            'from': club_name,
                            'to': fixed,
                            'count': name_counts[club_name]
                        })
            else:
                # Multiple variations - find the majority
                sorted_names = sorted(name_counts.items(), key=lambda x: -x[1])
                majority_name = sorted_names[0][0]
                majority_count = sorted_names[0][1]
                
                # Check if majority name has caps issues
                if is_caps_issue(majority_name):
                    majority_name = fix_caps(majority_name)
                
                # All other variations should be fixed to majority
                for name, count in sorted_names:
                    if name != majority_name:
                        # Skip regional branches
                        name_lower = name.lower()
                        majority_lower = majority_name.lower()
                        regional_indicators = ['north', 'south', 'east', 'west', 'central', 'clw', 'tpa', 'mesa', 'yuma', 'valley']
                        
                        # Check if either has a regional indicator the other doesn't
                        name_regions = [r for r in regional_indicators if r in name_lower]
                        majority_regions = [r for r in regional_indicators if r in majority_lower]
                        
                        if name_regions != majority_regions:
                            # Different regional branches - skip
                            continue
                        
                        # Determine fix type
                        if normalize_for_comparison(name) == normalize_for_comparison(majority_name):
                            fix_type = 'CAPS'
                        else:
                            fix_type = 'VARIATION'
                        
                        fixes.append({
                            'type': fix_type,
                            'state': state,
                            'from': name,
                            'to': majority_name,
                            'count': count
                        })
    
    return fixes

def generate_sql(fixes):
    """Generate SQL UPDATE statements."""
    lines = [
        "-- Club Name Standardization: Female Teams (All States)",
        "-- Generated by analyze_female_clubs.py",
        "-- IMPORTANT: Every UPDATE filters by state_code AND gender='Female'",
        "",
        "BEGIN;",
        ""
    ]
    
    # Group by state for organized output
    by_state = defaultdict(list)
    for fix in fixes:
        by_state[fix['state']].append(fix)
    
    total_teams = 0
    for state in sorted(by_state.keys()):
        state_fixes = by_state[state]
        lines.append(f"-- === {state} ===")
        for fix in sorted(state_fixes, key=lambda x: x['from']):
            escaped_from = fix['from'].replace("'", "''")
            escaped_to = fix['to'].replace("'", "''")
            lines.append(f"-- [{fix['type']}] \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")
            lines.append(f"UPDATE teams SET club_name = '{escaped_to}' WHERE club_name = '{escaped_from}' AND state_code = '{fix['state']}' AND gender = 'Female';")
            lines.append("")
            total_teams += fix['count']
        lines.append("")
    
    lines.append("COMMIT;")
    lines.append("")
    lines.append(f"-- Summary: {len(fixes)} fixes, {total_teams} teams affected")
    
    return '\n'.join(lines)

# Main execution
print("Fetching all Female teams...")
teams = fetch_all_female_teams()
print(f"Total Female teams: {len(teams)}")

# Filter out teams with None state_code
teams = [t for t in teams if t['state_code'] is not None]
print(f"Teams with valid state_code: {len(teams)}")

# Count by state
state_counts = defaultdict(int)
for t in teams:
    state_counts[t['state_code']] += 1
print(f"\nTeams by state:")
for state in sorted(state_counts.keys()):
    print(f"  {state}: {state_counts[state]}")

print("\nAnalyzing for standardization issues...")
fixes = analyze_teams(teams)

print(f"\nFound {len(fixes)} fixes:")
for fix in fixes:
    print(f"  [{fix['type']}] {fix['state']}: \"{fix['from']}\" → \"{fix['to']}\" ({fix['count']} teams)")

# Generate SQL
sql = generate_sql(fixes)
print("\n" + "="*60)
print("SQL OUTPUT:")
print("="*60)
print(sql)

# Save to file
output_path = "/Users/pitchrankio-dev/Projects/PitchRank/scripts/club_name_fixes_female_all_states.sql"
with open(output_path, 'w') as f:
    f.write(sql)
print(f"\nSaved to: {output_path}")

# Summary by state
print("\n" + "="*60)
print("SUMMARY BY STATE:")
print("="*60)
state_fix_counts = defaultdict(lambda: {'fixes': 0, 'teams': 0})
for fix in fixes:
    state_fix_counts[fix['state']]['fixes'] += 1
    state_fix_counts[fix['state']]['teams'] += fix['count']

for state in sorted(state_fix_counts.keys()):
    counts = state_fix_counts[state]
    print(f"  {state}: {counts['fixes']} fixes, {counts['teams']} teams")

total_teams_affected = sum(fix['count'] for fix in fixes)
print(f"\nTOTAL: {len(fixes)} fixes, {total_teams_affected} teams affected")
