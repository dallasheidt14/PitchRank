#!/usr/bin/env python3
"""
Weekly Cleany Job - Run all data hygiene tasks

Tasks in order:
1. Club name case normalization (majority rule)
2. Team name normalization (ages, gender words)
3. Duplicate team merges

Run: python3 scripts/run_weekly_cleany.py
"""

import os
import sys
import psycopg2
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv('/Users/pitchrankio-dev/Projects/PitchRank/.env')

DATABASE_URL = os.getenv('DATABASE_URL')

def run_club_case_normalization():
    """Fix club name case inconsistencies using majority rule."""
    print("\n" + "=" * 60)
    print("STEP 1: CLUB NAME CASE NORMALIZATION")
    print("=" * 60)
    
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    
    # Get all club names with counts
    cur.execute('''
        SELECT club_name, COUNT(*) as cnt
        FROM teams 
        WHERE club_name IS NOT NULL AND club_name != ''
        GROUP BY club_name
        ORDER BY club_name
    ''')
    club_counts = {row[0]: row[1] for row in cur.fetchall()}
    
    # Group by lowercase
    lowercase_groups = defaultdict(list)
    for club, count in club_counts.items():
        lowercase_groups[club.lower()].append((club, count))
    
    # Find groups with multiple variations
    fixes = []
    for lower_name, variations in lowercase_groups.items():
        if len(variations) > 1:
            variations.sort(key=lambda x: x[1], reverse=True)
            canonical = variations[0][0]
            for club, count in variations[1:]:
                fixes.append((club, canonical, count))
    
    if not fixes:
        print("✅ No club case inconsistencies found")
        conn.close()
        return 0
    
    print(f"Found {len(fixes)} club names to fix")
    
    # Apply fixes
    total_updated = 0
    for old_name, new_name, _ in fixes:
        cur.execute('UPDATE teams SET club_name = %s WHERE club_name = %s', (new_name, old_name))
        total_updated += cur.rowcount
    
    print(f"✅ Updated {total_updated} teams")
    conn.close()
    return total_updated


def run_team_name_normalization():
    """Normalize team names (ages, gender words)."""
    print("\n" + "=" * 60)
    print("STEP 2: TEAM NAME NORMALIZATION")
    print("=" * 60)
    
    # Import the normalizer
    from normalize_team_names import normalize_team_name
    
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    
    # Get teams that haven't been normalized yet
    cur.execute('''
        SELECT id, team_name, club_name 
        FROM teams 
        WHERE team_name_original IS NULL
        LIMIT 10000
    ''')
    teams = cur.fetchall()
    
    if not teams:
        print("✅ No teams need normalization")
        conn.close()
        return 0
    
    print(f"Found {len(teams)} teams to normalize")
    
    updated = 0
    for team_id, team_name, club_name in teams:
        normalized = normalize_team_name(team_name, club_name)
        if normalized != team_name:
            cur.execute('''
                UPDATE teams 
                SET team_name_original = %s, team_name = %s 
                WHERE id = %s
            ''', (team_name, normalized, team_id))
            updated += 1
    
    print(f"✅ Normalized {updated} teams")
    
    # Also strip any remaining gender words from all teams
    cur.execute('''
        SELECT id, team_name FROM teams 
        WHERE team_name ILIKE '%% boys%%' OR team_name ILIKE '%% girls%%'
    ''')
    gender_teams = cur.fetchall()
    
    if gender_teams:
        import re
        gender_fixed = 0
        for team_id, team_name in gender_teams:
            new_name = re.sub(r'\s+(boys|girls|boy|girl)\s*', ' ', team_name, flags=re.IGNORECASE)
            new_name = re.sub(r'\s+(boys|girls|boy|girl)$', '', new_name, flags=re.IGNORECASE)
            new_name = ' '.join(new_name.split())
            if new_name != team_name:
                cur.execute('UPDATE teams SET team_name = %s WHERE id = %s', (new_name, team_id))
                gender_fixed += 1
        print(f"✅ Stripped gender words from {gender_fixed} additional teams")
    
    conn.close()
    return updated


def run_duplicate_merges():
    """Run the duplicate team merger."""
    print("\n" + "=" * 60)
    print("STEP 3: DUPLICATE TEAM MERGES")
    print("=" * 60)
    
    # Import and run the merge script
    import run_all_merges
    results = run_all_merges.run_all_merges(dry_run=False)
    run_all_merges.save_tracker(results)
    
    return results['total_merged']


def preflight_check():
    """Quick check if any work is needed. Returns (needs_work, reason)."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Check 1: Club case inconsistencies
    cur.execute('''
        SELECT COUNT(DISTINCT LOWER(club_name)) as unique_lower,
               COUNT(DISTINCT club_name) as unique_exact
        FROM teams 
        WHERE club_name IS NOT NULL AND club_name != ''
    ''')
    row = cur.fetchone()
    club_inconsistencies = row[1] - row[0] if row else 0
    
    # Check 2: Teams needing normalization
    cur.execute('''
        SELECT COUNT(*) FROM teams 
        WHERE team_name_original IS NULL
        LIMIT 1
    ''')
    needs_normalization = cur.fetchone()[0] > 0
    
    # Check 3: Quick duplicate estimate (same club + similar team names)
    # This is a fast heuristic, not exact
    cur.execute('''
        SELECT COUNT(*) FROM (
            SELECT club_name, LOWER(REGEXP_REPLACE(team_name, '[^a-zA-Z0-9]', '', 'g'))
            FROM teams
            WHERE is_deprecated = false AND club_name IS NOT NULL
            GROUP BY club_name, LOWER(REGEXP_REPLACE(team_name, '[^a-zA-Z0-9]', '', 'g'))
            HAVING COUNT(*) > 1
            LIMIT 10
        ) dupes
    ''')
    potential_dupes = cur.fetchone()[0]
    
    conn.close()
    
    if club_inconsistencies > 0:
        return True, f"{club_inconsistencies} club case inconsistencies"
    if needs_normalization:
        return True, "Teams need normalization"
    if potential_dupes > 0:
        return True, f"~{potential_dupes}+ potential duplicate groups"
    
    return False, "No work needed"


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Weekly Cleany Job')
    parser.add_argument('--preflight', action='store_true', 
                       help='Quick check: exit 0 if no work (skip agent), exit 1 if work needed')
    args = parser.parse_args()
    
    # Pre-flight mode
    if args.preflight:
        needs_work, reason = preflight_check()
        if needs_work:
            print(f"PREFLIGHT_NEEDED: {reason}")
            sys.exit(1)
        else:
            print("PREFLIGHT_OK: No data hygiene work needed, skipping agent")
            sys.exit(0)
    
    print("=" * 60)
    print("WEEKLY CLEANY JOB")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    results = {
        'club_fixes': 0,
        'team_normalizations': 0,
        'merges': 0
    }
    
    try:
        results['club_fixes'] = run_club_case_normalization()
    except Exception as e:
        print(f"❌ Club normalization error: {e}")
    
    try:
        results['team_normalizations'] = run_team_name_normalization()
    except Exception as e:
        print(f"❌ Team normalization error: {e}")
    
    try:
        results['merges'] = run_duplicate_merges()
    except Exception as e:
        print(f"❌ Merge error: {e}")
    
    print("\n" + "=" * 60)
    print("WEEKLY CLEANY COMPLETE")
    print("=" * 60)
    print(f"Club case fixes: {results['club_fixes']}")
    print(f"Team normalizations: {results['team_normalizations']}")
    print(f"Duplicate merges: {results['merges']}")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return results


if __name__ == '__main__':
    main()
