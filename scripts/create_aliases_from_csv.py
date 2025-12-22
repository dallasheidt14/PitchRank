#!/usr/bin/env python3
"""
Create Modular11 Aliases from CSV Scrape Data

This script reads a Modular11 CSV scrape file and creates properly formatted
aliases ({club_id}_{age}_{division}) for all teams.

The CSV contains:
- team_id: Base club ID (e.g., 564)
- team_name: Full name with age/division (e.g., "Sacramento United U13 HD")
- age_group: Age group (e.g., U13)
- competition: Contains division (e.g., "HD Group Play", "AD Group Play")

Usage:
    python scripts/create_aliases_from_csv.py --csv-path data/raw/modular11_results.csv --dry-run
    python scripts/create_aliases_from_csv.py --csv-path data/raw/modular11_results.csv
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'


def get_supabase():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def extract_division(team_name: str, competition: str, mls_division: str = None) -> str:
    """Extract HD/AD division from mls_division column, team name, or competition field."""
    # Check mls_division column first (most reliable)
    if mls_division:
        div_upper = mls_division.upper().strip()
        if div_upper in ('HD', 'AD'):
            return div_upper

    # Check team name
    if team_name:
        name_upper = team_name.upper().strip()
        if name_upper.endswith(' HD') or ' HD ' in name_upper:
            return 'HD'
        elif name_upper.endswith(' AD') or ' AD ' in name_upper:
            return 'AD'

    # Check competition field
    if competition:
        comp_upper = competition.upper()
        if 'HD ' in comp_upper or comp_upper.startswith('HD'):
            return 'HD'
        elif 'AD ' in comp_upper or comp_upper.startswith('AD'):
            return 'AD'

    return None


def normalize_age(age_group: str) -> str:
    """Normalize age group to U13, U14, etc."""
    if not age_group:
        return None
    age = age_group.strip().upper()
    if not age.startswith('U'):
        age = f'U{age}'
    return age


def extract_club_name(team_name: str, age_group: str) -> str:
    """Extract club name by removing age and HD/AD suffix."""
    if not team_name:
        return ''

    name = team_name.strip()

    # Remove HD/AD suffix
    for suffix in [' HD', ' AD', ' hd', ' ad']:
        if name.endswith(suffix):
            name = name[:-3].strip()
            break

    # Remove age group
    if age_group:
        age_variants = [f' {age_group}', f' {age_group.upper()}', f' {age_group.lower()}']
        for variant in age_variants:
            if variant in name:
                name = name.replace(variant, '').strip()
                break

    return name


def read_csv_teams(csv_path: str) -> dict:
    """
    Read CSV and extract unique team definitions.

    Processes both team and opponent data from game records.
    Returns dict keyed by (club_id, age_group, division) with team info.
    """
    teams = {}

    def add_team(team_id, team_name, club_name, age_group, competition, mls_division):
        """Helper to add a team to the dict."""
        if not team_id or not age_group:
            return

        team_id = str(team_id).strip()
        team_name = str(team_name).strip() if team_name else ''
        club_name = str(club_name).strip() if club_name else ''
        age_group = normalize_age(age_group)

        if not age_group:
            return

        # Extract division (prioritize mls_division column)
        division = extract_division(team_name, competition, mls_division)

        if not division:
            return

        # Create unique key
        key = (team_id, age_group, division)

        if key not in teams:
            teams[key] = {
                'team_id': team_id,
                'team_name': team_name,
                'club_name': club_name or extract_club_name(team_name, age_group),
                'age_group': age_group,
                'division': division,
                'count': 0
            }

        teams[key]['count'] += 1

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            age_group = row.get('age_group', '')
            competition = row.get('competition', '')
            mls_division = row.get('mls_division', '')

            # Process team data
            add_team(
                row.get('team_id'),
                row.get('team_name'),
                row.get('club_name'),
                age_group,
                competition,
                mls_division
            )

            # Process opponent data
            add_team(
                row.get('opponent_id'),
                row.get('opponent_name'),
                row.get('opponent_club_name'),
                age_group,
                competition,
                mls_division
            )

    return teams


def find_matching_db_team(db, club_name: str, age_group: str, division: str):
    """Find a matching team in the database."""
    # Try exact match with division
    search_pattern = f"%{club_name}%{age_group}%{division}%"
    result = db.table('teams').select('team_id_master, team_name').ilike(
        'team_name', search_pattern
    ).limit(1).execute()

    if result.data:
        return result.data[0]

    # Try without division
    search_pattern = f"%{club_name}%{age_group}%"
    result = db.table('teams').select('team_id_master, team_name').ilike(
        'team_name', search_pattern
    ).limit(5).execute()

    if result.data:
        # Prefer exact match on age
        for team in result.data:
            if age_group.upper() in team['team_name'].upper():
                return team
        return result.data[0]

    return None


def create_alias(db, team_id_master: str, club_id: str, age_group: str, division: str, dry_run: bool = True):
    """Create a properly formatted alias."""
    # Build alias: {club_id}_{age}_{division}
    alias_id = f"{club_id}_{age_group}_{division}"

    # Check if alias already exists
    existing = db.table('team_alias_map').select('id, team_id_master').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('provider_team_id', alias_id).execute()

    if existing.data:
        existing_team = existing.data[0]['team_id_master']
        if existing_team == team_id_master:
            return 'exists_same'
        else:
            return 'exists_different'

    if dry_run:
        return 'would_create'

    # Create the alias
    db.table('team_alias_map').insert({
        'provider_id': MODULAR11_PROVIDER_ID,
        'provider_team_id': alias_id,
        'team_id_master': team_id_master,
        'match_method': 'migration',
        'match_confidence': 1.0,
        'review_status': 'approved',
        'division': division,
        'created_at': datetime.utcnow().isoformat() + 'Z'
    }).execute()

    return 'created'


def main():
    parser = argparse.ArgumentParser(description='Create Modular11 aliases from CSV scrape')
    parser.add_argument('--csv-path', required=True, help='Path to Modular11 CSV file')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without executing')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')

    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"❌ CSV file not found: {args.csv_path}")
        sys.exit(1)

    db = get_supabase()

    print("="*70)
    print("CREATE MODULAR11 ALIASES FROM CSV")
    print("="*70)
    print(f"\n📁 Reading CSV: {args.csv_path}")

    # Read teams from CSV
    csv_teams = read_csv_teams(args.csv_path)
    print(f"📊 Found {len(csv_teams)} unique team/age/division combinations in CSV")

    # Group by division
    by_division = defaultdict(list)
    for key, team in csv_teams.items():
        by_division[team['division']].append(team)

    print(f"   HD teams: {len(by_division['HD'])}")
    print(f"   AD teams: {len(by_division['AD'])}")

    # Process each team
    print(f"\n{'🔍 DRY RUN - ' if args.dry_run else ''}Processing teams...")

    stats = {
        'matched': 0,
        'not_found': 0,
        'alias_created': 0,
        'alias_exists': 0,
        'alias_conflict': 0,
        'errors': 0
    }

    not_found_teams = []

    for (club_id, age_group, division), team_info in sorted(csv_teams.items()):
        club_name = team_info['club_name']

        # Find matching team in database
        db_team = find_matching_db_team(db, club_name, age_group, division)

        if not db_team:
            stats['not_found'] += 1
            not_found_teams.append(team_info)
            if args.verbose:
                print(f"  ❌ Not found: {team_info['team_name']}")
            continue

        stats['matched'] += 1

        # Create alias
        try:
            result = create_alias(
                db,
                db_team['team_id_master'],
                club_id,
                age_group,
                division,
                dry_run=args.dry_run
            )

            if result == 'created':
                stats['alias_created'] += 1
                if args.verbose:
                    print(f"  ✅ Created: {club_id}_{age_group}_{division} → {db_team['team_name']}")
            elif result == 'would_create':
                stats['alias_created'] += 1
                if args.verbose:
                    print(f"  [DRY] Would create: {club_id}_{age_group}_{division} → {db_team['team_name']}")
            elif result == 'exists_same':
                stats['alias_exists'] += 1
            elif result == 'exists_different':
                stats['alias_conflict'] += 1
                if args.verbose:
                    print(f"  ⚠️ Conflict: {club_id}_{age_group}_{division} already points to different team")

        except Exception as e:
            stats['errors'] += 1
            print(f"  ❌ Error: {e}")

    # Print summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Teams in CSV:        {len(csv_teams)}")
    print(f"Matched in DB:       {stats['matched']}")
    print(f"Not found in DB:     {stats['not_found']}")
    print(f"Aliases {'would create' if args.dry_run else 'created'}:  {stats['alias_created']}")
    print(f"Aliases already exist: {stats['alias_exists']}")
    print(f"Alias conflicts:     {stats['alias_conflict']}")
    print(f"Errors:              {stats['errors']}")

    if not_found_teams and args.verbose:
        print(f"\n📋 Teams not found in database (first 20):")
        for team in not_found_teams[:20]:
            print(f"   - {team['team_name']} (club_id={team['team_id']})")

    if args.dry_run:
        print(f"\n💡 Run without --dry-run to create aliases")


if __name__ == '__main__':
    main()
