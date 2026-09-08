#!/usr/bin/env python3
"""
Catch paying/trialing customers who can't log in.

Guest checkout creates a password-less Supabase user and emails a single
set-password link. When that email is slow, spam-filtered, mistyped, or
opened after it expires, the customer is locked out. This monitor finds
anyone who is paying/trialing but has never signed in and emails an admin
digest naming them.

The digest carries no recovery link. Minting one here put a live 24h
credential for a paid account into a shared mailbox, and from there into
Resend's delivery history, where it outlives the incident that produced it.
The customer already has a working set-password link from checkout, and
/forgot-password is the self-service path for anyone whose link has expired.

Usage:
    python scripts/check_stuck_signups.py            # Send admin digest if any
    python scripts/check_stuck_signups.py --dry-run  # Report counts, do not send
"""

import argparse
import html
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv

# Load environment variables - prioritize .env.local if it exists
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

import requests  # noqa: E402

from supabase import create_client  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "pitchrankio@gmail.com")
FROM_EMAIL = "PitchRank <newsletter@mail.pitchrank.io>"
SITE_URL = os.environ.get("NEXT_PUBLIC_SITE_URL", "https://pitchrank.io")

# A signup still in its first couple of hours may legitimately not have logged
# in yet (the set-password email is in flight), so don't flag it.
STUCK_MIN_AGE = timedelta(hours=2)
STUCK_STATUSES = ("active", "trialing", "past_due")
PER_PAGE = 200


def _to_aware(value) -> datetime | None:
    """Coerce a gotrue timestamp (datetime or ISO string) to aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fetch_all_auth_users(supabase):
    """Page through the GoTrue admin API and return every auth user.

    Unlike the PostgREST queries elsewhere, list_users defaults to a small
    page, so it MUST be paginated explicitly — stop once a page comes back
    short of PER_PAGE.
    """
    users = []
    page = 1
    while True:
        result = supabase.auth.admin.list_users(page=page, per_page=PER_PAGE)
        page_users = getattr(result, "users", result) or []
        users.extend(page_users)
        if len(page_users) < PER_PAGE:
            break
        page += 1
    return users


def fetch_billing_by_id(supabase):
    """Map user_profiles.id -> billing fields (plan, status, period_end, ...).

    Pages explicitly with .range() — a bare select is capped at the project's
    max_rows (1000), which would silently drop paid accounts past the first page.
    """
    billing = {}
    start = 0
    while True:
        response = (
            supabase.table("user_profiles")
            .select("id, email, plan, subscription_status, subscription_period_end, stripe_customer_id")
            .range(start, start + PER_PAGE - 1)
            .execute()
        )
        rows = response.data or []
        for row in rows:
            billing[row["id"]] = row
        if len(rows) < PER_PAGE:
            break
        start += PER_PAGE
    return billing


def find_stuck_users(supabase):
    """Join auth state with billing state and return locked-out customers."""
    auth_users = fetch_all_auth_users(supabase)
    billing = fetch_billing_by_id(supabase)
    logger.info(f"Scanned {len(auth_users)} auth user(s), {len(billing)} profile(s)")

    now = datetime.now(timezone.utc)
    stuck = []

    for user in auth_users:
        if user.last_sign_in_at is not None:
            continue

        profile = billing.get(user.id)
        if not profile:
            continue
        if profile.get("plan") == "admin":
            continue
        if profile.get("subscription_status") not in STUCK_STATUSES:
            continue

        created = _to_aware(user.created_at)
        if created is not None and now - created < STUCK_MIN_AGE:
            continue

        stuck.append(
            {
                "email": profile.get("email") or user.email,
                "created_at": created.isoformat() if created else "unknown",
                "subscription_status": profile.get("subscription_status"),
                "period_end": profile.get("subscription_period_end") or "—",
                "source": (user.user_metadata or {}).get("source", "—"),
            }
        )

    return stuck


def build_digest_html(stuck: list) -> str:
    # Escape every interpolated field — email and source come from Stripe-synced
    # user data and are attacker-influenceable, same reason the webhook escapes them.
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    rows_html = ""
    for s in stuck:
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px'>{esc(s['email'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['subscription_status'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['created_at'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['period_end'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['source'])}</td>"
            f"</tr>"
        )

    return f"""
    <h2>Stuck signups — paying but never logged in</h2>
    <p>{len(stuck)} customer(s) are paying/trialing but have never signed in.
       They each already had a set-password link from checkout. Point them at
       <a href="{esc(SITE_URL)}/forgot-password">{esc(SITE_URL)}/forgot-password</a>,
       which issues a fresh one to the account holder.</p>
    <table border="1" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse; font-family:sans-serif; font-size:14px">
        <tr style="background:#f5f5f5">
            <th style="padding:8px 12px; text-align:left">Email</th>
            <th style="padding:8px 12px; text-align:left">Status</th>
            <th style="padding:8px 12px; text-align:left">Created</th>
            <th style="padding:8px 12px; text-align:left">Renews</th>
            <th style="padding:8px 12px; text-align:left">Source</th>
        </tr>
        {rows_html}
    </table>
    <p style="color:#666; font-size:12px; margin-top:16px">
        This alert was sent by the stuck-signup monitor workflow.
    </p>
    """


def send_alert_email(stuck: list) -> bool:
    """Send the admin digest via Resend HTTP API. Returns True only if delivered.

    The digest is the monitor's sole remediation channel, so a delivery failure
    means the locked-out customers went unreported — the caller fails the job.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        logger.warning("RESEND_API_KEY not set, skipping email alert")
        return False

    subject = f"PitchRank: {len(stuck)} stuck signup(s) — paying but locked out"

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
                "html": build_digest_html(stuck),
            },
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(f"Alert email sent to {ALERT_EMAIL}")
            return True
        logger.warning(f"Email send returned {resp.status_code}: {resp.text}")
        return False
    except Exception as e:
        logger.warning(f"Failed to send alert email: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Find paying/trialing customers who have never logged in")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many are stuck without sending the digest",
    )
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")).strip()

    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
        sys.exit(2)

    supabase = create_client(supabase_url, supabase_key)

    mode = "DRY RUN" if args.dry_run else "LIVE"
    logger.info(f"=== Stuck Signup Monitor ({mode}) ===")
    logger.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    stuck = find_stuck_users(supabase)

    # Addresses stay out of stdout. This repo is public and Actions logs on a public repo
    # are readable unauthenticated, and these are, by construction, customers currently
    # waiting on a set-password email — a pre-qualified target list for a forged one. The
    # digest carries the names; it goes only to ALERT_EMAIL.
    logger.info("\n=== Summary ===")
    logger.info(f"Stuck signups: {len(stuck)}")
    by_status: dict[str, int] = {}
    for s in stuck:
        by_status[s["subscription_status"]] = by_status.get(s["subscription_status"], 0) + 1
    for status, count in sorted(by_status.items()):
        logger.info(f"  {status}: {count}")

    if not stuck:
        logger.info("No stuck signups — everyone who paid has logged in.")
        return

    if args.dry_run:
        logger.info(f"\n=== Dry run — digest NOT sent ({len(stuck)} would be listed) ===")
        sys.exit(1)  # Signal "action needed" for dry-run

    if not send_alert_email(stuck):
        logger.error(f"{len(stuck)} stuck signup(s) found but the admin alert could not be delivered")
        sys.exit(1)


if __name__ == "__main__":
    main()
