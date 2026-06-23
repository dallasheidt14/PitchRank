#!/usr/bin/env python3
"""
Active-teams enqueue: find GotSport teams that played in the last few days and
re-enqueue them at priority 2 via the enqueue_scrape_request RPC (idempotent
UPSERT-with-LEAST). Catches new games an actively-playing team accrues
day-to-day — tournament bracket rounds, late-added fixtures — that the daily
yesterday-game enqueue can't see (no in-DB fixture yet) and that discovery
skips (team still has future games on record).

Does NOT scrape. process_missing_games (every 15min, 200/run) drains.

A per-team cooldown skips teams scraped within the last few hours so we don't
waste scrape budget re-pulling a team we just scraped.

Usage:
    python scripts/enqueue_active_teams.py
    python scripts/enqueue_active_teams.py --dry-run
    python scripts/enqueue_active_teams.py --limit 500 --window-days 7 --cooldown-hours 24
"""

import argparse
import logging
import os
import sys
from datetime import date

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_ACTIVE_TEAM = 2
REQUEST_TYPE = "active_team"
DEFAULT_LIMIT = 2000
DEFAULT_WINDOW_DAYS = 3
DEFAULT_COOLDOWN_HOURS = 20


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def find_teams_to_enqueue(
    supabase,
    gotsport_provider_id,
    window_days=DEFAULT_WINDOW_DAYS,
    cooldown_hours=DEFAULT_COOLDOWN_HOURS,
    limit=DEFAULT_LIMIT,
):
    """GotSport teams active in the last window_days, scraped > cooldown_hours ago.
    Uses find_recently_active_teams RPC."""
    r = supabase.rpc(
        "find_recently_active_teams",
        {
            "p_provider_id": gotsport_provider_id,
            "p_active_window_days": window_days,
            "p_cooldown_hours": cooldown_hours,
            "p_row_limit": limit,
        },
    ).execute()
    rows = r.data or []
    seen = {}
    for row in rows:
        seen[row["team_id_master"]] = row
    return list(seen.values())


def enqueue_team(supabase, team_id_master, team_name, provider_id, provider_team_id):
    """Call enqueue_scrape_request RPC at priority 2.

    scrape_requests.game_date is NOT NULL, so we pass today's date as a placeholder.
    The processor scrapes the team's full schedule (±90 days from this anchor), which
    captures whatever new games the team has accrued. The RPC's UPDATE branch uses
    COALESCE, so existing pending rows keep their original game_date when upserted.
    """
    return supabase.rpc(
        "enqueue_scrape_request",
        {
            "p_team_id_master": team_id_master,
            "p_team_name": team_name,
            "p_provider_id": provider_id,
            "p_provider_team_id": provider_team_id,
            "p_game_date": date.today().isoformat(),
            "p_request_type": REQUEST_TYPE,
            "p_priority": PRIORITY_ACTIVE_TEAM,
        },
    ).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log targets without enqueueing")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help="Count a team active if it played within this many days (default 3)",
    )
    parser.add_argument(
        "--cooldown-hours",
        type=int,
        default=DEFAULT_COOLDOWN_HOURS,
        help="Skip teams scraped within this many hours (default 20)",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)
    provider_id = get_gotsport_provider_id(supabase)

    teams = find_teams_to_enqueue(
        supabase,
        provider_id,
        window_days=args.window_days,
        cooldown_hours=args.cooldown_hours,
        limit=args.limit,
    )
    logger.info(
        f"Active teams: {len(teams)} GotSport teams played in last {args.window_days}d "
        f"and not scraped in last {args.cooldown_hours}h"
    )

    if args.dry_run:
        for t in teams[:20]:
            logger.info(f"  WOULD ENQUEUE: {t['team_id_master']} ({t.get('team_name', 'unknown')})")
        logger.info(f"...({len(teams)} total)")
        return

    success, fail = 0, 0
    for t in teams:
        try:
            enqueue_team(
                supabase,
                team_id_master=t["team_id_master"],
                team_name=t.get("team_name"),
                provider_id=provider_id,
                provider_team_id=t.get("provider_team_id"),
            )
            success += 1
        except Exception as e:
            logger.warning(f"Failed to enqueue {t['team_id_master']}: {e}")
            fail += 1

    logger.info(f"Enqueued {success} teams at priority {PRIORITY_ACTIVE_TEAM}, {fail} failed")


if __name__ == "__main__":
    main()
