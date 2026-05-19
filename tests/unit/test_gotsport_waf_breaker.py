"""Unit tests for the GotSport CloudFront WAF circuit-breaker primitive.

Covers:
- ``_is_cloudfront_waf_block`` header detector
- ``WAFBreaker`` state machine (closed/open/second-trip-raises/resume)
- ``wait_if_open_async`` blocks until ``_resume`` fires
- ``scrape_team_games`` trips the breaker on CloudFront 403, ignores nginx 403,
  and still raises ``TeamNotFoundError`` on 404.

Mock pattern mirrors tests/unit/test_scrapers_http.py.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, Mock

import pytest
import requests

from src.scrapers.gotsport import (
    GotSportScraper,
    TeamNotFoundError,
    WAFBlockedError,
    _is_cloudfront_waf_block,
    get_waf_breaker,
)


def _response(status_code: int, headers: dict[str, str] | None = None) -> Mock:
    mock = Mock()
    mock.status_code = status_code
    mock.headers = headers or {}
    mock.raw = Mock(retries=None)
    return mock


def _http_error(status_code: int, headers: dict[str, str] | None = None) -> requests.exceptions.HTTPError:
    """Return an HTTPError whose .response carries the given status + headers."""
    response = _response(status_code, headers)
    err = requests.exceptions.HTTPError(f"{status_code}", response=response)
    return err


def _make_scraper() -> GotSportScraper:
    """Build a GotSportScraper without touching the network or DB."""
    supabase = MagicMock()
    scraper = GotSportScraper(supabase, provider_code="gotsport")
    # Short cooldown so trip + resume don't slow the suite.
    scraper.waf_cooldown_sec = 0.05
    # Tight retry budget keeps "trip → continue → retry" loops short.
    scraper.max_retries = 2
    scraper.retry_delay = 0.01
    scraper.delay_min = 0
    scraper.delay_max = 0
    return scraper


# ---------------------------------------------------------------------------
# _is_cloudfront_waf_block
# ---------------------------------------------------------------------------


def test_is_cloudfront_waf_block_403_with_cloudfront_header_is_true():
    assert _is_cloudfront_waf_block(_response(403, {"Server": "CloudFront"})) is True


def test_is_cloudfront_waf_block_403_with_nginx_header_is_false():
    assert _is_cloudfront_waf_block(_response(403, {"Server": "nginx"})) is False


def test_is_cloudfront_waf_block_404_with_cloudfront_header_is_false():
    assert _is_cloudfront_waf_block(_response(404, {"Server": "CloudFront"})) is False


def test_is_cloudfront_waf_block_200_with_cloudfront_header_is_false():
    assert _is_cloudfront_waf_block(_response(200, {"Server": "CloudFront"})) is False


# ---------------------------------------------------------------------------
# WAFBreaker state machine
# ---------------------------------------------------------------------------


def test_breaker_first_trip_opens_state():
    breaker = get_waf_breaker()
    breaker.trip(0.05, url="https://example/api")

    assert breaker._state == "open"
    assert breaker.trip_count == 1
    assert breaker._async_event.is_set() is False


def test_breaker_second_trip_raises_wafblockederror():
    breaker = get_waf_breaker()
    breaker.trip(0.05, url="https://example/api")

    # Simulate a fresh CLOSED→OPEN transition by resuming first, then tripping.
    breaker._resume()
    with pytest.raises(WAFBlockedError) as excinfo:
        breaker.trip(0.05, url="https://example/api")

    assert excinfo.value.provider == "gotsport"
    assert excinfo.value.reason == "cloudfront-waf-second-trip"
    assert breaker.trip_count == 2


def test_breaker_concurrent_trips_only_count_closed_to_open():
    """Concurrent in-flight 403s during one WAF burst must count as one trip.

    Regression test: previously every call to ``trip()`` incremented
    ``_trip_count`` regardless of state, so two workers hitting 403 from the
    same burst would immediately raise WAFBlockedError (count=2) and abort
    the run before any cooldown elapsed.
    """
    breaker = get_waf_breaker()
    # Two concurrent trips from the same WAF burst.
    breaker.trip(60, url="https://example/api", team_id="A")
    breaker.trip(60, url="https://example/api", team_id="B")

    assert breaker.trip_count == 1
    assert breaker._state == "open"


def test_breaker_aborted_state_propagates_to_subsequent_waiters():
    """Once aborted, every subsequent trip/wait raises WAFBlockedError.

    Regression: ``asyncio.gather(return_exceptions=True)`` waits for the whole
    queue to finish, so without sticky aborted state the workers running
    after the second trip would happily continue scraping past the fatal abort.
    """
    breaker = get_waf_breaker()
    breaker.trip(60, url="https://example/api", team_id="A")
    breaker._resume()  # simulate cooldown completion

    # Second CLOSED→OPEN transition flips to terminal aborted state.
    with pytest.raises(WAFBlockedError):
        breaker.trip(60, url="https://example/api", team_id="B")
    assert breaker._state == "aborted"

    # Subsequent worker waiters fast-fail rather than proceed.
    with pytest.raises(WAFBlockedError):
        breaker.wait_if_open_sync()

    with pytest.raises(WAFBlockedError):
        breaker.trip(60, url="https://example/api", team_id="C")


@pytest.mark.asyncio
async def test_wait_if_open_async_raises_when_aborted():
    """Async waiters must raise WAFBlockedError once breaker is aborted."""
    breaker = get_waf_breaker()
    breaker.bind_loop(asyncio.get_running_loop())
    breaker.trip(60, url="https://example/api", team_id="A")
    breaker._resume()

    with pytest.raises(WAFBlockedError):
        breaker.trip(60, url="https://example/api", team_id="B")

    # async waiter should see the aborted state and raise.
    with pytest.raises(WAFBlockedError):
        await breaker.wait_if_open_async()


@pytest.mark.asyncio
async def test_suspended_async_waiter_wakes_and_raises_on_abort():
    """A coroutine already awaiting wait_if_open_async must wake + raise on abort.

    Regression: validates the cross-thread ``call_soon_threadsafe(event.set)``
    in ``trip()``'s aborted branch. Without it, queued workers parked on the
    cleared event would never wake to see the aborted state.
    """
    breaker = get_waf_breaker()
    breaker.bind_loop(asyncio.get_running_loop())

    # First trip → state=open, event cleared. Now park a waiter on the event.
    breaker.trip(60, url="https://example/api", team_id="A")
    waiter = asyncio.create_task(breaker.wait_if_open_async())
    await asyncio.sleep(0)
    assert not waiter.done()

    # Simulate cooldown completion then a second WAF hit → flips to aborted,
    # which call_soon_threadsafe(event.set)s and wakes the parked waiter.
    breaker._resume()
    with pytest.raises(WAFBlockedError):
        breaker.trip(60, url="https://example/api", team_id="B")

    with pytest.raises(WAFBlockedError):
        await asyncio.wait_for(waiter, timeout=1.0)


def test_bind_loop_resets_trip_count_across_runs():
    """``bind_loop`` must wipe singleton trip state so consecutive ``asyncio.run``
    invocations in the same process don't inherit a phantom first trip."""
    breaker = get_waf_breaker()
    breaker.trip(60, url="https://example/api", team_id="A")
    assert breaker.trip_count == 1

    loop = asyncio.new_event_loop()
    try:
        breaker.bind_loop(loop)
        assert breaker.trip_count == 0
        assert breaker._state == "closed"
    finally:
        loop.close()


def test_breaker_resume_does_not_override_aborted():
    """``_resume()`` must not flip ``aborted`` back to ``closed``."""
    breaker = get_waf_breaker()
    breaker.trip(60, url="https://example/api", team_id="A")
    breaker._resume()
    with pytest.raises(WAFBlockedError):
        breaker.trip(60, url="https://example/api", team_id="B")

    breaker._resume()  # should be a no-op now
    assert breaker._state == "aborted"


def test_breaker_resumes_after_cooldown():
    breaker = get_waf_breaker()
    breaker.trip(0.05, url="https://example/api")
    assert breaker._state == "open"

    # Sync waiter blocks until cooldown elapses, then flips state.
    breaker.wait_if_open_sync()

    assert breaker._state == "closed"
    assert breaker._async_event.is_set() is True


def test_breaker_wait_if_open_sync_returns_immediately_when_closed():
    breaker = get_waf_breaker()
    start = time.monotonic()
    breaker.wait_if_open_sync()
    assert time.monotonic() - start < 0.05


# ---------------------------------------------------------------------------
# async wait_if_open_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_if_open_async_blocks_until_resume():
    breaker = get_waf_breaker()
    breaker.bind_loop(asyncio.get_running_loop())
    breaker.trip(60, url="https://example/api")  # long cooldown — we resume manually

    waiter = asyncio.create_task(breaker.wait_if_open_async())

    # Give the task a chance to start; it should still be pending.
    await asyncio.sleep(0)
    assert not waiter.done()

    breaker._resume()
    await asyncio.wait_for(waiter, timeout=1.0)
    assert waiter.done()


# ---------------------------------------------------------------------------
# scrape_team_games integration
# ---------------------------------------------------------------------------


def _patch_club_name(scraper: GotSportScraper) -> None:
    """Bypass _extract_club_name so test session.get only sees the matches URL."""
    scraper._extract_club_name = lambda team_id: ""  # type: ignore[method-assign]


def test_scrape_team_games_trips_breaker_on_cloudfront_403():
    scraper = _make_scraper()
    _patch_club_name(scraper)

    cf_response = _response(403, {"Server": "CloudFront"})
    cf_response.raise_for_status = MagicMock(side_effect=_http_error(403, {"Server": "CloudFront"}))

    ok_response = _response(200)
    ok_response.raise_for_status = MagicMock()
    ok_response.json = MagicMock(return_value=[])
    ok_response.raw = MagicMock(retries=None)

    # First call → CloudFront 403 trips breaker; second call → 200 empty list.
    scraper.session = MagicMock()
    scraper.session.get = MagicMock(side_effect=[cf_response, ok_response])

    result = scraper.scrape_team_games("12345", since_date=None)

    assert result == []
    assert get_waf_breaker().trip_count == 1


def test_scrape_team_games_does_not_trip_breaker_on_nginx_403():
    scraper = _make_scraper()
    _patch_club_name(scraper)

    nginx_response = _response(403, {"Server": "nginx"})
    nginx_response.raise_for_status = MagicMock(side_effect=_http_error(403, {"Server": "nginx"}))

    ok_response = _response(200)
    ok_response.raise_for_status = MagicMock()
    ok_response.json = MagicMock(return_value=[])
    ok_response.raw = MagicMock(retries=None)

    scraper.session = MagicMock()
    scraper.session.get = MagicMock(side_effect=[nginx_response, ok_response])

    result = scraper.scrape_team_games("12345", since_date=None)

    assert result == []
    assert get_waf_breaker().trip_count == 0


def test_scrape_team_games_404_still_raises_team_not_found():
    scraper = _make_scraper()
    _patch_club_name(scraper)

    not_found = _response(404, {"Server": "nginx"})
    not_found.raise_for_status = MagicMock(side_effect=_http_error(404, {"Server": "nginx"}))

    scraper.session = MagicMock()
    scraper.session.get = MagicMock(return_value=not_found)

    with pytest.raises(TeamNotFoundError):
        scraper.scrape_team_games("12345", since_date=None)

    assert get_waf_breaker().trip_count == 0
