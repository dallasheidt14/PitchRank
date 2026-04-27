"""Unit tests for ``src.tournaments.triage.project_overrides``.

Pins latest-wins semantics, per-type field projections, the cohort-scoped
``recompute_medians`` lane, and forward-compat skip-with-warning behavior
for unrecognized override types.
"""

from __future__ import annotations

import logging

from src.tournaments.triage import (
    ProjectedCohortState,
    ProjectedTeamState,
    project_overrides,
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
