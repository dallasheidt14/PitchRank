#!/usr/bin/env python3
"""Maintenance script to ensure GotSport aliases with provider_team_id use direct_id match_method

GotSport teams exist in the teams table with provider_team_id, but many aliases
in team_alias_map use match_method='fuzzy_auto' instead of 'direct_id'.
This causes the import pipeline to skip Tier 1 (direct_id) matching and fall
through to slower/less reliable fuzzy matching.

This script upgrades those aliases to direct_id with confidence 1.0.

Run this before game imports (added to scrape-games.yml workflow).

Usage:
    python scripts/maintain_gotsport_direct_id_aliases.py [--dry-run]
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from supabase import create_client
import os
from dotenv import load_dotenv
from collections import Counter

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

supabase = create_client(
    os.getenv('SUPABASE_URL'),
    os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')
)


def get_gotsport_provider_id() -> str:
    """Look up GotSport provider UUID from providers table"""
    result = supabase.table('providers').select('id').eq('code', 'gotsport').execute()
    if not result.data:
        raise ValueError("GotSport provider not found in providers table")
    return result.data[0]['id']


def main(dry_run: bool = False):
    """Maintain GotSport direct_id aliases"""
    print("=" * 80)
    print("GotSport Direct ID Alias Maintenance")
    print("=" * 80)

    if dry_run:
        print("\n🔍 DRY RUN MODE - No changes will be made\n")

    gotsport_provider_id = get_gotsport_provider_id()
    print(f"GotSport provider_id: {gotsport_provider_id}")

    # Find all approved aliases that have provider_team_id but aren't using direct_id
    print("Finding aliases to update...")

    all_aliases = []
    page_size = 1000
    offset = 0

    while True:
        result = supabase.table('team_alias_map').select(
            'id,provider_team_id,match_method,review_status'
        ).eq('provider_id', gotsport_provider_id).eq(
            'review_status', 'approved'
        ).not_.is_('provider_team_id', 'null').range(
            offset, offset + page_size - 1
        ).execute()

        if not result.data:
            break
        all_aliases.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    print(f"Total approved aliases with provider_team_id: {len(all_aliases)}")

    # Filter to those that should be direct_id but aren't
    aliases_to_fix = [
        r for r in all_aliases
        if r['match_method'] != 'direct_id' and r.get('provider_team_id')
    ]

    print(f"Found {len(aliases_to_fix)} aliases that should use direct_id")

    if not aliases_to_fix:
        print("\n✅ All GotSport aliases with provider_team_id already use direct_id!")
        return

    # Show breakdown
    current_methods = Counter(r['match_method'] for r in aliases_to_fix)
    print("\nCurrent match_method breakdown (to be upgraded):")
    for method, count in sorted(current_methods.items()):
        print(f"  {method:20s}: {count:4d}")

    if dry_run:
        print(f"\n🔍 Would update {len(aliases_to_fix)} aliases to direct_id")
        return

    # Update aliases
    print(f"\nUpdating {len(aliases_to_fix)} aliases...")
    updated_count = 0
    error_count = 0

    for alias in aliases_to_fix:
        try:
            supabase.table('team_alias_map').update({
                'match_method': 'direct_id',
                'match_confidence': 1.0
            }).eq('id', alias['id']).execute()

            updated_count += 1

            if updated_count % 100 == 0:
                print(f"  Updated {updated_count}/{len(aliases_to_fix)}...")

        except Exception as e:
            error_str = str(e).lower()
            if 'unique' not in error_str and 'duplicate' not in error_str:
                print(f"  Error updating alias {alias['id']}: {e}")
                error_count += 1

    print(f"\n✅ Updated {updated_count} aliases to direct_id")
    if error_count > 0:
        print(f"⚠️  {error_count} errors encountered")

    # Verify results
    print("\nVerifying updates...")
    verify_aliases = []
    offset = 0

    while True:
        verify_result = supabase.table('team_alias_map').select(
            'match_method'
        ).eq('provider_id', gotsport_provider_id).eq(
            'review_status', 'approved'
        ).not_.is_('provider_team_id', 'null').range(
            offset, offset + page_size - 1
        ).execute()

        if not verify_result.data:
            break
        verify_aliases.extend(verify_result.data)
        if len(verify_result.data) < page_size:
            break
        offset += page_size

    final_methods = Counter(r['match_method'] for r in verify_aliases)
    print("\nFinal match_method breakdown:")
    for method, count in sorted(final_methods.items()):
        print(f"  {method:20s}: {count:4d}")

    direct_id_count = final_methods.get('direct_id', 0)
    total_count = len(verify_aliases)
    if total_count > 0:
        print(f"\n✅ {direct_id_count}/{total_count} ({direct_id_count/total_count*100:.1f}%) aliases now use direct_id")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Maintain GotSport direct_id aliases')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    args = parser.parse_args()

    main(dry_run=args.dry_run)
