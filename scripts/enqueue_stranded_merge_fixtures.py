#!/usr/bin/env python3
"""Re-enqueue surviving teams whose fixtures were stranded by a merge.

execute_team_merge never repoints game rows -- games are immutable and resolve to the
surviving team at read time. The scrape-enqueue RPCs, though, match games by the raw
team_id_master on the game row and then require teams.is_deprecated = false. After a merge
neither side satisfies both: the game still names the deprecated row, which is filtered out,
and the survivor is named by no game. So a merged team's unplayed fixtures silently stop
being enqueued for a score fill, and nothing else looks for them.

supabase/migrations/20260822000000_resolve_merges_in_scrape_enqueue_rpcs.sql closes that for
good. This script is the one-time repair for fixtures already stranded, and stays useful as
an operator tool after any manual merge.

It enqueues the SURVIVING team, whose team_alias_map row now carries the deprecated team's
provider_team_id, so scraping it returns the same fixtures with their scores.

Usage:
    python scripts/enqueue_stranded_merge_fixtures.py --since 2026-08-21              # dry run
    python scripts/enqueue_stranded_merge_fixtures.py --since 2026-08-21 --execute
    python scripts/enqueue_stranded_merge_fixtures.py --merged-by pitchrank-operator --execute
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

from supabase import create_client  # noqa: E402

REQUEST_TYPE = "missing_games"
PRIORITY = 2


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def merged_pairs(sb, since: str | None, merged_by: str | None):
    rows, off = [], 0
    while True:
        q = (sb.table("team_merge_audit")
             .select("deprecated_team_id,canonical_team_id,performed_at")
             .eq("action", "merge"))
        if since:
            q = q.gte("performed_at", f"{since}T00:00:00")
        if merged_by:
            q = q.eq("performed_by", merged_by)
        res = q.range(off, off + 999).execute()
        d = res.data or []
        rows.extend(d)
        if len(d) < 1000:
            break
        off += 1000
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=None, help="only merges performed on or after this date (YYYY-MM-DD)")
    ap.add_argument("--merged-by", default=None, help="only merges recorded by this actor")
    ap.add_argument("--execute", action="store_true", help="enqueue (default is a dry run)")
    ap.add_argument("--include-past", action="store_true",
                    help="also enqueue for fixtures already in the past (default: today onward only)")
    args = ap.parse_args()

    if not args.since and not args.merged_by:
        raise SystemExit("give --since and/or --merged-by so the scope is explicit")

    sb = get_client()
    pairs = merged_pairs(sb, args.since, args.merged_by)
    print(f"merges in scope: {len(pairs)}")
    if not pairs:
        return 0

    canonical_of = {p["deprecated_team_id"]: p["canonical_team_id"] for p in pairs}
    dep_ids = sorted(canonical_of)

    cutoff = date.today().isoformat()
    stranded = defaultdict(int)
    for i in range(0, len(dep_ids), 50):
        batch = dep_ids[i : i + 50]
        for side in ("home_team_master_id", "away_team_master_id"):
            off = 0
            while True:
                res = (sb.table("games")
                       .select(f"game_date,{side}")
                       .in_(side, batch)
                       .is_("home_score", "null")
                       .range(off, off + 999)
                       .execute())
                d = res.data or []
                for g in d:
                    if args.include_past or g["game_date"] >= cutoff:
                        stranded[canonical_of[g[side]]] += 1
                if len(d) < 1000:
                    break
                off += 1000

    print(f"surviving teams with stranded NULL-score fixtures: {len(stranded)}")
    print(f"stranded fixtures total: {sum(stranded.values())}")
    if not stranded:
        return 0

    ids = sorted(stranded)
    teams = {}
    for i in range(0, len(ids), 100):
        res = (sb.table("teams")
               .select("team_id_master,team_name,provider_id,provider_team_id,is_deprecated")
               .in_("team_id_master", ids[i : i + 100])
               .execute())
        for t in res.data or []:
            teams[t["team_id_master"]] = t

    ready, skipped = [], []
    for tid in ids:
        t = teams.get(tid)
        if not t or t["is_deprecated"] or not t.get("provider_team_id") or not t.get("provider_id"):
            skipped.append((tid, t))
            continue
        ready.append(t)

    print(f"enqueueable: {len(ready)}   skipped (deprecated or no provider id): {len(skipped)}")
    for t in ready[:15]:
        print(f"   {stranded[t['team_id_master']]:>3} fixtures  {t['team_name'][:52]!r}")
    if len(ready) > 15:
        print(f"   ... and {len(ready) - 15} more")

    if not args.execute:
        print("\nDRY RUN — nothing enqueued. Re-run with --execute.")
        return 0

    ok = fail = 0
    for t in ready:
        try:
            sb.rpc("enqueue_scrape_request", {
                "p_team_id_master": t["team_id_master"],
                "p_team_name": t["team_name"],
                "p_provider_id": t["provider_id"],
                "p_provider_team_id": t["provider_team_id"],
                "p_game_date": date.today().isoformat(),
                "p_request_type": REQUEST_TYPE,
                "p_priority": PRIORITY,
            }).execute()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            print(f"  FAILED {t['team_name'][:44]!r}: {str(exc)[:110]}")

    print(f"\nEnqueued {ok} teams at priority {PRIORITY}, {fail} failed.")
    print("process_missing_games drains the queue every 15 minutes, 40 teams per run.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
