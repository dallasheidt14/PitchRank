"""Pin the Shell 05 ``EventMetadata.extras`` round-trip.

Existing ``event_metadata.json`` files written before Shell 05 don't have an
``extras`` field; they must continue to load cleanly with ``extras=None``.
New writes always emit the field via ``asdict``.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.event_metadata import (
    EventMetadata,
    read_event_metadata,
    write_event_metadata,
)

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
        extras={"model_version_pin": "v2"},
    )
    payload.update(overrides)
    return EventMetadata(**payload)


def test_to_dict_emits_extras():
    payload = _meta().to_dict()
    assert payload["extras"] == {"model_version_pin": "v2"}


def test_from_dict_tolerates_missing_extras():
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
    assert meta.extras is None


def test_from_dict_extracts_extras():
    payload = {
        "schema_version": 1,
        "provider_code": "gotsport",
        "provider_event_id": "45224",
        "event_name": "Phoenix Cup",
        "event_slug": "events/45224",
        "event_start_date": "2026-04-15",
        "scrape_ts": "2026-04-25T12:00:00Z",
        "extras": {"x": 1, "nested": {"y": 2}},
    }
    meta = EventMetadata.from_dict(payload)
    assert meta.extras == {"x": 1, "nested": {"y": 2}}


def test_round_trip_preserves_extras(tmp_path: Path):
    meta = _meta(extras={"capped_gd_limit": 3, "balance_score_weights": {"preset_id": "default"}})
    write_event_metadata(EVENT_KEY, meta, base_dir=tmp_path)
    loaded = read_event_metadata(EVENT_KEY, base_dir=tmp_path)
    assert loaded.extras == {"capped_gd_limit": 3, "balance_score_weights": {"preset_id": "default"}}


def test_round_trip_with_none_extras(tmp_path: Path):
    """A meta written with ``extras=None`` round-trips back to ``None``."""
    meta = _meta(extras=None)
    write_event_metadata(EVENT_KEY, meta, base_dir=tmp_path)
    loaded = read_event_metadata(EVENT_KEY, base_dir=tmp_path)
    assert loaded.extras is None


def test_pre_shell_05_payload_loads_cleanly(tmp_path: Path):
    """A pre-Shell-05 ``event_metadata.json`` (no ``extras`` key) loads as ``extras=None``."""
    target = intake_dir(EVENT_KEY, base_dir=tmp_path) / "event_metadata.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "schema_version": 1,
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
    loaded = read_event_metadata(EVENT_KEY, base_dir=tmp_path)
    assert loaded.extras is None
