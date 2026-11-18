"""ZenRows request helpers, and a drop-in ``requests.Session`` shim for SincSports.

A request to ``ENDPOINT`` carries the API key in its query string. ``_redacted_zenrows_get``
strips it from the error or URL a request hands back, and importing this module
attaches ``_RedactApiKey`` to every urllib3 logger loaded so far, because urllib3
logs request URLs itself. A process that sends a request to ``ENDPOINT`` must import
this module first.

SincSports (``soccer.sincsports.com``) now returns ``403 Forbidden`` to direct
``requests`` — TLS/behavior fingerprinting, not a header fix. Routing through
ZenRows' residential proxy bypasses it. This shim mirrors the subset of the
``requests.Session`` API the SincSports scrapers use (``.get(url, timeout=...)``
returning a ``requests.Response`` with ``.text`` / ``.raise_for_status()``), so
it can be dropped in as ``scraper.session`` with no other changes.

**JS rendering must stay OFF for SincSports.** With ``js_render`` on, the
``schedule.aspx`` division links collapse into a JS dropdown that exposes only
the ``div=N`` placeholder (zero divisions parsed), and ``teamlist.aspx`` rows are
not in the rendered DOM. The pages are server-rendered, so the residential proxy
alone is sufficient — hence ``js_render`` defaults to ``False``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, Optional
from urllib.parse import quote_plus

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ENDPOINT = "https://api.zenrows.com/v1/"
_REDACTED = "REDACTED"
_API_KEY_PARAM = re.compile(r"apikey=[^&\s'\"]+")


def _redact(text: Optional[str], secret: Optional[str]) -> Optional[str]:
    """Replace ``secret`` with a placeholder in ``text`` (e.g. an apikey in a URL)."""
    if not text or not secret:
        return text
    return text.replace(secret, _REDACTED)


def _redact_key(text: str, api_key: Optional[str]) -> str:
    """Strip the ZenRows key from anything a caller may log, raise or persist.

    Both forms, because `requests` percent-encodes a key containing `+`, `/` or
    `=` into the prepared URL and a plain replace then misses it.
    """
    if not text or not api_key:
        return text
    for form in (api_key, quote_plus(api_key)):
        text = _redact(text, form) or text
    return text


def _redacted_zenrows_get(session, params: Dict[str, str], *, timeout) -> requests.Response:
    """GET the ZenRows endpoint with the key in ``params`` kept out of the error or URL that comes back.

    The key rides in the query string, so a RequestException's message can quote it, and so
    does the HTTPError a caller's raise_for_status() builds from ``response.url``.
    """
    api_key = params.get("apikey")
    try:
        response = session.get(ENDPOINT, params=params, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise type(exc)(_redact_key(str(exc), api_key)) from None
    response.url = _redact_key(str(response.url or ""), api_key)
    return response


class _RedactApiKey(logging.Filter):
    """urllib3 logs request URLs, key and all, before the request returns.

    A logger's filter sees only records logged on that logger, never its children's,
    so it is attached to each urllib3 logger rather than to ``urllib3``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "apikey=" in message:
            record.msg, record.args = _API_KEY_PARAM.sub(f"apikey={_REDACTED}", message), ()
        return True


_KEY_FILTER = _RedactApiKey()
for _name, _logger in list(logging.Logger.manager.loggerDict.items()):
    if _name.split(".")[0] == "urllib3" and isinstance(_logger, logging.Logger):
        _logger.addFilter(_KEY_FILTER)


class ZenRowsSession:
    """Minimal proxy-backed stand-in for ``requests.Session`` (GET only)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        js_render: bool = False,
        premium_proxy: Optional[bool] = None,
        proxy_country: str = "us",
        original_status: bool = True,
        timeout: int = 120,
    ):
        self.api_key = api_key or os.environ.get("ZENROWS_API_KEY")
        if not self.api_key:
            raise RuntimeError("ZENROWS_API_KEY is not set in the environment")
        self.js_render = js_render
        # Honor the ZENROWS_PREMIUM_PROXY convention (gotsport.py / outreach_scraper):
        # premium (residential) proxy is ~25x datacenter cost, so operators can dial it
        # off via env without code edits.
        if premium_proxy is None:
            premium_proxy = os.getenv("ZENROWS_PREMIUM_PROXY", "true").lower() == "true"
        self.premium_proxy = premium_proxy
        self.proxy_country = proxy_country
        self.original_status = original_status
        self.timeout = timeout
        self._session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        """A ``requests.Session`` with the same retry/backoff the SincSports scrapers mount."""
        session = requests.Session()
        adapter = HTTPAdapter(
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["GET", "HEAD"],
            )
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _build_params(self, url: str) -> Dict[str, str]:
        """Build the ZenRows query params for ``url``. Pure — unit-tested."""
        params: Dict[str, str] = {"apikey": self.api_key, "url": url}
        if self.premium_proxy:
            params["premium_proxy"] = "true"
            if self.proxy_country:
                params["proxy_country"] = self.proxy_country
        if self.js_render:
            params["js_render"] = "true"
        if self.original_status:
            # Surface the target page's real status (default ZenRows behavior returns
            # its own 200 even when the origin blocks with 403/404), so callers'
            # raise_for_status() can detect a target-side block.
            params["original_status"] = "true"
        return params

    def get(self, url: str, timeout: Optional[int] = None) -> requests.Response:
        """Fetch ``url`` through ZenRows; returns the raw ``requests.Response``.

        The key is redacted from the returned ``Response.url`` and from any request error, so
        callers can log either freely.
        """
        return _redacted_zenrows_get(self._session, self._build_params(url), timeout=timeout or self.timeout)
