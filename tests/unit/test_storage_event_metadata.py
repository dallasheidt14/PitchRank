"""Unit tests for ``src.tournaments.storage.event_metadata``.

Round-trips JSON, asserts ``from_dict`` tolerates missing ``season_year``,
and verifies the schema-version mismatch raises ``SchemaVersionError``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.event_metadata import (
    EventMetadata,
    read_event_metadata,
    write_event_metadata,
)
from src.tournaments.storage.schema_version import SchemaVersionError

EVENT_KEY = "gotsport__45224__2026"


def _meta(**overrides) -> EventMetadata:
    payload = dict(
        provider_code="gotsport",
        provider_event_id="45224",
        event_name="Phoenix Cup",
        event_slug="events/45224",
        event_start_date="2026-04-15",
        scrape_ts="2026-04-25T12:00:00Z",
        season_year=2026,
        series_id=None,
    )
    payload.update(overrides)
    return EventMetadata(**payload)


def test_round_trip(tmp_path: Path):
    meta = _meta()
    write_event_metadata(EVENT_KEY, meta, base_dir=tmp_path)
    loaded = read_event_metadata(EVENT_KEY, base_dir=tmp_path)
    assert loaded == meta


def test_round_trip_with_optional_season_year_missing(tmp_path: Path):
    meta = _meta(season_year=None)
    write_event_metadata(EVENT_KEY, meta, base_dir=tmp_path)
    loaded = read_event_metadata(EVENT_KEY, base_dir=tmp_path)
    assert loaded.season_year is None


def test_from_dict_tolerates_missing_season_year():
    payload = {
        "schema_version": 1,
        "provider_code": "gotsport",
        "provider_event_id": "45224",
        "event_name": "Phoenix Cup",
        "event_slug": "events/45224",
        "event_start_date": "2026-04-15",
        "scrape_ts": "2026-04-25T12:00:00Z",
    }
    meta = EventMetadata.from_dict(payload)
    assert meta.season_year is None


def test_from_dict_tolerates_missing_schema_version():
    """Lenient on read — Shell 01-era unstamped payloads still load."""
    payload = {
        "provider_code": "gotsport",
        "provider_event_id": "45224",
        "event_name": "Phoenix Cup",
        "event_slug": "events/45224",
        "event_start_date": "2026-04-15",
        "scrape_ts": "2026-04-25T12:00:00Z",
    }
    meta = EventMetadata.from_dict(payload)
    assert meta.schema_version == 1


def test_read_raises_schema_version_error_on_newer(tmp_path: Path):
    target = intake_dir(EVENT_KEY, base_dir=tmp_path) / "event_metadata.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider_code": "gotsport",
                "provider_event_id": "45224",
                "event_name": "Phoenix Cup",
                "event_slug": "events/45224",
                "event_start_date": "2026-04-15",
                "scrape_ts": "2026-04-25T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SchemaVersionError, match="schema_version=2"):
        read_event_metadata(EVENT_KEY, base_dir=tmp_path)


def test_to_dict_includes_schema_version():
    meta = _meta()
    payload = meta.to_dict()
    assert payload["schema_version"] == 1
    assert payload["season_year"] == 2026
    assert payload["provider_code"] == "gotsport"


def test_from_dict_does_not_validate_schema_version():
    """Validation belongs at the read boundary; ``from_dict`` is a pure constructor.

    Matches ``CohortConstraints.from_dict`` / ``FrozenMedians.from_dict``.
    A future "helpful" re-introduction of validation here would silently
    break the symmetry — pin the contract.
    """
    payload = {
        "schema_version": 999,
        "provider_code": "gotsport",
        "provider_event_id": "45224",
        "event_name": "Phoenix Cup",
        "event_slug": "events/45224",
        "event_start_date": "2026-04-15",
        "scrape_ts": "2026-04-25T12:00:00Z",
    }
    meta = EventMetadata.from_dict(payload)
    assert meta.schema_version == 999
