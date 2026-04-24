"""Unit tests for ``src.scrapers._http`` — retry backoff semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import pytest
import requests

from src.scrapers._http import RateLimitedError, backoff_for_event


def _response(status_code: int, headers: dict[str, str] | None = None) -> Mock:
    mock = Mock()
    mock.status_code = status_code
    mock.headers = headers or {}
    return mock


def test_backoff_429_with_retry_after_seconds_returns_header_value():
    event = {"kind": "response", "response": _response(429, {"Retry-After": "5"})}
    assert backoff_for_event(event, attempt=0, retry_delay=1.0) == 5.0


def test_backoff_429_with_retry_after_http_date_returns_delta():
    three_seconds_ahead = datetime.now(timezone.utc) + timedelta(seconds=3)
    header = format_datetime(three_seconds_ahead, usegmt=True)
    event = {"kind": "response", "response": _response(429, {"Retry-After": header})}
    wait = backoff_for_event(event, attempt=0, retry_delay=1.0)
    assert 0.0 <= wait <= 120.0
    assert 2.0 <= wait <= 4.0


def test_backoff_429_no_header_uses_exponential():
    event = {"kind": "response", "response": _response(429, {})}
    wait = backoff_for_event(event, attempt=2, retry_delay=1.0)
    assert 4.0 <= wait <= 5.0


def test_backoff_503_clamps_retry_after_at_120_seconds():
    event = {"kind": "response", "response": _response(503, {"Retry-After": "200"})}
    assert backoff_for_event(event, attempt=0, retry_delay=1.0) == 120.0


def test_backoff_timeout_uses_exponential_capped_at_60():
    event = {"kind": "timeout", "exc": requests.exceptions.Timeout("test")}
    wait = backoff_for_event(event, attempt=1, retry_delay=1.0)
    assert 2.0 <= wait <= 3.0


def test_backoff_short_body_uses_exponential():
    event = {"kind": "short_body", "response": _response(200), "len": 1000}
    wait = backoff_for_event(event, attempt=0, retry_delay=1.0, baseline_bytes=50_000)
    assert 1.0 <= wait <= 2.0


def test_backoff_successful_response_returns_zero():
    event = {"kind": "response", "response": _response(200)}
    assert backoff_for_event(event, attempt=0, retry_delay=1.0) == 0.0


def test_rate_limited_error_carries_context():
    err = RateLimitedError(provider="gotsport", url="https://x/y", last_retry_after=5.0, reason="429_exhausted")
    assert err.provider == "gotsport"
    assert err.url == "https://x/y"
    assert err.last_retry_after == 5.0
    assert err.reason == "429_exhausted"
    assert "429_exhausted" in str(err)


def test_retry_session_get_disable_env_short_circuits(monkeypatch):
    from src.scrapers._http import retry_session_get

    monkeypatch.setenv("SCRAPER_DISABLE_APP_RETRY", "1")
    session = Mock()
    expected = _response(200)
    session.get.return_value = expected
    got = retry_session_get(
        session,
        "https://host/x",
        attempts=5,
        retry_delay=1.0,
        baseline_bytes=None,
        is_event_url=False,
        provider="gotsport",
    )
    assert got is expected
    assert session.get.call_count == 1


def test_retry_session_get_gotsport_disable_alias_also_short_circuits(monkeypatch):
    from src.scrapers._http import retry_session_get

    monkeypatch.delenv("SCRAPER_DISABLE_APP_RETRY", raising=False)
    monkeypatch.setenv("GOTSPORT_DISABLE_APP_RETRY", "1")
    session = Mock()
    session.get.return_value = _response(200)
    retry_session_get(
        session,
        "https://host/x",
        attempts=5,
        retry_delay=1.0,
        baseline_bytes=None,
        is_event_url=False,
        provider="gotsport",
    )
    assert session.get.call_count == 1


def test_retry_session_get_returns_on_first_success(monkeypatch):
    from src.scrapers._http import retry_session_get

    monkeypatch.delenv("SCRAPER_DISABLE_APP_RETRY", raising=False)
    monkeypatch.delenv("GOTSPORT_DISABLE_APP_RETRY", raising=False)
    session = Mock()
    success = _response(200)
    success.text = "x" * 50_000
    session.get.return_value = success
    got = retry_session_get(
        session,
        "https://host/event",
        attempts=3,
        retry_delay=0.01,
        baseline_bytes=50_000,
        is_event_url=True,
        provider="gotsport",
    )
    assert got is success
    assert session.get.call_count == 1


def test_retry_session_get_raises_rate_limited_on_429_exhaustion(monkeypatch):
    from src.scrapers._http import retry_session_get

    monkeypatch.delenv("SCRAPER_DISABLE_APP_RETRY", raising=False)
    monkeypatch.delenv("GOTSPORT_DISABLE_APP_RETRY", raising=False)
    session = Mock()
    session.get.return_value = _response(429, {"Retry-After": "0"})
    with pytest.raises(RateLimitedError) as excinfo:
        retry_session_get(
            session,
            "https://host/rl",
            attempts=2,
            retry_delay=0.01,
            baseline_bytes=None,
            is_event_url=False,
            provider="gotsport",
        )
    assert excinfo.value.reason == "429_exhausted"
    assert session.get.call_count == 2


def test_retry_session_get_short_body_triggers_retry_then_raises(monkeypatch):
    from src.scrapers._http import retry_session_get

    monkeypatch.delenv("SCRAPER_DISABLE_APP_RETRY", raising=False)
    monkeypatch.delenv("GOTSPORT_DISABLE_APP_RETRY", raising=False)
    session = Mock()
    short = _response(200)
    short.text = "x" * 100
    session.get.return_value = short
    with pytest.raises(RateLimitedError) as excinfo:
        retry_session_get(
            session,
            "https://host/event",
            attempts=2,
            retry_delay=0.01,
            baseline_bytes=50_000,
            is_event_url=True,
            provider="gotsport",
        )
    assert excinfo.value.reason == "short_body_exhausted"
