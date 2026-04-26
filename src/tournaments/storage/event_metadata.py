"""``EventMetadata`` dataclass — event-level scrape result + storage round-trip.

Moved here from ``src/scrapers/provider.py:45`` so the storage layer owns
the canonical definition. Re-exported from ``src.scrapers.provider`` for
back-compat with Shell 01 callers.

The ``season_year`` field is **optional** — Shell 01 callers
(``gotsport.fetch_event_metadata`` at ``gotsport.py:2862-2869``) construct
without it and the legacy ``__unknown`` event-key form still applies via
``storage.event_key.event_key(..., season_year=None)``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.tournaments.storage._io import read_versioned_json, write_json
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "EventMetadata",
    "read_event_metadata",
    "write_event_metadata",
]


@dataclass(frozen=True)
class EventMetadata:
    """Event-level metadata scraped from the provider landing page.

    ``season_year`` is optional for Shell 01 back-compat — when ``None``,
    ``storage.event_key.event_key`` falls back to the ``__unknown`` form.
    """

    provider_code: str
    provider_event_id: str
    event_name: str
    event_slug: str
    event_start_date: str | None
    scrape_ts: str
    season_year: int | None = None
    series_id: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventMetadata":
        """Construct from a payload, tolerating a missing ``season_year``.

        Schema-version validation is the read boundary's job (matches
        ``CohortConstraints.from_dict`` / ``FrozenMedians.from_dict``).
        Callers that don't go through ``read_event_metadata`` should
        compose ``assert_supported_version(payload, source=...)`` first.
        """
        return cls(
            provider_code=payload["provider_code"],
            provider_event_id=payload["provider_event_id"],
            event_name=payload["event_name"],
            event_slug=payload["event_slug"],
            event_start_date=payload.get("event_start_date"),
            scrape_ts=payload["scrape_ts"],
            season_year=payload.get("season_year"),
            series_id=payload.get("series_id"),
            schema_version=int(payload.get("schema_version", 1)),
        )


def read_event_metadata(event_key: str, *, base_dir: Path | str = "reports") -> EventMetadata:
    """Read ``intake/event_metadata.json`` and return an ``EventMetadata``."""
    path = intake_dir(event_key, base_dir=base_dir) / "event_metadata.json"
    payload = read_versioned_json(path)
    return EventMetadata.from_dict(payload)


def write_event_metadata(
    event_key: str,
    meta: EventMetadata,
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Write ``meta`` to ``intake/event_metadata.json`` with the schema stamp."""
    path = intake_dir(event_key, base_dir=base_dir) / "event_metadata.json"
    write_json(path, stamp_schema_version(meta.to_dict()))
