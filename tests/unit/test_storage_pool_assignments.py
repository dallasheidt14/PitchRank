"""Round-trip + missing-file coverage for ``intake/pool_assignments.json``."""

from __future__ import annotations

from pathlib import Path

from src.scrapers.gotsport_pool_parser import PoolAssignment
from src.tournaments.storage.event_key import intake_dir
from src.tournaments.storage.pool_assignments import (
    read_pool_assignments,
    write_pool_assignments,
)

EVENT_KEY = "gotsport__42433__unknown"


def test_read_returns_empty_dict_when_file_absent(tmp_path: Path):
    assert read_pool_assignments(EVENT_KEY, base_dir=tmp_path) == {}


def test_round_trip_preserves_pool_layout(tmp_path: Path):
    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    payload = {
        "365847": [
            PoolAssignment(label="A", bracket_id="501350", provider_team_ids=("100", "101", "102", "103")),
            PoolAssignment(label="B", bracket_id="501351", provider_team_ids=("200", "201", "202", "203")),
        ],
    }
    write_pool_assignments(EVENT_KEY, payload, base_dir=tmp_path)
    loaded = read_pool_assignments(EVENT_KEY, base_dir=tmp_path)
    assert loaded == payload


def test_writes_schema_version_stamp(tmp_path: Path):
    """``pool_assignments.json`` must carry ``schema_version`` so future
    readers can ``assert_supported_version`` on it."""
    import json

    intake_dir(EVENT_KEY, base_dir=tmp_path).mkdir(parents=True, exist_ok=True)
    write_pool_assignments(EVENT_KEY, {}, base_dir=tmp_path)
    raw = json.loads(
        (intake_dir(EVENT_KEY, base_dir=tmp_path) / "pool_assignments.json").read_text(encoding="utf-8")
    )
    assert "schema_version" in raw
    assert isinstance(raw["schema_version"], int)
