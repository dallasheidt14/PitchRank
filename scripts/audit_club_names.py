#!/usr/bin/env python3
"""
Club Name Audit Script

Pulls all unique club names from the database, runs them through the normalizer,
and generates a report of clubs that need review.

Usage:
    # Run audit and print summary
    python scripts/audit_club_names.py

    # Export full report to CSV
    python scripts/audit_club_names.py --export clubs_audit.csv

    # Show only problematic fuzzy matches (85%+ confidence but not exact)
    python scripts/audit_club_names.py --risky-only

    # Show only clubs not in canonical registry
    python scripts/audit_club_names.py --unknown-only
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

from src.utils.club_normalizer import (
    normalize_to_club,
    get_matches_needing_review,
    get_confident_matches,
    ClubNormResult,
)


def get_supabase_client():
    """Initialize and return Supabase client."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
        sys.exit(1)

    return create_client(supabase_url, supabase_key)


def fetch_unique_club_names(supabase) -> list:
    """Fetch all unique club names from the teams table."""
    print("Fetching club names from database...")

    # Get club_name from teams table
    response = supabase.table('teams').select('club_name').not_.is_('club_name', 'null').execute()

    clubs = set()
    for row in response.data:
        if row.get('club_name'):
            clubs.add(row['club_name'].strip())

    print(f"Found {len(clubs)} unique club names")
    return sorted(clubs)


def run_audit(clubs: list) -> dict:
    """Run the normalizer against all clubs and categorize results."""
    results = {
        'confident': [],      # Exact canonical matches (100%)
        'fuzzy_correct': [],  # Fuzzy matches 85%+ (need verification)
        'unknown': [],        # Not in registry (80% baseline)
        'all': []
    }

    for club in clubs:
        result = normalize_to_club(club)
        results['all'].append(result)

        if result.matched_canonical and result.confidence == 1.0:
            results['confident'].append(result)
        elif result.matched_canonical and result.confidence >= 0.85:
            results['fuzzy_correct'].append(result)
        else:
            results['unknown'].append(result)

    return results


def print_summary(results: dict):
    """Print a summary of the audit results."""
    total = len(results['all'])
    confident = len(results['confident'])
    fuzzy = len(results['fuzzy_correct'])
    unknown = len(results['unknown'])

    print("\n" + "=" * 60)
    print("CLUB NAME AUDIT SUMMARY")
    print("=" * 60)
    print(f"Total unique clubs:     {total}")
    print(f"✓ Confident matches:    {confident} ({confident/total*100:.1f}%)")
    print(f"⚠ Fuzzy matches:        {fuzzy} ({fuzzy/total*100:.1f}%) - VERIFY THESE")
    print(f"? Unknown clubs:        {unknown} ({unknown/total*100:.1f}%)")
    print("=" * 60)


def print_risky_matches(results: dict):
    """Print fuzzy matches that might be wrong."""
    if not results['fuzzy_correct']:
        print("\nNo risky fuzzy matches found!")
        return

    print("\n" + "=" * 60)
    print("⚠️  RISKY FUZZY MATCHES (verify these!)")
    print("=" * 60)
    print(f"{'Original':<40} {'Matched To':<25} {'Conf':<6}")
    print("-" * 60)

    # Sort by confidence (lowest first = most risky)
    for r in sorted(results['fuzzy_correct'], key=lambda x: x.confidence):
        print(f"{r.original:<40} {r.club_norm:<25} {r.confidence:.0%}")


def print_unknown_clubs(results: dict, limit: int = 50):
    """Print clubs not in the canonical registry."""
    if not results['unknown']:
        print("\nNo unknown clubs found!")
        return

    print("\n" + "=" * 60)
    print(f"? UNKNOWN CLUBS (not in registry) - showing first {limit}")
    print("=" * 60)
    print(f"{'Original':<40} {'Normalized':<30}")
    print("-" * 60)

    for r in results['unknown'][:limit]:
        print(f"{r.original:<40} {r.club_norm:<30}")

    if len(results['unknown']) > limit:
        print(f"\n... and {len(results['unknown']) - limit} more")


def export_to_csv(results: dict, filename: str):
    """Export all results to CSV for review in Excel."""
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'original',
            'normalized',
            'club_id',
            'confidence',
            'status',
            'action'
        ])

        for r in results['all']:
            if r.matched_canonical and r.confidence == 1.0:
                status = 'CONFIDENT'
            elif r.matched_canonical:
                status = 'FUZZY_MATCH'
            else:
                status = 'UNKNOWN'

            writer.writerow([
                r.original,
                r.club_norm,
                r.club_id,
                f"{r.confidence:.0%}",
                status,
                ''  # Empty action column for user to fill in
            ])

    print(f"\nExported {len(results['all'])} clubs to {filename}")
    print("Open in Excel and fill in the 'action' column:")
    print("  - SKIP: Normalized form is correct")
    print("  - ADD:CLUB NAME: Add as new canonical club")
    print("  - MERGE:CLUB NAME: Should map to existing club")


def main():
    parser = argparse.ArgumentParser(description='Audit club names in database')
    parser.add_argument('--export', type=str, help='Export results to CSV file')
    parser.add_argument('--risky-only', action='store_true', help='Show only risky fuzzy matches')
    parser.add_argument('--unknown-only', action='store_true', help='Show only unknown clubs')
    args = parser.parse_args()

    # Connect to database
    supabase = get_supabase_client()

    # Fetch club names
    clubs = fetch_unique_club_names(supabase)

    if not clubs:
        print("No club names found in database!")
        return

    # Run audit
    print("Running normalizer against all clubs...")
    results = run_audit(clubs)

    # Print summary
    print_summary(results)

    # Print details based on flags
    if args.risky_only:
        print_risky_matches(results)
    elif args.unknown_only:
        print_unknown_clubs(results, limit=100)
    else:
        print_risky_matches(results)
        print_unknown_clubs(results, limit=20)

    # Export if requested
    if args.export:
        export_to_csv(results, args.export)


if __name__ == '__main__':
    main()
