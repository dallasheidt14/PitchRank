#!/usr/bin/env python3
"""
Viewed-teams enqueue: re-enqueue every team a signed-in subscriber opened in the
last day and a half, at priority 2, via the enqueue_scrape_request RPC (idempotent
UPSERT-with-LEAST).

The view itself is recorded by frontend/app/api/track-team-view. Every other
selector on the scrape path picks teams from fixture dates and scrape recency;
this one picks the teams somebody actually looked at, which is where a stale
scoreline is most likely to be noticed.

Admin views do not count. There is one admin account and it clicks through
hundreds of teams while investigating data, which would swamp the day's real
signal.

Does NOT scrape. process_missing_games (every 15min) drains.

Usage:
    python scripts/enqueue_viewed_teams.py
    python scripts/enqueue_viewed_teams.py --dry-run
    python scripts/enqueue_viewed_teams.py --limit 500 --window-hours 36 --cooldown-hours 20
"""

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

# Windows SSL workaround. Optional — CI runners use the system trust store.
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
    _chunks,
    _paged,
    load_team_rows,
    resolve_merges,
    teams_with_pending_user_request,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_VIEWED_TEAM = 2
REQUEST_TYPE = "viewed_team"
VIEW_TABLE = "team_page_views"

DEFAULT_LIMIT = 2000

# Twelve hours wider than the daily cadence. GitHub drops or delays scheduled runs
# under load, and a window equal to the cadence turns any delay into views nobody
# ever selects. Sized against the drift this repo has actually recorded, not a
# guess: enqueue-active-teams.yml documents a run sliding from 10:00 to 20:10 on
# 2026-08-27. A wholly skipped run would need ~54h to cover and is out of scope;
# re-enqueueing a team already queued is a no-op, so the overlap costs nothing.
DEFAULT_WINDOW_HOURS = 36

DEFAULT_COOLDOWN_HOURS = 20


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def collect_admin_user_ids(supabase):
    rows = _paged(lambda: supabase.table("user_profiles").select("id").eq("plan", "admin"))
    return {r["id"] for r in rows if r["id"]}


def collect_viewed_teams(supabase, window_hours=DEFAULT_WINDOW_HOURS, admin_ids=frozenset()):
    """Distinct teams opened inside the window, admin views excluded."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    rows = _paged(
        lambda: supabase.table(VIEW_TABLE).select("team_id_master,user_id").gte("viewed_at", cutoff)
    )
    return {r["team_id_master"] for r in rows if r["team_id_master"] and r["user_id"] not in admin_ids}


def teams_with_gotsport_alias(supabase, team_ids, gotsport_provider_id):
    """Teams the drainer can reach through an approved GotSport alias.

    Mirrors process_missing_games.get_gotsport_alias, which is the code that will
    actually follow the alias: same provider, same approved-only filter.
    """
    found = set()
    for batch in _chunks(sorted(team_ids)):
        rows = (
            supabase.table("team_alias_map")
            .select("team_id_master")
            .in_("team_id_master", batch)
            .eq("provider_id", gotsport_provider_id)
            .eq("review_status", "approved")
            .execute()
            .data
            or []
        )
        found.update(r["team_id_master"] for r in rows if r["team_id_master"])
    return found


def scraped_within_cooldown(last_scraped_at, cooldown_hours):
    """Whether a team was scraped recently enough to skip. Never scraped is not."""
    if not last_scraped_at:
        return False
    parsed = datetime.fromisoformat(last_scraped_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)


def enqueue_team(supabase, team):
    """Call enqueue_scrape_request RPC at priority 2.

    scrape_requests.game_date is NOT NULL, so we anchor on today. The processor
    scrapes a +/-90 day window around that anchor, which covers the season either
    side of whatever the viewer was looking at.
    """
    return supabase.rpc(
        "enqueue_scrape_request",
        {
            "p_team_id_master": team["team_id_master"],
            "p_team_name": team.get("team_name"),
            "p_provider_id": team.get("provider_id"),
            "p_provider_team_id": team.get("provider_team_id"),
            "p_game_date": date.today().isoformat(),
            "p_request_type": REQUEST_TYPE,
            "p_priority": PRIORITY_VIEWED_TEAM,
        },
    ).execute()


def select_targets(supabase, gotsport_provider_id, window_hours, cooldown_hours, limit):
    """The day's viewed teams, reduced to the ones worth enqueueing."""
    admin_ids = collect_admin_user_ids(supabase)
    viewed = collect_viewed_teams(supabase, window_hours=window_hours, admin_ids=admin_ids)
    logger.info(f"Viewed teams: {len(viewed)} distinct in last {window_hours}h (admin views excluded)")
    if not viewed:
        return []

    canonical = resolve_merges(supabase, viewed)
    merged = sum(1 for t, c in canonical.items() if t != c)
    target_ids = set(canonical.values())
    if merged:
        logger.info(f"Merge resolution: {merged} deprecated ids -> {len(target_ids)} canonical teams")

    team_rows = load_team_rows(supabase, target_ids)
    missing = target_ids - set(team_rows)
    if missing:
        logger.warning(f"{len(missing)} viewed teams have no teams row; skipping them")

    # process_missing_games only has a GotSport scraper, but it does not give up on a
    # team filed under another provider: it looks for an approved GotSport alias and
    # scrapes that instead. Filtering on teams.provider_id alone would discard teams
    # the drainer can serve, so admit those too and drop only the genuinely unservable.
    #
    # teams.provider_id is nullable, and process_missing_games validates the queue row
    # before it reaches that fallback, so a team carrying no provider of its own is
    # unservable whatever aliases it has. Enqueueing one buys a failed queue item.
    aliased = teams_with_gotsport_alias(supabase, set(team_rows), gotsport_provider_id)
    eligible = {
        tid: row
        for tid, row in team_rows.items()
        if row.get("provider_id") and (row["provider_id"] == gotsport_provider_id or tid in aliased)
    }
    if len(eligible) < len(team_rows):
        logger.info(
            f"{len(team_rows) - len(eligible)} viewed teams skipped: "
            f"no provider, or no GotSport row and no approved alias"
        )

    fresh = {
        tid: row
        for tid, row in eligible.items()
        if not scraped_within_cooldown(row.get("last_scraped_at"), cooldown_hours)
    }
    if len(fresh) < len(eligible):
        logger.info(f"{len(eligible) - len(fresh)} viewed teams skipped: scraped within {cooldown_hours}h")

    protected = teams_with_pending_user_request(supabase, set(fresh))
    if protected:
        logger.info(f"{len(protected)} teams hold a pending user request; leaving those rows untouched")

    targets = [fresh[tid] for tid in sorted(fresh) if tid not in protected]
    if len(targets) > limit:
        logger.info(f"Capping {len(targets)} targets at --limit {limit}")
        targets = targets[:limit]
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log targets without enqueueing")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help=f"Enqueue teams viewed within this many hours (default {DEFAULT_WINDOW_HOURS})",
    )
    parser.add_argument(
        "--cooldown-hours",
        type=int,
        default=DEFAULT_COOLDOWN_HOURS,
        help=f"Skip teams scraped within this many hours (default {DEFAULT_COOLDOWN_HOURS})",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)
    gotsport_provider_id = get_gotsport_provider_id(supabase)

    targets = select_targets(
        supabase,
        gotsport_provider_id,
        window_hours=args.window_hours,
        cooldown_hours=args.cooldown_hours,
        limit=args.limit,
    )

    if args.dry_run:
        for t in targets[:20]:
            logger.info(f"  WOULD ENQUEUE: {t['team_id_master']} ({t.get('team_name', 'unknown')})")
        logger.info(f"...({len(targets)} total)")
        return

    success, fail = 0, 0
    for t in targets:
        try:
            enqueue_team(supabase, t)
            success += 1
        except Exception as e:
            logger.warning(f"Failed to enqueue {t['team_id_master']}: {e}")
            fail += 1

    logger.info(f"Enqueued {success} teams at priority {PRIORITY_VIEWED_TEAM}, {fail} failed")


if __name__ == "__main__":
    main()
