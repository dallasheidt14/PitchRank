"""
Local ZenRows helper for the outreach_scraper project.

Models the request shape used by ``src/scrapers/gotsport.py`` (apikey, url,
js_render, premium_proxy, proxy_country) but is kept local here on purpose:
gotsport.py has several ZenRows callers with intentionally different
timeout/CAPTCHA handling, so this is a copy of the shape, not a shared import.

Most outreach source pages are lightweight association/media sites that can be
fetched directly (Scrapy with ROBOTSTXT_OBEY honors the target's robots.txt).
Route a source through ZenRows only when it is behind anti-bot protection — note
that proxying changes the request host, so robots.txt is then evaluated against
the proxy, not the target. Reserve ``fetch: zenrows`` for sites you have
confirmed are publicly listed and permit harvesting.
"""

import os
from urllib.parse import urlencode

import requests

ZENROWS_ENDPOINT = "https://api.zenrows.com/v1/"


def _zenrows_params(target_url, *, js_render=False, premium_proxy=None, proxy_country="us"):
    api_key = os.getenv("ZENROWS_API_KEY")
    if not api_key:
        raise RuntimeError("ZENROWS_API_KEY is not set — required for fetch: zenrows sources")
    # premium_proxy=true uses residential IPs (~25x datacenter cost); default
    # follows the ZENROWS_PREMIUM_PROXY convention used by gotsport.py.
    if premium_proxy is None:
        premium_proxy = os.getenv("ZENROWS_PREMIUM_PROXY", "true").lower() == "true"
    return {
        "apikey": api_key,
        "url": target_url,
        "js_render": "true" if js_render else "false",
        "premium_proxy": "true" if premium_proxy else "false",
        "proxy_country": proxy_country,
    }


def zenrows_url(target_url, **kwargs) -> str:
    """Build the proxied ZenRows URL so a Scrapy Request can fetch through it."""
    return f"{ZENROWS_ENDPOINT}?{urlencode(_zenrows_params(target_url, **kwargs))}"


def make_zenrows_request(target_url, *, session=None, timeout=30, **kwargs) -> requests.Response:
    """GET ``target_url`` through the ZenRows proxy (for non-Scrapy callers)."""
    params = _zenrows_params(target_url, **kwargs)
    getter = session or requests
    return getter.get(ZENROWS_ENDPOINT, params=params, timeout=timeout)
