"""Product scope for completed-tournament MatchBalance Backtests."""

from __future__ import annotations

import re
from dataclasses import replace

from src.tournaments.backtest_intake_state import BacktestSnapshot, effective_roster
from src.tournaments.gotsport_event_roster import EventRoster

BACKTEST_MIN_AGE = 10
BACKTEST_MAX_AGE = 18


def backtest_cohort_ages(age_group: str) -> tuple[int, ...]:
    """Return every explicit U-age in a single or combined cohort label."""

    return tuple(int(value) for value in re.findall(r"u([0-9]{1,2})", str(age_group).casefold()))


def is_backtest_cohort(age_group: str) -> bool:
    """Whether the cohort falls wholly within the supported U10-U18 range."""

    ages = backtest_cohort_ages(age_group)
    return bool(ages) and all(BACKTEST_MIN_AGE <= age <= BACKTEST_MAX_AGE for age in ages)


def backtest_group_ids(roster: EventRoster) -> frozenset[str]:
    return frozenset(
        division.group_id
        for division in roster.divisions
        if is_backtest_cohort(division.age_group)
    )


def backtest_scope_roster(roster: EventRoster) -> EventRoster:
    """Return a U10-U18 working view without changing the immutable capture."""

    group_ids = backtest_group_ids(roster)
    divisions = tuple(division for division in roster.divisions if division.group_id in group_ids)
    excluded_divisions = len(roster.divisions) - len(divisions)
    return replace(
        roster,
        divisions_found=max(len(divisions), roster.divisions_found - excluded_divisions),
        divisions_walked=max(len(divisions), roster.divisions_walked - excluded_divisions),
        divisions_unreadable=sum(
            not (division.pools_readable and division.fixtures_readable)
            for division in divisions
        ),
        divisions=divisions,
        teams=tuple(team for team in roster.teams if team.group_id in group_ids),
    )


def backtest_scope_snapshot(snapshot: BacktestSnapshot) -> BacktestSnapshot:
    """Build a consistent U10-U18 snapshot view for UI-only workflows."""

    roster = backtest_scope_roster(effective_roster(snapshot))
    group_ids = backtest_group_ids(roster)
    source_indexes = {team.source_index for team in roster.teams}
    return replace(
        snapshot,
        roster=roster,
        resolved=tuple(
            outcome for outcome in snapshot.resolved if outcome.source_index in source_indexes
        ),
        reviews=tuple(review for review in snapshot.reviews if review.group_id in group_ids),
        cohort_decisions=tuple(
            decision for decision in snapshot.cohort_decisions if decision.group_id in group_ids
        ),
    )
