#!/usr/bin/env python3
"""
Undo Alias Creation from CSV

This script deletes aliases that were created by create_aliases_from_csv.py
by finding aliases created recently with the specific pattern.

Usage:
    # Preview what will be deleted (dry run)
    python scripts/undo_aliases_from_csv.py --dry-run --minutes 10

    # Delete aliases created in the last 10 minutes
    python scripts/undo_aliases_from_csv.py --minutes 10
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

# Load environment variables
env_local = Path(__file__).parent.parent / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

MODULAR11_PROVIDER_ID = 'b376e2a4-4b81-47be-b2aa-a06ba0616110'


def get_supabase():
    """Get Supabase client"""
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)
    return create_client(url, key)


def main():
    parser = argparse.ArgumentParser(
        description='Undo alias creation from CSV script'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without deleting aliases'
    )
    parser.add_argument(
        '--minutes',
        type=int,
        default=10,
        help='Look for aliases created in the last N minutes (default: 10)'
    )
    parser.add_argument(
        '--csv-path',
        help='Optional: CSV file path to get exact aliases to delete'
    )
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt'
    )
    
    args = parser.parse_args()
    
    db = get_supabase()
    
    # Calculate cutoff time
    cutoff_time = datetime.utcnow() - timedelta(minutes=args.minutes)
    cutoff_iso = cutoff_time.isoformat() + 'Z'
    
    print(f"🔍 Looking for aliases created after {cutoff_iso}")
    print(f"   (within the last {args.minutes} minutes)\n")
    
    # Find aliases created recently with the pattern from create_aliases_from_csv.py
    # Pattern: provider_id = MODULAR11_PROVIDER_ID, match_method = 'manual'
    result = db.table('team_alias_map').select('*').eq(
        'provider_id', MODULAR11_PROVIDER_ID
    ).eq('match_method', 'manual').gte(
        'created_at', cutoff_iso
    ).execute()
    
    aliases = result.data if result.data else []
    
    if not aliases:
        print("✅ No aliases found to delete")
        return
    
    print(f"Found {len(aliases)} aliases created recently:")
    
    # Group by pattern to show summary
    patterns = {}
    for alias in aliases:
        provider_team_id = alias.get('provider_team_id', '')
        # Check if it matches the pattern {id}_{age}_{division}
        if '_' in provider_team_id and len(provider_team_id.split('_')) == 3:
            patterns[provider_team_id] = patterns.get(provider_team_id, 0) + 1
    
    print(f"  - {len(patterns)} unique alias patterns")
    print(f"  - Sample aliases:")
    for i, (alias_id, count) in enumerate(list(patterns.items())[:10]):
        print(f"    {alias_id}")
    if len(patterns) > 10:
        print(f"    ... and {len(patterns) - 10} more")
    
    if args.dry_run:
        print(f"\n🔍 DRY RUN: Would delete {len(aliases)} aliases")
        print("Run without --dry-run to actually delete them")
        return
    
    # Ask for confirmation (unless --yes flag is provided)
    if not args.yes:
        print(f"\n⚠️  WARNING: This will delete {len(aliases)} aliases!")
        response = input("Type 'yes' to confirm deletion: ").strip().lower()
        
        if response != 'yes':
            print("❌ Cancelled")
            return
    else:
        print(f"\n⚠️  Auto-confirming deletion (--yes flag provided)...")
    
    # Delete aliases
    print(f"\n🗑️  Deleting {len(aliases)} aliases...")
    deleted = 0
    errors = 0
    
    for alias in aliases:
        alias_id = alias.get('id')
        provider_team_id = alias.get('provider_team_id', 'unknown')
        
        try:
            db.table('team_alias_map').delete().eq('id', alias_id).execute()
            deleted += 1
        except Exception as e:
            print(f"  ❌ Error deleting {provider_team_id}: {e}")
            errors += 1
    
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Deleted: {deleted}")
    if errors:
        print(f"Errors: {errors}")
    print(f"\n✅ Undo complete")


if __name__ == '__main__':
    main()

