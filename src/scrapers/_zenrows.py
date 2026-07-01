"""Drop-in ``requests.Session`` shim that routes GETs through the ZenRows proxy.

SincSports (``soccer.sincsports.com``) now returns ``403 Forbidden`` to direct
``requests`` — TLS/behavior fingerprinting, not a header fix. Routing through
ZenRows' residential proxy bypasses it. This shim mirrors the subset of the
``requests.Session`` API the SincSports scrapers use (``.get(url, timeout=...)``
returning a ``requests.Response`` with ``.text`` / ``.raise_for_status()``), so
it can be dropped in as ``scraper.session`` with no other changes.

This is a deliberately separate, ``requests.Session``-shaped copy of the ZenRows
request shape. Other one-shot ZenRows callers exist (``src/scrapers/gotsport.py``,
``scrapers/outreach_scraper/.../zenrows.py``); those are single-call helpers,
whereas the SincSports scrapers drive every fetch through a swappable
``self.session``, so a Session-duck-typed shim is the clean seam here. It follows
the same ``ZENROWS_PREMIUM_PROXY`` env convention as those callers.

**JS rendering must stay OFF for SincSports.** With ``js_render`` on, the
``schedule.aspx`` division links collapse into a JS dropdown that exposes only
the ``div=N`` placeholder (zero divisions parsed), and ``teamlist.aspx`` rows are
not in the rendered DOM. The pages are server-rendered, so the residential proxy
alone is sufficient — hence ``js_render`` defaults to ``False``.

Requires ``ZENROWS_API_KEY`` in the environment.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ENDPOINT = "https://api.zenrows.com/v1/"
_REDACTED = "REDACTED"


def _redact(text: Optional[str], secret: Optional[str]) -> Optional[str]:
    """Replace ``secret`` with a placeholder in ``text`` (e.g. an apikey in a URL)."""
    if not text or not secret:
        return text
    return text.replace(secret, _REDACTED)


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

        The API key travels in the query string, so it would otherwise surface in
        ``Response.url`` (and any ``raise_for_status()`` / log line built from it).
        We redact it before returning so callers can log the response freely.
        """
        resp = self._session.get(ENDPOINT, params=self._build_params(url), timeout=timeout or self.timeout)
        resp.url = _redact(resp.url, self.api_key)
        return resp
