#!/usr/bin/env python3
"""
Migrate Modular11 Aliases to Division-Suffixed Format

This script finds all existing Modular11 aliases that don't have the _HD/_AD
suffix and creates properly suffixed versions based on the team's division.

The old aliases are NOT deleted - they serve as fallbacks. This script only
creates the new division-suffixed aliases if they don't already exist.

Usage:
    # Dry run - show what would change
    python scripts/migrate_modular11_aliases.py --dry-run

    # Actually create the new aliases
    python scripts/migrate_modular11_aliases.py

    # Only migrate for a specific age group
    python scripts/migrate_modular11_aliases.py --age-group u16
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Modular11 provider UUID
MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'


def get_supabase():
    """Get Supabase client"""
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def detect_division_from_team_name(team_name: str) -> str:
    """
    Detect HD/AD division from team name.

    Returns 'HD' or 'AD' based on team name suffix, or 'HD' as default
    (since original teams without suffix are typically HD).
    """
    if not team_name:
        return 'HD'  # Default to HD

    name_upper = team_name.upper().strip()
    if name_upper.endswith(' AD') or ' AD ' in name_upper:
        return 'AD'
    elif name_upper.endswith(' HD') or ' HD ' in name_upper:
        return 'HD'
    else:
        # No explicit division in name - assume HD (original tier)
        return 'HD'


def find_aliases_needing_migration(db, age_group: str = None):
    """
    Find all Modular11 aliases that don't have _HD/_AD suffix.

    Returns list of aliases with their team info.
    """
    # Get all Modular11 aliases
    query = db.table('team_alias_map').select(
        'id, provider_team_id, team_id_master, division, match_method, match_confidence'
    ).eq('provider_id', MODULAR11_PROVIDER_ID)

    result = query.execute()

    aliases_to_migrate = []

    for alias in (result.data or []):
        provider_team_id = alias['provider_team_id']

        # Skip if already has _HD or _AD suffix
        if provider_team_id.endswith('_HD') or provider_team_id.endswith('_AD'):
            continue

        # Get team info
        team_result = db.table('teams').select(
            'team_name, age_group, gender'
        ).eq('team_id_master', alias['team_id_master']).single().execute()

        if not team_result.data:
            continue

        team_info = team_result.data

        # Filter by age group if specified
        if age_group and team_info['age_group'].lower() != age_group.lower():
            continue

        # Detect division from team name
        detected_division = detect_division_from_team_name(team_info['team_name'])

        # Check if division-suffixed alias already exists
        new_provider_team_id = f"{provider_team_id}_{detected_division}"
        existing = db.table('team_alias_map').select('id').eq(
            'provider_id', MODULAR11_PROVIDER_ID
        ).eq('provider_team_id', new_provider_team_id).execute()

        if existing.data:
            # Already has division-suffixed alias
            continue

        aliases_to_migrate.append({
            'old_alias_id': alias['id'],
            'old_provider_team_id': provider_team_id,
            'new_provider_team_id': new_provider_team_id,
            'team_id_master': alias['team_id_master'],
            'team_name': team_info['team_name'],
            'age_group': team_info['age_group'],
            'gender': team_info['gender'],
            'detected_division': detected_division,
            'stored_division': alias.get('division'),
            'match_method': alias['match_method'],
            'match_confidence': alias['match_confidence']
        })

    return aliases_to_migrate


def create_division_suffixed_aliases(db, aliases: list, dry_run: bool = True):
    """
    Create new division-suffixed aliases for the given list.

    Does NOT delete the old aliases - they serve as fallbacks.
    """
    if dry_run:
        print(f"\n🔍 DRY RUN - Would create {len(aliases)} new aliases:\n")
        for alias in aliases:
            print(f"  {alias['old_provider_team_id']:10} → {alias['new_provider_team_id']:15} "
                  f"| {alias['team_name'][:40]} ({alias['age_group']}, {alias['detected_division']})")
        return

    print(f"\n🔄 Creating {len(aliases)} new division-suffixed aliases...\n")

    success = 0
    errors = 0

    for alias in aliases:
        try:
            alias_data = {
                'provider_id': MODULAR11_PROVIDER_ID,
                'provider_team_id': alias['new_provider_team_id'],
                'team_id_master': alias['team_id_master'],
                'match_method': 'migration',  # Mark as migrated
                'match_confidence': alias['match_confidence'],
                'review_status': 'approved',
                'division': alias['detected_division'],
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }

            db.table('team_alias_map').insert(alias_data).execute()

            print(f"  ✅ {alias['old_provider_team_id']} → {alias['new_provider_team_id']} "
                  f"({alias['team_name'][:30]})")
            success += 1

        except Exception as e:
            print(f"  ❌ Error creating {alias['new_provider_team_id']}: {e}")
            errors += 1

    print(f"\n✅ Created {success} aliases")
    if errors:
        print(f"❌ {errors} errors occurred")


def show_summary(aliases: list):
    """Show summary of aliases to migrate by age group and division."""
    by_age = {}
    by_division = {'HD': 0, 'AD': 0}

    for alias in aliases:
        age = alias['age_group']
        div = alias['detected_division']

        if age not in by_age:
            by_age[age] = {'HD': 0, 'AD': 0}
        by_age[age][div] += 1
        by_division[div] += 1

    print("\n📊 MIGRATION SUMMARY")
    print("=" * 50)
    print(f"Total aliases needing migration: {len(aliases)}")
    print(f"  HD teams: {by_division['HD']}")
    print(f"  AD teams: {by_division['AD']}")
    print()
    print("By Age Group:")
    for age in sorted(by_age.keys()):
        stats = by_age[age]
        print(f"  {age.upper()}: {stats['HD']} HD, {stats['AD']} AD")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Modular11 aliases to division-suffixed format'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Show what would change without making changes'
    )
    parser.add_argument(
        '--age-group', type=str,
        help='Only migrate aliases for a specific age group (e.g., u16)'
    )

    args = parser.parse_args()

    db = get_supabase()

    print("🔍 Finding Modular11 aliases needing migration...")
    aliases = find_aliases_needing_migration(db, args.age_group)

    if not aliases:
        print("\n✅ No aliases need migration! All Modular11 aliases already have division suffixes.")
        return

    show_summary(aliases)

    if args.dry_run:
        create_division_suffixed_aliases(db, aliases, dry_run=True)
        print("\n💡 To actually create these aliases, run without --dry-run")
    else:
        confirm = input(f"\n⚠️  Create {len(aliases)} new aliases? (yes/no): ")
        if confirm.lower() == 'yes':
            create_division_suffixed_aliases(db, aliases, dry_run=False)
        else:
            print("Cancelled.")


if __name__ == '__main__':
    main()
