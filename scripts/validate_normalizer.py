#!/usr/bin/env python3
"""
Validate team name normalizer against historical merges.
Replays every historical merge through the production dedup gate
(should_skip_pair) and reports false_skip rate as a baseline.
"""

import os
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv("C:/PitchRank/.env.local")
load_dotenv("C:/PitchRank/.env")

import truststore  # noqa: E402
truststore.inject_into_ssl()

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ for _team_distinction
from _team_distinction import should_skip_pair  # production masters-dedup gate  # noqa: E402


def replay_merge_verdict(dep, can):
    """Replay one historical merge through the production dedup gate.

    dep/can are team rows (dicts) with 'team_name' and 'club_name', or None.
    Returns:
      'no_data'    - a row is missing or has a blank team_name
      'allowed'    - gate would NOT skip the pair (a real merge stays reachable)
      'false_skip' - gate WOULD skip the pair (it would block this real merge)

    Uses require_age_token_match=True to mirror find_fuzzy_duplicate_teams.py
    (the path that produces masters merges).
    """
    if not dep or not can:
        return "no_data"
    dep_name = (dep.get("team_name") or "").strip()
    can_name = (can.get("team_name") or "").strip()
    if not dep_name or not can_name:
        return "no_data"
    club = (can.get("club_name") or dep.get("club_name") or "")
    skipped = should_skip_pair(dep_name, can_name, club_name=club, require_age_token_match=True)
    return "false_skip" if skipped else "allowed"


def safe_query(query_fn, retries=3, delay=2):
    """Execute query with retry logic."""
    for attempt in range(retries):
        try:
            return query_fn()
        except Exception as e:
            if attempt < retries - 1:
                print(f"    Query failed, retrying in {delay}s... ({e})")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                raise


def main():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not (url and key):
        print("Missing Supabase creds (need SUPABASE_URL + a service key)")
        return
    supabase = create_client(url, key)

    # Get all merges
    print("Fetching merge history...")
    all_merges = []
    start = 0
    while True:
        batch = safe_query(lambda s=start: supabase.table("team_merge_map").select("*").range(s, s + 999).execute())
        if not batch.data:
            break
        all_merges.extend(batch.data)
        if len(batch.data) < 1000:
            break
        start += 1000

    print(f"Total merges: {len(all_merges)}")

    # Pre-fetch ALL team data to avoid per-merge queries
    print("\nPre-fetching team data (this avoids rate limits)...")
    team_ids = set()
    for m in all_merges:
        team_ids.add(m["deprecated_team_id"])
        team_ids.add(m["canonical_team_id"])

    print(f"  Need {len(team_ids)} unique teams...")

    teams_cache = {}
    team_ids_list = list(team_ids)

    for i in range(0, len(team_ids_list), 50):
        batch_ids = team_ids_list[i : i + 50]
        if i % 1000 == 0:
            print(f"  Fetched {i}/{len(team_ids_list)} teams...")
        try:
            result = safe_query(
                lambda b=batch_ids: (
                    supabase.table("teams")
                    .select("team_id_master, team_name, club_name, state_code, gender, age_group")
                    .in_("team_id_master", b)
                    .execute()
                )
            )
            for row in (result.data or []):
                teams_cache[row["team_id_master"]] = row
        except Exception as e:
            print(f"    Failed to fetch batch at {i}: {e}")
        time.sleep(0.05)

    print(f"  Cached {len(teams_cache)} teams")

    verdicts = Counter()
    false_skips = []

    print("\nReplaying merges through the production dedup gate...")
    for i, merge in enumerate(all_merges):
        if i % 500 == 0:
            print(f"  Processing {i}/{len(all_merges)}...")
        dep = teams_cache.get(merge["deprecated_team_id"])
        can = teams_cache.get(merge["canonical_team_id"])
        verdict = replay_merge_verdict(dep, can)
        verdicts[verdict] += 1
        if verdict == "false_skip" and len(false_skips) < 40:
            false_skips.append((dep, can))

    total = len(all_merges)
    allowed = verdicts["allowed"]
    false_skip = verdicts["false_skip"]
    no_data = verdicts["no_data"]
    evaluable = total - no_data

    print("\n" + "=" * 60)
    print("MERGE-VERDICT BASELINE (production gate: should_skip_pair)")
    print("=" * 60)
    print(f"\nHistorical merges replayed: {total:,}")
    if evaluable:
        print(f"  allowed (gate keeps merge reachable): {allowed:,}  ({100*allowed/evaluable:.2f}% of evaluable)")
        print(f"  false_skip (gate would BLOCK this merge): {false_skip:,}  ({100*false_skip/evaluable:.2f}% of evaluable)")
    else:
        print("  (no evaluable rows)")
    print(f"  no_data (missing team rows): {no_data:,}")

    print("\n" + "-" * 60)
    print(f"SAMPLE FALSE-SKIPS (first {len(false_skips)})")
    print("-" * 60)
    for dep, can in false_skips:
        print(f"\n  deprecated: {dep.get('team_name')!r}  (club={dep.get('club_name')!r})")
        print(f"  canonical : {can.get('team_name')!r}  (club={can.get('club_name')!r})")


if __name__ == "__main__":
    main()
