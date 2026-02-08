#!/usr/bin/env python3
"""
Find and delete duplicate games that have different game_uids but are the same game.

Duplicates are identified by: (home_team_master_id, away_team_master_id, game_date, home_score, away_score)
Keeps the oldest record, deletes the rest.

Usage:
  python scripts/cleanup_dupe_games_by_composite.py              # Dry run
  python scripts/cleanup_dupe_games_by_composite.py --execute    # Apply
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

env_path = Path(__file__).parent.parent / '.env.local'
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv()

supabase_url = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    sys.exit(1)

supabase = create_client(supabase_url, supabase_key)


def paginated_fetch(table, select_fields, filters=None, page_size=1000):
    all_data = []
    offset = 0
    while True:
        query = supabase.table(table).select(select_fields)
        if filters:
            for col, val in filters:
                query = query.eq(col, val)
        result = query.range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_data.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_data


def main():
    dry_run = '--execute' not in sys.argv

    print("=" * 70)
    print("CLEANUP DUPLICATE GAMES BY COMPOSITE KEY")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 70)

    # Get modular11 provider
    provider_result = supabase.table('providers').select('id').eq('code', 'modular11').single().execute()
    provider_id = provider_result.data['id']
    print(f"\nModular11 provider_id: {provider_id}")

    # Fetch ALL modular11 games
    print("\nFetching all Modular11 games...")
    all_games = paginated_fetch(
        'games',
        'id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score, created_at',
        filters=[('provider_id', provider_id)]
    )
    print(f"Total games: {len(all_games)}")

    # Group by composite key
    games_by_key = defaultdict(list)
    for game in all_games:
        home = game.get('home_team_master_id', '')
        away = game.get('away_team_master_id', '')
        date = game.get('game_date', '')
        hs = game.get('home_score')
        as_ = game.get('away_score')
        
        # Normalize: sort team IDs so (A vs B) and (B vs A) aren't treated differently
        # Actually for home/away it matters, keep as-is
        key = (home, away, date, hs, as_)
        games_by_key[key].append(game)

    # Find duplicates
    dupe_groups = {k: v for k, v in games_by_key.items() if len(v) > 1}

    if not dupe_groups:
        print("\nNo duplicate games found!")
        return

    total_dupes = sum(len(g) - 1 for g in dupe_groups.values())
    print(f"\nFound {len(dupe_groups)} game groups with duplicates ({total_dupes} extra records)")

    # Collect IDs to delete
    ids_to_delete = []
    
    for i, (key, games) in enumerate(dupe_groups.items()):
        # Sort by created_at, keep oldest
        games_sorted = sorted(games, key=lambda g: g.get('created_at', '') or '')
        keep = games_sorted[0]
        delete = games_sorted[1:]

        if i < 15:
            home, away, date, hs, as_ = key
            print(f"\n  {i+1}. {date}: score {hs}-{as_} ({len(games)} copies)")
            print(f"     Keep:   {keep['game_uid'][:60]} (created {keep.get('created_at', '?')[:19]})")
            for d in delete:
                print(f"     Delete: {d['game_uid'][:60]} (created {d.get('created_at', '?')[:19]})")

        for d in delete:
            ids_to_delete.append(d['id'])

    if len(dupe_groups) > 15:
        print(f"\n  ... and {len(dupe_groups) - 15} more groups")

    print(f"\n  Total records to delete: {len(ids_to_delete)}")

    if not dry_run:
        print("\n  Deleting...")
        deleted = 0
        failed = 0
        batch_size = 50

        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i + batch_size]
            try:
                supabase.table('games').delete().in_('id', batch).execute()
                deleted += len(batch)
                if deleted % 200 == 0 or i + batch_size >= len(ids_to_delete):
                    print(f"    Deleted {deleted}/{len(ids_to_delete)}...")
            except Exception:
                for gid in batch:
                    try:
                        supabase.table('games').delete().eq('id', gid).execute()
                        deleted += 1
                    except Exception as e:
                        failed += 1
                        if failed <= 3:
                            print(f"    Failed: {e}")

        print(f"\n  Done: {deleted} deleted, {failed} failed")
    else:
        print(f"\n  Run with --execute to delete:")
        print(f"    python scripts/cleanup_dupe_games_by_composite.py --execute")

    print("=" * 70)


if __name__ == '__main__':
    main()
