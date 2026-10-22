#!/usr/bin/env python3
"""Correct stored TGS scores that TGS has since changed.

TGS edits a score after posting it. The importer corrects what it re-scrapes, but a game outside its scan
range, or one whose pair already holds a second live row, keeps its first score. This re-reads the live
schedule of every event that has recent stored games and compares.

A change is applied only when the live score is the same one the run recorded in --snapshot-in saw,
because TGS has no last-updated field and has shown a correct result replaced by an unrelated one. A dry
run only reports: it writes no snapshot, so the file that seeds the next run comes from an --execute run.
A change that moves both sides of the score, other than the stored pair swapped, is held and never
applied. A game TGS
now shows unscored, one no longer listed under the same date and teams, and one whose pair meets twice
that day, whichever way round it is listed, are left alone.

Games are immutable, so a changed score goes through game_corrections + apply_game_correction. Where the
corrected score already sits in a second live row for the same game, the stale row is hidden instead
(is_excluded), which fires trg_propagate_game_exclusion; a hide is refused when that would also hide any
other game, whichever provider's. Where an excluded row already holds the live score the stale row is
left alone, because the games composite unique index counts excluded rows.

Usage:
    python scripts/reconcile_tgs_scores.py                                  # dry run, last 45 days
    python scripts/reconcile_tgs_scores.py --since 2026-10-01 --limit-events 5
    python scripts/reconcile_tgs_scores.py --snapshot-in last.json          # dry run against a recorded snapshot
    python scripts/reconcile_tgs_scores.py --execute --snapshot-in last.json --snapshot-out this.json --out log.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from scripts.exclude_none_opponent_games import cascade_collisions, cascade_key  # noqa: E402
from scripts.scrape_tgs_event import BASE, compute_result  # noqa: E402
from src.etl.game_corrections import apply_score_correction, moves_both_sides  # noqa: E402
from supabase import create_client  # noqa: E402

GAME_FIELDS = (
    "id,game_uid,provider_id,game_date,home_team_master_id,away_team_master_id,"
    "home_provider_id,away_provider_id,home_score,away_score,is_excluded,source_url"
)
EVENT_URL = re.compile(r"/public/event/(\d+)$")
ID_BATCH = 100
PAGE = 1000
FETCH_TRIES = 3
DEFAULT_LOOKBACK_DAYS = 45
MAX_SCORE = 50
SUBMITTED_BY = "reconcile_tgs_scores"
HEADERS = {
    "Origin": "https://public.totalglobalsports.com",
    "Referer": "https://public.totalglobalsports.com/",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

ACTIONABLE = ("reversed", "one_side")


class LiveFetchError(Exception):
    """A TGS request failed on every attempt; the event cannot be compared."""


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


def event_id_of(source_url: str | None) -> str | None:
    match = EVENT_URL.search(source_url or "")
    return match.group(1) if match else None


def fetch_stored(sb, since: str, excluded: bool = False) -> list[dict]:
    """Scored TGS games dated on or after since, with an event page as their source."""
    [provider] = sb.table("providers").select("id").eq("code", "tgs").execute().data
    return [
        g
        for g in _paged(
            lambda: (
                sb.table("games")
                .select(GAME_FIELDS)
                .eq("provider_id", provider["id"])
                .eq("is_excluded", excluded)
                .gte("game_date", since)
                .not_.is_("home_score", "null")
                .not_.is_("away_score", "null")
                .order("id", desc=False)
            )
        )
        if event_id_of(g["source_url"])
    ]


def fetch_cascade_neighbours(sb, rows: list[dict]) -> list[dict]:
    """Every live game of any provider on the rows' dates between the rows' teams.

    trg_propagate_game_exclusion matches on date, master pair and scores whatever the provider, so
    this is the set a hide can reach, not just the TGS rows.
    """
    teams_by_date: dict[str, set[str]] = defaultdict(set)
    for g in rows:
        teams_by_date[g["game_date"]].update(t for t in (g["home_team_master_id"], g["away_team_master_id"]) if t)
    found: dict[str, dict] = {}
    for game_date, teams in sorted(teams_by_date.items()):
        ids = sorted(teams)
        for i in range(0, len(ids), ID_BATCH):
            for g in _paged(
                lambda batch=ids[i : i + ID_BATCH], day=game_date: (
                    sb.table("games")
                    .select(GAME_FIELDS)
                    .eq("game_date", day)
                    .eq("is_excluded", False)
                    .in_("home_team_master_id", batch)
                    .order("id", desc=False)
                )
            ):
                found[g["id"]] = g
    return list(found.values())


def _get_json(url: str):
    for attempt in range(FETCH_TRIES):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code == 200:
                return response.json()
        except (requests.RequestException, ValueError):
            pass
        if attempt < FETCH_TRIES - 1:
            time.sleep(2 * (attempt + 1))
    raise LiveFetchError(url)


def _flight_games(payload) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    if isinstance(payload, dict):
        payload = payload.get("schedules", payload.get("games", []))
    return payload if isinstance(payload, list) else []


def _score(game: dict, *keys: str) -> int | None:
    """A score as a plausible integer, or None where TGS gives none (blank, null or outside 0-MAX_SCORE)."""
    for key in keys:
        value = game.get(key)
        if value is None:
            continue
        try:
            score = int(str(value).strip())
        except ValueError:
            return None
        return score if 0 <= score <= MAX_SCORE else None
    return None


def _live_score(game: dict) -> tuple:
    home = _score(game, "hometeamscore", "homeScore")
    away = _score(game, "awayteamscore", "awayScore")
    return (None, None) if home is None or away is None else (home, away)


def _flight_ids(structure) -> list[int]:
    """The flight ids of an event's schedule structure, as integers so none can reach a URL as text."""
    data = structure.get("data") or {}
    return [
        int(flight["flightID"])
        for key in ("girlsDivAndFlightList", "boysDivAndFlightList")
        for division in data.get(key) or []
        for flight in division.get("flightList") or []
    ]


def fetch_live_event(event_id: str) -> dict[tuple, list]:
    """Every game on an event's live schedule, keyed (date, home team id, away team id).

    Each key holds the list of (home, away) scores TGS reports for it, (None, None) where unscored.
    Raises LiveFetchError when any request fails: a failed fetch is not an empty schedule.
    """
    structure = _get_json(f"{BASE}/Event/get-event-schedule-or-standings/{event_id}")
    try:
        flight_ids = _flight_ids(structure)
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        raise LiveFetchError(f"event {event_id}: unexpected schedule structure") from e
    live: dict[tuple, list] = defaultdict(list)
    for flight_id in flight_ids:
        payload = _get_json(f"{BASE}/Event/get-schedules-by-flight/{event_id}/{flight_id}/0")
        for game in _flight_games(payload):
            if not isinstance(game, dict) or not game.get("gameDate"):
                continue
            key = (str(game["gameDate"])[:10], str(game.get("hometeamID")), str(game.get("awayteamID")))
            live[key].append(_live_score(game))
    return dict(live)


def classify(row: dict, live: dict[tuple, list]) -> tuple[str, tuple | None]:
    """How a stored game compares with the live schedule, and the live score where it is a change."""
    date_, home, away = row["game_date"], str(row["home_provider_id"]), str(row["away_provider_id"])
    entries = live.get((date_, home, away))
    if not entries:
        return "not_found", None
    if len(entries) + len(live.get((date_, away, home), ())) > 1:
        return "ambiguous", None
    score = entries[0]
    if score == (None, None):
        return "live_unscored", None
    stored = (row["home_score"], row["away_score"])
    if score == stored:
        return "unchanged", None
    if score == stored[::-1]:
        return "reversed", score
    if moves_both_sides(stored, score):
        return "both_sides", score
    return "one_side", score


def _on_sides_of(row: dict, other: dict) -> tuple:
    """other's score read as (home, away) of row, whichever way round the two are stored."""
    scores = (other["home_score"], other["away_score"])
    return scores if str(other["home_provider_id"]) == str(row["home_provider_id"]) else scores[::-1]


def _game_key(row: dict) -> tuple:
    pair = frozenset((str(row["home_provider_id"]), str(row["away_provider_id"])))
    return (row["game_date"], row["provider_id"], pair)


def _group_by_game(rows: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        groups[_game_key(row)].append(row)
    return groups


def build_plan(rows: list[dict], excluded_rows: list[dict], live_by_event: dict[str, dict], snapshot_in: dict) -> dict:
    """Sort every stored game into what is applied, what waits for a second sighting and what is left."""
    seen_before = snapshot_in.get("changes", {})
    plan = {"correct": [], "hide": [], "waiting": [], "observed": {}}
    counts: Counter = Counter()
    live_rows, dead_rows = _group_by_game(rows), _group_by_game(excluded_rows)
    for row in rows:
        live = live_by_event.get(event_id_of(row["source_url"]))
        if live is None:
            counts["event_skipped"] += 1
            continue
        kind, score = classify(row, live)
        counts[kind] += 1
        if kind not in ACTIONABLE:
            continue
        key = _game_key(row)
        twin = next((o for o in live_rows[key] if o["id"] != row["id"] and _on_sides_of(row, o) == score), None)
        if not twin and any(_on_sides_of(row, o) == score for o in dead_rows[key]):
            counts["blocked_by_excluded_twin"] += 1
            continue
        if not twin and len(live_rows[key]) > 1:
            counts["ambiguous_stored"] += 1
            continue
        stored = [row["home_score"], row["away_score"]]
        plan["observed"][row["id"]] = {"stored": stored, "live": list(score)}
        if seen_before.get(row["id"]) != {"stored": stored, "live": list(score)}:
            plan["waiting"].append(row)
            continue
        plan["hide" if twin else "correct"].append({"row": row, "live": score, "twin": twin})
    plan["counts"] = dict(counts)
    return plan


def split_refused_hides(sb, plan: dict) -> list[dict]:
    """Take the hides that would also hide another game out of the plan; returns them.

    The check runs against every provider's live games on the hide dates, with this run's own
    corrections already applied, because a corrected row can come to match a stale row's key.
    """
    hide_rows = [item["row"] for item in plan["hide"]]
    if not hide_rows:
        return []
    corrected = {item["row"]["id"]: item["live"] for item in plan["correct"]}
    neighbours = [
        {**g, "home_score": corrected[g["id"]][0], "away_score": corrected[g["id"]][1]} if g["id"] in corrected else g
        for g in fetch_cascade_neighbours(sb, hide_rows)
    ]
    colliding_keys = {cascade_key(g) for g in cascade_collisions(hide_rows, neighbours)}
    refused = [item for item in plan["hide"] if cascade_key(item["row"]) in colliding_keys]
    plan["hide"] = [item for item in plan["hide"] if item not in refused]
    return refused


def apply_plan(sb, plan: dict, out_path: Path) -> dict:
    """Write the plan; returns the counts. The log is written before the first write and again after the last."""
    log = {
        "applied": False,
        "corrections": [
            {
                "game_id": item["row"]["id"],
                "game_uid": item["row"]["game_uid"],
                "from": [item["row"]["home_score"], item["row"]["away_score"]],
                "to": list(item["live"]),
                "outcome": "pending",
            }
            for item in plan["correct"]
        ],
        "hidden": [
            {
                "game_id": item["row"]["id"],
                "score": [item["row"]["home_score"], item["row"]["away_score"]],
                "twin_id": item["twin"]["id"],
                "outcome": "pending",
            }
            for item in plan["hide"]
        ],
    }
    out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")

    try:
        for item, entry in zip(plan["correct"], log["corrections"]):
            row, (home, away) = item["row"], item["live"]
            current = sb.table("games").select("home_score,away_score,is_excluded").eq("id", row["id"]).execute().data
            if not current or current[0] != {
                "home_score": row["home_score"],
                "away_score": row["away_score"],
                "is_excluded": False,
            }:
                entry["outcome"] = "skipped"
                continue
            applied = apply_score_correction(
                sb,
                game_uid=row["game_uid"],
                original={"home_score": row["home_score"], "away_score": row["away_score"]},
                corrected={"home_score": home, "away_score": away, "result": compute_result(home, away)},
                reason="tgs schedule now reports a different score",
                submitted_by=SUBMITTED_BY,
            )
            entry["outcome"] = "applied" if applied else "failed"
        for item, entry in zip(plan["hide"], log["hidden"]):
            row, twin = item["row"], item["twin"]
            fresh = (
                sb.table("games")
                .select("is_excluded,home_score,away_score,home_provider_id")
                .eq("id", twin["id"])
                .execute()
                .data
            )
            # Hiding the stale copy is only right while the twin it defers to is still live at the live score
            if not fresh or fresh[0]["is_excluded"] or _on_sides_of(row, {**twin, **fresh[0]}) != item["live"]:
                entry["outcome"] = "skipped"
                continue
            # A row whose score moved since it was read is no longer the stale copy
            res = (
                sb.table("games")
                .update({"is_excluded": True})
                .eq("id", row["id"])
                .eq("home_score", row["home_score"])
                .eq("away_score", row["away_score"])
                .eq("is_excluded", False)
                .execute()
            )
            entry["outcome"] = "applied" if res.data else "skipped"
    finally:
        log["applied"] = True
        out_path.write_text(json.dumps(log, indent=1), encoding="utf-8")
    entries = log["corrections"] + log["hidden"]
    return {
        "corrected": sum(e["outcome"] == "applied" for e in log["corrections"]),
        "hidden": sum(e["outcome"] == "applied" for e in log["hidden"]),
        "skipped": sum(e["outcome"] == "skipped" for e in entries),
        "failed": sum(e["outcome"] == "failed" for e in entries),
    }


def load_snapshot(path: str | None) -> dict:
    """The previous run's observations, or {} when none was given or its shape is not ours."""
    if not path:
        return {}
    if not Path(path).exists():
        raise SystemExit(f"--snapshot-in {path} does not exist")
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError:
        return {}
    changes = snapshot.get("changes") if isinstance(snapshot, dict) else None
    if not isinstance(changes, dict) or not all(
        isinstance(v, dict) and isinstance(v.get("stored"), list) and isinstance(v.get("live"), list)
        for v in changes.values()
    ):
        return {}
    return snapshot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="apply the confirmed changes (default is a dry run)")
    ap.add_argument(
        "--since", default=None, help=f"earliest game_date (YYYY-MM-DD); default {DEFAULT_LOOKBACK_DAYS} days ago"
    )
    ap.add_argument("--snapshot-in", default=None, help="the previous run's snapshot; without it nothing is confirmed")
    ap.add_argument("--snapshot-out", default=None, help="where an --execute run writes what it saw")
    ap.add_argument("--out", default=None, help="where to write the rollback log")
    ap.add_argument("--limit-events", type=int, default=None, help="compare only this many events")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    dry_run = not args.execute

    since = args.since or (date.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()
    snapshot_in = load_snapshot(args.snapshot_in)
    sb = get_client()
    rows = fetch_stored(sb, since)
    excluded_rows = fetch_stored(sb, since, excluded=True)
    event_ids = sorted({event_id_of(g["source_url"]) for g in rows})
    if args.limit_events:
        event_ids = event_ids[: args.limit_events]
        rows = [g for g in rows if event_id_of(g["source_url"]) in set(event_ids)]
    print(f"stored scored TGS games since {since}: {len(rows):,} in {len(event_ids):,} events")

    def read(event_id):
        try:
            return event_id, fetch_live_event(event_id)
        except LiveFetchError as e:
            print(f"   skipped event {event_id}: could not read {e!r}")
            return event_id, None

    with ThreadPoolExecutor(args.workers) as pool:
        live_by_event = {eid: live for eid, live in pool.map(read, event_ids) if live is not None}
    if event_ids and not live_by_event:
        print("every event failed to read; nothing compared")
        return 1

    plan = build_plan(rows, excluded_rows, live_by_event, snapshot_in)
    for name, n in sorted(plan["counts"].items()):
        print(f"   {name}: {n:,}")
    print(f"changes confirmed by the previous run: correct {len(plan['correct']):,}, hide {len(plan['hide']):,}")
    print(f"changes seen for the first time or since altered: {len(plan['waiting']):,}")

    snapshot = {"seen_at": datetime.now(UTC).isoformat(), "since": since, "changes": plan["observed"]}
    if args.snapshot_out and dry_run:
        print(f"DRY RUN — would write {len(plan['observed']):,} observations to {args.snapshot_out}")
    elif args.snapshot_out:
        Path(args.snapshot_out).write_text(json.dumps(snapshot, indent=1), encoding="utf-8")

    refused = split_refused_hides(sb, plan)
    print(f"hides refused because they would also hide another game: {len(refused):,}")
    for item in refused:
        g = item["row"]
        live_home, live_away = item["live"]
        print(f"   {g['game_date']}  {g['id']}  {g['home_score']}-{g['away_score']} -> {live_home}-{live_away}")

    if not plan["correct"] and not plan["hide"]:
        return 0
    if dry_run:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    out_path = Path(args.out) if args.out else Path(f"reconcile_tgs_scores_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    if out_path.exists():
        raise SystemExit(
            f"{out_path} already exists and is the only rollback record for that run. Pass a different --out."
        )
    done = apply_plan(sb, plan, out_path)
    print(
        f"\nCorrected {done['corrected']:,} games, hid {done['hidden']:,} games, "
        f"skipped {done['skipped']:,} that changed since read, failed {done['failed']:,}. Log: {out_path}"
    )
    print(
        "To undo: file a correction back to the 'from' score of each correction with outcome 'applied', "
        "and set is_excluded = false for each hidden game with outcome 'applied'."
    )
    return 1 if done["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
