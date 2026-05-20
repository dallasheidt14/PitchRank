#!/usr/bin/env python3
"""
Weekly safety-net enqueue: catch GotSport teams the daily yesterday-game
enqueue and weekly discovery enqueue both miss. Targets teams that have
either never been scraped or haven't been scraped in 90+ days.

Enqueues at priority 4 via the enqueue_scrape_request RPC (idempotent
UPSERT-with-LEAST). Does NOT scrape. process_missing_games (every 15min,
200/run) drains.

Volume: 500 teams/week by default. Mostly a backstop — should rarely match
many teams once daily + discovery enqueues stabilize.

Usage:
    python scripts/enqueue_safety_net.py
    python scripts/enqueue_safety_net.py --dry-run
    python scripts/enqueue_safety_net.py --limit 100
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
PRIORITY_SAFETY_NET = 4
REQUEST_TYPE = "safety_net"
DEFAULT_LIMIT = 500


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def find_teams_to_enqueue(supabase, gotsport_provider_id, limit=DEFAULT_LIMIT):
    """Stale GotSport teams (never scraped or last_scraped_at > 90d). Uses find_stale_teams RPC."""
    r = supabase.rpc("find_stale_teams", {
        "p_provider_id": gotsport_provider_id,
        "p_row_limit": limit,
    }).execute()
    rows = r.data or []
    seen = {}
    for row in rows:
        seen[row["team_id_master"]] = row
    return list(seen.values())


def enqueue_team(supabase, team_id_master, team_name, provider_id, provider_team_id):
    """Call enqueue_scrape_request RPC at priority 4.

    scrape_requests.game_date is NOT NULL — pass today's date as placeholder
    (safety-net scrapes are schedule-wide, not tied to a specific fixture).
    """
    return supabase.rpc("enqueue_scrape_request", {
        "p_team_id_master": team_id_master,
        "p_team_name": team_name,
        "p_provider_id": provider_id,
        "p_provider_team_id": provider_team_id,
        "p_game_date": date.today().isoformat(),
        "p_request_type": REQUEST_TYPE,
        "p_priority": PRIORITY_SAFETY_NET,
    }).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log targets without enqueueing")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)
    provider_id = get_gotsport_provider_id(supabase)

    teams = find_teams_to_enqueue(supabase, provider_id, limit=args.limit)
    logger.info(f"Safety net: {len(teams)} GotSport teams stale (never scraped or 90d+ old)")

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

    logger.info(f"Enqueued {success} teams at priority {PRIORITY_SAFETY_NET}, {fail} failed")


if __name__ == "__main__":
    main()
