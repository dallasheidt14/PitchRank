"""Provider-scraper abstraction for event-level intake.

Shell-01 foundations for the MatchBalance backtest intake pipeline. Defines:

- ``ProviderScraper`` ABC — the cohort/team/canonical-ID surface every provider
  implements.
- Dataclasses ``EventMetadata``, ``ScrapedTeam``, ``CanonicalResolution`` —
  the wire format between scraper and downstream persistence.
- ``UnsupportedProviderError`` — raised when a provider row is missing or a
  URL does not route to a known provider.
- ``get_provider_scraper`` — URL-pattern factory.
- Path helpers ``_derive_event_key`` / ``_intake_path`` — wire-compatible with
  Shell 02's directory re-keying (``__unknown__`` placeholder until that
  shell lands the season_year convention).

``RateLimitedError`` lives in ``src.scrapers._http`` and is re-exported here
for caller convenience.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.scrapers._http import RateLimitedError

__all__ = [
    "CanonicalResolution",
    "EventMetadata",
    "ProviderScraper",
    "RateLimitedError",
    "ScrapedTeam",
    "UnsupportedProviderError",
    "get_provider_scraper",
]


class UnsupportedProviderError(Exception):
    """Raised when a provider URL or code has no scraper registered."""


@dataclass(frozen=True)
class EventMetadata:
    """Event-level metadata scraped from the provider landing page."""

    provider_code: str
    provider_event_id: str
    event_name: str
    event_slug: str
    event_start_date: str | None
    scrape_ts: str
    series_id: str | None = None


@dataclass(frozen=True)
class ScrapedTeam:
    """One row of cohort-assigned team metadata produced by ``fetch_teams_by_cohort``."""

    provider_team_id: str
    team_name: str
    club_name: str | None
    cohort_age_group: str
    cohort_gender: str
    division: str | None
    bracket_name: str | None
    playing_up: bool = False
    has_view_rankings_link: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalResolution:
    """Outcome of resolving a scraped team to a canonical ``team_id_master``."""

    team_id_master: str | None
    confidence: float | None
    resolved_status: str
    match_method: str | None
    candidates: list[dict[str, Any]]
    provider_id_resolution_status: str


class ProviderScraper(ABC):
    """Abstract base for event-level cohort scrapers.

    Parallels ``src.base.BaseProvider`` but targets tournament intake: cohort
    walks, canonical-ID resolution, and journal-aware re-scrapes. Implementations
    compose (rather than subclass) their provider's team-games scraper when
    game-history remains needed.
    """

    @abstractmethod
    def fetch_event_metadata(self, event_url: str) -> EventMetadata:
        """Scrape event-level metadata (name, start date, slug)."""

    @abstractmethod
    def fetch_teams_by_cohort(
        self,
        event_url: str,
        *,
        force_teams: bool = False,
        revalidate: bool = False,
    ) -> dict[str, list[ScrapedTeam]]:
        """Return ``{cohort_key: [ScrapedTeam, ...]}`` for every cohort in the event.

        ``force_teams`` bypasses the team-level resume skip.
        ``revalidate`` re-resolves canonical IDs whose stored alias is
        machine-written (not ``review_status='approved'`` or
        ``match_method='direct_id'``).
        """

    @abstractmethod
    def resolve_canonical_team_id(
        self,
        team: ScrapedTeam,
        *,
        provider_uuid: str | None = None,
        provider_code: str | None = None,
    ) -> CanonicalResolution:
        """Resolve one ``ScrapedTeam`` to a canonical team_id_master (or review queue)."""


def _derive_event_key(meta: EventMetadata) -> str:
    """Return the storage key for an event.

    Shell 01 uses ``__unknown__`` as the season-year placeholder; Shell 02
    owns the season-year convention + migration. Keep the three-segment
    ``provider__eventid__season`` shape so Shell 02 only needs to re-key.
    """
    return f"{meta.provider_code}__{meta.provider_event_id}__unknown"


def _intake_path(event_key: str) -> Path:
    """Resolve the on-disk ``raw_scrape.jsonl`` location for an event key."""
    return Path("reports") / event_key / "intake" / "raw_scrape.jsonl"


_GOTSPORT_EVENT_URL = re.compile(
    r"^https?://system\.gotsport\.com/org_event/events/\d+",
    re.IGNORECASE,
)


def get_provider_scraper(event_url: str, supabase_client: Any) -> ProviderScraper:
    """Return a ``ProviderScraper`` instance for the given event URL.

    v1 routes ``system.gotsport.com/org_event/events/<id>`` to ``GotsportScraper``.
    Any other URL raises ``UnsupportedProviderError``.
    """
    if _GOTSPORT_EVENT_URL.match(event_url):
        from src.scrapers.gotsport import GotsportScraper

        return GotsportScraper(supabase_client)
    raise UnsupportedProviderError(f"No provider scraper registered for URL: {event_url}")
