"""Unit tests for ``src.tournaments.storage.constraints``.

Asserts the four spec §7 fields, their defaults, and ``Literal`` validation
for ``rematch_avoidance_scope``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tournaments.storage.constraints import (
    CohortConstraints,
    read_constraints,
    write_constraints,
)
from src.tournaments.storage.scenario import ensure_scenario

EVENT_KEY = "gotsport__45224__2026"
SCENARIO = "default"


def test_defaults_match_spec_section_7():
    constraint = CohortConstraints(cohort_age_group="u14", cohort_gender="Female")
    assert constraint.avoid_same_club_early is True
    assert constraint.avoid_same_coach_early is True
    assert constraint.avoid_same_state_pool is False
    assert constraint.rematch_avoidance_scope == "same_event"
    assert constraint.schema_version == 1


def test_round_trip(tmp_path: Path):
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    constraints = [
        CohortConstraints(
            cohort_age_group="u14",
            cohort_gender="Female",
            avoid_same_state_pool=True,
            rematch_avoidance_scope="prior_weekend",
        ),
        CohortConstraints(cohort_age_group="u15", cohort_gender="Male"),
    ]
    write_constraints(EVENT_KEY, SCENARIO, constraints, base_dir=tmp_path)
    loaded = read_constraints(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    assert loaded == constraints


def test_rejects_out_of_vocabulary_rematch_scope():
    with pytest.raises(ValueError, match="rematch_avoidance_scope"):
        CohortConstraints(
            cohort_age_group="u14",
            cohort_gender="Female",
            rematch_avoidance_scope="never",  # type: ignore[arg-type]
        )


def test_from_dict_defaults_missing_fields():
    constraint = CohortConstraints.from_dict({"cohort_age_group": "u14", "cohort_gender": "Female"})
    assert constraint.avoid_same_club_early is True
    assert constraint.rematch_avoidance_scope == "same_event"


def test_from_dict_rejects_invalid_scope():
    with pytest.raises(ValueError, match="rematch_avoidance_scope"):
        CohortConstraints.from_dict(
            {
                "cohort_age_group": "u14",
                "cohort_gender": "Female",
                "rematch_avoidance_scope": "yearly",
            }
        )


def test_from_dict_does_not_validate_schema_version():
    """Schema-version validation is the read boundary's job, not ``from_dict``'s.

    Pinned in symmetry with ``EventMetadata.from_dict`` /
    ``FrozenMedians.from_dict`` so a future re-introduction of validation
    here would break a test.
    """
    constraint = CohortConstraints.from_dict(
        {
            "schema_version": 999,
            "cohort_age_group": "u14",
            "cohort_gender": "Female",
        }
    )
    assert constraint.schema_version == 999


def test_per_cohort_writes_preserve_other_cohorts(tmp_path: Path):
    """Editing one cohort's constraints must not rewrite a sibling's entry.

    Pins Shell 05's ``_persist_constraint`` "read-then-replace" semantics: an
    operator toggling u14 Male shouldn't silently re-emit u14 Female's defaults.
    """
    ensure_scenario(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    male_entry = CohortConstraints(
        cohort_age_group="u14",
        cohort_gender="Male",
        avoid_same_state_pool=True,
        rematch_avoidance_scope="prior_weekend",
    )
    female_entry = CohortConstraints(
        cohort_age_group="u14",
        cohort_gender="Female",
        avoid_same_club_early=False,
        avoid_same_state_pool=True,
        rematch_avoidance_scope="same_season",
    )
    write_constraints(EVENT_KEY, SCENARIO, [male_entry, female_entry], base_dir=tmp_path)

    loaded = read_constraints(EVENT_KEY, SCENARIO, base_dir=tmp_path)
    updated: list[CohortConstraints] = []
    for entry in loaded:
        if entry.cohort_age_group == "u14" and entry.cohort_gender == "Male":
            from dataclasses import replace as _replace

            updated.append(_replace(entry, avoid_same_club_early=False))
        else:
            updated.append(entry)
    write_constraints(EVENT_KEY, SCENARIO, updated, base_dir=tmp_path)

    final = {(c.cohort_age_group, c.cohort_gender): c for c in read_constraints(EVENT_KEY, SCENARIO, base_dir=tmp_path)}
    assert final[("u14", "Male")].avoid_same_club_early is False
    assert final[("u14", "Female")] == female_entry
