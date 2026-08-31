#!/usr/bin/env python3
"""Exclude the redundant copy of a fixture that got recorded twice.

Nothing downstream removes such a copy. src/rankings/data_adapter.py dedupes with
drop_duplicates(subset=["id"]) -- the game row's own id -- so two distinct rows describing
one real match both feed the ranking engine, and the team's record is inflated.

This excludes exactly one shape: the one a team merge leaves behind. One match imported twice
-- once from an event schedule page, once from a rankings scrape -- under two team rows.
Merging those rows fixes the team, not the games: execute_team_merge never touches `games`,
so both rows survive and both now resolve to the surviving team.

Its signature is that the two copies carry DIFFERENT raw team_id_master values, and that is
load-bearing twice over. It is what separates certain merge damage from a genuine same-day
rematch, which carries identical ids. And it is what makes excluding one copy safe -- see
SAME_ID_NOTE, which is the reason a fixture duplicated under identical ids is only ever
reported here, never excluded, at either scope.

--scope widens the search, never the action. `merge-clusters` (default) reads only games in a
merge cluster; `all` sweeps every scored game, which costs several minutes and finds the
same-id groups so they can be counted. Both exclude the differing-id shape alone.

The grouping key keeps home/away orientation. Collapsing it would fuse a real reverse fixture
into its own first leg.

Games are immutable, so this sets is_excluded rather than deleting. The copy naming the
surviving team is kept; failing that the richer metadata wins, then the most recently created
row. scripts/cleanup_dupe_games_by_composite.py reaches neither shape safely: it keys on raw
team_id_master, and it deletes rows outright.

Only scored games are considered -- an unplayed fixture recorded twice does not reach the
ranking engine, which filters NULL scores before this ever matters.

Usage:
    python scripts/exclude_merge_duplicate_games.py                      # dry run
    python scripts/exclude_merge_duplicate_games.py --execute
    python scripts/exclude_merge_duplicate_games.py --scope all          # count same-id too
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from supabase import create_client  # noqa: E402

GAME_FIELDS = (
    "id,game_date,home_team_master_id,away_team_master_id,home_score,away_score,"
    "event_name,competition,division_name,venue,source_url,created_at"
)
METADATA_FIELDS = ("event_name", "competition", "division_name", "venue", "source_url")
ID_BATCH = 100
PAGE = 1000

SAME_ID_NOTE = """\
Excluding one of these is self-destructive, so this script never does it. When a fixture is
duplicated under IDENTICAL raw team ids -- a changed game_uid recipe, e.g. modular11 moving
from integer team ids to UUIDs, or one team holding two provider ids -- both copies share the
key that EnhancedETLPipeline's auto-exclude cascade reads: (sorted raw master ids, scores)
on a game_date (src/etl/enhanced_pipeline.py:1899-1926). Exclude one copy and the next import
touching that fixture excludes its twin, and the match vanishes from the rankings entirely.
Tried on 50 rows 2026-08-31: 48 twins were gone within minutes, and all 100 were restored.

The differing-id shape is immune because the excluded copy's raw ids never match the survivor's.

Fixing this class means deduplicating at the source -- a stable game_uid, or an importer that
matches on merge-resolved fixture identity -- not is_excluded. See IMP-137."""


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def load_merge_map(sb) -> dict[str, str]:
    mapping, off = {}, 0
    while True:
        res = (sb.table("team_merge_map").select("deprecated_team_id,canonical_team_id")
               .range(off, off + PAGE - 1).execute())
        rows = res.data or []
        for r in rows:
            mapping[r["deprecated_team_id"]] = r["canonical_team_id"]
        if len(rows) < PAGE:
            break
        off += PAGE
    return mapping


def fetch_games_for(sb, team_ids: list[str]) -> dict[str, dict]:
    games: dict[str, dict] = {}
    for i in range(0, len(team_ids), ID_BATCH):
        batch = team_ids[i : i + ID_BATCH]
        for side in ("home_team_master_id", "away_team_master_id"):
            off = 0
            while True:
                res = (sb.table("games").select(GAME_FIELDS)
                       .in_(side, batch)
                       .eq("is_excluded", False)
                       .not_.is_("home_score", "null")
                       .not_.is_("away_score", "null")
                       .range(off, off + PAGE - 1)
                       .execute())
                rows = res.data or []
                for g in rows:
                    games[g["id"]] = g
                if len(rows) < PAGE:
                    break
                off += PAGE
    return games


def fetch_all_scored_games(sb, chunk_days: int = 7) -> dict[str, dict]:
    """Page by game_date window rather than raw offset.

    A duplicate always shares a game_date, so every window is independently complete and no
    group straddles a boundary. It also keeps each query's offset small, which deep offset
    pagination over 1.4M rows does not.
    """
    bounds = (sb.table("games").select("game_date")
              .eq("is_excluded", False).not_.is_("home_score", "null")
              .order("game_date", desc=False).limit(1).execute().data)
    if not bounds:
        return {}
    first = date.fromisoformat(bounds[0]["game_date"])
    last_row = (sb.table("games").select("game_date")
                .eq("is_excluded", False).not_.is_("home_score", "null")
                .order("game_date", desc=True).limit(1).execute().data)
    last = date.fromisoformat(last_row[0]["game_date"])

    games: dict[str, dict] = {}
    window_start = first
    while window_start <= last:
        window_end = window_start + timedelta(days=chunk_days - 1)
        off = 0
        while True:
            res = (sb.table("games").select(GAME_FIELDS)
                   .gte("game_date", window_start.isoformat())
                   .lte("game_date", window_end.isoformat())
                   .eq("is_excluded", False)
                   .not_.is_("home_score", "null")
                   .not_.is_("away_score", "null")
                   .order("id", desc=False)
                   .range(off, off + PAGE - 1)
                   .execute())
            rows = res.data or []
            for g in rows:
                games[g["id"]] = g
            if len(rows) < PAGE:
                break
            off += PAGE
        window_start = window_end + timedelta(days=1)
    return games


def keep_rank(game: dict, deprecated: set[str]) -> tuple:
    survivor_sides = sum(
        1 for side in ("home_team_master_id", "away_team_master_id") if game[side] not in deprecated
    )
    populated = sum(1 for f in METADATA_FIELDS if game.get(f))
    return (survivor_sides, populated, game["created_at"] or "")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=("merge-clusters", "all"), default="merge-clusters",
                    help="merge-clusters: duplicates a merge created, told apart by differing raw "
                         "team ids. all: every scored game, including copies under identical ids")
    ap.add_argument("--execute", action="store_true", help="write is_excluded (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None, help="exclude at most N rows")
    ap.add_argument("--out", default=None, help="where to write the excluded-id log")
    args = ap.parse_args()
    dry_run = not args.execute
    merge_scope = args.scope == "merge-clusters"

    sb = get_client()
    merge_map = load_merge_map(sb)
    if merge_scope and not merge_map:
        print("no merges on record — nothing to do")
        return 0

    def resolve(tid: str) -> str:
        seen: set[str] = set()
        while tid in merge_map and tid not in seen:
            seen.add(tid)
            tid = merge_map[tid]
        return tid

    deprecated = set(merge_map)
    if merge_scope:
        cluster_ids = sorted(deprecated | {resolve(c) for c in merge_map.values()})
        print(f"merged team rows: {len(deprecated):,}   clusters to scan: {len(cluster_ids):,}")
        games = fetch_games_for(sb, cluster_ids)
        print(f"scored games in those clusters: {len(games):,}")
    else:
        print("scanning every scored game by date window — this takes several minutes")
        games = fetch_all_scored_games(sb)
        print(f"scored games scanned: {len(games):,}")

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for g in games.values():
        key = (
            resolve(g["home_team_master_id"]),
            resolve(g["away_team_master_id"]),
            g["game_date"],
            g["home_score"],
            g["away_score"],
        )
        groups[key].append(g)

    to_exclude: list[dict] = []
    same_id_groups = 0
    for key, rows in groups.items():
        if len(rows) < 2:
            continue
        raw_pairs = {(r["home_team_master_id"], r["away_team_master_id"]) for r in rows}
        if len(raw_pairs) == 1:
            same_id_groups += 1
            continue
        rows.sort(key=lambda r: (keep_rank(r, deprecated), r["id"]), reverse=True)
        for r in rows[1:]:
            to_exclude.append({
                "id": r["id"],
                "game_date": r["game_date"],
                "kept_id": rows[0]["id"],
                "home_team_master_id": r["home_team_master_id"],
                "away_team_master_id": r["away_team_master_id"],
                "score": f"{key[3]}-{key[4]}",
            })

    differing_ids = sum(1 for r in groups.values() if len(r) > 1) - same_id_groups
    print(f"fixture tuples recorded twice under differing team ids: {differing_ids:,}")
    print(f"fixture tuples recorded twice under identical team ids: {same_id_groups:,} (never excluded)")
    if same_id_groups:
        print(SAME_ID_NOTE)
    print(f"redundant rows to exclude: {len(to_exclude):,}")
    for r in to_exclude[:10]:
        print(f"   {r['game_date']}  {r['score']}  exclude {r['id'][:8]} keep {r['kept_id'][:8]}")
    if len(to_exclude) > 10:
        print(f"   ... and {len(to_exclude) - 10:,} more")

    if not to_exclude:
        return 0
    if args.limit is not None:
        to_exclude = to_exclude[: args.limit]
        print(f"limited to {len(to_exclude):,} rows")

    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    ids = [r["id"] for r in to_exclude]
    done = 0
    for i in range(0, len(ids), ID_BATCH):
        batch = ids[i : i + ID_BATCH]
        sb.table("games").update({"is_excluded": True}).in_("id", batch).execute()
        done += len(batch)

    out_path = Path(args.out) if args.out else Path("exclude_merge_duplicate_games_log.json")
    out_path.write_text(json.dumps(to_exclude, indent=1), encoding="utf-8")
    print(f"\nExcluded {done:,} redundant game rows. Log: {out_path}")
    print("To undo: set is_excluded = false for the ids in that log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
