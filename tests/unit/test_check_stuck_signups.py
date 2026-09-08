"""Tests for the stuck-signup monitor (paying customers who never logged in)."""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.check_stuck_signups import (
    PER_PAGE,
    STUCK_MIN_AGE,
    STUCK_STATUSES,
    _to_aware,
    build_digest_html,
    fetch_all_auth_users,
    fetch_billing_by_id,
    find_stuck_users,
)

# A real Supabase recovery token_hash and the URL it would be embedded in. The digest
# must contain neither. Asserting against a link-free fixture would pass against the
# unchanged renderer, which is the shape this pair of tests exists to rule out.
LIVE_TOKEN = "hashed-xyz"
LIVE_LINK = f"https://pitchrank.io/auth/confirm?token_hash={LIVE_TOKEN}&type=recovery&next=/reset-password"

NOW = datetime.now(timezone.utc)


def make_user(uid, email, last_sign_in_at=None, created_at=None, source="stripe_checkout"):
    return SimpleNamespace(
        id=uid,
        email=email,
        last_sign_in_at=last_sign_in_at,
        created_at=created_at if created_at is not None else NOW - timedelta(hours=3),
        user_metadata={"source": source},
    )


def billing_row(uid, email, status="active", plan="premium"):
    return {
        "id": uid,
        "email": email,
        "plan": plan,
        "subscription_status": status,
        "subscription_period_end": None,
        "stripe_customer_id": "cus_x",
    }


def make_supabase(auth_users, billing_rows):
    supabase = Mock()
    supabase.auth.admin.list_users.return_value = auth_users
    supabase.auth.admin.generate_link.return_value = SimpleNamespace(
        properties=SimpleNamespace(action_link="https://supabase.example/verify?token=raw", hashed_token=LIVE_TOKEN)
    )
    table = supabase.table.return_value
    table.select.return_value.range.return_value.execute.return_value = SimpleNamespace(data=billing_rows)
    return supabase


def test_constants():
    assert STUCK_MIN_AGE == timedelta(hours=2)
    assert set(STUCK_STATUSES) == {"active", "trialing", "past_due"}
    assert PER_PAGE == 200


def test_to_aware_passes_through_aware_datetime():
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert _to_aware(dt) == dt


def test_to_aware_adds_utc_to_naive_datetime():
    assert _to_aware(datetime(2026, 1, 1)).tzinfo == timezone.utc


def test_to_aware_parses_iso_string_with_z():
    assert _to_aware("2026-01-01T00:00:00Z") == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_to_aware_none_returns_none():
    assert _to_aware(None) is None


def test_flags_paying_customer_who_never_logged_in():
    user = make_user("u1", "stuck@example.com")  # never signed in, created 3h ago
    supabase = make_supabase([user], [billing_row("u1", "stuck@example.com")])
    stuck = find_stuck_users(supabase)
    assert [s["email"] for s in stuck] == ["stuck@example.com"]
    assert "action_link" not in stuck[0]


def test_no_recovery_token_is_minted_for_a_stuck_user():
    """The whole point of the monitor's redesign: it reports, it does not mint.

    Dropping the rendered column alone would leave generation in place, and every run
    would still put a live 24h credential into Supabase's flow_state and invalidate the
    set-password link the customer already received at checkout.
    """
    user = make_user("u1", "stuck@example.com")
    supabase = make_supabase([user], [billing_row("u1", "stuck@example.com")])

    find_stuck_users(supabase)

    supabase.auth.admin.generate_link.assert_not_called()


def test_skips_user_who_has_signed_in():
    user = make_user("u1", "in@example.com", last_sign_in_at=NOW - timedelta(days=1))
    supabase = make_supabase([user], [billing_row("u1", "in@example.com")])
    assert find_stuck_users(supabase) == []


def test_skips_admin_plan():
    user = make_user("u1", "admin@example.com")
    supabase = make_supabase([user], [billing_row("u1", "admin@example.com", plan="admin")])
    assert find_stuck_users(supabase) == []


def test_skips_non_paying_status():
    user = make_user("u1", "free@example.com")
    supabase = make_supabase([user], [billing_row("u1", "free@example.com", status="canceled")])
    assert find_stuck_users(supabase) == []


def test_skips_signup_younger_than_min_age():
    user = make_user("u1", "fresh@example.com", created_at=NOW - timedelta(minutes=30))
    supabase = make_supabase([user], [billing_row("u1", "fresh@example.com")])
    assert find_stuck_users(supabase) == []


def test_skips_auth_user_with_no_billing_profile():
    user = make_user("u1", "orphan@example.com")
    supabase = make_supabase([user], [])  # no profile row
    assert find_stuck_users(supabase) == []


def test_fetch_all_auth_users_paginates_until_short_page():
    full = [make_user(f"u{i}", f"{i}@x.com") for i in range(PER_PAGE)]
    short = [make_user("last", "last@x.com")]
    supabase = Mock()
    supabase.auth.admin.list_users.side_effect = [full, short]
    users = fetch_all_auth_users(supabase)
    assert len(users) == PER_PAGE + 1
    assert supabase.auth.admin.list_users.call_count == 2


def test_fetch_all_auth_users_single_short_page_stops_immediately():
    supabase = Mock()
    supabase.auth.admin.list_users.return_value = [make_user("u1", "a@x.com")]
    users = fetch_all_auth_users(supabase)
    assert len(users) == 1
    assert supabase.auth.admin.list_users.call_count == 1


def stuck_entry(**overrides):
    entry = {
        "email": "a@x.com",
        "subscription_status": "active",
        "created_at": "2026-01-01",
        "period_end": "—",
        "source": "stripe_checkout",
    }
    entry.update(overrides)
    return entry


def test_build_digest_html_escapes_attacker_influenceable_fields():
    html_out = build_digest_html(
        [stuck_entry(email="<script>alert(1)</script>@x.com", source="<img src=x onerror=alert(2)>")]
    )
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert "<img src=x onerror=alert(2)>" not in html_out


def test_build_digest_html_carries_no_credential_even_when_handed_one():
    """The digest goes to a shared mailbox and on into Resend's delivery history, so a
    live token there outlives the incident that produced it.

    The fixture carries a real token_hash on purpose. A link-free fixture would make
    these assertions pass against the unchanged renderer, which is exactly the vacuous
    shape this test replaces.
    """
    html_out = build_digest_html([stuck_entry(action_link=LIVE_LINK)])

    assert LIVE_TOKEN not in html_out
    assert "token_hash" not in html_out
    assert "/auth/confirm" not in html_out

    # Anchors as such are fine — the digest links /forgot-password. What must never appear
    # is one whose href carries a credential or an auth-redemption path.
    hrefs = re.findall(r"href=['\"]([^'\"]+)['\"]", html_out)
    assert not [h for h in hrefs if "token" in h or "/auth/" in h], hrefs


def test_build_digest_html_still_names_the_stuck_account():
    """Removing the link must not remove the report: the digest's remaining job is to
    say who is locked out."""
    html_out = build_digest_html([stuck_entry(email="stuck@example.com", subscription_status="trialing")])

    assert "stuck@example.com" in html_out
    assert "trialing" in html_out


def test_fetch_billing_by_id_paginates_until_short_page():
    page1 = [billing_row(f"u{i}", f"{i}@x.com") for i in range(PER_PAGE)]
    page2 = [billing_row("last", "last@x.com")]
    supabase = Mock()
    execute = supabase.table.return_value.select.return_value.range.return_value.execute
    execute.side_effect = [SimpleNamespace(data=page1), SimpleNamespace(data=page2)]
    billing = fetch_billing_by_id(supabase)
    assert len(billing) == PER_PAGE + 1
    assert execute.call_count == 2


def _run_main(monkeypatch, caplog, supabase, argv):
    """Drive main() against a stubbed client, returning (exit_code, sent, log_text)."""
    import logging

    import scripts.check_stuck_signups as mod

    sent: list = []
    monkeypatch.setattr(mod, "create_client", lambda url, key: supabase)
    monkeypatch.setattr(mod, "send_alert_email", lambda stuck: sent.append(stuck) or True)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(sys, "argv", ["check_stuck_signups.py", *argv])

    caplog.set_level(logging.INFO, logger=mod.logger.name)
    code = 0
    try:
        mod.main()
    except SystemExit as exit_:
        code = exit_.code
    return code, sent, "\n".join(r.getMessage() for r in caplog.records)


def test_main_never_logs_a_customer_address(monkeypatch, caplog):
    """This repo is public and Actions logs on a public repo are readable unauthenticated,
    and the stuck list is by construction people awaiting a set-password email — a
    pre-qualified target set for a forged one. The digest carries the addresses; stdout
    must not."""
    users = [make_user("u1", "stuck@example.com"), make_user("u2", "other@example.com")]
    rows = [billing_row("u1", "stuck@example.com"), billing_row("u2", "other@example.com", status="trialing")]

    _, _, log_text = _run_main(monkeypatch, caplog, make_supabase(users, rows), [])

    assert "@" not in log_text, log_text
    assert "stuck@example.com" not in log_text


def test_main_reports_real_counts_per_status(monkeypatch, caplog):
    """A hardcoded count would leave the run's only remaining operator signal wrong."""
    users = [make_user(f"u{i}", f"{i}@x.com") for i in range(3)]
    rows = [
        billing_row("u0", "0@x.com", status="active"),
        billing_row("u1", "1@x.com", status="active"),
        billing_row("u2", "2@x.com", status="trialing"),
    ]

    _, _, log_text = _run_main(monkeypatch, caplog, make_supabase(users, rows), [])

    assert "active: 2" in log_text
    assert "trialing: 1" in log_text


def test_dry_run_sends_nothing_and_signals_action_needed(monkeypatch, caplog):
    """--dry-run must not reach send_alert_email, and must exit non-zero so the workflow
    surfaces that someone is locked out."""
    users = [make_user("u1", "stuck@example.com")]
    rows = [billing_row("u1", "stuck@example.com")]

    code, sent, _ = _run_main(monkeypatch, caplog, make_supabase(users, rows), ["--dry-run"])

    assert sent == [], "dry run sent the digest"
    assert code == 1
