"""Unit tests for ``src.tournaments.storage.overrides``.

Append-only contract: 3 appends produce 3 records, insertion order is
preserved, and every record carries ``schema_version: 1``.
"""

from __future__ import annotations

from pathlib import Path

from src.tournaments.storage.overrides import append_override, load_overrides
from src.tournaments.storage.scenario import ensure_scenario

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def test_append_three_records_preserves_order(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    for index in range(3):
        append_override(
            EVENT_KEY,
            SCENARIO,
            {"provider_team_id": f"t{index}", "ts": f"2026-04-25T12:0{index}:00Z"},
            base_dir=tmp_path,
        )
    records = load_overrides(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert len(records) == 3
    assert [r["provider_team_id"] for r in records] == ["t0", "t1", "t2"]


def test_every_record_stamped_schema_version_one(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    append_override(EVENT_KEY, SCENARIO, {"provider_team_id": "t1"}, base_dir=tmp_path)
    records = load_overrides(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert records[0]["schema_version"] == 1


def test_load_returns_empty_when_no_overrides(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert load_overrides(EVENT_KEY, SCENARIO, base_dir=tmp_path) == []


def test_user_supplied_schema_version_is_overridden_by_stamp(tmp_path: Path):
    """Strict-on-write: callers can't slip in a stale stamp."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    append_override(
        EVENT_KEY,
        SCENARIO,
        {"provider_team_id": "t1", "schema_version": 0},
        base_dir=tmp_path,
    )
    records = load_overrides(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert records[0]["schema_version"] == 1
