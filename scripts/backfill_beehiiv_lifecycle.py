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
    """Pull every user_profile with a stripe_customer_id."""
    response = (
        supabase.table("user_profiles")
        .select("email, subscription_status")
        .not_.is_("stripe_customer_id", "null")
        .execute()
    )
    rows = response.data or []
    if len(rows) == 1000:
        logger.warning("Fetched exactly 1000 rows — pagination may be needed")
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
    users = fetch_paying_users(supabase)
    logger.info("Found %d users with a Stripe customer", len(users))

    counts = {"trialing": 0, "paid": 0, "past_due": 0, "free_drip": 0, "missing_email": 0, "not_in_beehiiv": 0, "failed": 0}

    for row in users:
        email = (row.get("email") or "").strip().lower()
        if not email:
            counts["missing_email"] += 1
            continue

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

    logger.info("")
    logger.info("Summary: %s", counts)
    if args.dry_run:
        logger.info("(dry-run — no writes performed)")


if __name__ == "__main__":
    main()
