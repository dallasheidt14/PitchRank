#!/usr/bin/env python3
"""Hide the unscored fixture a rescheduled game left on its original date.

A league schedule is saved before it is played. When a game is moved, its result arrives on the
date it was played, which builds a new game_uid, so it is saved as a second row and the fixture
on the original date stays behind: the team page lists a blank game that never happened.
GotSport's team feed lists played games only, so no later scrape can show the fixture is gone.
A result on the fixture's own date is exclude_unscored_fixture_twins.py's case, not this one.

A past unscored GotSport row qualifies when the same team pair, resolved through team_merge_map,
has a scored GotSport row on another date within WINDOW_DAYS that was saved at least
MIN_SAVED_GAP after the fixture. Both legs of a home-and-away series arrive from the same
schedule, so a result saved later is the moved game rather than another leg — unless its own
date already held a blank for the pair by the time the fixture was saved, which makes it a game
scheduled there. Each result explains one fixture, nearest date first, so a pair with more
fixtures than results keeps the rest; a fixture hidden by an earlier run claims its result first,
so a re-run over the same --since cannot spend one twice. Rows from the last MIN_AGE_DAYS are left
alone, because their own result may still be on its way. Results on one date count once, so a match
stored twice cannot explain two fixtures. --execute needs --since: the rule was checked for one
season, and earlier tournament weekends held real games it would hide.

Games are immutable, so this sets is_excluded, which the team page and the ranking loader skip.
Nothing in the import path clears it: should a hidden fixture's game turn up on its own date
after all, a result with the same game_uid is backfilled onto the hidden row and stays hidden,
so the rollback log is the only way back to it. Excluding a row fires
trg_propagate_game_exclusion, which also excludes every other game on that date with the same
saved pair and aligned scores; the script refuses --execute on a collision.

Usage:
    python scripts/exclude_rescheduled_fixture_leftovers.py                      # dry run
    python scripts/exclude_rescheduled_fixture_leftovers.py --since 2026-08-01   # one season
    python scripts/exclude_rescheduled_fixture_leftovers.py --since 2026-08-01 --execute --out log.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from scripts.exclude_merge_duplicate_games import load_merge_map  # noqa: E402
from scripts.exclude_none_opponent_games import cascade_collisions  # noqa: E402
from scripts.exclude_unscored_fixture_twins import ID_BATCH, _linked, _paged, get_client  # noqa: E402

GAME_FIELDS = (
    "id,provider_id,game_date,home_team_master_id,away_team_master_id,home_score,away_score,is_excluded,created_at"
)
WINDOW_DAYS = 21
MIN_AGE_DAYS = 7
MIN_SAVED_GAP = timedelta(days=1)


def fetch_unscored(sb, since: str | None, until: str) -> list[dict]:
    """Excluded rows too: an earlier run's fixture keeps its result, and a result's own date is checked for a blank."""
    def query():
        q = (sb.table("games").select(GAME_FIELDS)
             .is_("home_score", "null").is_("away_score", "null")
             .lt("game_date", until))
        if since:
            q = q.gte("game_date", since)
        return q.order("id", desc=False)

    return _linked(_paged(query))


def fetch_scored_for(sb, provider_id: str, first: str, last: str, team_ids: list[str]) -> list[dict]:
    """Every id a candidate pair's teams are saved under is in team_ids, so a result is found whichever side is home."""
    rows: dict[str, dict] = {}
    for i in range(0, len(team_ids), ID_BATCH):
        batch = team_ids[i : i + ID_BATCH]
        for g in _paged(lambda b=batch: sb.table("games").select(GAME_FIELDS)
                        .eq("provider_id", provider_id)
                        .eq("is_excluded", False)
                        .gte("game_date", first)
                        .lte("game_date", last)
                        .in_("home_team_master_id", b)
                        .order("id", desc=False)):
            if g["home_score"] is not None and g["away_score"] is not None:
                rows[g["id"]] = g
    return _linked(list(rows.values()))


def resolved_pair(game: dict, merge_map: dict[str, str]) -> tuple:
    return tuple(sorted(merge_map.get(t, t) for t in (game["home_team_master_id"], game["away_team_master_id"])))


def _saved_at(game: dict) -> datetime:
    return datetime.fromisoformat(game["created_at"])


def _days_apart(a: dict, b: dict) -> int:
    return abs((date.fromisoformat(a["game_date"]) - date.fromisoformat(b["game_date"])).days)


def select_leftovers(
    fixtures: list[dict], scored: list[dict], blanks: list[dict], merge_map: dict[str, str]
) -> list[tuple[dict, dict]]:
    """(fixture, result) pairs, each result explaining at most one fixture of its pair, matched nearest date first.

    blanks are every GotSport unscored row read, hidden or not, and show which dates a pair was scheduled on. A
    fixture is among them, so a result on the fixture's own date is ruled out as scheduled there.
    """
    results: dict[tuple, list[dict]] = defaultdict(list)
    for g in scored:
        results[resolved_pair(g, merge_map)].append(g)
    scheduled: dict[tuple, list[datetime]] = defaultdict(list)
    for g in blanks:
        scheduled[(g["game_date"], resolved_pair(g, merge_map))].append(_saved_at(g))
    by_pair: dict[tuple, list[dict]] = defaultdict(list)
    for g in fixtures:
        by_pair[resolved_pair(g, merge_map)].append(g)

    def moved_here(fixture: dict, result: dict, key: tuple) -> bool:
        return (
            _days_apart(fixture, result) <= WINDOW_DAYS
            and _saved_at(result) - _saved_at(fixture) >= MIN_SAVED_GAP
            and not any(saved <= _saved_at(fixture) for saved in scheduled[(result["game_date"], key)])
        )

    chosen: list[tuple[dict, dict]] = []
    for key, rows in by_pair.items():
        candidates = sorted(
            (not f["is_excluded"], _days_apart(f, r), f["id"], r["id"], f, r)
            for f in rows
            for r in results[key]
            if moved_here(f, r, key)
        )
        claimed_fixtures: set[str] = set()
        # By date, not row: one match stored twice must not explain two fixtures
        claimed_dates: set[str] = set()
        for _live, _gap, fixture_id, _result_id, fixture, result in candidates:
            if fixture_id not in claimed_fixtures and result["game_date"] not in claimed_dates:
                claimed_fixtures.add(fixture_id)
                claimed_dates.add(result["game_date"])
                chosen.append((fixture, result))
    return chosen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="write is_excluded (default is a dry run)")
    ap.add_argument("--since", default=None, help="earliest game_date to consider (YYYY-MM-DD)")
    ap.add_argument("--out", default=None, help="where to write the rollback log")
    args = ap.parse_args()
    dry_run = not args.execute
    if args.execute and not args.since:
        # The rule was checked against GotSport for one season; earlier tournaments broke it
        raise SystemExit("--execute needs --since, the first game_date to hide (e.g. 2026-08-01)")

    sb = get_client()
    gotsport_id = sb.table("providers").select("id").eq("code", "gotsport").execute().data[0]["id"]
    merge_map = load_merge_map(sb)
    absorbed: dict[str, set[str]] = defaultdict(set)
    for deprecated, canonical in merge_map.items():
        absorbed[canonical].add(deprecated)
    today = date.today()
    until = (today - timedelta(days=MIN_AGE_DAYS)).isoformat()
    # A result can sit a window before the first fixture, and its own date is checked for a blank
    earliest = (date.fromisoformat(args.since) - timedelta(days=WINDOW_DAYS)).isoformat() if args.since else None
    unscored = fetch_unscored(sb, earliest, today.isoformat())
    blanks = [g for g in unscored if g["provider_id"] == gotsport_id]
    fixtures = [g for g in blanks if (not args.since or g["game_date"] >= args.since) and g["game_date"] < until]
    teams: set[str] = set()
    for g in fixtures:
        for team in (g["home_team_master_id"], g["away_team_master_id"]):
            canonical = merge_map.get(team, team)
            teams.update((canonical, *absorbed[canonical]))
    scored: list[dict] = []
    if fixtures:
        dates = [date.fromisoformat(g["game_date"]) for g in fixtures]
        first = (min(dates) - timedelta(days=WINDOW_DAYS)).isoformat()
        last = (max(dates) + timedelta(days=WINDOW_DAYS)).isoformat()
        scored = fetch_scored_for(sb, gotsport_id, first, last, sorted(teams))

    pairs = [(f, r) for f, r in select_leftovers(fixtures, scored, blanks, merge_map) if not f["is_excluded"]]
    to_exclude = [fixture for fixture, _result in pairs]
    collisions = cascade_collisions(to_exclude, unscored)
    under_merged = sum(1 for g in to_exclude if {g["home_team_master_id"], g["away_team_master_id"]} & merge_map.keys())

    live = sum(1 for g in fixtures if not g["is_excluded"])
    print(f"unscored GotSport games dated before {until} scanned: {live:,} ({len(fixtures) - live:,} already hidden)")
    print(f"fixtures a rescheduled game left behind: {len(to_exclude):,}")
    print(f"   saved under a team since merged away: {under_merged:,}")
    for month, n in sorted(Counter(g["game_date"][:7] for g in to_exclude).items()):
        print(f"   {month}: {n:,}")
    print(f"cascade collisions: {len(collisions):,}")
    for g in collisions:
        print(f"   {g['game_date']}  {g['id']}  {g['home_score']}-{g['away_score']}")
    for fixture, result in pairs[:5]:
        print(f"   {fixture['game_date']}  exclude {fixture['id'][:8]}  "
              f"{fixture['home_team_master_id'][:8]} vs {fixture['away_team_master_id'][:8]}  "
              f"(played {result['game_date']} as {result['id'][:8]} {result['home_score']}-{result['away_score']})")

    if not to_exclude:
        return 0

    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    if collisions:
        print("\nRefusing --execute: excluding these games would also exclude the collisions above.")
        return 1

    out_path = Path(args.out) if args.out else Path(
        f"exclude_rescheduled_fixture_leftovers_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    if out_path.exists():
        raise SystemExit(
            f"{out_path} already exists and is the only rollback record for that run. "
            "Pass a different --out; a re-run skips already-excluded rows and cannot reconstruct the ids."
        )

    log = {"applied": False, "game_ids": [g["id"] for g in to_exclude]}
    # Written before the first update, not after the last. A failure mid-run otherwise leaves
    # rows excluded with no record of which, and a re-run cannot find them again.
    out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    excluded = 0
    try:
        ids = log["game_ids"]
        for i in range(0, len(ids), ID_BATCH):
            batch = ids[i : i + ID_BATCH]
            # A fixture scored since it was read is a game that did happen on its own date
            res = (sb.table("games").update({"is_excluded": True})
                   .in_("id", batch).eq("is_excluded", False)
                   .is_("home_score", "null").is_("away_score", "null").execute())
            excluded += len(res.data or [])
    finally:
        log.update({"applied": True, "games_excluded": excluded})
        out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    print(f"\nExcluded {excluded:,} games. Log: {out_path}")
    if excluded != len(to_exclude):
        print(f"WARNING: planned {len(to_exclude):,} games — "
              "the run stopped early or another process changed them first.")
    print("To undo: set is_excluded = false for the game_ids in that log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
