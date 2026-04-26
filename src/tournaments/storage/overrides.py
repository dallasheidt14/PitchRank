"""Scenario-level intake-time overrides — append-only JSONL.

Spec §10 fold-in 14: overrides survive rescrape via merge on
``provider_team_id`` (cf. ``rescrape.merge_rescrape``). The append-only
contract means there is no edit/delete API — corrections are new records
with ``ts`` ordering. Replay-from-zero produces the canonical overrides
state.

Each record is stamped ``schema_version: 1`` on write and validated per
record on load.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tournaments.storage._io import append_jsonl, read_jsonl
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import (
    assert_supported_version,
    stamp_schema_version,
)

__all__ = [
    "append_override",
    "load_overrides",
]


def _overrides_path(scenario_path: Path) -> Path:
    return scenario_path / "overrides.jsonl"


def append_override(
    event_key: str,
    scenario: str,
    override: dict[str, Any],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Append one override record. Stamps ``schema_version: 1`` automatically."""
    path = _overrides_path(scenario_dir(event_key, scenario, base_dir=base_dir))
    append_jsonl(path, stamp_schema_version(override))


def load_overrides(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> list[dict[str, Any]]:
    """Return all override records in insertion order, validating each schema version."""
    path = _overrides_path(scenario_dir(event_key, scenario, base_dir=base_dir))
    records: list[dict[str, Any]] = []
    for index, record in enumerate(read_jsonl(path)):
        assert_supported_version(record, source=f"{path}:record[{index}]")
        records.append(record)
    return records
