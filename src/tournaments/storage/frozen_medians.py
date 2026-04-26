"""Per-division power_score medians, frozen at the start of a run.

Used by the optimizer when an external team's strength must be approximated
from its division-level peers — keeps the optimizer's input deterministic
across rescrapes that happen mid-run. The Supabase query that produces the
input ``power_scores_by_division`` lives outside this shell; this module
just owns the computation + persistence.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.tournaments.storage._io import read_versioned_json, utc_now_iso, write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "FrozenMedians",
    "compute_frozen_medians",
    "read_frozen_medians",
    "write_frozen_medians",
]


@dataclass(frozen=True)
class FrozenMedians:
    """Per-division ``power_score`` median snapshot."""

    medians_by_division: dict[str, float]
    """``{division_name: median_power_score}``."""

    computed_at: str
    """UTC ISO-8601 timestamp."""

    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FrozenMedians":
        return cls(
            medians_by_division=dict(payload.get("medians_by_division") or {}),
            computed_at=payload["computed_at"],
            schema_version=int(payload.get("schema_version", 1)),
        )


def compute_frozen_medians(
    power_scores_by_division: dict[str, list[float]],
) -> FrozenMedians:
    """Compute per-division medians from a mapping of division -> scores.

    Pure function. Empty score lists are skipped (a division with no
    members produces no median entry rather than raising).
    """
    medians: dict[str, float] = {}
    for division, scores in power_scores_by_division.items():
        if not scores:
            continue
        medians[division] = float(statistics.median(scores))
    return FrozenMedians(medians_by_division=medians, computed_at=utc_now_iso())


def _medians_path(scenario_path: Path) -> Path:
    return scenario_path / "frozen_medians.json"


def read_frozen_medians(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> FrozenMedians:
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    payload = read_versioned_json(_medians_path(scenario_path))
    return FrozenMedians.from_dict(payload)


def write_frozen_medians(
    event_key: str,
    scenario: str,
    medians: FrozenMedians,
    *,
    base_dir: Path | str = "reports",
) -> None:
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    write_json(_medians_path(scenario_path), stamp_schema_version(medians.to_dict()))
