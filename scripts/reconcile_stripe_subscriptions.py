#!/usr/bin/env python3
"""
Reconcile Stripe subscriptions with user_profiles in Supabase.

Detects and fixes mismatches where the webhook failed to update plan/status.
Sends an email alert via Resend when mismatches are found.

Usage:
    python scripts/reconcile_stripe_subscriptions.py           # Fix mismatches
    python scripts/reconcile_stripe_subscriptions.py --dry-run  # Check only
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables - prioritize .env.local if it exists
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

import requests
import stripe
from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "pitchrankio@gmail.com")
FROM_EMAIL = "PitchRank <newsletter@mail.pitchrank.io>"


def stripe_status_to_plan(status: str) -> str:
    """Map Stripe subscription status to PitchRank plan.

    Mirrors webhook handler logic in
    frontend/app/api/stripe/webhook/route.ts lines 158-161.
    """
    if status in ("active", "trialing", "past_due"):
        return "premium"
    return "free"


def fetch_stripe_users(supabase):
    """Fetch all user_profiles rows with a stripe_customer_id."""
    response = (
        supabase.table("user_profiles")
        .select("id, email, plan, subscription_status, stripe_customer_id, stripe_subscription_id, subscription_period_end")
        .not_.is_("stripe_customer_id", "null")
        .execute()
    )
    rows = response.data or []
    if len(rows) == 1000:
        logger.warning("Fetched exactly 1000 rows — pagination may be needed")
    return rows


def check_stripe_subscription(customer_id: str):
    """Query Stripe for a customer's most recent subscription."""
    subs = stripe.Subscription.list(customer=customer_id, limit=1)
    if not subs.data:
        return None
    sub = subs.data[0]
    item = sub["items"]["data"][0] if sub["items"]["data"] else None
    try:
        period_end = item["current_period_end"] if item else None
    except (KeyError, TypeError):
        period_end = None
    if period_end is None:
        # Fallback: 30 days from now (mirrors webhook handler at route.ts:164-165)
        period_end = int(datetime.now(timezone.utc).timestamp()) + 30 * 24 * 60 * 60
    return {
        "status": sub.status,
        "subscription_id": sub.id,
        "period_end": period_end,
    }


def reconcile(supabase, dry_run: bool):
    """Compare DB state with Stripe and fix mismatches."""
    users = fetch_stripe_users(supabase)
    logger.info(f"Found {len(users)} user(s) with stripe_customer_id")

    mismatches = []
    checked = 0

    for row in users:
        # Skip admin users
        if row.get("plan") == "admin":
            logger.info(f"  SKIP {row.get('email', '?')} (admin)")
            continue

        customer_id = row["stripe_customer_id"]
        email = row.get("email", "unknown")

        try:
            sub_data = check_stripe_subscription(customer_id)
            time.sleep(0.1)  # Rate limit: 100 req/sec max
        except Exception as e:
            logger.error(f"  ERROR checking {email} ({customer_id}): {e}")
            continue

        checked += 1

        if sub_data:
            expected_plan = stripe_status_to_plan(sub_data["status"])
            stripe_status = sub_data["status"]
            stripe_sub_id = sub_data["subscription_id"]
            period_end = sub_data["period_end"]
        else:
            # No subscription in Stripe
            expected_plan = "free"
            stripe_status = None
            stripe_sub_id = None
            period_end = None

        db_plan = row.get("plan") or "free"
        db_status = row.get("subscription_status")
        db_sub_id = row.get("stripe_subscription_id")

        # Check for mismatch
        plan_mismatch = db_plan != expected_plan
        status_mismatch = db_status != stripe_status
        sub_id_mismatch = sub_data and db_sub_id != stripe_sub_id

        if not (plan_mismatch or status_mismatch or sub_id_mismatch):
            logger.info(f"  OK {email}: plan={db_plan}, status={db_status}")
            continue

        mismatch = {
            "user_id": row["id"],
            "email": email,
            "stripe_customer_id": customer_id,
            "before": {
                "plan": db_plan,
                "subscription_status": db_status,
                "stripe_subscription_id": db_sub_id,
            },
            "after": {
                "plan": expected_plan,
                "subscription_status": stripe_status,
                "stripe_subscription_id": stripe_sub_id,
            },
        }
        mismatches.append(mismatch)

        logger.warning(
            f"  MISMATCH {email}: "
            f"plan {db_plan}->{expected_plan}, "
            f"status {db_status}->{stripe_status}"
        )

        if not dry_run:
            update = {
                "plan": expected_plan,
                "subscription_status": stripe_status,
                "stripe_subscription_id": stripe_sub_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if period_end:
                update["subscription_period_end"] = datetime.fromtimestamp(
                    period_end, tz=timezone.utc
                ).isoformat()

            supabase.table("user_profiles").update(update).eq("id", row["id"]).execute()
            logger.info(f"  FIXED {email}")

    return mismatches, checked


def send_alert_email(mismatches: list, dry_run: bool):
    """Send email alert via Resend HTTP API when mismatches are found."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        logger.warning("RESEND_API_KEY not set, skipping email alert")
        return

    prefix = "[DRY RUN] " if dry_run else ""
    subject = f"{prefix}PitchRank Stripe Reconciliation: {len(mismatches)} mismatch(es) fixed"

    rows_html = ""
    for m in mismatches:
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px'>{m['email']}</td>"
            f"<td style='padding:6px 12px'>{m['before']['plan']} &rarr; {m['after']['plan']}</td>"
            f"<td style='padding:6px 12px'>{m['before']['subscription_status']} &rarr; {m['after']['subscription_status']}</td>"
            f"</tr>"
        )

    action = "No changes were made (dry run)" if dry_run else f"{len(mismatches)} user profile(s) were updated"

    html_body = f"""
    <h2>Stripe Subscription Reconciliation</h2>
    <p>{action}.</p>
    <table border="1" cellpadding="0" cellspacing="0" style="border-collapse:collapse; font-family:sans-serif; font-size:14px">
        <tr style="background:#f5f5f5">
            <th style="padding:8px 12px; text-align:left">User</th>
            <th style="padding:8px 12px; text-align:left">Plan Change</th>
            <th style="padding:8px 12px; text-align:left">Status Change</th>
        </tr>
        {rows_html}
    </table>
    <p style="color:#666; font-size:12px; margin-top:16px">
        This alert was sent by the daily Stripe reconciliation workflow.
    </p>
    """

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [ALERT_EMAIL],
                "subject": subject,
                "html": html_body,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"Alert email sent to {ALERT_EMAIL}")
        else:
            logger.warning(f"Email send returned {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.warning(f"Failed to send alert email: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile Stripe subscriptions with user_profiles"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log mismatches without writing to DB",
    )
    args = parser.parse_args()

    # Validate required env vars
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()
    stripe_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()

    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
        sys.exit(2)
    if not stripe_key:
        logger.error("Missing STRIPE_SECRET_KEY")
        sys.exit(2)

    stripe.api_key = stripe_key

    supabase = create_client(supabase_url, supabase_key)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    logger.info(f"=== Stripe Subscription Reconciliation ({mode}) ===")
    logger.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    mismatches, checked = reconcile(supabase, args.dry_run)

    logger.info(f"\n=== Summary ===")
    logger.info(f"Checked: {checked} user(s)")
    logger.info(f"Mismatches: {len(mismatches)}")
    logger.info(f"Mode: {mode}")

    if mismatches:
        send_alert_email(mismatches, args.dry_run)
        if args.dry_run:
            sys.exit(1)  # Signal "action needed" for dry-run
    else:
        logger.info("All profiles in sync with Stripe.")


if __name__ == "__main__":
    main()
