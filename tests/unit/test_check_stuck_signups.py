"""Tests for the stuck-signup monitor (paying customers who never logged in)."""

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.check_stuck_signups import (
    LINK_FAILED,
    PER_PAGE,
    STUCK_MIN_AGE,
    STUCK_STATUSES,
    _to_aware,
    build_digest_html,
    fetch_all_auth_users,
    fetch_billing_by_id,
    find_stuck_users,
)

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
        properties=SimpleNamespace(action_link="https://supabase.example/verify?token=raw", hashed_token="hashed-xyz")
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
    # Forwardable token_hash URL through our callback, not Supabase's raw action_link
    assert stuck[0]["action_link"] == (
        "https://pitchrank.io/auth/callback?token_hash=hashed-xyz&type=recovery&next=/reset-password"
    )


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
        "action_link": "https://pitchrank.io/auth/callback",
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


def test_build_digest_html_renders_failed_link_as_warning_not_anchor():
    html_out = build_digest_html([stuck_entry(action_link=LINK_FAILED)])
    assert "link generation failed" in html_out
    assert "<a " not in html_out  # no clickable anchor is rendered for a failed-link row


def test_build_digest_html_renders_anchor_for_a_good_link():
    html_out = build_digest_html([stuck_entry(action_link="https://pitchrank.io/auth/callback")])
    assert "<a href='https://pitchrank.io/auth/callback'>set-password link</a>" in html_out


def test_fetch_billing_by_id_paginates_until_short_page():
    page1 = [billing_row(f"u{i}", f"{i}@x.com") for i in range(PER_PAGE)]
    page2 = [billing_row("last", "last@x.com")]
    supabase = Mock()
    execute = supabase.table.return_value.select.return_value.range.return_value.execute
    execute.side_effect = [SimpleNamespace(data=page1), SimpleNamespace(data=page2)]
    billing = fetch_billing_by_id(supabase)
    assert len(billing) == PER_PAGE + 1
    assert execute.call_count == 2
