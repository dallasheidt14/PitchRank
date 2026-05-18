#!/usr/bin/env python3
"""
Backfill the Beehiiv `lifecycle` custom field for existing subscribers.

Run this once after deploying the lifecycle webhook changes so existing
subscribers land in the right automation buckets.

Mapping (mirrors stripe_status → lifecycle logic in
frontend/app/api/stripe/webhook/route.ts):

| user_profiles.subscription_status | lifecycle |
|-----------------------------------|-----------|
| trialing                          | trialing  |
| active                            | paid      |
| past_due                          | past_due  |
| canceled / null                   | free_drip |

Pass 1 covers everyone in user_profiles with a Stripe customer ID
(paginated). Pass 2 sweeps Beehiiv directly to catch free-tier
subscribers (report-card leads, newsletter signups) who never opened
a Stripe checkout — they get lifecycle=free_drip unless they already
have a lifecycle value from prior webhook activity.

Spec: docs/superpowers/specs/2026-05-17-lifecycle-automation-flow.md

Usage:
    python scripts/backfill_beehiiv_lifecycle.py --dry-run
    python scripts/backfill_beehiiv_lifecycle.py
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

import requests  # noqa: E402

from supabase import create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

BEEHIIV_API_URL = "https://api.beehiiv.com/v2"
RATE_LIMIT_SLEEP_S = 0.25  # be polite — ~4 req/s
SUPABASE_PAGE_SIZE = 1000  # Supabase REST default cap
BEEHIIV_PAGE_SIZE = 100  # Beehiiv list endpoint max


def status_to_lifecycle(status: str | None) -> str:
    """Map current subscription_status to the lifecycle bucket."""
    if status == "trialing":
        return "trialing"
    if status == "active":
        return "paid"
    if status == "past_due":
        return "past_due"
    return "free_drip"


def fetch_paying_users(supabase):
    """Pull every user_profile with a stripe_customer_id, paginated."""
    rows = []
    offset = 0
    while True:
        response = (
            supabase.table("user_profiles")
            .select("email, subscription_status")
            .not_.is_("stripe_customer_id", "null")
            .range(offset, offset + SUPABASE_PAGE_SIZE - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < SUPABASE_PAGE_SIZE:
            break
        offset += SUPABASE_PAGE_SIZE
    return rows


def beehiiv_find_subscriber(api_key: str, pub_id: str, email: str) -> str | None:
    """Look up a Beehiiv subscriber by email; return id or None."""
    resp = requests.get(
        f"{BEEHIIV_API_URL}/publications/{pub_id}/subscriptions/by_email/{quote(email)}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10,
    )
    if resp.status_code == 404:
        return None
    if not resp.ok:
        logger.warning("  lookup failed (%s): %s", resp.status_code, resp.text[:200])
        return None
    return (resp.json().get("data") or {}).get("id")


def beehiiv_set_lifecycle(api_key: str, pub_id: str, subscriber_id: str, lifecycle: str) -> bool:
    resp = requests.put(
        f"{BEEHIIV_API_URL}/publications/{pub_id}/subscriptions/{subscriber_id}",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"custom_fields": [{"name": "lifecycle", "value": lifecycle}]},
        timeout=10,
    )
    if not resp.ok:
        logger.warning("  set lifecycle failed (%s): %s", resp.status_code, resp.text[:200])
        return False
    return True


def iter_beehiiv_free_subscribers(api_key: str, pub_id: str):
    """Yield every active free-tier Beehiiv subscriber (cursor-paginated).

    Yields dicts with at least `id`, `email`, and `custom_fields` so the
    caller can skip subscribers who already have a lifecycle value set.
    """
    cursor = None
    while True:
        params = {"status": "active", "tier": "free", "limit": BEEHIIV_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(
            f"{BEEHIIV_API_URL}/publications/{pub_id}/subscriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            params=params,
            timeout=15,
        )
        if not resp.ok:
            logger.warning("Beehiiv list failed (%s): %s", resp.status_code, resp.text[:200])
            return
        payload = resp.json()
        for sub in payload.get("data") or []:
            yield sub
        if not payload.get("has_more"):
            return
        cursor = payload.get("next_cursor")
        if not cursor:
            return
        time.sleep(RATE_LIMIT_SLEEP_S)


def has_lifecycle(subscriber: dict) -> bool:
    for field in subscriber.get("custom_fields") or []:
        if (field.get("name") or "").lower() == "lifecycle" and field.get("value"):
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing to Beehiiv")
    args = parser.parse_args()

    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    api_key = os.environ.get("BEEHIIV_API_KEY")
    pub_id = os.environ.get("BEEHIIV_PUBLICATION_ID")

    missing = [
        name
        for name, val in [
            ("NEXT_PUBLIC_SUPABASE_URL", supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", supabase_key),
            ("BEEHIIV_API_KEY", api_key),
            ("BEEHIIV_PUBLICATION_ID", pub_id),
        ]
        if not val
    ]
    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)

    counts = {
        "trialing": 0,
        "paid": 0,
        "past_due": 0,
        "free_drip": 0,
        "missing_email": 0,
        "not_in_beehiiv": 0,
        "already_set": 0,
        "failed": 0,
    }
    touched_emails: set[str] = set()

    # --- Pass 1: Stripe customers → lifecycle from subscription_status ---
    users = fetch_paying_users(supabase)
    logger.info("Pass 1: found %d users with a Stripe customer", len(users))

    for row in users:
        email = (row.get("email") or "").strip().lower()
        if not email:
            counts["missing_email"] += 1
            continue
        touched_emails.add(email)

        lifecycle = status_to_lifecycle(row.get("subscription_status"))
        counts[lifecycle] += 1

        if args.dry_run:
            logger.info("[dry-run] %s → %s", email, lifecycle)
            continue

        subscriber_id = beehiiv_find_subscriber(api_key, pub_id, email)
        time.sleep(RATE_LIMIT_SLEEP_S)
        if not subscriber_id:
            counts["not_in_beehiiv"] += 1
            logger.info("  %s not in Beehiiv (skipping)", email)
            continue

        if not beehiiv_set_lifecycle(api_key, pub_id, subscriber_id, lifecycle):
            counts["failed"] += 1
            continue
        logger.info("  %s → lifecycle=%s", email, lifecycle)
        time.sleep(RATE_LIMIT_SLEEP_S)

    # --- Pass 2: free-tier Beehiiv subscribers (report-card leads etc.)
    #     not already touched in pass 1 and without an existing lifecycle ---
    logger.info("")
    logger.info("Pass 2: sweeping free-tier Beehiiv subscribers for free_drip backfill")

    for sub in iter_beehiiv_free_subscribers(api_key, pub_id):
        email = (sub.get("email") or "").strip().lower()
        if not email or email in touched_emails:
            continue
        if has_lifecycle(sub):
            counts["already_set"] += 1
            continue

        counts["free_drip"] += 1
        if args.dry_run:
            logger.info("[dry-run] %s → free_drip", email)
            continue

        if not beehiiv_set_lifecycle(api_key, pub_id, sub["id"], "free_drip"):
            counts["failed"] += 1
            continue
        logger.info("  %s → lifecycle=free_drip", email)
        time.sleep(RATE_LIMIT_SLEEP_S)

    logger.info("")
    logger.info("Summary: %s", counts)
    if args.dry_run:
        logger.info("(dry-run — no writes performed)")


if __name__ == "__main__":
    main()
