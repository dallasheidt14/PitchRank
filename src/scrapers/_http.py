"""HTTP retry + backoff helpers reused across provider scrapers.

Layered on top of urllib3's built-in Retry. urllib3 handles transport-layer
retries for {500, 502, 503, 504} in ``status_forcelist``. This module adds a
single app-level layer that handles:

- 429 responses (with or without a ``Retry-After`` header)
- Timeouts raised by requests
- Suspicious short bodies on event-URL fetches

Division of responsibility:
- Leave ``_init_http_session``'s ``Retry.status_forcelist`` at ``[500, 502, 503, 504]``.
- Do NOT add 429 to urllib3's Retry — it is owned here.
- The short-body rule is applied ONLY to event-URL fetches, never to schedule
  or detail pages.

The ``SCRAPER_DISABLE_APP_RETRY=1`` environment variable suppresses this retry
wrapper so the Phase A diagnostic can observe raw behavior.
``GOTSPORT_DISABLE_APP_RETRY=1`` is kept as a back-compat alias.
"""

from __future__ import annotations

import logging
import os
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)


__all__ = [
    "RateLimitedError",
    "backoff_for_event",
    "retry_session_get",
]


class RateLimitedError(Exception):
    """Raised when app-level retry budget is exhausted on 429 / timeout / short body."""

    def __init__(self, *, provider: str, url: str, last_retry_after: float | None, reason: str):
        self.provider = provider
        self.url = url
        self.last_retry_after = last_retry_after
        self.reason = reason
        super().__init__(
            f"{provider}: retry exhausted for {url} (reason={reason}, last_retry_after={last_retry_after})"
        )


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header as seconds or HTTP-date; return None if absent/unparseable."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return float(int(raw))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc) if dt.tzinfo else _dt.datetime.now()
    delta = (dt - now).total_seconds()
    return max(delta, 0.0)


def _exponential_backoff(attempt: int, retry_delay: float, cap: float) -> float:
    """``retry_delay * 2**attempt + uniform(0, 1)``, clamped to ``[0, cap]``. ``attempt`` is 0-indexed."""
    wait = retry_delay * (2**attempt) + random.uniform(0, 1.0)
    return max(0.0, min(cap, wait))


def backoff_for_event(
    event: dict[str, Any],
    attempt: int,
    retry_delay: float,
    baseline_bytes: int | None = None,
) -> float:
    """Return seconds to sleep before the next retry, or 0 if no retry is needed.

    ``attempt`` is 0-indexed: 0 before the first retry, incremented after each
    failed attempt.

    Event shapes:
    - ``{"kind": "response", "response": <requests.Response>}``
    - ``{"kind": "timeout", "exc": <requests.exceptions.Timeout>}``
    - ``{"kind": "short_body", "response": <r>, "len": <n>}``
    """
    del baseline_bytes  # unused here; kept for caller-side clarity + future use
    kind = event.get("kind")

    if kind == "response":
        response = event["response"]
        status = getattr(response, "status_code", None)
        headers = getattr(response, "headers", {}) or {}
        retry_after = _parse_retry_after(headers.get("Retry-After"))
        if status == 429:
            if retry_after is not None:
                return max(0.0, min(120.0, retry_after))
            return _exponential_backoff(attempt, retry_delay, cap=60.0)
        if status in {500, 502, 503, 504}:
            if retry_after is not None:
                return max(0.0, min(120.0, retry_after))
            return _exponential_backoff(attempt, retry_delay, cap=60.0)
        return 0.0

    if kind == "timeout":
        return _exponential_backoff(attempt, retry_delay, cap=60.0)

    if kind == "short_body":
        return _exponential_backoff(attempt, retry_delay, cap=60.0)

    return 0.0


def _app_retry_disabled() -> bool:
    return bool(os.environ.get("SCRAPER_DISABLE_APP_RETRY")) or bool(os.environ.get("GOTSPORT_DISABLE_APP_RETRY"))


def retry_session_get(
    session: requests.Session,
    url: str,
    *,
    attempts: int,
    retry_delay: float,
    baseline_bytes: int | None,
    is_event_url: bool,
    provider: str,
    **kwargs: Any,
) -> requests.Response:
    """GET with app-level retry handling for 429 / timeout / short-body.

    Short-body detection runs only when ``is_event_url=True`` AND
    ``baseline_bytes`` is not None — a 2xx whose ``len(response.text)`` is
    below ``baseline_bytes * 0.1`` is treated as a failed attempt.

    Raises ``RateLimitedError`` when ``attempts`` is exhausted.
    """
    if _app_retry_disabled():
        return session.get(url, **kwargs)

    retriable_statuses = {429, 500, 502, 503, 504}
    last_wait: float | None = None
    last_reason = "unknown"

    for attempt in range(attempts):
        event: dict[str, Any]
        try:
            response = session.get(url, **kwargs)
        except requests.exceptions.Timeout as exc:
            event = {"kind": "timeout", "exc": exc}
            last_reason = "timeout"
        else:
            status_code = getattr(response, "status_code", None)
            if (
                is_event_url
                and baseline_bytes is not None
                and status_code is not None
                and 200 <= status_code < 300
                and len(response.text) < baseline_bytes * 0.1
            ):
                event = {"kind": "short_body", "response": response, "len": len(response.text)}
                last_reason = "short_body"
            else:
                event = {"kind": "response", "response": response}
                if status_code in retriable_statuses:
                    last_reason = "429" if status_code == 429 else f"{status_code}"
                else:
                    return response

        wait = backoff_for_event(event, attempt, retry_delay, baseline_bytes)
        last_wait = wait
        if attempt < attempts - 1:
            logger.warning(
                "%s retry: attempt=%d/%d reason=%s url=%s sleep=%.2fs",
                provider,
                attempt + 1,
                attempts,
                last_reason,
                url,
                wait,
            )
            time.sleep(wait)

    raise RateLimitedError(
        provider=provider,
        url=url,
        last_retry_after=last_wait if last_reason == "429" else None,
        reason=f"{last_reason}_exhausted",
    )
