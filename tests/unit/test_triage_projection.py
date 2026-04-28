"""Unit tests for ``src.tournaments.triage.project_overrides``.

Pins latest-wins semantics, per-type field projections, the cohort-scoped
``recompute_medians`` lane, and forward-compat skip-with-warning behavior
for unrecognized override types.
"""

from __future__ import annotations

import logging

import pytest

from src.tournaments.triage import (
    DivisionResolution,
    ProjectedCohortState,
    ProjectedTeamState,
    _apply_team_override,
    project_overrides,
    resolve_division_assignment,
)


def _team_record(type_: str, team_ref: str, after: dict, *, ts: str | None = None, before: dict | None = None) -> dict:
    return {
        "ts": ts or "2026-04-26T12:00:00+00:00",
        "actor": "dallas@example.com",
        "scope": "team",
        "type": type_,
        "team_ref": team_ref,
        "before": before or {},
        "after": after,
        "reason": "test",
    }


def _cohort_record(type_: str, team_ref: str, after: dict, *, ts: str | None = None) -> dict:
    return {
        "ts": ts or "2026-04-26T12:00:00+00:00",
        "actor": "dallas@example.com",
        "scope": "cohort",
        "type": type_,
        "team_ref": team_ref,
        "before": {},
        "after": after,
        "reason": "test",
    }


def test_empty_records_returns_two_empty_mappings():
    team_state, cohort_state = project_overrides([])
    assert team_state == {}
    assert cohort_state == {}


def test_accept_match_produces_resolved_team_state():
    records = [
        _team_record(
            "accept_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "abc", "match_rank": 1},
        )
    ]
    team_state, _ = project_overrides(records)
    assert "pid-1" in team_state
    assert team_state["pid-1"] == ProjectedTeamState(
        state="resolved",
        team_id_master="abc",
        last_override_ts="2026-04-26T12:00:00+00:00",
    )


def test_accept_match_does_not_project_match_rank():
    """``match_rank`` lives in the JSONL ``after`` payload but is NOT
    projected — ``ProjectedTeamState`` has no ``match_rank`` attribute."""
    records = [
        _team_record(
            "accept_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "abc", "match_rank": 1},
        )
    ]
    team_state, _ = project_overrides(records)
    assert not hasattr(team_state["pid-1"], "match_rank")


def test_latest_record_wins_per_team_ref():
    """``mark_external`` after ``accept_match`` flips the team to
    external — by design (no revert type in the append-only contract)."""
    records = [
        _team_record(
            "accept_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "abc"},
            ts="2026-04-26T12:00:00+00:00",
        ),
        _team_record(
            "mark_external",
            "pid-1",
            {"state": "external"},
            ts="2026-04-26T13:00:00+00:00",
        ),
    ]
    team_state, _ = project_overrides(records)
    assert team_state["pid-1"].state == "external"
    assert team_state["pid-1"].team_id_master is None


def test_recompute_medians_appears_in_cohort_state_only():
    records = [
        _cohort_record(
            "recompute_medians",
            "u14_Male",
            {"medians_by_division": {"Premier": 14.2, "Champions": 12.0}},
        )
    ]
    team_state, cohort_state = project_overrides(records)
    assert team_state == {}
    assert "u14_Male" in cohort_state
    assert cohort_state["u14_Male"] == ProjectedCohortState(
        medians_by_division={"Premier": 14.2, "Champions": 12.0},
        last_override_ts="2026-04-26T12:00:00+00:00",
    )


def test_manual_add_then_edit_external_reflects_edit():
    records = [
        _team_record(
            "manual_add",
            "manual_pid-1",
            {
                "state": "external",
                "manual_seed_group": "Premier",
                "strength_mode": "median",
            },
            ts="2026-04-26T12:00:00+00:00",
        ),
        _team_record(
            "edit_external",
            "manual_pid-1",
            {
                "state": "external",
                "manual_seed_group": "Champions",
                "strength_mode": "manual",
                "manual_power_score": 13.5,
                "note": "operator-assigned",
            },
            ts="2026-04-26T13:00:00+00:00",
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["manual_pid-1"]
    assert final.state == "external"
    assert final.manual_seed_group == "Champions"
    assert final.strength_mode == "manual"
    assert final.manual_power_score == 13.5
    assert final.note == "operator-assigned"


def test_edit_external_clears_manual_power_score_when_strength_not_manual():
    records = [
        _team_record(
            "edit_external",
            "pid-1",
            {
                "state": "external",
                "manual_seed_group": "Premier",
                "strength_mode": "median",
                "manual_power_score": 99.0,
            },
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["pid-1"]
    assert final.strength_mode == "median"
    assert final.manual_power_score is None


def test_edit_external_carries_team_id_master_from_prior():
    """``edit_external`` carries ``team_id_master`` over from the prior
    projection — relevant when an externalized team was previously
    DB-resolved via manual_add."""
    records = [
        _team_record(
            "manual_add",
            "manual_pid-1",
            {"state": "resolved", "team_id_master": "abc", "manual_seed_group": "Premier"},
        ),
        _team_record(
            "edit_external",
            "manual_pid-1",
            {
                "state": "external",
                "manual_seed_group": "Champions",
                "strength_mode": "median",
            },
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["manual_pid-1"]
    assert final.state == "external"
    assert final.team_id_master == "abc"


def test_mark_external_clears_team_id_master():
    records = [
        _team_record(
            "accept_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "abc"},
        ),
        _team_record("mark_external", "pid-1", {"state": "external"}),
    ]
    team_state, _ = project_overrides(records)
    assert team_state["pid-1"].team_id_master is None


def test_unknown_type_is_skipped_with_warning(caplog):
    records = [
        _team_record(
            "accept_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "abc"},
        ),
        {
            "ts": "2026-04-26T13:00:00+00:00",
            "actor": "dallas@example.com",
            "scope": "team",
            "type": "future_v2_action",
            "team_ref": "pid-1",
            "before": {},
            "after": {},
            "reason": "from a v2 ledger",
        },
    ]
    with caplog.at_level(logging.WARNING, logger="src.tournaments.triage"):
        team_state, _ = project_overrides(records)
    # First record still projected; second skipped.
    assert team_state["pid-1"].state == "resolved"
    assert any("future_v2_action" in record.message for record in caplog.records)


def test_fix_match_produces_resolved_state():
    records = [
        _team_record(
            "fix_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "xyz"},
        )
    ]
    team_state, _ = project_overrides(records)
    final = team_state["pid-1"]
    assert final.state == "resolved"
    assert final.team_id_master == "xyz"


def test_manual_add_external_projects_strength_fields():
    records = [
        _team_record(
            "manual_add",
            "manual_abc",
            {
                "state": "external",
                "manual_seed_group": "Premier",
                "strength_mode": "manual",
                "manual_power_score": 14.5,
                "note": "guest team",
                "cohort_age_group": "u14",
                "cohort_gender": "Male",
            },
        )
    ]
    team_state, _ = project_overrides(records)
    final = team_state["manual_abc"]
    assert final.state == "external"
    assert final.manual_seed_group == "Premier"
    assert final.strength_mode == "manual"
    assert final.manual_power_score == 14.5
    assert final.note == "guest team"
    assert final.cohort_age_group == "u14"
    assert final.cohort_gender == "Male"


# -------- assign_division ------------------------------------------------


def test_assign_division_carries_team_id_master_from_prior_resolved():
    """``assign_division`` after ``accept_match`` preserves ``team_id_master``
    AND populates ``assigned_division_name`` — the carry-forward ``replace``
    semantics."""
    records = [
        _team_record(
            "accept_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "abc"},
            ts="2026-04-26T12:00:00+00:00",
        ),
        _team_record(
            "assign_division",
            "pid-1",
            {"assigned_division_name": "BU14 Premier"},
            ts="2026-04-26T13:00:00+00:00",
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["pid-1"]
    assert final.state == "resolved"
    assert final.team_id_master == "abc"
    assert final.assigned_division_name == "BU14 Premier"


def test_assign_division_then_fix_match_preserves_assignment():
    """Order-dependence guard: ``fix_match`` after ``assign_division`` must
    carry the assignment forward so subsequent consumers still route
    correctly."""
    records = [
        _team_record(
            "assign_division",
            "pid-1",
            {"assigned_division_name": "BU14 Champions"},
            ts="2026-04-26T12:00:00+00:00",
        ),
        _team_record(
            "fix_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "xyz"},
            ts="2026-04-26T13:00:00+00:00",
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["pid-1"]
    assert final.state == "resolved"
    assert final.team_id_master == "xyz"
    assert final.assigned_division_name == "BU14 Champions"


def test_fix_match_then_assign_division_preserves_team_id_master():
    """Symmetric order: ``assign_division`` after ``fix_match`` must
    preserve the prior ``team_id_master``."""
    records = [
        _team_record(
            "fix_match",
            "pid-1",
            {"state": "resolved", "team_id_master": "xyz"},
            ts="2026-04-26T12:00:00+00:00",
        ),
        _team_record(
            "assign_division",
            "pid-1",
            {"assigned_division_name": "BU14 Premier"},
            ts="2026-04-26T13:00:00+00:00",
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["pid-1"]
    assert final.state == "resolved"
    assert final.team_id_master == "xyz"
    assert final.assigned_division_name == "BU14 Premier"


def test_assign_division_starting_from_no_prior_creates_unknown_state():
    """``assign_division`` with no prior projection lands as ``state=unknown``
    with the assignment populated — the writer can land an assignment for a
    team that has no other override yet, and the next override fixes the
    state."""
    records = [
        _team_record(
            "assign_division",
            "pid-1",
            {"assigned_division_name": "BU14 Premier"},
        ),
    ]
    team_state, _ = project_overrides(records)
    final = team_state["pid-1"]
    assert final.state == "unknown"
    assert final.assigned_division_name == "BU14 Premier"


# -------- per-type reset regression: external-only fields drop on flip ---


@pytest.mark.parametrize(
    ("target_type", "target_after", "expected_state"),
    [
        ("accept_match", {"state": "resolved", "team_id_master": "abc"}, "resolved"),
        ("fix_match", {"state": "resolved", "team_id_master": "xyz"}, "resolved"),
        ("mark_external", {"state": "external"}, "external"),
        (
            "manual_add",
            {"state": "resolved", "team_id_master": "abc", "manual_seed_group": "Premier"},
            "resolved",
        ),
        (
            "manual_add",
            {
                "state": "external",
                "manual_seed_group": "Champions",
                "strength_mode": "median",
            },
            "external",
        ),
    ],
)
def test_external_only_fields_drop_when_flipping_state(target_type, target_after, expected_state):
    """Pin Step 3's per-branch reset semantics: every existing branch must
    drop external-only fields (``manual_seed_group`` from a prior
    ``edit_external``, ``strength_mode``, ``manual_power_score``, ``note``)
    when projecting a new override that does not itself populate them.
    ``assigned_division_name`` always defaults to ``None`` here because the
    prior had no assignment to carry forward — pins both directions of
    Step 3's carry-forward fix."""
    prior = _apply_team_override(
        "edit_external",
        {
            "state": "external",
            "manual_seed_group": "X",
            "strength_mode": "manual",
            "manual_power_score": 12.5,
            "note": "frozen",
        },
        prior=None,
        ts="2026-04-26T12:00:00+00:00",
    )
    assert prior.manual_seed_group == "X"
    assert prior.strength_mode == "manual"

    result = _apply_team_override(
        target_type,
        target_after,
        prior=prior,
        ts="2026-04-26T13:00:00+00:00",
    )
    assert result.state == expected_state
    if target_type in ("accept_match", "fix_match", "mark_external"):
        # Reset semantics: the target's ``after`` does not include any of
        # the external-only fields, so the projection must be ``None`` for
        # all of them.
        assert result.manual_seed_group is None
        assert result.strength_mode is None
        assert result.manual_power_score is None
        assert result.note is None
    elif target_type == "manual_add" and target_after.get("state") == "resolved":
        # manual_add resolved branch: only ``manual_seed_group`` flows from
        # ``after``; strength fields drop.
        assert result.manual_seed_group == "Premier"
        assert result.strength_mode is None
        assert result.manual_power_score is None
        assert result.note is None
    else:  # manual_add external branch
        # manual_add external rebuilds from scratch — ``manual_seed_group``
        # comes from ``after``, NOT carried from the prior.
        assert result.manual_seed_group == "Champions"
        assert result.strength_mode == "median"
    # In all cases the prior had no assignment, so this defaults to None
    # both before and after the flip — pins "no carry, no erasure".
    assert result.assigned_division_name is None


# -------- resolve_division_assignment ------------------------------------


def test_resolve_division_assignment_no_signal_returns_none_source():
    res = resolve_division_assignment(
        None,
        "Phoenix Rising 2012 Boys",
        division_names=["BU14 Premier", "BU14 Champions"],
    )
    assert res == DivisionResolution(name=None, source="none")


def test_resolve_division_assignment_explicit_wins_over_prefix():
    projected = ProjectedTeamState(state="resolved", assigned_division_name="BU14 Premier")
    res = resolve_division_assignment(
        projected,
        "BU14 Champions Phoenix Rising",
        division_names=["BU14 Premier", "BU14 Champions"],
    )
    assert res == DivisionResolution(name="BU14 Premier", source="explicit")


def test_resolve_division_assignment_stale_falls_through_to_prefix():
    projected = ProjectedTeamState(state="resolved", assigned_division_name="BU14 Renamed")
    res = resolve_division_assignment(
        projected,
        "BU14 Premier Phoenix",
        division_names=["BU14 Premier", "BU14 Champions"],
    )
    assert res == DivisionResolution(name="BU14 Premier", source="stale")


def test_resolve_division_assignment_stale_with_no_prefix_match_returns_no_name():
    projected = ProjectedTeamState(state="resolved", assigned_division_name="BU14 Removed")
    res = resolve_division_assignment(
        projected,
        "Phoenix Rising 2012 Boys",
        division_names=["BU14 Premier"],
    )
    assert res == DivisionResolution(name=None, source="stale")


def test_resolve_division_assignment_longest_prefix_wins():
    res = resolve_division_assignment(
        None,
        "Premier Elite Phoenix",
        division_names=["Premier", "Premier Elite"],
    )
    assert res == DivisionResolution(name="Premier Elite", source="prefix")


def test_resolve_division_assignment_empty_divisions_returns_none():
    res = resolve_division_assignment(None, "Anything", division_names=[])
    assert res == DivisionResolution(name=None, source="none")


def test_resolve_division_assignment_empty_bracket_returns_none():
    res = resolve_division_assignment(None, "", division_names=["BU14 Premier"])
    assert res == DivisionResolution(name=None, source="none")


def test_recompute_medians_latest_wins():
    records = [
        _cohort_record(
            "recompute_medians",
            "u14_Male",
            {"medians_by_division": {"Premier": 10.0}},
            ts="2026-04-26T12:00:00+00:00",
        ),
        _cohort_record(
            "recompute_medians",
            "u14_Male",
            {"medians_by_division": {"Premier": 14.2, "Champions": 12.0}},
            ts="2026-04-26T13:00:00+00:00",
        ),
    ]
    _, cohort_state = project_overrides(records)
    assert cohort_state["u14_Male"].medians_by_division == {
        "Premier": 14.2,
        "Champions": 12.0,
    }
