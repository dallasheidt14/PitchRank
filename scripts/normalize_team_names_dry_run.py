#!/usr/bin/env python3
"""
Dry run: Normalize team names in database
Shows what would change without making changes
"""

import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)

def normalize_age_in_name(team_name: str) -> tuple[str, bool]:
    """
    Normalize age portion of team name.
    Returns (normalized_name, was_changed)
    
    Rules:
    - Birth year formats (12B, B12, 2012B, B2012) → 2012
    - Age group formats (U14B, U-14, BU14) → U14
    - Combined ages (11/12B, 2011/2012) → oldest age (2011)
    - Strip gender from age, keep everything else
    """
    if not team_name:
        return team_name, False
    
    original = team_name
    result = team_name
    
    # FIRST: Handle combined age groups - take the oldest (smallest year number)
    # Pattern: ##/##B or ##/##G (combined 2-digit years + gender)
    def combined_short_years(m):
        y1 = int(m.group(1))
        y2 = int(m.group(2))
        oldest = min(y1, y2)  # Smaller number = older (2011 < 2012)
        if 6 <= oldest <= 18:
            return str(2000 + oldest)
        return m.group(0)
    result = re.sub(r'\b(\d{2})/(\d{2})[BbGg]?\b', combined_short_years, result)
    
    # Pattern: ####/####B or ####/#### (combined 4-digit years, optional gender)
    def combined_full_years(m):
        y1 = int(m.group(1))
        y2 = int(m.group(2))
        oldest = min(y1, y2)
        return str(oldest)
    result = re.sub(r'\b(\d{4})/(\d{4})[BbGg]?\b', combined_full_years, result)
    
    # Pattern: B#### or G#### (gender prefix + 4-digit year) → ####
    result = re.sub(r'\b([BbGg])(\d{4})\b', r'\2', result)
    
    # Pattern: ####B or ####G (4-digit year + gender suffix) → ####
    result = re.sub(r'\b(\d{4})([BbGg])\b', r'\1', result)
    
    # Pattern: B## or G## where ## is 06-18 (gender prefix + 2-digit year) → 20##
    def expand_short_year_prefix(m):
        year = int(m.group(2))
        if 6 <= year <= 18:
            return str(2000 + year)
        return m.group(0)  # Keep original if not a valid birth year
    result = re.sub(r'\b([BbGg])(\d{2})\b', expand_short_year_prefix, result)
    
    # Pattern: ##B or ##G where ## is 06-18 (2-digit year + gender suffix) → 20##
    def expand_short_year_suffix(m):
        year = int(m.group(1))
        if 6 <= year <= 18:
            return str(2000 + year)
        return m.group(0)
    result = re.sub(r'\b(\d{2})([BbGg])\b', expand_short_year_suffix, result)
    
    # Pattern: BU## or GU## (gender prefix on age group) → U##
    result = re.sub(r'\b[BbGg]([Uu]\d{1,2})\b', r'\1', result)
    
    # Pattern: U##B or U##G or U-##B (age group + gender suffix) → U##
    result = re.sub(r'\b([Uu]-?\d{1,2})[BbGg]\b', r'\1', result)
    
    # Pattern: U-## → U## (remove hyphen)
    result = re.sub(r'\b[Uu]-(\d{1,2})\b', r'U\1', result)
    
    # Normalize U to uppercase
    result = re.sub(r'\bu(\d{1,2})\b', r'U\1', result)
    
    # Clean up any double spaces
    result = re.sub(r'  +', ' ', result).strip()
    
    return result, result != original


def main():
    age_group = sys.argv[1].lower() if len(sys.argv) > 1 else 'u15'
    gender = sys.argv[2] if len(sys.argv) > 2 else 'Male'
    
    print(f"=== DRY RUN: Normalize {age_group} {gender} Team Names ===\n")
    
    # Fetch teams - need to paginate past 1000 limit
    print(f"Fetching {age_group} {gender} teams...")
    all_teams = []
    offset = 0
    page_size = 1000
    
    while True:
        result = supabase.table('teams').select('id, team_name, club_name, state_code').eq('age_group', age_group).eq('gender', gender).eq('is_deprecated', False).range(offset, offset + page_size - 1).execute()
        all_teams.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    
    teams = all_teams
    print(f"Found {len(teams)} teams\n")
    
    changes = []
    no_changes = []
    
    for team in teams:
        old_name = team['team_name']
        new_name, changed = normalize_age_in_name(old_name)
        
        if changed:
            changes.append({
                'id': team['id'],
                'club': team['club_name'],
                'state': team['state_code'],
                'old': old_name,
                'new': new_name
            })
        else:
            no_changes.append(team)
    
    # Show changes
    print(f"📝 WOULD CHANGE: {len(changes)} teams")
    print(f"✅ ALREADY CLEAN: {len(no_changes)} teams")
    if teams:
        print(f"📊 CHANGE RATE: {len(changes)/len(teams)*100:.1f}%\n")
    else:
        print("📊 No teams found\n")
    
    if changes:
        print("=" * 80)
        print("CHANGES PREVIEW (first 50):")
        print("=" * 80)
        
        for i, c in enumerate(changes[:50]):
            print(f"\n[{c['state']}] {c['club']}")
            print(f"  OLD: {c['old']}")
            print(f"  NEW: {c['new']}")
        
        if len(changes) > 50:
            print(f"\n... and {len(changes) - 50} more")
    
    # Group by change pattern
    print("\n" + "=" * 80)
    print("CHANGE PATTERNS:")
    print("=" * 80)
    
    patterns = {}
    for c in changes:
        # Detect what kind of change
        old = c['old']
        new = c['new']
        
        if re.search(r'[BbGg]\d{4}', old):
            pattern = 'B/G#### → ####'
        elif re.search(r'\d{4}[BbGg]', old):
            pattern = '####B/G → ####'
        elif re.search(r'[BbGg]\d{2}(?!\d)', old):
            pattern = 'B/G## → 20##'
        elif re.search(r'(?<!\d)\d{2}[BbGg]', old):
            pattern = '##B/G → 20##'
        elif re.search(r'[BbGg][Uu]', old):
            pattern = 'BU/GU## → U##'
        elif re.search(r'[Uu]\d+[BbGg]', old):
            pattern = 'U##B/G → U##'
        elif re.search(r'[Uu]-\d', old):
            pattern = 'U-## → U##'
        else:
            pattern = 'Other'
        
        patterns[pattern] = patterns.get(pattern, 0) + 1
    
    for pattern, count in sorted(patterns.items(), key=lambda x: -x[1]):
        print(f"  {pattern}: {count}")
    
    # Check for --execute flag
    execute = '--execute' in sys.argv
    
    if not execute:
        print(f"\n✅ Dry run complete. No changes made.")
        print(f"To apply changes, run with --execute flag")
    else:
        print(f"\n🚀 EXECUTING {len(changes)} changes...")
        
        success = 0
        errors = []
        
        for i, c in enumerate(changes):
            try:
                supabase.table('teams').update({'team_name': c['new']}).eq('id', c['id']).execute()
                success += 1
                if (i + 1) % 100 == 0:
                    print(f"  Progress: {i + 1}/{len(changes)} ({success} success)")
            except Exception as e:
                errors.append({'id': c['id'], 'old': c['old'], 'new': c['new'], 'error': str(e)})
        
        print(f"\n✅ COMPLETE!")
        print(f"  Success: {success}")
        print(f"  Errors: {len(errors)}")
        
        if errors:
            print("\nErrors:")
            for e in errors[:10]:
                print(f"  {e['id']}: {e['error']}")


if __name__ == '__main__':
    main()
