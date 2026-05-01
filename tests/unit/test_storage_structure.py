"""Unit tests for ``src.tournaments.storage.structure``."""

from __future__ import annotations

from pathlib import Path

from src.tournaments.seeding_optimizer import DivisionSpec
from src.tournaments.storage.scenario import ensure_scenario
from src.tournaments.storage.structure import (
    CohortStructure,
    DivisionStructure,
    derive_structure_from_raw_scrape,
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


# -------- derive_structure_from_raw_scrape --------------------------


def _scraped(
    bracket: str,
    group: str,
    *,
    cohort_age: str | None = None,
    cohort_gender: str | None = None,
) -> dict:
    return {
        "bracket_name": bracket,
        "group_name": group,
        "cohort_age_group": cohort_age,
        "cohort_gender": cohort_gender,
    }


def test_derive_structure_uses_normalized_natural_cohort_keys():
    """Cohort keys come from ``cohort_age_group`` / ``cohort_gender`` so they
    match the Streamlit UI's ``_group_cohorts`` iteration. Division names
    stay verbatim (gotsport ``group_name``)."""
    records = [
        _scraped("U13G", "Red", cohort_age="U13", cohort_gender="F"),
        _scraped("U13G", "Red", cohort_age="U13", cohort_gender="F"),
        _scraped("U13G", "White", cohort_age="U13", cohort_gender="F"),
        _scraped("U13B", "Blue", cohort_age="U13", cohort_gender="M"),
    ]
    result = derive_structure_from_raw_scrape(records)
    cohort_keys = [(c.age_group, c.gender) for c in result]
    assert cohort_keys == [("u13", "Female"), ("u13", "Male")]
    u13f = next(c for c in result if c.gender == "Female")
    assert {d.name: d.team_count for d in u13f.divisions} == {"Red": 2, "White": 1}


def test_derive_structure_preserves_exact_group_name():
    """``group_name`` is the literal tournament designation; never renamed."""
    records = [
        _scraped("U18B", "Capelli Sport+ Southwest", cohort_age="U18", cohort_gender="M"),
        _scraped("U17B", "PDT Academy Cup", cohort_age="U17", cohort_gender="M"),
        _scraped("U17B", "PDT Academy Cup", cohort_age="U17", cohort_gender="M"),
    ]
    result = derive_structure_from_raw_scrape(records)
    division_names = {d.name for c in result for d in c.divisions}
    assert "Capelli Sport+ Southwest" in division_names
    assert "PDT Academy Cup" in division_names


def test_derive_structure_groups_play_ups_under_natural_cohort():
    """A U12 girl playing in U13G Jefferson appears in the *natural* U12 F
    cohort with division "Jefferson" — matches the UI's natural-cohort
    iteration. (Bracket-keyed grouping is a separate, larger refactor.)"""
    records = [
        _scraped("U13G", "Jefferson", cohort_age="U12", cohort_gender="F"),
        _scraped("U13G", "Jefferson", cohort_age="U12", cohort_gender="F"),
        _scraped("U13G", "Jefferson", cohort_age="U13", cohort_gender="F"),
    ]
    result = derive_structure_from_raw_scrape(records)
    by_cohort = {(c.age_group, c.gender): c for c in result}
    assert by_cohort[("u12", "Female")].divisions[0].name == "Jefferson"
    assert by_cohort[("u12", "Female")].divisions[0].team_count == 2
    assert by_cohort[("u13", "Female")].divisions[0].team_count == 1


def test_derive_structure_drops_records_with_no_age_or_no_division():
    records = [
        _scraped("U13G", "Red", cohort_age="", cohort_gender="F"),  # no age
        _scraped("U13G", "", cohort_age="U13", cohort_gender="F"),  # no division
        _scraped("U13G", "Red", cohort_age="U13", cohort_gender="F"),
    ]
    result = derive_structure_from_raw_scrape(records)
    assert len(result) == 1
    assert result[0].divisions[0].name == "Red"
    assert result[0].divisions[0].team_count == 1


def test_derive_structure_sorts_cohorts_oldest_first_then_female():
    records = [
        _scraped("U13B", "Red", cohort_age="U13", cohort_gender="M"),
        _scraped("U10G", "Blue", cohort_age="U10", cohort_gender="F"),
        _scraped("U13G", "Red", cohort_age="U13", cohort_gender="F"),
    ]
    result = derive_structure_from_raw_scrape(records)
    assert [(c.age_group, c.gender) for c in result] == [
        ("u10", "Female"),
        ("u13", "Female"),
        ("u13", "Male"),
    ]


def test_derive_structure_empty_records_returns_empty_list():
    assert derive_structure_from_raw_scrape([]) == []


def test_derive_structure_populates_pool_sizes_from_pool_assignments():
    """When ``pools_by_group_id`` is supplied, ``DivisionStructure.pool_sizes``
    reflects the per-pool team counts, sorted by pool label."""
    records = [
        _scraped("U13B", "Red", cohort_age="U13", cohort_gender="M"),
        _scraped("U13B", "Red", cohort_age="U13", cohort_gender="M"),
    ]
    for rec in records:
        rec["group_id"] = 365847
    pools_by_group_id = {
        "365847": [
            {"label": "B", "bracket_id": "501351", "provider_team_ids": ["1", "2", "3"]},
            {"label": "A", "bracket_id": "501350", "provider_team_ids": ["4", "5", "6", "7"]},
        ],
    }
    result = derive_structure_from_raw_scrape(records, pools_by_group_id=pools_by_group_id)
    assert len(result) == 1
    assert result[0].divisions[0].pool_sizes == (4, 3)


def test_derive_structure_pool_sizes_empty_when_group_id_not_in_map():
    records = [_scraped("U13B", "Red", cohort_age="U13", cohort_gender="M")]
    records[0]["group_id"] = 999
    result = derive_structure_from_raw_scrape(records, pools_by_group_id={"365847": []})
    assert result[0].divisions[0].pool_sizes == ()


def test_derive_structure_no_pools_arg_leaves_pool_sizes_empty():
    """Backwards-compatible: omitting ``pools_by_group_id`` matches the
    pre-pool behavior — empty ``pool_sizes`` everywhere."""
    records = [_scraped("U13B", "Red", cohort_age="U13", cohort_gender="M")]
    records[0]["group_id"] = 365847
    result = derive_structure_from_raw_scrape(records)
    assert result[0].divisions[0].pool_sizes == ()
