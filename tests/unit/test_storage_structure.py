"""Unit tests for ``src.tournaments.storage.structure``."""

from __future__ import annotations

from pathlib import Path

from src.tournaments.seeding_optimizer import DivisionSpec
from src.tournaments.storage.scenario import ensure_scenario
from src.tournaments.storage.structure import (
    CohortStructure,
    DivisionStructure,
    read_structure,
    write_structure,
)

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def test_to_division_spec_field_match():
    division = DivisionStructure(
        name="Premier",
        team_count=8,
        pool_sizes=(4, 4),
        advancement="cross_semis_final",
    )
    spec = division.to_division_spec()
    assert isinstance(spec, DivisionSpec)
    assert spec.name == "Premier"
    assert spec.team_count == 8
    assert spec.pool_sizes == (4, 4)
    assert spec.advancement == "cross_semis_final"


def test_pool_sizes_round_trip(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    cohorts = [
        CohortStructure(
            age_group="u14",
            gender="Female",
            divisions=(
                DivisionStructure(
                    name="Premier",
                    team_count=12,
                    pool_sizes=(4, 4, 4),
                ),
                DivisionStructure(
                    name="Champions",
                    team_count=8,
                ),
            ),
        ),
    ]
    write_structure(EVENT_KEY, SCENARIO, cohorts, base_dir=tmp_path)
    loaded = read_structure(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded == cohorts
    # Empty tuple round-trips as empty string in CSV
    assert loaded[0].divisions[1].pool_sizes == ()


def test_advancement_none_round_trip(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    cohorts = [
        CohortStructure(
            age_group="u15",
            gender="Male",
            divisions=(DivisionStructure(name="A", team_count=4, pool_sizes=(4,)),),
        ),
    ]
    write_structure(EVENT_KEY, SCENARIO, cohorts, base_dir=tmp_path)
    loaded = read_structure(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded[0].divisions[0].advancement is None


def test_grouping_by_cohort(tmp_path: Path):
    """Multiple divisions per cohort group correctly on read."""
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    cohorts = [
        CohortStructure(
            age_group="u14",
            gender="Female",
            divisions=(
                DivisionStructure(name="Premier", team_count=4),
                DivisionStructure(name="Champions", team_count=4),
            ),
        ),
        CohortStructure(
            age_group="u15",
            gender="Male",
            divisions=(DivisionStructure(name="Premier", team_count=8),),
        ),
    ]
    write_structure(EVENT_KEY, SCENARIO, cohorts, base_dir=tmp_path)
    loaded = read_structure(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert len(loaded) == 2
    assert len(loaded[0].divisions) == 2
    assert len(loaded[1].divisions) == 1
