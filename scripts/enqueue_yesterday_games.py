#!/usr/bin/env python3
"""
Daily enqueue: queue one GotSport team per game from yesterday that still has
no score, at priority 2, via the enqueue_scrape_request RPC.

Either team's scrape fills the shared game row, so queueing both sides of every
game doubles the work. This reads yesterday's NULL-score games and picks a small
set of teams that covers all of them (a greedy cover). A merged-away side is
queued as its survivor. A side that cannot be scraped -- no team row, deprecated
with no survivor, already scraped today, a placeholder provider id, or an active
queue row that cannot cover the game (any processing row, or a pending row for
another registration or provider, or dated more than 90 days away) -- leaves its
game to the opponent.

Does NOT scrape. process_missing_games drains.

Usage:
    python scripts/enqueue_yesterday_games.py
    python scripts/enqueue_yesterday_games.py --dry-run
"""
import argparse
import heapq
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

# Windows SSL workaround (see project memory gotcha_python_supabase_ssl_truststore).
# truststore must be injected BEFORE supabase is imported. Optional — CI runners
# that use the system trust store don't need it; only Windows local runs do.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv  # noqa: E402

from supabase import create_client  # noqa: E402

load_dotenv(".env.local")
load_dotenv(".env")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.enqueue_helpers import (  # noqa: E402
    PAGE_SIZE,
    _chunks,
    expand_to_aliases,
    load_team_rows,
    resolve_merges,
)
from src.utils.provider_ids import is_blank_provider_id  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_YESTERDAY_GAME = 2
REQUEST_TYPE = "yesterday_game"

GAME_COLUMNS = "id,home_team_master_id,away_team_master_id,home_provider_id,away_provider_id"
TEAM_COLUMNS = "team_id_master,team_name,is_deprecated,last_scraped_at"
ACTIVE_REQUEST_COLUMNS = "id,team_id_master,status,provider_id,provider_team_id,game_date,requested_at"
ACTIVE_STATUSES = ["pending", "processing"]
REQUEST_WINDOW_DAYS = 90

SKIP_REASONS = (
    "no_master",
    "blank_provider_id",
    "missing_team",
    "deprecated",
    "scraped_today",
    "active_request_conflict",
)


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def fetch_unscored_games(supabase, provider_id, game_date):
    """The provider's games on game_date with no home score -- find_yesterday_null_score_teams' filters.

    Pages by id rather than by offset: scores land while the read runs, and each
    one shrinks the filtered set, which would shift an offset past an unread game.
    """
    games, after = [], None
    while True:
        query = (
            supabase.table("games")
            .select(GAME_COLUMNS)
            .eq("game_date", game_date)
            .eq("provider_id", provider_id)
            .is_("home_score", "null")
        )
        if after is not None:
            query = query.gt("id", after)
        batch = query.order("id").limit(PAGE_SIZE).execute().data or []
        games.extend(batch)
        if len(batch) < PAGE_SIZE:
            return games
        after = batch[-1]["id"]


def load_active_requests(supabase, canonical):
    """Pending and processing queue rows, keyed by surviving team id.

    enqueue_scrape_request matches a row stored under any id merged into the
    survivor, so this reads under every such id, not only those the games carry.
    """
    survivor_of = expand_to_aliases(supabase, canonical)
    active = {}
    for batch in _chunks(sorted(survivor_of)):
        rows = (
            supabase.table("scrape_requests")
            .select(ACTIVE_REQUEST_COLUMNS)
            .in_("team_id_master", batch)
            .in_("status", ACTIVE_STATUSES)
            .execute()
            .data
            or []
        )
        for r in rows:
            active.setdefault(survivor_of[r["team_id_master"]], []).append(r)
    return active


def scraped_today(last_scraped_at, today):
    """Whether the team was last scraped on or after today's UTC date. Never scraped is not."""
    if not last_scraped_at:
        return False
    parsed = datetime.fromisoformat(last_scraped_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date() >= today


def _reusable(row, unit, gotsport_provider_id, yesterday):
    row_date = date.fromisoformat(row["game_date"])
    return (
        row["provider_id"] == gotsport_provider_id
        and row["provider_team_id"] == unit[1]
        and row_date <= yesterday
        and abs((yesterday - row_date).days) <= REQUEST_WINDOW_DAYS
    )


def active_request_verdict(rows, unit, gotsport_provider_id, yesterday):
    """What enqueue_scrape_request would do with this unit, given its team's active rows.

    Returns "none" (no active row), "reuse" (a compatible pending row the RPC
    adopts and promotes), "already_queued" (a pending row whose +/-90 day scrape
    covers yesterday but which the RPC would reject because it is dated after
    yesterday), or "conflict".

    A processing row counts as a conflict: nothing reclaims a stranded one, so it
    cannot be trusted to cover the game, and the opponent can.
    """
    if not rows:
        return "none"

    def rpc_order(r):
        return (not _reusable(r, unit, gotsport_provider_id, yesterday), r["requested_at"], r["id"])

    row = min(rows, key=rpc_order)
    row_date = date.fromisoformat(row["game_date"])
    if (
        row["status"] != "pending"
        or row["provider_id"] != gotsport_provider_id
        or row["provider_team_id"] != unit[1]
        or abs((yesterday - row_date).days) > REQUEST_WINDOW_DAYS
    ):
        return "conflict"
    return "reuse" if row_date <= yesterday else "already_queued"


def pick_cover(game_candidates):
    """Pick units (team_id_master, provider_team_id) so every game holds at least one.

    game_candidates has one set of eligible units per game. Returns the picked
    units sorted, the number of games with no eligible unit, and the number left
    uncovered because their only units were sibling registrations of a team
    already picked -- the queue holds one active row per team.

    Games with a single eligible unit are settled before the greedy pass, so a
    team's only registration for one game is not crowded out by a sibling that
    merely covers more games.
    """
    games_of = {}
    for i, units in enumerate(game_candidates):
        for unit in units:
            games_of.setdefault(unit, set()).add(i)

    picked, picked_masters, covered = [], set(), set()

    def take(unit):
        picked.append(unit)
        picked_masters.add(unit[0])
        covered.update(games_of[unit])

    for unit in sorted({next(iter(units)) for units in game_candidates if len(units) == 1}):
        if unit[0] not in picked_masters:
            take(unit)

    heap = [(-len(games), unit) for unit, games in games_of.items()]
    heapq.heapify(heap)
    while heap:
        neg_gain, unit = heapq.heappop(heap)
        if unit[0] in picked_masters:
            continue
        gain = len(games_of[unit] - covered)
        if gain == 0:
            continue
        if gain != -neg_gain:
            heapq.heappush(heap, (-gain, unit))
            continue
        take(unit)

    uncovered_no_side = sum(1 for units in game_candidates if not units)
    uncovered_sibling_blocked = sum(1 for i, units in enumerate(game_candidates) if units and i not in covered)
    return sorted(picked), uncovered_no_side, uncovered_sibling_blocked


def find_teams_to_enqueue(supabase, gotsport_provider_id, yesterday, today):
    """Pick the teams to queue for yesterday's unscored games. Returns (picks, stats)."""
    games = fetch_unscored_games(supabase, gotsport_provider_id, yesterday.isoformat())
    stats = {"games": len(games), **{reason: 0 for reason in SKIP_REASONS}}

    raw_ids = {g[f"{side}_team_master_id"] for g in games for side in ("home", "away")} - {None}
    canonical = resolve_merges(supabase, raw_ids)
    teams = load_team_rows(supabase, set(canonical.values()), TEAM_COLUMNS)
    active = load_active_requests(supabase, canonical)

    old_rule_masters, verdicts, game_candidates = set(), {}, []
    for g in games:
        units = set()
        for side in ("home", "away"):
            raw = g[f"{side}_team_master_id"]
            provider_team_id = g[f"{side}_provider_id"]
            if raw is None:
                stats["no_master"] += 1
                continue
            master = canonical[raw]
            team = teams.get(master)
            # The SQL selectors test is_deprecated = false, so NULL counts as deprecated.
            deprecated = team is not None and team["is_deprecated"] is not False
            live_and_unscraped = (
                team is not None and not deprecated and not scraped_today(team["last_scraped_at"], today)
            )
            # find_yesterday_null_score_teams tests provider ids with IS NOT NULL only, so a placeholder passes it.
            if provider_team_id is not None and live_and_unscraped:
                old_rule_masters.add(master)

            if is_blank_provider_id(provider_team_id):
                stats["blank_provider_id"] += 1
            elif team is None:
                stats["missing_team"] += 1
            elif deprecated:
                stats["deprecated"] += 1
            elif scraped_today(team["last_scraped_at"], today):
                stats["scraped_today"] += 1
            else:
                unit = (master, str(provider_team_id))
                if unit not in verdicts:
                    verdicts[unit] = active_request_verdict(
                        active.get(master, []), unit, gotsport_provider_id, yesterday
                    )
                if verdicts[unit] == "conflict":
                    stats["active_request_conflict"] += 1
                else:
                    units.add(unit)
        game_candidates.append(units)

    picked, stats["uncovered_no_side"], stats["uncovered_sibling_blocked"] = pick_cover(game_candidates)
    picks = [
        {
            "team_id_master": master,
            "team_name": teams[master].get("team_name"),
            "provider_team_id": provider_team_id,
            "enqueue": verdicts[(master, provider_team_id)] != "already_queued",
        }
        for master, provider_team_id in picked
    ]
    stats["old_rule_teams"] = len(old_rule_masters)
    stats["picked"] = len(picks)
    stats["already_queued"] = sum(1 for p in picks if not p["enqueue"])
    return picks, stats


def enqueue_team(supabase, team_id_master, team_name, provider_id, provider_team_id, game_date):
    """Call enqueue_scrape_request RPC at priority 2."""
    return supabase.rpc("enqueue_scrape_request", {
        "p_team_id_master": team_id_master,
        "p_team_name": team_name,
        "p_provider_id": provider_id,
        "p_provider_team_id": provider_team_id,
        "p_game_date": game_date,
        "p_request_type": REQUEST_TYPE,
        "p_priority": PRIORITY_YESTERDAY_GAME,
    }).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log targets without enqueueing")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)
    provider_id = get_gotsport_provider_id(supabase)
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)

    picks, stats = find_teams_to_enqueue(supabase, provider_id, yesterday, today)
    logger.info(
        f"{stats['games']} unscored games on {yesterday}; "
        f"old rule would queue {stats['old_rule_teams']} teams; "
        f"queueing {stats['picked']} ({stats['already_queued']} already queued); "
        f"{stats['uncovered_no_side']} games had no scrapeable side, "
        f"{stats['uncovered_sibling_blocked']} blocked by a sibling registration"
    )
    logger.info("Sides skipped: " + ", ".join(f"{reason} {stats[reason]}" for reason in SKIP_REASONS))

    if args.dry_run:
        for t in picks[:20]:
            note = "" if t["enqueue"] else " [already queued]"
            logger.info(f"  WOULD ENQUEUE: {t['team_id_master']} ({t.get('team_name', 'unknown')}){note}")
        logger.info(f"...({len(picks)} total)")
        return

    success, fail = 0, 0
    for t in picks:
        if not t["enqueue"]:
            continue
        try:
            enqueue_team(
                supabase,
                team_id_master=t["team_id_master"],
                team_name=t.get("team_name"),
                provider_id=provider_id,
                provider_team_id=t["provider_team_id"],
                game_date=yesterday.isoformat(),
            )
            success += 1
        except Exception as e:
            logger.warning(f"Failed to enqueue {t['team_id_master']}: {e}")
            fail += 1

    logger.info(f"Enqueued {success} teams at priority {PRIORITY_YESTERDAY_GAME}, {fail} failed")


if __name__ == "__main__":
    main()
