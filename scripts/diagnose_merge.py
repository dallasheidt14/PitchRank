#!/usr/bin/env python3
"""
Diagnostic script to trace merge resolution for a specific team pair.

Usage:
    python scripts/diagnose_merge.py --canonical 691eb36d-95b2-4a08-bd59-13c1b0e830bb

This script traces the exact pipeline used in fetch_games_for_rankings
to identify where deprecated team games are being lost.
"""
import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
import os
import logging

from src.utils.merge_resolver import MergeResolver
from src.rankings.data_adapter import age_group_to_age

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()


def diagnose_merge(canonical_team_id: str):
    """Trace the merge resolution pipeline for a specific canonical team."""
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return

    supabase = create_client(supabase_url, supabase_key)

    print("=" * 80)
    print(f"MERGE RESOLUTION DIAGNOSTIC for {canonical_team_id}")
    print("=" * 80)

    # Step 1: Load merge map
    print("\n--- Step 1: Load merge map ---")
    resolver = MergeResolver(supabase)
    resolver.load_merge_map()
    print(f"Merge map loaded: {resolver.merge_count} entries")
    print(f"Has merges: {resolver.has_merges}")
    print(f"Version: {resolver.version}")

    if not resolver.has_merges:
        print("ERROR: No merges found! Cannot proceed.")
        return

    # Find deprecated teams that map to this canonical
    deprecated_ids = []
    for dep_id in resolver.get_deprecated_teams():
        if resolver.resolve(dep_id) == canonical_team_id:
            deprecated_ids.append(dep_id)
            print(f"  Found deprecated team: {dep_id} → {canonical_team_id}")

    if not deprecated_ids:
        print(f"No deprecated teams map to canonical {canonical_team_id}")
        return

    # Step 2: Check team metadata
    print("\n--- Step 2: Team metadata ---")
    for team_id in [canonical_team_id] + deprecated_ids:
        result = supabase.table('teams').select(
            'team_id_master, age_group, gender, is_deprecated'
        ).eq('team_id_master', team_id).execute()
        if result.data:
            row = result.data[0]
            age = age_group_to_age(row.get('age_group', ''))
            print(f"  {team_id[:12]}... age_group={row['age_group']}, "
                  f"normalized_age={age}, gender={row['gender']}, "
                  f"is_deprecated={row['is_deprecated']}")
        else:
            print(f"  {team_id[:12]}... NOT FOUND in teams table!")

    # Step 3: Count games in database
    print("\n--- Step 3: Games in database (365-day window) ---")
    cutoff = (pd.Timestamp.utcnow() - pd.Timedelta(days=365)).strftime('%Y-%m-%d')
    today_str = pd.Timestamp.utcnow().strftime('%Y-%m-%d')

    for team_id in [canonical_team_id] + deprecated_ids:
        # Count as home
        home_result = supabase.table('games').select(
            'id', count='exact'
        ).eq('home_team_master_id', team_id).gte(
            'game_date', cutoff
        ).lte('game_date', today_str).not_.is_(
            'home_score', 'null'
        ).not_.is_(
            'away_score', 'null'
        ).eq('is_excluded', False).execute()

        # Count as away
        away_result = supabase.table('games').select(
            'id', count='exact'
        ).eq('away_team_master_id', team_id).gte(
            'game_date', cutoff
        ).lte('game_date', today_str).not_.is_(
            'home_score', 'null'
        ).not_.is_(
            'away_score', 'null'
        ).eq('is_excluded', False).execute()

        home_count = home_result.count if home_result.count is not None else len(home_result.data)
        away_count = away_result.count if away_result.count is not None else len(away_result.data)
        label = "CANONICAL" if team_id == canonical_team_id else "DEPRECATED"
        print(f"  {label} {team_id[:12]}... home={home_count}, away={away_count}, total={home_count + away_count}")

    # Step 4: Simulate merge resolution on a small sample
    print("\n--- Step 4: Simulate merge resolution ---")

    # Fetch a few games for the deprecated team
    for dep_id in deprecated_ids:
        sample = supabase.table('games').select(
            'id, home_team_master_id, away_team_master_id'
        ).or_(
            f'home_team_master_id.eq.{dep_id},away_team_master_id.eq.{dep_id}'
        ).gte('game_date', cutoff).lte('game_date', today_str).not_.is_(
            'home_score', 'null'
        ).not_.is_('away_score', 'null').eq(
            'is_excluded', False
        ).limit(3).execute()

        if sample.data:
            print(f"\n  Sample games for deprecated {dep_id[:12]}...:")
            for game in sample.data:
                home_id = str(game['home_team_master_id'])
                away_id = str(game['away_team_master_id'])
                resolved_home = resolver.resolve(home_id)
                resolved_away = resolver.resolve(away_id)
                print(f"    Game {game['id'][:12]}...")
                print(f"      home: {home_id[:12]}... → {resolved_home[:12]}... {'RESOLVED' if home_id != resolved_home else '(unchanged)'}")
                print(f"      away: {away_id[:12]}... → {resolved_away[:12]}... {'RESOLVED' if away_id != resolved_away else '(unchanged)'}")

                # Check if the game's team IDs match the merge map keys exactly
                if home_id == dep_id:
                    in_map = home_id in resolver._merge_map
                    print(f"      home_id in merge_map: {in_map}")
                    if not in_map:
                        print(f"      MISMATCH! home_id repr: {repr(home_id)}")
                        # Check for close matches
                        for key in resolver._merge_map:
                            if dep_id[:8] in key:
                                print(f"      Close match in map: {repr(key)}")
                if away_id == dep_id:
                    in_map = away_id in resolver._merge_map
                    print(f"      away_id in merge_map: {in_map}")
                    if not in_map:
                        print(f"      MISMATCH! away_id repr: {repr(away_id)}")
                        for key in resolver._merge_map:
                            if dep_id[:8] in key:
                                print(f"      Close match in map: {repr(key)}")
        else:
            print(f"  No games found for deprecated {dep_id[:12]}...")

    # Step 5: Test resolve_series with actual data
    print("\n--- Step 5: Test resolve_series ---")
    test_ids = [canonical_team_id] + deprecated_ids
    test_series = pd.Series(test_ids)
    resolved = resolver.resolve_series(test_series)
    for orig, res in zip(test_ids, resolved):
        status = "RESOLVED" if orig != res else "unchanged"
        print(f"  {orig[:12]}... → {res[:12]}... ({status})")

    # Step 6: Check rankings_full current values
    print("\n--- Step 6: Current rankings_full entries ---")
    for team_id in [canonical_team_id] + deprecated_ids:
        result = supabase.table('rankings_full').select(
            'team_id, games_played, last_calculated'
        ).eq('team_id', team_id).execute()
        if result.data:
            row = result.data[0]
            print(f"  {team_id[:12]}... games_played={row['games_played']}, "
                  f"last_calculated={row['last_calculated']}")
        else:
            print(f"  {team_id[:12]}... NO ENTRY in rankings_full")

    print("\n" + "=" * 80)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Diagnose merge resolution')
    parser.add_argument('--canonical', required=True, help='Canonical team ID')
    args = parser.parse_args()
    diagnose_merge(args.canonical)
