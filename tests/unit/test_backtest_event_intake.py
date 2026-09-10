"""Tests for the Backtest event-intake surface."""

from __future__ import annotations

from src.tournaments.backtest_event_intake import summarize_structure
from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)


def _fixture(kind: str, label: str = "") -> Fixture:
    return Fixture(
        match_number="1", bracket_label=label, kind=kind,
        home_registration_id="1", away_registration_id="2",
        home_score=None, away_score=None, kickoff="", location="",
    )


def _division(**overrides) -> ScrapedDivision:
    base = dict(
        group_id="501350",
        division_label="U13 Boys Red",
        pools=(
            Pool(pool_id="1", label="Bracket A", members=(
                PoolMember(registration_id="1", team_name="One", standings_position=1),
            )),
            Pool(pool_id="2", label="Bracket B", members=(
                PoolMember(registration_id="2", team_name="Two", standings_position=1),
            )),
        ),
        fixtures=(_fixture("pool"), _fixture("cross_pool"), _fixture("bracket", "Final")),
        pools_readable=True,
        fixtures_readable=True,
        warnings=(),
    )
    base.update(overrides)
    return ScrapedDivision(**base)


def test_summarize_counts_pools_and_every_kind_of_game():
    row = summarize_structure([_division()])[0]

    assert row["division"] == "U13 Boys Red"
    assert row["pools"] == "Bracket A (1), Bracket B (1)"
    assert row["pool_games"] == 1
    assert row["cross_pool_games"] == 1
    assert row["knockout_games"] == 1
    assert row["knockout"] == "Final"
    assert row["readable"] is True


def test_summarize_reports_an_unreadable_division_as_unreadable_not_absent():
    row = summarize_structure([_division(pools=(), pools_readable=False)])[0]

    assert row["readable"] is False
    assert row["pools"] == "could not be read"
    assert row["note"] != ""


def test_summarize_never_drops_a_division():
    rows = summarize_structure([_division(), _division(pools_readable=False, pools=())])

    assert len(rows) == 2
