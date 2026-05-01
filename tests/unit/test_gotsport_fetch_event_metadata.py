"""Coverage for ``GotsportScraper.fetch_event_metadata`` event_name extraction.

Gotsport event pages render the bare brand ``"GotSport"`` in ``<title>``
and the real tournament name in ``<h1>``. Auth-redirected URLs render the
login-page title in ``<title>`` and a generic sign-in heading in ``<h1>``.
The extractor must prefer ``<h1>`` and reject brand-only / login-page
``<title>`` values so a typo'd event id never silently surfaces login
copy as the event name.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.scrapers.gotsport import GotsportScraper
from src.scrapers.provider import EventMetadata


def _patch_fetch(scraper: GotsportScraper, html: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``_fetch_event_page`` with a canned-HTML response."""
    response = SimpleNamespace(
        text=html,
        url="https://system.gotsport.com/org_event/events/42433",
        headers={},
        history=[],
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(scraper, "_fetch_event_page", lambda event_id: response)


@pytest.fixture
def scraper() -> GotsportScraper:
    # Bypass __init__ — it pings Supabase to verify the provider row, which
    # is irrelevant to fetch_event_metadata's parsing surface.
    return GotsportScraper.__new__(GotsportScraper)


class TestFetchEventMetadataEventName:
    def test_prefers_h1_over_brand_title(self, scraper, monkeypatch):
        """Real tournament <h1> wins even when <title> is the bare brand."""
        _patch_fetch(
            scraper,
            "<html><head><title>GotSport</title></head>"
            "<body><h1>SC Del Sol Presidents Day Tournament</h1></body></html>",
            monkeypatch,
        )
        meta = scraper.fetch_event_metadata("https://system.gotsport.com/org_event/events/42433")
        assert isinstance(meta, EventMetadata)
        assert meta.event_name == "SC Del Sol Presidents Day Tournament"

    def test_falls_back_to_useful_title_when_h1_missing(self, scraper, monkeypatch):
        """Non-junk <title> is still acceptable as a fallback."""
        _patch_fetch(
            scraper,
            "<html><head><title>Desert Classic 2026 — GotSport</title></head>"
            "<body></body></html>",
            monkeypatch,
        )
        meta = scraper.fetch_event_metadata("https://system.gotsport.com/org_event/events/42433")
        assert meta.event_name == "Desert Classic 2026 — GotSport"

    def test_rejects_brand_only_title(self, scraper, monkeypatch):
        """Bare ``GotSport`` title falls through to the Event-{id} fallback."""
        _patch_fetch(
            scraper,
            "<html><head><title>GotSport</title></head><body></body></html>",
            monkeypatch,
        )
        meta = scraper.fetch_event_metadata("https://system.gotsport.com/org_event/events/42433")
        assert meta.event_name == "Event 42433"

    def test_rejects_login_page_title(self, scraper, monkeypatch):
        """Auth-redirected login page title must not surface as event name."""
        _patch_fetch(
            scraper,
            "<html><head><title>Sign in to your GotSport Account and Access Powerful Solutions - GotSport</title></head>"
            "<body></body></html>",
            monkeypatch,
        )
        meta = scraper.fetch_event_metadata("https://system.gotsport.com/org_event/events/42433")
        assert meta.event_name == "Event 42433"

    def test_no_h1_no_title_uses_event_id_fallback(self, scraper, monkeypatch):
        _patch_fetch(scraper, "<html><body></body></html>", monkeypatch)
        meta = scraper.fetch_event_metadata("https://system.gotsport.com/org_event/events/42433")
        assert meta.event_name == "Event 42433"
