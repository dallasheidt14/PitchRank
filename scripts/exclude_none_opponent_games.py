#!/usr/bin/env python3
"""Hide the games a placeholder GotSport alias attached to one team, and reject that alias.

A blank provider id ("", "None", "null") names no team, so an approved alias keyed on one
attaches every game carrying it to a single team.

A game is a candidate when it comes from the alias's provider and the side carrying a blank
provider id is the side the alias attached to the sink team. The team's real games, where its own
provider id is set, and games from other providers are kept.

Games are immutable, so this sets is_excluded, which the team page and the ranking loader skip,
rather than deleting or unlinking. The alias is rejected rather than deleted, so its history
survives and a re-run can still find it.

Excluding a game fires trg_propagate_game_exclusion, which also excludes every other game on the
same date with the same team pair and aligned scores. Such a twin that is not itself a candidate
is a collision: the script prints them and refuses --execute while any exist.

Re-running is safe and sweeps stragglers: a rejected alias is left alone, and only games still
not excluded are updated.

Usage:
    python scripts/exclude_none_opponent_games.py                      # dry run
    python scripts/exclude_none_opponent_games.py --execute --out log.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from src.utils.provider_ids import is_blank_provider_id  # noqa: E402
from supabase import create_client  # noqa: E402

GAME_FIELDS = (
    "id,provider_id,game_date,home_team_master_id,away_team_master_id,home_provider_id,away_provider_id,"
    "home_score,away_score,is_excluded"
)
ALIAS_FIELDS = "id,provider_team_id,team_id_master,review_status,match_method"
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


def fetch_blank_aliases(sb, provider_id: str) -> list[dict]:
    """Every alias under this provider keyed on "" or on "none"/"null" in any case, whatever its
    review_status. Whitespace-padded spellings are not matched.

    ilike with no wildcard is a case-insensitive equality.
    """
    spelled = _paged(lambda: sb.table("team_alias_map").select(ALIAS_FIELDS)
                     .eq("provider_id", provider_id)
                     .or_("provider_team_id.ilike.none,provider_team_id.ilike.null")
                     .order("id", desc=False))
    empty = _paged(lambda: sb.table("team_alias_map").select(ALIAS_FIELDS)
                   .eq("provider_id", provider_id)
                   .eq("provider_team_id", "")
                   .order("id", desc=False))
    by_id = {a["id"]: a for a in spelled + empty if is_blank_provider_id(a["provider_team_id"])}
    return list(by_id.values())


def fetch_team_games(sb, team_id: str) -> list[dict]:
    return _paged(lambda: sb.table("games").select(GAME_FIELDS)
                  .or_(f"home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}")
                  .order("id", desc=False))


def select_candidates(games: list[dict], sink_team_id: str, provider_id: str) -> list[dict]:
    """Games the blank-id alias attached to the sink team, on either side.

    Provider team ids are scoped to their provider, so only the alias's provider's games count.
    """
    return [
        g for g in games
        if g["provider_id"] == provider_id
        and (
            (is_blank_provider_id(g["home_provider_id"]) and g["home_team_master_id"] == sink_team_id)
            or (is_blank_provider_id(g["away_provider_id"]) and g["away_team_master_id"] == sink_team_id)
        )
    ]


def cascade_key(game: dict) -> tuple | None:
    """The key trg_propagate_game_exclusion matches on, or None where the trigger never fires.

    Home/away-swapped copies of one fixture share a key.
    """
    home, away = game["home_team_master_id"], game["away_team_master_id"]
    if not home or not away:
        return None
    if home < away:
        return (game["game_date"], home, away, game["home_score"], game["away_score"])
    return (game["game_date"], away, home, game["away_score"], game["home_score"])


def cascade_collisions(to_exclude: list[dict], all_games: list[dict]) -> list[dict]:
    """Games outside to_exclude that the trigger would also exclude."""
    excluding_ids = {g["id"] for g in to_exclude}
    keys = {k for k in map(cascade_key, to_exclude) if k is not None}
    return [
        g for g in all_games
        if g["id"] not in excluding_ids and not g["is_excluded"] and cascade_key(g) in keys
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true",
                    help="reject the alias and write is_excluded (default is a dry run)")
    ap.add_argument("--out", default=None, help="where to write the rollback log")
    args = ap.parse_args()
    dry_run = not args.execute

    sb = get_client()
    provider = sb.table("providers").select("id").eq("code", "gotsport").single().execute().data
    aliases = fetch_blank_aliases(sb, provider["id"])
    if not aliases:
        print("no GotSport alias is keyed on a blank provider id — nothing to do")
        return 0

    sink_ids = sorted({a["team_id_master"] for a in aliases})
    names = {
        t["team_id_master"]: t["team_name"]
        for t in sb.table("teams").select("team_id_master,team_name").in_("team_id_master", sink_ids).execute().data
        or []
    }
    print(f"GotSport aliases keyed on a blank provider id: {len(aliases):,}")
    for a in aliases:
        print(f"   {a['id']}  {a['provider_team_id']!r} -> {names.get(a['team_id_master'], '?')} "
              f"({a['team_id_master']})  review_status={a['review_status']}  match_method={a['match_method']}")

    candidates: list[dict] = []
    kept: list[dict] = []
    collisions: list[dict] = []
    for team_id in sink_ids:
        games = fetch_team_games(sb, team_id)
        team_candidates = select_candidates(games, team_id, provider["id"])
        candidate_ids = {g["id"] for g in team_candidates}
        candidates.extend(team_candidates)
        kept.extend(g for g in games if g["id"] not in candidate_ids)
        collisions.extend(cascade_collisions([g for g in team_candidates if not g["is_excluded"]], games))

    to_exclude = [g for g in candidates if not g["is_excluded"]]
    print(f"candidate games: {len(candidates):,}")
    print(f"   already excluded: {len(candidates) - len(to_exclude):,}")
    print(f"   to exclude: {len(to_exclude):,}")
    print(f"non-candidate games kept: {len(kept):,}")
    print(f"cascade collisions: {len(collisions):,}")
    for g in collisions:
        print(f"   {g['game_date']}  {g['id']}  {g['home_provider_id']!r} vs {g['away_provider_id']!r}  "
              f"{g['home_score']}-{g['away_score']}")
    for g in to_exclude[:10]:
        print(f"   {g['game_date']}  exclude {g['id'][:8]}  {g['home_provider_id']!r} vs {g['away_provider_id']!r}  "
              f"{g['home_score']}-{g['away_score']}")
    if len(to_exclude) > 10:
        print(f"   ... and {len(to_exclude) - 10:,} more")

    to_reject = [a for a in aliases if a["review_status"] != "rejected"]
    if not to_exclude and not to_reject:
        return 0

    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    if collisions:
        print("\nRefusing --execute: excluding these games would also exclude the collisions above.")
        return 1

    out_path = Path(args.out) if args.out else Path(
        f"exclude_none_opponent_games_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    if out_path.exists():
        raise SystemExit(
            f"{out_path} already exists and is the only rollback record for that run. "
            "Pass a different --out; a re-run skips already-excluded rows and cannot reconstruct the ids."
        )

    log = {
        "applied": False,
        "aliases": [
            {
                "id": a["id"],
                "provider_team_id": a["provider_team_id"],
                "team_id_master": a["team_id_master"],
                "prior_review_status": a["review_status"],
                "prior_match_method": a["match_method"],
            }
            for a in aliases
        ],
        "game_ids": [g["id"] for g in to_exclude],
    }
    # Written before the first update, not after the last. A failure mid-run otherwise leaves
    # rows excluded with no record of which, and a re-run cannot find them again.
    out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    rejected = 0
    excluded = 0
    try:
        for a in to_reject:
            res = sb.table("team_alias_map").update({"review_status": "rejected"}).eq("id", a["id"]).execute()
            rejected += len(res.data or [])
        ids = log["game_ids"]
        for i in range(0, len(ids), ID_BATCH):
            batch = ids[i : i + ID_BATCH]
            res = (sb.table("games").update({"is_excluded": True})
                   .in_("id", batch).eq("is_excluded", False).execute())
            excluded += len(res.data or [])
    finally:
        log.update({"applied": True, "aliases_rejected": rejected, "games_excluded": excluded})
        out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    print(f"\nRejected {rejected:,} aliases and excluded {excluded:,} games. Log: {out_path}")
    if rejected != len(to_reject) or excluded != len(to_exclude):
        print(f"WARNING: planned {len(to_reject):,} aliases and {len(to_exclude):,} games — "
              "the run stopped early or another process changed them first.")
    print("To undo: set is_excluded = false for the game_ids in that log, and restore each "
          "alias's prior_review_status.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
