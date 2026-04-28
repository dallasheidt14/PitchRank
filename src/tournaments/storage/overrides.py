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
from src.tournaments.storage.scenario import acquire_scenario_lock
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
    _already_locked: bool = False,
    timeout: float = 2.0,
) -> None:
    """Append one override record. Stamps ``schema_version: 1`` automatically.

    When ``_already_locked=True``, the caller MUST already hold
    ``acquire_scenario_lock(event_key, scenario, base_dir=base_dir)``. This
    escape hatch exists so callers nested inside an existing scenario lock
    (e.g., ``_recompute_medians_inner``) don't self-deadlock on the
    non-reentrant advisory lock.

    ``timeout`` is the per-call lock-acquire timeout. Default ``2.0``s
    matches existing UI write paths; the backfill script passes ``10.0``s
    to absorb contention with operator UI writes.
    """
    path = _overrides_path(scenario_dir(event_key, scenario, base_dir=base_dir))
    record = stamp_schema_version(override)
    if _already_locked:
        append_jsonl(path, record)
        return
    with acquire_scenario_lock(event_key, scenario, base_dir=base_dir, timeout=timeout):
        append_jsonl(path, record)


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
