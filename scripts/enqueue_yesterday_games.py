#!/usr/bin/env python3
"""
Daily enqueue: scan games table for yesterday's NULL-score rows, enqueue each
affected GotSport team into scrape_requests at priority 2 via the
enqueue_scrape_request RPC (idempotent UPSERT-with-LEAST).

Does NOT scrape. process_missing_games (every 15min, 200/run) drains.

Usage:
    python scripts/enqueue_yesterday_games.py
    python scripts/enqueue_yesterday_games.py --dry-run
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GOTSPORT_PROVIDER_CODE = "gotsport"
PRIORITY_YESTERDAY_GAME = 2
REQUEST_TYPE = "yesterday_game"


def get_gotsport_provider_id(supabase):
    r = supabase.table("providers").select("id").eq("code", GOTSPORT_PROVIDER_CODE).single().execute()
    if not r.data:
        raise RuntimeError(f"Provider '{GOTSPORT_PROVIDER_CODE}' not found")
    return r.data["id"]


def find_teams_to_enqueue(supabase, gotsport_provider_id):
    """
    Return distinct dicts {team_id_master, team_name, provider_team_id} for
    GotSport teams that had a game yesterday with NULL home_score.

    Uses RPC find_yesterday_null_score_teams (created in this PR's migration).
    """
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = supabase.rpc("find_yesterday_null_score_teams", {
        "p_yesterday": yesterday,
        "p_provider_id": gotsport_provider_id,
    }).execute()
    rows = r.data or []
    # Distinct on team_id_master (RPC should already DISTINCT, but defensive)
    seen = {}
    for row in rows:
        seen[row["team_id_master"]] = row
    return list(seen.values())


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
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    teams = find_teams_to_enqueue(supabase, provider_id)
    logger.info(f"Found {len(teams)} GotSport teams with yesterday ({yesterday}) NULL-score games")

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
                game_date=yesterday,
            )
            success += 1
        except Exception as e:
            logger.warning(f"Failed to enqueue {t['team_id_master']}: {e}")
            fail += 1

    logger.info(f"Enqueued {success} teams at priority {PRIORITY_YESTERDAY_GAME}, {fail} failed")


if __name__ == "__main__":
    main()
