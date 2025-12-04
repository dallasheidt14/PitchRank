#!/usr/bin/env python3
"""
Fix team age_groups based on birth year in team names.

This script finds teams where the age_group doesn't match the birth year
indicated in the team name (e.g., "ILLINOIS MAGIC FC 2014" should be U12, not U13).

Usage:
    python scripts/fix_team_age_groups.py --dry-run  # Preview changes
    python scripts/fix_team_age_groups.py            # Apply fixes
"""

import os
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load .env.local first if it exists
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from supabase import create_client

# Current year for age calculation
CURRENT_YEAR = 2025


def calculate_age_group(birth_year: int) -> str:
    """Calculate age group from birth year.

    Formula: age_group = current_year - birth_year + 1
    Example: 2025 - 2014 + 1 = 12 → U12
    """
    age = CURRENT_YEAR - birth_year + 1
    if 7 <= age <= 19:
        return f"u{age}"
    return None


def extract_birth_year(team_name: str) -> int:
    """Extract birth year from team name.

    Handles multiple formats:
    - Single year: "Team 2014" → 2014
    - Two years with slash: "Team 2013/2014" → 2013 (use older/first year)
    - Two years with dash: "Team 2009-2010" → 2009 (use older/first year)
    - Two years after letter: "B2013/2014" → 2013 (use older/first year)
    
    Returns the birth year if found and valid, None otherwise.
    """
    # First, check for two-year patterns like "2013/2014" or "2009-2010" or "B2013/2014"
    # Use the FIRST (older) year in these cases
    # Note: Using (?<![0-9]) instead of \b to allow patterns like "B2013/2014"
    two_year_match = re.search(r'(?<![0-9])(20\d{2})[/-](20\d{2})(?![0-9])', team_name)
    if two_year_match:
        year1 = int(two_year_match.group(1))
        year2 = int(two_year_match.group(2))
        # Use the older (smaller) year
        year = min(year1, year2)
        if 2005 <= year <= 2018:
            return year
    
    # Also check for patterns like "2013/14" or "2009/10" or "B2007/08" (short second year)
    short_year_match = re.search(r'(?<![0-9])(20\d{2})[/-](\d{2})(?![0-9])', team_name)
    if short_year_match:
        year1 = int(short_year_match.group(1))
        year2_short = int(short_year_match.group(2))
        # Convert short year to full year (e.g., 14 -> 2014)
        year2 = 2000 + year2_short
        # Use the older (smaller) year
        year = min(year1, year2)
        if 2005 <= year <= 2018:
            return year
    
    # Fall back to single year match
    match = re.search(r'(?<![0-9])(20\d{2})(?![0-9])', team_name)
    if match:
        year = int(match.group(1))
        # Validate it's a reasonable birth year (2005-2018 for youth soccer)
        if 2005 <= year <= 2018:
            return year
    return None


def main():
    parser = argparse.ArgumentParser(description="Fix team age_groups based on birth year in names")
    parser.add_argument('--dry-run', action='store_true', help="Preview changes without applying")
    parser.add_argument('--team-name', type=str, help="Fix only teams matching this name (partial match)")
    args = parser.parse_args()

    # Initialize Supabase client
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print("❌ Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    print("=" * 70)
    print("TEAM AGE GROUP FIX SCRIPT")
    print("=" * 70)
    print(f"Current Year: {CURRENT_YEAR}")
    print(f"Mode: {'DRY RUN (no changes)' if args.dry_run else 'LIVE (applying changes)'}")
    print()

    # Fetch all teams with pagination
    print("📥 Fetching teams from database...")

    teams = []
    offset = 0
    batch_size = 1000

    while True:
        query = client.table('teams').select('team_id_master, team_name, age_group, birth_year, gender, state_code')
        
        if args.team_name:
            query = query.ilike('team_name', f'%{args.team_name}%')
        
        query = query.range(offset, offset + batch_size - 1)
        result = query.execute()
        
        if not result.data:
            break
        
        teams.extend(result.data)
        print(f"   Fetched {len(teams)} teams...")
        
        if len(result.data) < batch_size:
            break
        
        offset += batch_size

    print(f"✅ Found {len(teams)} teams total")
    print()

    # Find mismatches
    mismatches = []

    for team in teams:
        team_name = team.get('team_name', '')
        current_age_group = (team.get('age_group') or '').lower()

        # Extract birth year from team name
        birth_year = extract_birth_year(team_name)

        if birth_year:
            expected_age_group = calculate_age_group(birth_year)

            if expected_age_group and expected_age_group != current_age_group:
                mismatches.append({
                    'team_id_master': team['team_id_master'],
                    'team_name': team_name,
                    'current_age_group': current_age_group,
                    'expected_age_group': expected_age_group,
                    'birth_year': birth_year,
                    'gender': team.get('gender'),
                    'state_code': team.get('state_code')
                })

    if not mismatches:
        print("✅ No age group mismatches found!")
        return

    print(f"⚠️  Found {len(mismatches)} teams with age group mismatches:")
    print("-" * 70)
    print(f"{'Team Name':<40} {'Current':^10} {'Expected':^10} {'Birth Year':^10}")
    print("-" * 70)

    for m in mismatches[:50]:  # Show first 50
        name = m['team_name'][:38] + '..' if len(m['team_name']) > 40 else m['team_name']
        print(f"{name:<40} {m['current_age_group']:^10} {m['expected_age_group']:^10} {m['birth_year']:^10}")

    if len(mismatches) > 50:
        print(f"... and {len(mismatches) - 50} more")

    print("-" * 70)
    print()

    if args.dry_run:
        print("🔍 DRY RUN - No changes applied")
        print("   Run without --dry-run to apply fixes")
        return

    # Apply fixes
    print("🔧 Applying fixes...")
    fixed_count = 0
    error_count = 0

    for m in mismatches:
        try:
            # Update team's age_group and birth_year
            client.table('teams').update({
                'age_group': m['expected_age_group'],
                'birth_year': m['birth_year'],
                'updated_at': datetime.now().isoformat()
            }).eq('team_id_master', m['team_id_master']).execute()

            fixed_count += 1
            print(f"  ✓ Fixed: {m['team_name'][:50]} ({m['current_age_group']} → {m['expected_age_group']})")

        except Exception as e:
            error_count += 1
            print(f"  ✗ Error fixing {m['team_name'][:50]}: {e}")

    print()
    print("=" * 70)
    print(f"SUMMARY: Fixed {fixed_count} teams, {error_count} errors")
    print("=" * 70)

    if fixed_count > 0:
        print()
        print("⚠️  IMPORTANT: You need to recalculate rankings for the affected teams.")
        print("   Run: python -m src.rankings.calculator")


if __name__ == "__main__":
    main()
