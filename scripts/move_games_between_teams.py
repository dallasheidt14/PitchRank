#!/usr/bin/env python3
"""
Move specific games from one team to another.

Finds games by date and competition, then reassigns the team ID.
Handles immutable game flags automatically (unlock -> update -> relock).

Usage:
    # Dry run first
    python scripts/move_games_between_teams.py --dry-run

    # Execute the move
    python scripts/move_games_between_teams.py
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

env_local = Path(__file__).parent.parent / '.env.local'
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv(Path(__file__).parent.parent / '.env')

import httpx

SUPABASE_URL = os.getenv('SUPABASE_URL') or os.getenv('NEXT_PUBLIC_SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
    'Prefer': 'return=representation',
}

REST_URL = f"{SUPABASE_URL}/rest/v1"

FROM_TEAM = '49609b32-0248-4bc9-bf9a-3671142b9c3d'
TO_TEAM = 'c87030ed-4448-4b2b-b8e5-81029d865d20'


def query(table, params):
    """GET from PostgREST."""
    resp = httpx.get(f"{REST_URL}/{table}", headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def update(table, match_params, data):
    """PATCH (update) via PostgREST."""
    resp = httpx.patch(
        f"{REST_URL}/{table}",
        headers=HEADERS,
        params=match_params,
        json=data,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def delete(table, match_params):
    """DELETE via PostgREST."""
    resp = httpx.delete(
        f"{REST_URL}/{table}",
        headers=HEADERS,
        params=match_params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp


def get_team_info(team_id):
    rows = query('teams', {
        'select': 'team_name,age_group,gender',
        'team_id_master': f'eq.{team_id}',
    })
    return rows[0] if rows else None


def check_merge_map():
    """Check for team_merge_map entries linking FROM_TEAM and TO_TEAM."""
    entries = []

    # Check if FROM_TEAM is deprecated → TO_TEAM
    rows = query('team_merge_map', {
        'select': 'id,deprecated_team_id,canonical_team_id',
        'deprecated_team_id': f'eq.{FROM_TEAM}',
        'canonical_team_id': f'eq.{TO_TEAM}',
    })
    entries.extend(rows)

    # Check if TO_TEAM is deprecated → FROM_TEAM
    rows = query('team_merge_map', {
        'select': 'id,deprecated_team_id,canonical_team_id',
        'deprecated_team_id': f'eq.{TO_TEAM}',
        'canonical_team_id': f'eq.{FROM_TEAM}',
    })
    entries.extend(rows)

    return entries


def remove_merge_entries(entries, dry_run=True):
    """Remove team_merge_map entries that link FROM and TO teams."""
    removed = 0
    for entry in entries:
        entry_id = entry['id']
        dep = entry['deprecated_team_id'][:8]
        can = entry['canonical_team_id'][:8]
        print(f"  Merge entry: {dep}... → {can}... (id: {entry_id})")
        if not dry_run:
            delete('team_merge_map', {'id': f'eq.{entry_id}'})
            removed += 1
    return removed


def find_target_games():
    """Find the Playmaker Sports Tournaments games on 2026-02-28 and 2026-03-01."""
    games_to_move = []

    # Home games
    home = query('games', {
        'select': 'id,game_date,competition,home_score,away_score,is_immutable',
        'home_team_master_id': f'eq.{FROM_TEAM}',
        'competition': 'ilike.*Playmaker*',
        'game_date': 'in.(2026-02-28,2026-03-01)',
    })
    for g in home:
        games_to_move.append({
            'id': g['id'],
            'position': 'home',
            'field': 'home_team_master_id',
            'game_date': g['game_date'],
            'competition': g['competition'],
            'score': f"{g['home_score']}-{g['away_score']}",
            'is_immutable': g['is_immutable'],
        })

    # Away games
    away = query('games', {
        'select': 'id,game_date,competition,home_score,away_score,is_immutable',
        'away_team_master_id': f'eq.{FROM_TEAM}',
        'competition': 'ilike.*Playmaker*',
        'game_date': 'in.(2026-02-28,2026-03-01)',
    })
    for g in away:
        games_to_move.append({
            'id': g['id'],
            'position': 'away',
            'field': 'away_team_master_id',
            'game_date': g['game_date'],
            'competition': g['competition'],
            'score': f"{g['home_score']}-{g['away_score']}",
            'is_immutable': g['is_immutable'],
        })

    games_to_move.sort(key=lambda x: x['game_date'] or '')
    return games_to_move


def move_game(game, dry_run=True):
    """Unlock, reassign, relock a single game."""
    game_id = game['id']
    field = game['field']
    was_immutable = game['is_immutable']

    if dry_run:
        return True

    try:
        if was_immutable:
            update('games', {'id': f'eq.{game_id}'}, {'is_immutable': False})

        update('games', {'id': f'eq.{game_id}'}, {field: TO_TEAM})

        if was_immutable:
            update('games', {'id': f'eq.{game_id}'}, {'is_immutable': True})

        return True
    except Exception as e:
        print(f"  Error moving game {game_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Move Playmaker games between teams')
    parser.add_argument('--dry-run', action='store_true', help='Preview without changes')
    args = parser.parse_args()

    from_info = get_team_info(FROM_TEAM)
    to_info = get_team_info(TO_TEAM)

    if not from_info:
        print(f"Source team not found: {FROM_TEAM}")
        sys.exit(1)
    if not to_info:
        print(f"Target team not found: {TO_TEAM}")
        sys.exit(1)

    print("=" * 65)
    print("MOVE GAMES BETWEEN TEAMS")
    print("=" * 65)
    print(f"\nFROM: {from_info['team_name']} ({FROM_TEAM[:8]}...)")
    print(f"TO:   {to_info['team_name']} ({TO_TEAM[:8]}...)")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    # Check for merge map entries that would make the move invisible on the frontend
    # The frontend resolves team IDs through team_merge_map, so if these teams are
    # linked, games show on BOTH teams regardless of which team ID is on the record.
    merge_entries = check_merge_map()
    if merge_entries:
        print(f"\n⚠  Found {len(merge_entries)} team_merge_map entries linking these teams:")
        for entry in merge_entries:
            dep = entry['deprecated_team_id'][:8]
            can = entry['canonical_team_id'][:8]
            print(f"    {dep}... → {can}...")
        print("  These MUST be removed or the frontend will still show games on both teams.")
        print("  (The frontend resolves merged team IDs and queries games for ALL linked IDs)")
    else:
        print("\n✓  No team_merge_map entries linking these teams.")

    games = find_target_games()

    if not games:
        print("\nNo matching games found for Playmaker Sports Tournaments "
              "on 2026-02-28 / 2026-03-01.")
        if not merge_entries:
            sys.exit(1)
        # Still proceed to remove merge entries even if games already moved
        print("  (Games may have already been moved in a prior run.)")

    if games:
        print(f"\nFound {len(games)} Playmaker games to move:")
        print("-" * 65)
        for g in games:
            lock = "locked" if g['is_immutable'] else "unlocked"
            print(f"  [{lock}] {g['game_date']} | {g['position']:4} | "
                  f"{g['score']:5} | {g['competition']}")
        print("-" * 65)

        if len(games) != 3:
            print(f"\nExpected 3 games but found {len(games)}. Please verify.")

    moved = 0
    errors = 0
    if games:
        for g in games:
            ok = move_game(g, dry_run=args.dry_run)
            if ok:
                moved += 1
            else:
                errors += 1

    # Remove merge map entries between source and target teams
    merge_removed = 0
    if merge_entries:
        if args.dry_run:
            print(f"\n  Would remove {len(merge_entries)} merge map entries")
        else:
            print(f"\nRemoving {len(merge_entries)} merge map entries...")
            merge_removed = remove_merge_entries(merge_entries, dry_run=False)
            print(f"  Removed {merge_removed} merge map entries")

    print("\n" + "=" * 65)
    print("SUMMARY")
    print("=" * 65)
    if args.dry_run:
        if games:
            print(f"  Would move: {len(games)} games")
        if merge_entries:
            print(f"  Would remove: {len(merge_entries)} merge map entries")
        print(f"\n  Run without --dry-run to execute")
    else:
        if games:
            print(f"  Moved: {moved} games")
        if merge_entries:
            print(f"  Merge entries removed: {merge_removed}")
        if errors:
            print(f"  Errors: {errors}")


if __name__ == '__main__':
    main()
