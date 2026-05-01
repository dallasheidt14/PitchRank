"""Provider-scraper abstraction for event-level intake.

Shell-01 foundations for the MatchBalance backtest intake pipeline. Defines:

- ``ProviderScraper`` ABC — the cohort/team/canonical-ID surface every provider
  implements.
- Dataclasses ``ScrapedTeam``, ``CanonicalResolution`` — the wire format
  between scraper and downstream persistence. ``EventMetadata`` lives in
  ``src.tournaments.storage.event_metadata`` and is re-exported here.
- ``UnsupportedProviderError`` — raised when a provider row is missing or a
  URL does not route to a known provider.
- ``get_provider_scraper`` — URL-pattern factory.
- Path helpers ``_derive_event_key`` / ``_intake_path`` — thin shims over
  ``src.tournaments.storage`` that fall back to the ``__unknown`` season
  segment for Shell 01 callers that don't populate ``season_year``.

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
from src.tournaments.storage.event_key import event_key as _storage_event_key
from src.tournaments.storage.event_key import intake_dir as _storage_intake_dir
from src.tournaments.storage.event_metadata import EventMetadata

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
    # Tier-section enrichment (Shell 02 — gotsport tier-section parser).
    # IMPORTANT: ``group_name`` here is the TIER RESIDUE (e.g., "Red", "GOLD"),
    # NOT the bracket-section label that ``EventTeam.group_name`` carries.
    # See ``.turbo/specs/gotsport-tier-section-parser.md`` for the persisted-data contract.
    group_name: str | None = None
    group_id: int | None = None
    tier_discovery_source: str = "none"
    tier_membership_source: str = "none"
    tier_parse_outcome: str = "unenriched"


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

    Thin shim over ``storage.event_key.event_key``. When ``meta.season_year``
    is ``None`` (Shell 01 callers that don't populate it), the legacy
    ``__unknown`` segment is used; the rekey migration in
    ``storage.event_key.rekey_unknown_directories`` is the sanctioned path
    for upgrading those keys once a season_year becomes derivable.
    """
    return _storage_event_key(meta.provider_code, meta.provider_event_id, meta.season_year)


def _intake_path(event_key: str) -> Path:
    """Resolve the on-disk ``raw_scrape.jsonl`` location for an event key."""
    return _storage_intake_dir(event_key) / "raw_scrape.jsonl"


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
