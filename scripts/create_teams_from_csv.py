#!/usr/bin/env python3
"""
Create Modular11 Teams and Aliases from CSV Scrape Data

This script reads a Modular11 CSV scrape file and creates:
1. Teams in the `teams` table with proper names (e.g., "Sacramento United U13 HD")
2. Aliases in `team_alias_map` with format {club_id}_{age}_{division} (e.g., "564_U13_HD")

Usage:
    python scripts/create_teams_from_csv.py --csv-path data/raw/modular11_results.csv --dry-run
    python scripts/create_teams_from_csv.py --csv-path data/raw/modular11_results.csv
"""
import argparse
import csv
import os
import sys
import uuid
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
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def extract_division(team_name: str, competition: str, mls_division: str = None) -> str:
    """Extract HD/AD division from mls_division column, team name, or competition field."""
    if mls_division:
        div_upper = mls_division.upper().strip()
        if div_upper in ('HD', 'AD'):
            return div_upper

    if team_name:
        name_upper = team_name.upper().strip()
        if name_upper.endswith(' HD') or ' HD ' in name_upper:
            return 'HD'
        elif name_upper.endswith(' AD') or ' AD ' in name_upper:
            return 'AD'

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


def read_csv_teams(csv_path: str) -> dict:
    """Read CSV and extract unique team definitions."""
    teams = {}

    def add_team(team_id, team_name, club_name, age_group, competition, mls_division):
        if not team_id or not age_group:
            return

        team_id = str(team_id).strip()
        team_name = str(team_name).strip() if team_name else ''
        club_name = str(club_name).strip() if club_name else ''
        age_group = normalize_age(age_group)

        if not age_group:
            return

        division = extract_division(team_name, competition, mls_division)

        if not division:
            return

        key = (team_id, age_group, division)

        if key not in teams:
            teams[key] = {
                'club_id': team_id,
                'team_name': team_name,
                'club_name': club_name,
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


def create_team_and_alias(db, team_info: dict, dry_run: bool = True) -> dict:
    """Create a team and its alias."""
    club_id = team_info['club_id']
    team_name = team_info['team_name']
    club_name = team_info['club_name'] or team_name.rsplit(' ', 2)[0]  # Fallback: remove last 2 words
    age_group = team_info['age_group']
    division = team_info['division']

    # Build alias: {club_id}_{age}_{division}
    alias_id = f"{club_id}_{age_group}_{division}"

    # Normalize age for DB (lowercase)
    age_db = age_group.lower()

    if dry_run:
        return {
            'status': 'would_create',
            'team_name': team_name,
            'alias_id': alias_id
        }

    # Generate UUID for new team
    team_id_master = str(uuid.uuid4())

    # Create team - use alias_id as provider_team_id to avoid unique constraint violation
    # (same club_id is used for multiple age groups / divisions)
    team_data = {
        'team_id_master': team_id_master,
        'team_name': team_name,
        'club_name': club_name,
        'age_group': age_db,
        'gender': 'Male',  # MLS NEXT is all boys
        'provider_id': MODULAR11_PROVIDER_ID,
        'provider_team_id': alias_id,  # Use full alias format to be unique
        'created_at': datetime.utcnow().isoformat() + 'Z'
    }

    try:
        db.table('teams').insert(team_data).execute()
    except Exception as e:
        return {'status': 'error', 'error': str(e), 'team_name': team_name}

    # Create alias
    alias_data = {
        'provider_id': MODULAR11_PROVIDER_ID,
        'provider_team_id': alias_id,
        'team_id_master': team_id_master,
        'match_method': 'import',
        'match_confidence': 1.0,
        'review_status': 'approved',
        'division': division,
        'created_at': datetime.utcnow().isoformat() + 'Z'
    }

    try:
        db.table('team_alias_map').insert(alias_data).execute()
    except Exception as e:
        return {'status': 'alias_error', 'error': str(e), 'team_name': team_name}

    return {
        'status': 'created',
        'team_name': team_name,
        'team_id': team_id_master,
        'alias_id': alias_id
    }


def main():
    parser = argparse.ArgumentParser(description='Create Modular11 teams and aliases from CSV')
    parser.add_argument('--csv-path', required=True, help='Path to Modular11 CSV file')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without executing')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')

    args = parser.parse_args()

    if not os.path.exists(args.csv_path):
        print(f"CSV file not found: {args.csv_path}")
        sys.exit(1)

    db = get_supabase()

    print("=" * 70)
    print("CREATE MODULAR11 TEAMS AND ALIASES FROM CSV")
    print("=" * 70)
    print(f"\nReading CSV: {args.csv_path}")

    # Read teams from CSV
    csv_teams = read_csv_teams(args.csv_path)
    print(f"Found {len(csv_teams)} unique team/age/division combinations")

    # Count by division
    hd_count = sum(1 for t in csv_teams.values() if t['division'] == 'HD')
    ad_count = sum(1 for t in csv_teams.values() if t['division'] == 'AD')
    print(f"   HD teams: {hd_count}")
    print(f"   AD teams: {ad_count}")

    # Process each team
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Processing teams...")

    stats = {
        'created': 0,
        'errors': 0
    }

    errors = []

    for (club_id, age_group, division), team_info in sorted(csv_teams.items()):
        result = create_team_and_alias(db, team_info, dry_run=args.dry_run)

        if result['status'] in ('created', 'would_create'):
            stats['created'] += 1
            if args.verbose:
                action = "Would create" if args.dry_run else "Created"
                print(f"  {action}: {result['team_name']} -> {result['alias_id']}")
        else:
            stats['errors'] += 1
            errors.append(result)
            print(f"  Error: {result.get('error', 'Unknown')[:80]}")

    # Print summary
    print(f"\n{'=' * 70}")
    print("SUMMARY")
    print(f"{'=' * 70}")
    print(f"Teams in CSV:     {len(csv_teams)}")
    print(f"{'Would create' if args.dry_run else 'Created'}:      {stats['created']}")
    print(f"Errors:           {stats['errors']}")

    if errors:
        print(f"\nErrors (first 10):")
        for err in errors[:10]:
            print(f"  - {err.get('team_name', 'Unknown')}: {err.get('error', 'Unknown')[:60]}")

    if args.dry_run:
        print(f"\nRun without --dry-run to create teams and aliases")
    else:
        print(f"\nTeams and aliases created. You can now import games.")


if __name__ == '__main__':
    main()
