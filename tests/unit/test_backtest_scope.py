from dataclasses import replace

import pytest

from src.tournaments.backtest_scope import (
    backtest_cohort_ages,
    backtest_scope_roster,
    backtest_scope_snapshot,
    is_backtest_cohort,
)
from tests.unit.test_backtest_request import _snapshot


@pytest.mark.parametrize(
    ("cohort", "expected"),
    (
        ("u9", False),
        ("U10", True),
        ("u10/u11", True),
        ("u17/u18", True),
        ("u18", True),
        ("u19", False),
        ("", False),
    ),
)
def test_backtest_age_scope(cohort, expected):
    assert is_backtest_cohort(cohort) is expected


def test_combined_cohort_ages_are_preserved():
    assert backtest_cohort_ages("U17/U18 Boys") == (17, 18)


def test_scope_roster_preserves_capture_while_filtering_working_view():
    snapshot = _snapshot()
    division = snapshot.roster.divisions[0]
    team = snapshot.roster.teams[0]
    u9_division = replace(division, group_id="u9-group", age_group="u9")
    u9_team = replace(team, source_index=99, group_id="u9-group", age_group="u9")
    roster = replace(
        snapshot.roster,
        divisions=(*snapshot.roster.divisions, u9_division),
        teams=(*snapshot.roster.teams, u9_team),
    )

    scoped = backtest_scope_roster(roster)

    assert [division.group_id for division in scoped.divisions] == ["group-1"]
    assert [team.group_id for team in scoped.teams] == ["group-1", "group-1"]
    assert len(roster.divisions) == 2
    assert len(roster.teams) == 3
    assert scoped.is_complete is True


def test_scope_snapshot_filters_matching_outcomes_with_the_working_roster():
    snapshot = _snapshot()
    division = snapshot.roster.divisions[0]
    team = snapshot.roster.teams[0]
    resolved = snapshot.resolved[0]
    u9_division = replace(division, group_id="u9-group", age_group="u9")
    u9_team = replace(team, source_index=99, group_id="u9-group", age_group="u9")
    u9_resolved = replace(resolved, source_index=99)
    snapshot = replace(
        snapshot,
        roster=replace(
            snapshot.roster,
            divisions=(*snapshot.roster.divisions, u9_division),
            teams=(*snapshot.roster.teams, u9_team),
        ),
        resolved=(*snapshot.resolved, u9_resolved),
    )

    scoped = backtest_scope_snapshot(snapshot)

    assert [team.source_index for team in scoped.roster.teams] == [0, 1]
    assert [outcome.source_index for outcome in scoped.resolved] == [0, 1]
    assert len(snapshot.roster.teams) == 3
    assert len(snapshot.resolved) == 3
