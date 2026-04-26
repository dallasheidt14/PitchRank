"""Unit tests for ``src.tournaments.storage.frozen_medians``."""

from __future__ import annotations

from pathlib import Path

from src.tournaments.storage.frozen_medians import (
    FrozenMedians,
    compute_frozen_medians,
    read_frozen_medians,
    write_frozen_medians,
)
from src.tournaments.storage.scenario import ensure_scenario

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def test_compute_medians_per_division():
    result = compute_frozen_medians(
        {
            "Premier": [10.0, 20.0, 30.0],
            "Champions": [5.0, 15.0],
        }
    )
    assert result.medians_by_division == {"Premier": 20.0, "Champions": 10.0}
    assert result.computed_at  # ISO timestamp set


def test_compute_skips_empty_division():
    result = compute_frozen_medians({"Premier": [10.0], "Empty": []})
    assert result.medians_by_division == {"Premier": 10.0}


def test_round_trip_preserves_values(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    medians = FrozenMedians(
        medians_by_division={"Premier": 20.5, "Champions": 12.25},
        computed_at="2026-04-25T12:00:00+00:00",
    )
    write_frozen_medians(EVENT_KEY, SCENARIO, medians, base_dir=tmp_path)
    loaded = read_frozen_medians(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded == medians


def test_from_dict_does_not_validate_schema_version():
    """Schema-version validation is the read boundary's job, not ``from_dict``'s.

    Pinned in symmetry with ``EventMetadata.from_dict`` /
    ``CohortConstraints.from_dict``.
    """
    medians = FrozenMedians.from_dict(
        {
            "schema_version": 999,
            "medians_by_division": {"Premier": 10.0},
            "computed_at": "2026-04-25T12:00:00+00:00",
        }
    )
    assert medians.schema_version == 999
