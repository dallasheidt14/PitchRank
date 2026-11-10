#!/usr/bin/env python3
"""Hide the GotSport results that were never played, and the copies and fixtures they left.

GotSport can record a 3-0 for a match that was never played, in the cases seen a team's whole
league schedule at once, and sends no status that marks it. It has moved such matches to a
placeholder date (the season's first day, or the first day of a later month) with no field or
venue, and moved them again later. The importer copies date and score as given and
builds a game's uid from its date and team pair, so each move saves another row while the earlier
copy stays. All of these count as played games in the rankings.

A GotSport row is hidden when it is one of:

  whole slate   a 3-0 or 0-3 whose losing team, resolved through team_merge_map, lost 3-0 to WHOLE_SLATE_MIN or
                more different opponents in one competition on that date, and had no other
                GotSport result in that competition that day. No team plays that many games in a
                day, so these are the slate of a team that left the competition.
  early         a 3-0 or 0-3 whose current score was saved more than EARLY_MARGIN before the game's own date: the
                later of scraped_at and its newest approved score correction, which changes the
                score without touching scraped_at. A real score cannot exist before the game is
                played.

  copy          and, for each of those, the same resolved pairing in the same competition on
                another date in the same season: another 3-0 with the same loser and the same
                home team, which is the same forfeit stored again (a moved match keeps its home
                team; a return leg swaps it and may have been played), or an unscored
                fixture when one of the two teams is a whole-slate team there that season, which
                is a fixture that will not be played. An unscored fixture beside an early result
                alone is kept: the pair may still meet a second time.

A forfeit entered after its own date, where the team played its other games, looks exactly like a
real 3-0 and is out of reach here.

Games are immutable, so this sets is_excluded, which the team page and the ranking loader skip.
Excluding a row fires trg_propagate_game_exclusion, which also excludes every other game on that
date with the same saved pair and aligned scores, from any provider; --execute refuses while any
such game sits outside the run. Just before writing, --execute reads and selects everything again
and refuses if the selection changed or a collision appeared. Nothing in the import path clears is_excluded, and a
re-scrape of a hidden row stays hidden, so the log is the only way back: --revert replays it,
restoring the rows this run's own updates changed.

Usage:
    python scripts/exclude_unplayed_forfeit_games.py                       # dry run
    python scripts/exclude_unplayed_forfeit_games.py --show-group early    # list one group's rows
    python scripts/exclude_unplayed_forfeit_games.py --execute                     # log goes to data/backups/
    python scripts/exclude_unplayed_forfeit_games.py --revert data/backups/<log>.json --execute
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env.local", override=True)

from scripts.apply_vetted_team_merges import new_log, write_log  # noqa: E402
from scripts.exclude_merge_duplicate_games import load_merge_map, still_excluded  # noqa: E402
from scripts.exclude_none_opponent_games import cascade_collisions, cascade_key  # noqa: E402
from scripts.exclude_rescheduled_fixture_leftovers import resolved_pair  # noqa: E402
from scripts.exclude_unscored_fixture_twins import ID_BATCH, _linked, _paged, get_client  # noqa: E402
from scripts.reconcile_tgs_scores import fetch_cascade_neighbours  # noqa: E402
from src.etl.glicko_config import GlickoConfig  # noqa: E402

GAME_FIELDS = (
    "id,game_uid,provider_id,game_date,home_team_master_id,away_team_master_id,home_provider_id,away_provider_id,"
    "home_score,away_score,competition,scraped_at,is_excluded"
)
COUNT_FIELDS = "id,game_date,home_team_master_id,away_team_master_id,home_score,away_score"
FORFEIT_SCORES = frozenset({(3, 0), (0, 3)})
WHOLE_SLATE_MIN = 5
# Wider than any gap between a naive local scraped_at and UTC, and than any time zone's date offset
EARLY_MARGIN = timedelta(days=1)
# A week per read, so no page needs a deep offset
PAGE_WINDOW_DAYS = 7
GROUPS = ("whole_slate", "early", "copy")
SHAPES = ((3, 0), (0, 3), (None, None))
LOG_STEM = "exclude_unplayed_forfeit_games"
LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "backups"


def ranking_window_days() -> int:
    """How far back fetch_games_for_rankings reads, as calculator._effective_fetch_lookback_days sets it."""
    return GlickoConfig.WINDOW_DAYS + max(GlickoConfig.WINDOW_GRACE_DAYS, 0)


def is_forfeit(game: dict) -> bool:
    return (game["home_score"], game["away_score"]) in FORFEIT_SCORES


def is_unscored(game: dict) -> bool:
    return game["home_score"] is None and game["away_score"] is None


def is_scored(game: dict) -> bool:
    return game["home_score"] is not None and game["away_score"] is not None


def is_linked(game: dict) -> bool:
    return bool(game["home_team_master_id"] and game["away_team_master_id"])


def resolve(merge_map: dict[str, str], team: str | None) -> str | None:
    return merge_map.get(team, team)


def loser(game: dict, merge_map: dict[str, str]) -> str | None:
    side = "home_team_master_id" if game["home_score"] < game["away_score"] else "away_team_master_id"
    return resolve(merge_map, game[side])


def host_and_loser(game: dict, merge_map: dict[str, str]) -> tuple:
    return resolve(merge_map, game["home_team_master_id"]), loser(game, merge_map)


def season(game_date: str) -> int:
    """The Aug 1 - Jul 31 season a date falls in, named by its first year."""
    day = date.fromisoformat(game_date)
    return day.year if day.month >= 8 else day.year - 1


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    stamp = datetime.fromisoformat(value)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def scored_early(game: dict, corrected_at: dict[str, datetime]) -> bool:
    saved = _timestamp(game.get("scraped_at"))
    corrected = corrected_at.get(game["game_uid"])
    if saved is not None and corrected is not None:
        saved = max(saved, corrected)
    day_starts = datetime.combine(date.fromisoformat(game["game_date"]), time.min, UTC)
    return saved is not None and saved < day_starts - EARLY_MARGIN


def date_windows(first: str, last: str):
    start, end = date.fromisoformat(first), date.fromisoformat(last)
    while start <= end:
        stop = min(start + timedelta(days=PAGE_WINDOW_DAYS - 1), end)
        yield start.isoformat(), stop.isoformat()
        start = stop + timedelta(days=1)


def fetch_forfeits(sb, provider_id: str, since: str) -> list[dict]:
    """Live, linked 3-0 and 0-3 rows of provider_id dated since or later, future dates included."""
    def bounded(q):
        return (q.eq("provider_id", provider_id).eq("is_excluded", False)
                .in_("home_score", [0, 3]).in_("away_score", [0, 3]))

    last = (bounded(sb.table("games").select("game_date")).gte("game_date", since)
            .order("game_date", desc=True).limit(1).execute().data)
    if not last:
        return []
    rows: dict[str, dict] = {}
    for first, stop in date_windows(since, last[0]["game_date"]):
        for g in _paged(lambda a=first, b=stop: bounded(sb.table("games").select(GAME_FIELDS))
                        .lte("game_date", b).gte("game_date", a).order("id", desc=False)):
            rows[g["id"]] = g
    return [g for g in _linked(list(rows.values())) if is_forfeit(g)]


def fetch_corrected_at(sb, game_uids: list[str]) -> dict[str, datetime]:
    """When an approved correction last changed each game's score."""
    latest: dict[str, datetime] = {}
    for i in range(0, len(game_uids), ID_BATCH):
        for c in _paged(lambda b=game_uids[i : i + ID_BATCH]: sb.table("game_corrections")
                        .select("original_game_uid,approved_at")
                        .eq("correction_type", "score").eq("status", "approved")
                        .in_("original_game_uid", b).order("id", desc=False)):
            approved, previous = _timestamp(c["approved_at"]), latest.get(c["original_game_uid"])
            if approved is not None and (previous is None or approved > previous):
                latest[c["original_game_uid"]] = approved
    return latest


def fetch_ranking_exclusions(sb, merge_map: dict[str, str]) -> set[str]:
    """The teams fetch_games_for_rankings drops every game of, resolved as the games it reads are."""
    rows = _paged(lambda: sb.table("team_ranking_exclusions").select("team_id_master")
                  .order("team_id_master", desc=False))
    return {resolve(merge_map, r["team_id_master"]) for r in rows}


def fetch_team_games(sb, team_ids: list[str], *, provider_id: str | None = None, since: str | None = None,
                     until: str | None = None, fields: str = GAME_FIELDS) -> list[dict]:
    """Live games with either side among team_ids, whatever the other side holds, including no master id."""
    rows: dict[str, dict] = {}
    for i in range(0, len(team_ids), ID_BATCH):
        batch = team_ids[i : i + ID_BATCH]
        for side in ("home_team_master_id", "away_team_master_id"):
            def query(b=batch, s=side):
                q = sb.table("games").select(fields).eq("is_excluded", False).in_(s, b)
                if provider_id:
                    q = q.eq("provider_id", provider_id)
                if since:
                    q = q.gte("game_date", since)
                if until:
                    q = q.lte("game_date", until)
                return q.order("id", desc=False)

            for g in _paged(query):
                rows[g["id"]] = g
    return list(rows.values())


def saved_ids(teams: set[str], merge_map: dict[str, str], absorbed: dict[str, set[str]]) -> list[str]:
    ids: set[str] = set()
    for team in teams:
        canonical = resolve(merge_map, team)
        ids.update((canonical, *absorbed[canonical]))
    return sorted(ids)


def whole_slate_groups(forfeits: list[dict], merge_map: dict[str, str]) -> dict[tuple, list[dict]]:
    """(loser, date, competition) -> its 3-0 rows, where the loser met WHOLE_SLATE_MIN or more opponents."""
    losses: dict[tuple, list[dict]] = defaultdict(list)
    for g in forfeits:
        losses[(loser(g, merge_map), g["game_date"], g["competition"])].append(g)
    return {
        key: rows for key, rows in losses.items()
        if len({t for g in rows for t in resolved_pair(g, merge_map)} - {key[0]}) >= WHOLE_SLATE_MIN
    }


def select_unplayed(
    slates: dict[tuple, list[dict]], early: list[dict], related: list[dict], merge_map: dict[str, str]
) -> dict[str, dict]:
    """Rows to hide, by id, each as {"game": row, "labels": [...]}.

    related holds every live GotSport row of the teams of the whole-slate and early rows, partly linked
    ones included, from the start of the sweep.
    """
    chosen: dict[str, dict] = {}

    def add(game: dict, label: str) -> None:
        entry = chosen.setdefault(game["id"], {"game": game, "labels": []})
        if label not in entry["labels"]:
            entry["labels"].append(label)

    withdrawn: set[tuple] = set()
    for (team, game_date, competition), rows in slates.items():
        theirs = [
            g for g in related
            if g["game_date"] == game_date and g["competition"] == competition and is_scored(g)
            and team in {resolve(merge_map, g["home_team_master_id"]), resolve(merge_map, g["away_team_master_id"])}
        ]
        if all(is_forfeit(g) and loser(g, merge_map) == team for g in theirs):
            withdrawn.add((team, competition, season(game_date)))
            for g in rows:
                add(g, "whole_slate")
    for g in early:
        add(g, "early")

    sources: dict[tuple, list[dict]] = defaultdict(list)
    for entry in list(chosen.values()):
        source = entry["game"]
        sources[(resolved_pair(source, merge_map), source["competition"], season(source["game_date"]))].append(source)
    for g in related:
        if g["id"] in chosen or not is_linked(g):
            continue
        pair, game_season = resolved_pair(g, merge_map), season(g["game_date"])
        for source in sources[(pair, g["competition"], game_season)]:
            if g["game_date"] != source["game_date"] and (
                (is_forfeit(g) and host_and_loser(g, merge_map) == host_and_loser(source, merge_map))
                or (is_unscored(g) and any((t, g["competition"], game_season) in withdrawn for t in pair))
            ):
                add(g, "copy")
                break
    return chosen


def log_rows(chosen: dict[str, dict]) -> list[dict]:
    """In the order they are sent: one run of batches per score shape, each guarded on that shape."""
    rows = []
    for entry in chosen.values():
        g = entry["game"]
        rows.append({
            "id": g["id"],
            "labels": entry["labels"],
            "game_date": g["game_date"],
            "competition": g["competition"],
            "home_team_master_id": g["home_team_master_id"],
            "away_team_master_id": g["away_team_master_id"],
            "home_score": g["home_score"],
            "away_score": g["away_score"],
        })
    return sorted(rows, key=lambda r: (SHAPES.index((r["home_score"], r["away_score"])), r["id"]))


def guarded_update(sb, ids: list[str], shape: tuple):
    q = sb.table("games").update({"is_excluded": True}).in_("id", ids).eq("is_excluded", False)
    if shape == (None, None):
        return q.is_("home_score", "null").is_("away_score", "null").execute()
    return q.eq("home_score", shape[0]).eq("away_score", shape[1]).execute()


def blast_radius(rows: list[dict], counted: list[dict], merge_map: dict[str, str], excluded_teams: set[str],
                 window_start: date, today: date) -> dict:
    """How the run changes what the ranking loader reads: games removed, teams touched, and teams pushed below
    the floor or to zero."""
    first, last = window_start.isoformat(), today.isoformat()

    def teams_of(g: dict) -> set:
        return {resolve(merge_map, g["home_team_master_id"]), resolve(merge_map, g["away_team_master_id"])}

    removed = {
        r["id"] for r in rows
        if first <= r["game_date"] <= last and r["home_score"] is not None and not teams_of(r) & excluded_teams
    }
    before: Counter = Counter()
    after: Counter = Counter()
    touched: set[str] = set()
    for g in counted:
        teams = teams_of(g)
        if teams & excluded_teams:
            continue
        for team in teams:
            before[team] += 1
            if g["id"] in removed:
                touched.add(team)
            else:
                after[team] += 1
    floor = GlickoConfig.MIN_GAMES_PROVISIONAL
    return {
        "games_counted_now": len(removed),
        "teams": len(touched),
        "below_floor": sorted((t, before[t], after[t]) for t in touched if before[t] >= floor > after[t]),
        "at_zero": sorted((t, before[t]) for t in touched if after[t] == 0),
        "floor": floor,
    }


def build_plan(sb, provider_id: str, since: str, today: date) -> dict:
    merge_map = load_merge_map(sb)
    absorbed: dict[str, set[str]] = defaultdict(set)
    for deprecated, canonical in merge_map.items():
        absorbed[canonical].add(deprecated)

    forfeits = fetch_forfeits(sb, provider_id, since)
    corrected_at = fetch_corrected_at(sb, sorted({g["game_uid"] for g in forfeits if scored_early(g, {})}))
    early = [g for g in forfeits if scored_early(g, corrected_at)]
    slates = whole_slate_groups(forfeits, merge_map)
    sources = [g for rows in slates.values() for g in rows] + early
    source_teams = {t for g in sources for t in (g["home_team_master_id"], g["away_team_master_id"])}
    related = fetch_team_games(sb, saved_ids(source_teams, merge_map, absorbed), provider_id=provider_id, since=since)

    chosen = select_unplayed(slates, early, related, merge_map)
    games = [entry["game"] for entry in chosen.values()]
    collisions = cascade_collisions(games, fetch_cascade_neighbours(sb, games))
    rows = log_rows(chosen)

    window_start = today - timedelta(days=ranking_window_days())
    touched = {resolve(merge_map, t) for r in rows for t in (r["home_team_master_id"], r["away_team_master_id"])}
    counted = [
        g for g in fetch_team_games(sb, saved_ids(touched, merge_map, absorbed), fields=COUNT_FIELDS,
                                    since=window_start.isoformat(), until=today.isoformat())
        if is_scored(g) and is_linked(g)
    ]
    radius = blast_radius(rows, counted, merge_map, fetch_ranking_exclusions(sb, merge_map), window_start, today)
    return {"scanned": len(forfeits), "chosen": chosen, "rows": rows, "collisions": collisions,
            "radius": radius, "merge_map": merge_map}


def selection(plan: dict) -> list[tuple]:
    return [(r["id"], r["home_score"], r["away_score"], tuple(r["labels"])) for r in plan["rows"]]


def report(plan: dict, since: str, today: date, show_group: str | None) -> None:
    rows, radius, merge_map = plan["rows"], plan["radius"], plan["merge_map"]
    print(f"3-0 / 0-3 GotSport results dated {since} or later scanned: {plan['scanned']:,}")
    for group in GROUPS:
        print(f"   {group}: {sum(1 for r in rows if group in r['labels']):,}")
    print(f"rows to hide: {len(rows):,}")
    print(f"   counted by rankings now: {radius['games_counted_now']:,}")
    print(f"   future-dated: {sum(1 for r in rows if r['game_date'] > today.isoformat()):,}")
    print(f"   unscored fixtures: {sum(1 for r in rows if r['home_score'] is None):,}")
    print(f"   saved under a team since merged away: "
          f"{sum(1 for r in rows if {r['home_team_master_id'], r['away_team_master_id']} & merge_map.keys()):,}")
    for month, n in sorted(Counter(r["game_date"][:7] for r in rows).items()):
        print(f"   {month}: {n:,}")
    print(f"teams losing a counted game: {radius['teams']:,} ({radius['games_counted_now']:,} games)")
    print(f"   falling below {radius['floor']} games in the ranking window: {len(radius['below_floor']):,}")
    for team, games_before, games_after in radius["below_floor"]:
        print(f"      {team}  {games_before} -> {games_after}")
    print(f"   left with no games in the ranking window: {len(radius['at_zero']):,}")
    for team, games_before in radius["at_zero"]:
        print(f"      {team}  {games_before} -> 0")
    print(f"cascade collisions: {len(plan['collisions']):,}")
    for g in plan["collisions"]:
        print(f"   {g['game_date']}  {g['id']}  {g['home_score']}-{g['away_score']}")
    for group in GROUPS:
        for r in [r for r in rows if group in r["labels"]][: None if group == show_group else 5]:
            g = plan["chosen"][r["id"]]["game"]
            print(f"   {group:11} {r['game_date']}  {r['id']}  "
                  f"{g['home_provider_id']} v {g['away_provider_id']}  "
                  f"{r['home_score']}-{r['away_score']}  {r['competition']}")


def revert(sb, path: Path, execute: bool) -> int:
    """Set is_excluded back to false, while still true, on the rows this run's updates changed, the batch
    whose reply never came, and any logged row sharing a trigger key with one of them. Stamped once every such
    row is restored, so a replay cannot undo another run's exclusion of the same games."""
    logged = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(logged, dict) or logged.get("stem") != LOG_STEM or not isinstance(logged.get("rows"), list):
        raise SystemExit(f"{path} holds no {LOG_STEM}.py log")
    if logged.get("reverted_at"):
        print(f"{path} was reverted at {logged['reverted_at']} — nothing to do")
        return 0
    changed, inflight = logged.get("changed"), logged.get("inflight")
    if not isinstance(changed, list) or not isinstance(inflight, list):
        raise SystemExit(f"{path} records no rows changed; settle its games by hand")
    rows = logged["rows"]
    reached = set(changed) | set(inflight)
    keys = {cascade_key(r) for r in rows if r["id"] in reached} - {None}
    ids = [r["id"] for r in rows if r["id"] in reached or cascade_key(r) in keys]
    hidden = still_excluded(sb, ids)
    print(f"games {path} excluded: {len(ids):,}, of which still excluded: {len(hidden):,}")
    if not execute:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0
    restored = 0
    for i in range(0, len(ids), ID_BATCH):
        res = (sb.table("games").update({"is_excluded": False})
               .in_("id", ids[i : i + ID_BATCH]).eq("is_excluded", True).execute())
        restored += len(res.data or [])
    print(f"\nRestored {restored:,} game rows.")
    if restored != len(hidden):
        print(f"WARNING: {len(hidden) - restored:,} still-hidden rows were not restored (does this key have write "
              f"access?). {path} is not stamped, so the revert can be run again.")
        return 1
    write_log(path, {**logged, "reverted_at": datetime.now(UTC).isoformat()})
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--execute", action="store_true", help="write is_excluded (default is a dry run)")
    ap.add_argument("--since", default=None,
                    help="earliest game_date to consider (default: the start of the ranking window)")
    ap.add_argument("--out", default=None, help=f"where to write the rollback log (default: {LOG_DIR})")
    ap.add_argument("--show-group", choices=GROUPS, default=None, help="list every row in one group")
    ap.add_argument("--revert", default=None, help="this script's own log: un-exclude the games it excluded")
    args = ap.parse_args()
    if args.revert and (args.since or args.out or args.show_group):
        ap.error("--revert undoes the whole log it is given and takes only --execute")

    sb = get_client()
    if args.revert:
        return revert(sb, Path(args.revert), args.execute)

    today = date.today()
    since = args.since or (today - timedelta(days=ranking_window_days())).isoformat()
    gotsport_id = sb.table("providers").select("id").eq("code", "gotsport").execute().data[0]["id"]
    plan = build_plan(sb, gotsport_id, since, today)
    report(plan, since, today, args.show_group)
    rows = plan["rows"]

    if not rows:
        return 0

    if not args.execute:
        print("\nDRY RUN — nothing written. Re-run with --execute.")
        return 0

    if plan["collisions"]:
        print("\nRefusing --execute: excluding these games would also exclude the collisions above.")
        return 1

    again = build_plan(sb, gotsport_id, since, today)
    if selection(again) != selection(plan) or again["collisions"]:
        print("\nRefusing --execute: the games changed while the run was reading them. Nothing was written; "
              "run it again.")
        return 1

    out_path = new_log(args.out, LOG_DIR, LOG_STEM)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Written before each batch is sent, so a run killed outright still names every row it may have reached
    log = {"stem": LOG_STEM, "applied": False, "sent": 0, "changed": [], "inflight": [], "rows": rows}
    write_log(out_path, log)
    try:
        for shape in SHAPES:
            ids = [r["id"] for r in rows if (r["home_score"], r["away_score"]) == shape]
            for i in range(0, len(ids), ID_BATCH):
                batch = ids[i : i + ID_BATCH]
                log.update(sent=log["sent"] + len(batch), inflight=batch)
                write_log(out_path, log)
                done = [g["id"] for g in guarded_update(sb, batch, shape).data or []]
                log.update(changed=log["changed"] + done, inflight=[])
    finally:
        log["applied"] = True
        write_log(out_path, log)

    hidden = still_excluded(sb, [r["id"] for r in rows])
    print(f"\nExcluded {len(log['changed']):,} rows; {len(hidden):,} of {len(rows):,} logged rows now read back "
          f"hidden. Log: {out_path}")
    status = 0
    if len(hidden) != len(rows):
        print(f"WARNING: {len(rows) - len(hidden):,} logged rows are not hidden — the run stopped early "
              "or another process changed them first.")
        status = 1
    print(f"To undo: python scripts/exclude_unplayed_forfeit_games.py --revert {out_path}  (a dry run; add --execute)")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
