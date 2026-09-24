#!/usr/bin/env python3
"""Hide the unscored fixture left beside its own scored result.

A fixture saved before both teams were linked keeps a game_uid built from provider team ids. When
the result arrived fully matched, its master-id game_uid missed the fixture, and the importer added
a second row, so the team page lists the game twice: once blank, once with the score.

A past-dated (date, team pair) group qualifies when it holds at least one unscored row and no more
unscored rows than scored ones; each unscored row there is a stale fixture of a game that has a
result. A group with more fixtures than results may hold a game still awaiting its score, so it is
left alone. Only games not already excluded and with both master ids count, and a row from a
rematch provider, which can hold two same-day games for one pair, is never a twin or a result.

Games are immutable, so this sets is_excluded, which the team page and the ranking loader skip.
Excluding a row fires trg_propagate_game_exclusion, which also excludes every other game on that
date with the same pair and aligned scores. An unscored row only aligns with other unscored rows,
so a scored result is never caught; the script still checks and refuses --execute on a collision.

Usage:
    python scripts/exclude_unscored_fixture_twins.py                      # dry run
    python scripts/exclude_unscored_fixture_twins.py --since 2026-08-01   # one season
    python scripts/exclude_unscored_fixture_twins.py --execute --out log.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from scripts.exclude_none_opponent_games import cascade_collisions  # noqa: E402
from src.models.game_matcher import REMATCH_PROVIDERS  # noqa: E402
from supabase import create_client  # noqa: E402

GAME_FIELDS = "id,provider_id,game_date,home_team_master_id,away_team_master_id,home_score,away_score,is_excluded"
ID_BATCH = 100
PAGE = 1000


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    return create_client(url, key)


def _paged(make_query) -> list[dict]:
    rows_out, off = [], 0
    while True:
        rows = make_query().range(off, off + PAGE - 1).execute().data or []
        rows_out.extend(rows)
        if len(rows) < PAGE:
            return rows_out
        off += PAGE


def _linked(games: list[dict]) -> list[dict]:
    return [g for g in games if g["home_team_master_id"] and g["away_team_master_id"]]


def fetch_unscored(sb, since: str | None, until: str) -> list[dict]:
    def query():
        q = (sb.table("games").select(GAME_FIELDS)
             .is_("home_score", "null").is_("away_score", "null")
             .eq("is_excluded", False)
             .lt("game_date", until))
        if since:
            q = q.gte("game_date", since)
        return q.order("id", desc=False)

    return _linked(_paged(query))


def fetch_scored_for(sb, game_date: str, team_ids: list[str]) -> list[dict]:
    """Every team of a candidate pair is in team_ids, so a result is found whichever side is home."""
    rows: dict[str, dict] = {}
    for i in range(0, len(team_ids), ID_BATCH):
        batch = team_ids[i : i + ID_BATCH]
        for g in _paged(lambda b=batch: sb.table("games").select(GAME_FIELDS)
                        .eq("game_date", game_date)
                        .eq("is_excluded", False)
                        .in_("home_team_master_id", b)
                        .order("id", desc=False)):
            if g["home_score"] is not None and g["away_score"] is not None:
                rows[g["id"]] = g
    return _linked(list(rows.values()))


def pair_key(game: dict) -> tuple:
    return (game["game_date"], *sorted((game["home_team_master_id"], game["away_team_master_id"])))


def select_twins(unscored: list[dict], scored: list[dict], rematch_provider_ids: set[str]) -> list[dict]:
    """Unscored rows whose (date, pair) holds at least as many scored rows.

    Rematch providers can put one pair on the pitch twice in a day, so their rows are neither twins
    nor evidence of one. A row scored between the two reads appears in both lists and must not be
    its own result.
    """
    unscored_ids = {g["id"] for g in unscored}
    results = Counter(
        pair_key(g) for g in scored if g["id"] not in unscored_ids and g["provider_id"] not in rematch_provider_ids
    )
    fixtures: dict[tuple, list[dict]] = defaultdict(list)
    for g in unscored:
        if g["provider_id"] not in rematch_provider_ids:
            fixtures[pair_key(g)].append(g)
    return [g for key, rows in fixtures.items() if len(rows) <= results[key] for g in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="write is_excluded (default is a dry run)")
    ap.add_argument("--since", default=None, help="earliest game_date to consider (YYYY-MM-DD)")
    ap.add_argument("--out", default=None, help="where to write the rollback log")
    args = ap.parse_args()
    dry_run = not args.execute

    sb = get_client()
    rematch_provider_ids = {
        p["id"] for p in sb.table("providers").select("id").in_("code", sorted(REMATCH_PROVIDERS)).execute().data or []
    }
    unscored = fetch_unscored(sb, args.since, date.today().isoformat())
    teams_by_date: dict[str, set[str]] = defaultdict(set)
    for g in unscored:
        teams_by_date[g["game_date"]].update((g["home_team_master_id"], g["away_team_master_id"]))
    scored: list[dict] = []
    for game_date, teams in sorted(teams_by_date.items()):
        scored.extend(fetch_scored_for(sb, game_date, sorted(teams)))

    to_exclude = select_twins(unscored, scored, rematch_provider_ids)
    collisions = cascade_collisions(to_exclude, unscored + scored)

    print(f"unscored past games scanned: {len(unscored):,}")
    print(f"unscored twins of a scored result: {len(to_exclude):,}")
    for month, n in sorted(Counter(g["game_date"][:7] for g in to_exclude).items()):
        print(f"   {month}: {n:,}")
    print(f"cascade collisions: {len(collisions):,}")
    for g in collisions:
        print(f"   {g['game_date']}  {g['id']}  {g['home_score']}-{g['away_score']}")
    results = {pair_key(g): g for g in scored}
    for g in to_exclude[:5]:
        r = results[pair_key(g)]
        print(f"   {g['game_date']}  exclude {g['id'][:8]}  "
              f"{g['home_team_master_id'][:8]} vs {g['away_team_master_id'][:8]}  "
              f"(kept {r['id'][:8]} {r['home_score']}-{r['away_score']})")

    if not to_exclude:
        return 0

    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    if collisions:
        print("\nRefusing --execute: excluding these games would also exclude the collisions above.")
        return 1

    out_path = Path(args.out) if args.out else Path(
        f"exclude_unscored_fixture_twins_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
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
            # A fixture scored since it was read is no longer a stale twin
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
