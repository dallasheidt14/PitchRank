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
same-id groups so they can be counted. Both exclude the differing-id shape alone. --merge-log
narrows `merge-clusters` to the clusters of the teams an apply_vetted_team_merges.py log merged
into, so one batch's repair can be undone without touching another's.

--revert undoes a run from its own log: it sets is_excluded back to false on each logged game the
run's updates reached, directly or through the exclusion trigger, while it is still excluded, and
stamps the log so it is not replayed. Un-excluding
a game cascades to nothing. Excluding one does: a copy whose exclusion the trigger would carry to
another copy outside the run is left in place, so every game a run hides is in its log. Every
--execute run leaves a log, an empty one when it excludes nothing.

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
    python scripts/exclude_merge_duplicate_games.py --merge-log merge_results.json --execute --out excluded.json
    python scripts/exclude_merge_duplicate_games.py --revert excluded.json --execute
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from scripts.apply_vetted_team_merges import new_log, read_log, write_log  # noqa: E402
from scripts.exclude_none_opponent_games import cascade_collisions, cascade_key  # noqa: E402
from supabase import create_client  # noqa: E402

GAME_FIELDS = (
    "id,game_date,home_team_master_id,away_team_master_id,home_score,away_score,"
    "event_name,competition,division_name,venue,source_url,created_at,game_uid,is_excluded"
)
METADATA_FIELDS = ("event_name", "competition", "division_name", "venue", "source_url")
LOG_STEM = "exclude_merge_duplicate_games"
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
               .order("deprecated_team_id", desc=False)
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
                       .order("id", desc=False)
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


def _has_distinct_match_ids(rows: list[dict]) -> bool:
    """True when the provider itself says these are different matches.

    Same teams, date and score is one match for every provider here except PlayMetrics
    tournaments, where bracket play routinely pairs two teams twice in a day (pool then
    final) and the same scoreline is unremarkable. Only that provider mints a per-match
    discriminator: game_matcher.py:734-741 suffixes schedule_id onto the game_uid. Where
    those suffixes disagree the rows are two fixtures, and collapsing them would delete a
    real result.

    Modular11's ':age_group:division' tail is not such a discriminator -- it labels the
    cohort, and a pair differing only by it is one match spanning a uid recipe change.
    """
    uids = {r.get("game_uid") or "" for r in rows}
    return len(uids) > 1 and any(u.startswith("playmetrics_tournament:") for u in uids)


def keep_rank(game: dict, deprecated: set[str]) -> tuple:
    survivor_sides = sum(
        1 for side in ("home_team_master_id", "away_team_master_id") if game[side] not in deprecated
    )
    populated = sum(1 for f in METADATA_FIELDS if game.get(f))
    return (survivor_sides, populated, game["created_at"] or "")


def logged_survivors(path: Path) -> set[str]:
    """The teams an apply_vetted_team_merges.py log records merges into, whether or not each merge was
    confirmed: scanning a cluster no merge changed excludes nothing a full scan would not."""
    return {entry["keep_id"] for entry in read_log(path)}


def still_excluded(sb, ids: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(ids), ID_BATCH):
        rows = sb.table("games").select("id").in_("id", ids[i : i + ID_BATCH]).eq("is_excluded", True).execute()
        found |= {row["id"] for row in rows.data or []}
    return found


def logged_cascade_key(row: dict) -> tuple | None:
    home, away = (int(score) for score in row["score"].split("-"))
    return cascade_key({**row, "home_score": home, "away_score": away})


def revert(sb, path: Path, execute: bool) -> int:
    """Set is_excluded back to false, while still true, on the games a run's updates reached: its first
    `sent` logged rows (updates ran in log order, and `sent` counts a batch whose reply was lost) plus any
    later logged row the trigger excluded along with one of them. A log with no `sent` falls back to
    `confirmed`. The log is stamped once reverted, so a later replay cannot undo another run's exclusion of
    the same games."""
    logged = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(logged, dict) or not isinstance(logged.get("rows"), list):
        raise SystemExit(f"{path} holds no exclude_merge_duplicate_games.py log")
    if logged.get("reverted_at"):
        print(f"{path} was reverted at {logged['reverted_at']} — nothing to do")
        return 0
    sent = logged.get("sent", logged.get("confirmed"))
    if not isinstance(sent, int):
        raise SystemExit(
            f"{path} records no count of rows sent, so its run stopped before it could say which games it "
            "excluded; settle them by hand"
        )
    rows = logged["rows"]
    reached = {logged_cascade_key(row) for row in rows[:sent]} - {None}
    ids = [row["id"] for n, row in enumerate(rows) if n < sent or logged_cascade_key(row) in reached]
    excluded = still_excluded(sb, ids)
    print(f"games {path} excluded: {len(ids):,}, of which still excluded: {len(excluded):,}")
    if not execute:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0
    restored = 0
    for i in range(0, len(ids), ID_BATCH):
        batch = ids[i : i + ID_BATCH]
        res = sb.table("games").update({"is_excluded": False}).in_("id", batch).eq("is_excluded", True).execute()
        restored += len(res.data or [])
    write_log(path, {**logged, "reverted_at": datetime.now(UTC).isoformat()})
    print(f"\nRestored {restored:,} game rows.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", choices=("merge-clusters", "all"), default="merge-clusters",
                    help="merge-clusters: duplicates a merge created, told apart by differing raw "
                         "team ids. all: every scored game, including copies under identical ids")
    ap.add_argument("--merge-log", default=None,
                    help="an apply_vetted_team_merges.py log: scan only the clusters of the teams it merged into")
    ap.add_argument("--revert", default=None, help="this script's own log: un-exclude the games it excluded")
    ap.add_argument("--execute", action="store_true", help="write is_excluded (default is a dry run)")
    ap.add_argument("--limit", type=int, default=None, help="exclude at most N rows")
    ap.add_argument("--out", default=None, help="where to write the excluded-id log")
    args = ap.parse_args()
    dry_run = not args.execute
    merge_scope = args.scope == "merge-clusters"
    if args.revert and (args.merge_log or not merge_scope or args.limit is not None or args.out):
        ap.error("--revert undoes the whole log it is given and takes only --execute")
    if args.merge_log and not merge_scope:
        ap.error("--merge-log narrows the merge-clusters scope; --scope all reads every game")

    sb = get_client()
    if args.revert:
        return revert(sb, Path(args.revert), args.execute)

    def nothing_to_exclude(why: str) -> int:
        """With --execute, leaves an empty log so a revert of this run has one to read."""
        print(why)
        if args.execute:
            write_log(new_log(args.out, Path(), LOG_STEM), {"applied": True, "confirmed": 0, "sent": 0, "rows": []})
        return 0

    merge_map = load_merge_map(sb)
    if merge_scope and not merge_map:
        return nothing_to_exclude("no merges on record — nothing to do")

    def resolve(tid: str) -> str:
        seen: set[str] = set()
        while tid in merge_map and tid not in seen:
            seen.add(tid)
            tid = merge_map[tid]
        return tid

    deprecated = set(merge_map)
    if args.merge_log:
        survivors = {resolve(t) for t in logged_survivors(Path(args.merge_log))}
        if not survivors:
            return nothing_to_exclude(f"{args.merge_log} records no merge — nothing to do")
        cluster_ids = sorted(survivors | {d for d in deprecated if resolve(d) in survivors})
        print(f"teams {args.merge_log} merged into: {len(survivors):,}   rows in their clusters: {len(cluster_ids):,}")
    elif merge_scope:
        cluster_ids = sorted(deprecated | {resolve(c) for c in merge_map.values()})
        print(f"merged team rows: {len(deprecated):,}   clusters to scan: {len(cluster_ids):,}")
    if merge_scope:
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

    candidates: list[tuple[dict, dict]] = []
    same_id_groups = 0
    distinct_match_ids = 0
    for rows in groups.values():
        if len(rows) < 2:
            continue
        raw_pairs = {(r["home_team_master_id"], r["away_team_master_id"]) for r in rows}
        if len(raw_pairs) == 1:
            same_id_groups += 1
            continue
        if _has_distinct_match_ids(rows):
            distinct_match_ids += 1
            continue
        rows.sort(key=lambda r: (keep_rank(r, deprecated), r["id"]), reverse=True)
        candidates += [(r, rows[0]) for r in rows[1:]]

    differing_ids = sum(1 for r in groups.values() if len(r) > 1) - same_id_groups
    print(f"fixture tuples recorded twice under differing team ids: {differing_ids:,}")
    print(f"fixture tuples recorded twice under identical team ids: {same_id_groups:,} (never excluded)")
    if same_id_groups:
        print(SAME_ID_NOTE)
    if distinct_match_ids:
        print(f"skipped, provider gave the rows distinct match ids: {distinct_match_ids:,}")
    if args.limit is not None:
        candidates = candidates[: args.limit]
        print(f"limited to {len(candidates):,} rows")

    # trg_propagate_game_exclusion would also exclude any other copy sharing a candidate's cascade key,
    # the copy kept included, and no log would name it.
    colliding = {cascade_key(g) for g in cascade_collisions([r for r, _ in candidates], list(games.values()))}
    to_exclude = [
        {
            "id": r["id"],
            "game_date": r["game_date"],
            "kept_id": kept["id"],
            "home_team_master_id": r["home_team_master_id"],
            "away_team_master_id": r["away_team_master_id"],
            "score": f"{r['home_score']}-{r['away_score']}",
        }
        for r, kept in candidates
        if cascade_key(r) not in colliding
    ]
    if left := len(candidates) - len(to_exclude):
        print(f"left in place, the exclusion trigger would also hide another copy: {left:,}")
    print(f"redundant rows to exclude: {len(to_exclude):,}")
    for r in to_exclude[:10]:
        print(f"   {r['game_date']}  {r['score']}  exclude {r['id'][:8]} keep {r['kept_id'][:8]}")
    if len(to_exclude) > 10:
        print(f"   ... and {len(to_exclude) - 10:,} more")

    if not to_exclude:
        return nothing_to_exclude("nothing to exclude")

    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    out_path = new_log(args.out, Path(), LOG_STEM)

    # Written before each batch is sent, not only in the closing write: a run killed outright skips that
    # write, and a later scan cannot find the rows again -- it filters out exactly the rows it already
    # excluded. `sent` counts a batch whose reply was lost, which may still have committed.
    ids = [r["id"] for r in to_exclude]
    done = sent = 0
    write_log(out_path, {"applied": False, "sent": sent, "rows": to_exclude})
    try:
        for i in range(0, len(ids), ID_BATCH):
            batch = ids[i : i + ID_BATCH]
            sent = done + len(batch)
            write_log(out_path, {"applied": False, "sent": sent, "rows": to_exclude})
            sb.table("games").update({"is_excluded": True}).in_("id", batch).execute()
            done += len(batch)
    finally:
        write_log(out_path, {"applied": True, "confirmed": done, "sent": sent, "rows": to_exclude})

    print(f"\nExcluded {done:,} redundant game rows. Log: {out_path}")
    if done != len(ids):
        print(f"WARNING: {len(ids) - done:,} planned rows were not written — the run stopped early.")
    print(f"To undo: python scripts/exclude_merge_duplicate_games.py --revert {out_path}  (a dry run; add --execute)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
