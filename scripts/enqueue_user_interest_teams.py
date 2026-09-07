#!/usr/bin/env python3
"""
User-interest enqueue: re-enqueue every team a real user has shown interest in,
at priority 1, via the enqueue_scrape_request RPC (idempotent UPSERT-with-LEAST).

Three interest signals, unioned:
  - watchlist_items      a premium user saved the team
  - report_card_leads    someone traded an email for that team's report card
  - scrape_requests      a user clicked "find missing game" on the team page

These are the teams a churning user is most likely to look at next, so their data
is worth keeping fresh whether or not the automated selectors would pick them.

Does NOT scrape. process_missing_games (every 15min) drains.

Usage:
    python scripts/enqueue_user_interest_teams.py
    python scripts/enqueue_user_interest_teams.py --dry-run
    python scripts/enqueue_user_interest_teams.py --out .turbo/reports/user-interest.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta

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
    USER_CLICK_REQUEST_TYPE,
    _paged,
    load_team_rows,
    resolve_merges,
    teams_with_pending_user_request,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

PRIORITY_USER_INTEREST = 1

# Tag this job's rows so the user-click signal stays readable. Reading back
# priority-1 rows without filtering would re-collect whatever this job wrote
# last week, and the list would grow on its own forever.
REQUEST_TYPE = "retention_hygiene"

# A watchlist entry is standing interest; a single click is a one-off. Age the
# click out after a full season-and-then-some so the batch stops growing forever.
CLICK_WINDOW_DAYS = 365


def collect_watchlisted_teams(supabase):
    rows = _paged(lambda: supabase.table("watchlist_items").select("team_id_master"))
    return {r["team_id_master"] for r in rows if r["team_id_master"]}


def collect_report_card_teams(supabase):
    """report_card_leads.team_id holds a teams.team_id_master value."""
    rows = _paged(lambda: supabase.table("report_card_leads").select("team_id"))
    return {r["team_id"] for r in rows if r["team_id"]}


def collect_user_requested_teams(supabase, window_days=CLICK_WINDOW_DAYS):
    """Teams clicked within the window.

    A watchlist entry and a report-card capture are standing interest and never
    expire. A single click is a one-off, so age it out — otherwise the batch only
    ever grows.

    Known gap: a click on a team that already holds a lower-priority pending row
    takes the RPC's UPDATE branch, which promotes priority but leaves
    request_type as the automatic producer wrote it. That click is invisible
    here. The team is still scraped at click time, and is still collected if it
    is watchlisted or has a report-card lead; it just does not join the weekly
    set on the strength of the click alone. Closing it needs the click recorded
    outside the mutable queue row.
    """
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    rows = _paged(
        lambda: supabase.table("scrape_requests")
        .select("team_id_master")
        .eq("priority", PRIORITY_USER_INTEREST)
        .eq("request_type", USER_CLICK_REQUEST_TYPE)
        .gte("requested_at", cutoff)
    )
    return {r["team_id_master"] for r in rows if r["team_id_master"]}


def enqueue_team(supabase, team):
    """Call enqueue_scrape_request RPC at priority 1.

    scrape_requests.game_date is NOT NULL, so we anchor on today. The processor
    scrapes a +/-90 day window around that anchor, so a weekly run keeps the last
    three months covered. Anchoring on the team's own last game instead would
    close the window three months after that game, which for a team that stopped
    playing in spring lands before the current season even starts.
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
            "p_priority": PRIORITY_USER_INTEREST,
        },
    ).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Log targets without enqueueing")
    parser.add_argument("--out", help="Write the resolved team list to this JSON path")
    parser.add_argument(
        "--click-window-days",
        type=int,
        default=CLICK_WINDOW_DAYS,
        help=f"Age out a one-off user click after this many days (default {CLICK_WINDOW_DAYS})",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
        sys.exit(1)

    supabase = create_client(url, key)

    watchlisted = collect_watchlisted_teams(supabase)
    report_card = collect_report_card_teams(supabase)
    requested = collect_user_requested_teams(supabase, args.click_window_days)
    raw_ids = watchlisted | report_card | requested
    logger.info(
        f"Interest signals: {len(watchlisted)} watchlisted, {len(report_card)} report-card leads, "
        f"{len(requested)} user-requested -> {len(raw_ids)} distinct teams"
    )

    canonical = resolve_merges(supabase, raw_ids)
    merged = sum(1 for t, c in canonical.items() if t != c)
    target_ids = set(canonical.values())
    if merged:
        logger.info(f"Merge resolution: {merged} deprecated ids -> {len(target_ids)} canonical teams")

    team_rows = load_team_rows(supabase, target_ids)
    missing = target_ids - set(team_rows)
    if missing:
        logger.warning(f"{len(missing)} interest teams have no teams row; skipping them")

    sources = {}
    for raw, canon in canonical.items():
        entry = sources.setdefault(canon, {"watchlisted": False, "report_card": False, "requested": False})
        entry["watchlisted"] |= raw in watchlisted
        entry["report_card"] |= raw in report_card
        entry["requested"] |= raw in requested

    protected = teams_with_pending_user_request(supabase, set(team_rows))
    if protected:
        logger.info(f"{len(protected)} teams hold a pending user request; leaving those rows untouched")

    targets = []
    for team_id in sorted(team_rows):
        if team_id in protected:
            continue
        row = team_rows[team_id]
        targets.append({**row, **sources.get(team_id, {})})

    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(targets, f, indent=1)
        logger.info(f"Wrote {len(targets)} teams to {args.out}")

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

    logger.info(f"Enqueued {success} teams at priority {PRIORITY_USER_INTEREST}, {fail} failed")


if __name__ == "__main__":
    main()
