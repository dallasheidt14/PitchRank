#!/usr/bin/env python3
"""
Catch paying/trialing customers who can't log in.

Guest checkout creates a password-less Supabase user and emails a single
set-password link. When that email is slow, spam-filtered, mistyped, or
opened after it expires, the customer is locked out with no self-service
path. This monitor finds anyone who is paying/trialing but has never signed
in, generates a fresh recovery link for each, and emails an admin digest with
ready-to-forward links.

Usage:
    python scripts/check_stuck_signups.py            # Send admin digest if any
    python scripts/check_stuck_signups.py --dry-run  # Print digest, don't send
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

# Sentinel returned by generate_recovery_link when Supabase link generation
# fails — the digest renders these rows as a visible warning, not a dead link.
LINK_FAILED = "(link generation failed — reset manually)"


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

        action_link = generate_recovery_link(supabase, profile.get("email") or user.email)
        stuck.append(
            {
                "email": profile.get("email") or user.email,
                "created_at": created.isoformat() if created else "unknown",
                "subscription_status": profile.get("subscription_status"),
                "period_end": profile.get("subscription_period_end") or "—",
                "source": (user.user_metadata or {}).get("source", "—"),
                "action_link": action_link,
            }
        )

    return stuck


def generate_recovery_link(supabase, email: str) -> str:
    """Generate a fresh set-password (recovery) link for a stuck user.

    Build the URL from hashed_token through our own /auth/callback (the verifyOtp
    token_hash branch) instead of returning Supabase's raw action_link: a link
    generated server-side and forwarded to the customer hits the PKCE code path
    with no code_verifier cookie in their browser and falls through to /login
    instead of establishing the recovery session.
    """
    try:
        resp = supabase.auth.admin.generate_link(
            {
                "type": "recovery",
                "email": email,
                "options": {"redirect_to": f"{SITE_URL}/auth/callback?next=/reset-password"},
            }
        )
        return f"{SITE_URL}/auth/callback?token_hash={resp.properties.hashed_token}&type=recovery&next=/reset-password"
    except Exception as e:
        logger.error(f"  ERROR generating recovery link for {email}: {e}")
        return LINK_FAILED


def build_digest_html(stuck: list) -> str:
    # Escape every interpolated field — email and source come from Stripe-synced
    # user data and are attacker-influenceable, same reason the webhook escapes them.
    def esc(value) -> str:
        return html.escape(str(value), quote=True)

    rows_html = ""
    for s in stuck:
        recovery = (
            "<span style='color:#b91c1c'>⚠ link generation failed — reset manually</span>"
            if s["action_link"] == LINK_FAILED
            else f"<a href='{esc(s['action_link'])}'>set-password link</a>"
        )
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 12px'>{esc(s['email'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['subscription_status'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['created_at'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['period_end'])}</td>"
            f"<td style='padding:6px 12px'>{esc(s['source'])}</td>"
            f"<td style='padding:6px 12px'>{recovery}</td>"
            f"</tr>"
        )

    return f"""
    <h2>Stuck signups — paying but never logged in</h2>
    <p>{len(stuck)} customer(s) are paying/trialing but have never signed in.
       Forward each the set-password link below so they can get in.
       Always use the latest alert: links from earlier alerts stop working.</p>
    <table border="1" cellpadding="0" cellspacing="0"
           style="border-collapse:collapse; font-family:sans-serif; font-size:14px">
        <tr style="background:#f5f5f5">
            <th style="padding:8px 12px; text-align:left">Email</th>
            <th style="padding:8px 12px; text-align:left">Status</th>
            <th style="padding:8px 12px; text-align:left">Created</th>
            <th style="padding:8px 12px; text-align:left">Renews</th>
            <th style="padding:8px 12px; text-align:left">Source</th>
            <th style="padding:8px 12px; text-align:left">Recovery</th>
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
        help="Print the digest without sending the email",
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

    logger.info("\n=== Summary ===")
    logger.info(f"Stuck signups: {len(stuck)}")
    for s in stuck:
        logger.info(f"  STUCK {s['email']} ({s['subscription_status']}, created {s['created_at']})")

    if not stuck:
        logger.info("No stuck signups — everyone who paid has logged in.")
        return

    if args.dry_run:
        # Never log the action_links: they are live account-recovery credentials
        # and dry-run is reachable from workflow_dispatch, so the digest would
        # leak them into GitHub Actions logs. Confirm generation, don't print it.
        logger.info("\n=== Dry run — digest NOT sent; recovery links redacted from logs ===")
        for s in stuck:
            link_ok = s["action_link"] != LINK_FAILED
            logger.info(f"  would-email: {s['email']} (recovery link generated: {link_ok})")
        sys.exit(1)  # Signal "action needed" for dry-run

    if not send_alert_email(stuck):
        logger.error(f"{len(stuck)} stuck signup(s) found but the admin alert could not be delivered")
        sys.exit(1)


if __name__ == "__main__":
    main()
