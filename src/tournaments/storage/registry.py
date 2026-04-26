"""Per-team event registry CSV — wire format mirrors the existing CLI consumer.

Spec §8 line 302: *"the existing ``backtest_tournament_event.py`` CLI is
unchanged for v1."* The columns the CLI reads from
``event_team_registry.csv`` are authoritative — this storage library is a
passthrough to that format.

Authoritative column set (verified against
``scripts/backtest_tournament_event.py:145-153, 167-217``):

- Input columns the Streamlit layer writes / the CLI reads:
  ``event_registration_id``, ``event_team_name``, ``event_age_group``,
  ``display_age_group``, ``event_gender``, ``display_gender``,
  ``event_club_name``, ``search_age_group``,
  ``resolved_gotsport_provider_team_id``, ``canonical_resolution_status``,
  ``in_scope_u10_u19`` (string ``"True"``/``"False"`` — see
  ``backtest_tournament_event.py:177``), ``resolved_team_id_master``,
  ``resolved_team_name``, ``resolved_club_name``.
- Matcher-output columns the CLI appends and re-reads on a round trip:
  ``matcher_status``, ``matcher_best_score``, ``matcher_second_score``,
  ``matcher_score_gap``, ``matcher_resolved_team_id_master``,
  ``matcher_resolved_team_name``, ``matcher_resolved_club_name``,
  ``matcher_resolved_provider_team_id``.

Schema-version stamp lives in the sibling ``event_team_registry.schema.json``
(one stamp per file), not as a per-row dataclass field — JSON-backed
dataclasses (``EventMetadata``, ``CohortConstraints``, ``FrozenMedians``)
carry ``schema_version`` because they round-trip as a single dict.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from src.tournaments.storage._io import read_csv, read_json, write_csv, write_json
from src.tournaments.storage.event_key import scenario_dir
from src.tournaments.storage.schema_version import (
    assert_supported_version,
    stamp_schema_version,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FIELDNAMES",
    "TeamRegistryEntry",
    "read_registry",
    "write_registry",
]


FIELDNAMES: tuple[str, ...] = (
    # Input columns — Streamlit writes, CLI reads
    "event_registration_id",
    "event_team_name",
    "event_age_group",
    "display_age_group",
    "event_gender",
    "display_gender",
    "event_club_name",
    "search_age_group",
    "resolved_gotsport_provider_team_id",
    "canonical_resolution_status",
    "in_scope_u10_u19",
    "resolved_team_id_master",
    "resolved_team_name",
    "resolved_club_name",
    # Matcher-output columns — CLI appends in this order
    # (see ``backtest_tournament_event.py:168-175``)
    "matcher_status",
    "matcher_best_score",
    "matcher_second_score",
    "matcher_score_gap",
    "matcher_resolved_team_id_master",
    "matcher_resolved_team_name",
    "matcher_resolved_club_name",
    "matcher_resolved_provider_team_id",
)


@dataclass(frozen=True)
class TeamRegistryEntry:
    """One row of ``event_team_registry.csv``.

    Every field is ``str`` to round-trip the CSV exactly — the CLI consumes
    strings and the matcher stores numeric scores as ``int | float | ""``,
    which only round-trips losslessly through string fields.

    No ``schema_version`` field — schema versioning for the CSV-backed
    registry lives in the sibling ``event_team_registry.schema.json`` (one
    stamp per file), not per row.
    """

    event_registration_id: str = ""
    event_team_name: str = ""
    event_age_group: str = ""
    display_age_group: str = ""
    event_gender: str = ""
    display_gender: str = ""
    event_club_name: str = ""
    search_age_group: str = ""
    resolved_gotsport_provider_team_id: str = ""
    canonical_resolution_status: str = ""
    in_scope_u10_u19: str = ""
    resolved_team_id_master: str = ""
    resolved_team_name: str = ""
    resolved_club_name: str = ""
    matcher_status: str = ""
    matcher_best_score: str = ""
    matcher_second_score: str = ""
    matcher_score_gap: str = ""
    matcher_resolved_team_id_master: str = ""
    matcher_resolved_team_name: str = ""
    matcher_resolved_club_name: str = ""
    matcher_resolved_provider_team_id: str = ""

    def to_row(self) -> dict[str, str]:
        """String-only round-trip — no type coercion (CLI consumes strings)."""
        return {field.name: getattr(self, field.name) for field in fields(self)}

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "TeamRegistryEntry":
        """Construct from a CSV row, defaulting missing columns to ``""``.

        Extra columns in the CSV are silently ignored (forward-compat
        within ``schema_version: 1``; cf. ``write_registry`` policy).
        """
        kwargs = {field.name: str(row.get(field.name, "") or "") for field in fields(cls)}
        return cls(**kwargs)


def _schema_path(scenario_path: Path) -> Path:
    return scenario_path / "event_team_registry.schema.json"


def _csv_path(scenario_path: Path) -> Path:
    return scenario_path / "event_team_registry.csv"


def read_registry(
    event_key: str,
    scenario: str,
    *,
    base_dir: Path | str = "reports",
) -> list[TeamRegistryEntry]:
    """Read the per-scenario team registry CSV.

    Validates the sibling ``event_team_registry.schema.json`` via
    ``assert_supported_version`` (raises ``SchemaVersionError`` on a newer
    schema). A FIELDNAMES mismatch is **logged as a warning but does NOT
    raise** — the CSV header itself is the authoritative wire-format check,
    and v1.x adds of optional matcher-output columns must remain
    forward-compatible within ``schema_version: 1``.
    """
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    schema_path = _schema_path(scenario_path)
    if schema_path.exists():
        sidecar = read_json(schema_path)
        assert_supported_version(sidecar, source=str(schema_path))
        sidecar_fields = tuple(sidecar.get("fieldnames") or ())
        if sidecar_fields and sidecar_fields != FIELDNAMES:
            logger.warning(
                "[registry] %s sibling FIELDNAMES drift; on-disk=%s expected=%s",
                schema_path.name,
                sidecar_fields,
                FIELDNAMES,
            )

    rows = read_csv(_csv_path(scenario_path))
    return [TeamRegistryEntry.from_row(row) for row in rows]


def write_registry(
    event_key: str,
    scenario: str,
    entries: list[TeamRegistryEntry],
    *,
    base_dir: Path | str = "reports",
) -> None:
    """Write the per-scenario team registry CSV + sibling schema stamp."""
    scenario_path = scenario_dir(event_key, scenario, base_dir=base_dir)
    rows = [entry.to_row() for entry in entries]
    write_csv(_csv_path(scenario_path), rows, fieldnames=FIELDNAMES)
    write_json(
        _schema_path(scenario_path),
        stamp_schema_version({"fieldnames": list(FIELDNAMES)}),
    )
