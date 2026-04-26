"""Per-cohort seeding constraints — JSON-backed dataclass.

Spec §7 names exactly four per-cohort constraints. v1 ships these four
data-model-only fields and nothing more — the optimizer signature is
unchanged in v1; the *post-run* Report Card metrics in Shell 07 compute
violations from the optimizer output. v2 wires the fields into the
optimizer.

The on-disk shape is::

    {
      "schema_version": 1,
      "cohorts": [
        {
          "cohort_age_group": "u14",
          "cohort_gender": "Female",
          "avoid_same_club_early": true,
          "avoid_same_coach_early": true,
          "avoid_same_state_pool": false,
          "rematch_avoidance_scope": "same_event"
        },
        ...
      ]
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from src.tournaments.storage._io import read_versioned_json, write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import stamp_schema_version

__all__ = [
    "CohortConstraints",
    "RematchAvoidanceScope",
    "read_constraints",
    "write_constraints",
]


RematchAvoidanceScope = Literal["same_event", "same_season", "prior_weekend"]
_REMATCH_SCOPE_VALUES: frozenset[str] = frozenset(("same_event", "same_season", "prior_weekend"))


@dataclass(frozen=True)
class CohortConstraints:
    """Spec §7 row defaults are enforced here, not in the JSON file.

    A new constraints.json with no entries for a cohort yields the v1
    defaults via ``CohortConstraints(cohort_age_group=..., cohort_gender=...)``.
    """

    cohort_age_group: str
    cohort_gender: str
    avoid_same_club_early: bool = True
    avoid_same_coach_early: bool = True
    avoid_same_state_pool: bool = False
    rematch_avoidance_scope: RematchAvoidanceScope = "same_event"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.rematch_avoidance_scope not in _REMATCH_SCOPE_VALUES:
            raise ValueError(
                f"rematch_avoidance_scope must be one of "
                f"{sorted(_REMATCH_SCOPE_VALUES)}; got {self.rematch_avoidance_scope!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CohortConstraints":
        """Construct from a payload, defaulting missing fields to spec §7 values."""
        return cls(
            cohort_age_group=payload["cohort_age_group"],
            cohort_gender=payload["cohort_gender"],
            avoid_same_club_early=bool(payload.get("avoid_same_club_early", True)),
            avoid_same_coach_early=bool(payload.get("avoid_same_coach_early", True)),
            avoid_same_state_pool=bool(payload.get("avoid_same_state_pool", False)),
            rematch_avoidance_scope=payload.get("rematch_avoidance_scope", "same_event"),
            schema_version=int(payload.get("schema_version", 1)),
        )


def _constraints_path(scenario_path: Path) -> Path:
    return scenario_path / "constraints.json"


def read_constraints(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> list[CohortConstraints]:
    """Read ``constraints.json`` and return one ``CohortConstraints`` per cohort entry."""
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    payload = read_versioned_json(_constraints_path(scenario_path))
    cohorts = payload.get("cohorts") or []
    return [CohortConstraints.from_dict(entry) for entry in cohorts]


def write_constraints(
    event_key: str,
    scenario: str,
    constraints: list[CohortConstraints],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Write ``constraints.json`` with the schema-version stamp."""
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    payload = stamp_schema_version({"cohorts": [entry.to_dict() for entry in constraints]})
    write_json(_constraints_path(scenario_path), payload)
