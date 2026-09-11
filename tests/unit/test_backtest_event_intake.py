"""Tests for the Backtest event-intake surface."""

from __future__ import annotations

from src.tournaments.backtest_event_intake import (
    _would_replace_a_complete_structure,
    summarize_structure,
)
from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    ScrapedDivision,
)
from src.tournaments.storage.event_key import event_key
from src.tournaments.storage.event_structure import (
    EventStructure,
    event_structure_path,
    read_event_structure,
    write_event_structure,
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


def test_summarize_surfaces_unclassified_games():
    """classify_fixtures marks a game 'unknown' when a side is missing from
    every pool's standings table. A fully readable division can still have
    one, and a count that only ever adds pool + cross_pool + knockout would
    under-report how many games were played without ever saying so."""
    row = summarize_structure([_division(fixtures=(_fixture("pool"), _fixture("unknown")))])[0]

    assert row["unclassified_games"] == 1
    assert row["readable"] is True, "an unclassified game is not the same failure as an unreadable page"


def test_a_partial_save_never_overwrites_a_complete_structure(tmp_path):
    """The guard `_write_event_roster_recovery` already applies to its own
    paid artifact, mirrored here: a probe costing pennies must not silently
    replace a walk that cost dollars."""
    key = event_key("gotsport", "52975", None)
    complete = EventStructure(
        event_id="52975",
        walked_at="2026-01-01T00:00:00+00:00",
        is_complete=True,
        divisions=(_division(),),
    )
    write_event_structure(key, complete, base_dir=tmp_path)
    path = event_structure_path(key, base_dir=tmp_path)

    assert _would_replace_a_complete_structure(path, is_complete=False) is True

    # Exactly what the render function's save button does: skip the write
    # entirely when the guard says refuse, rather than call
    # write_event_structure and hope it declines on its own.
    if not _would_replace_a_complete_structure(path, is_complete=False):
        write_event_structure(
            key,
            EventStructure(
                event_id="52975",
                walked_at="2026-02-02T00:00:00+00:00",
                is_complete=False,
                divisions=(),
            ),
            base_dir=tmp_path,
        )

    survived = read_event_structure(key, base_dir=tmp_path)
    assert survived.is_complete is True
    assert survived.walked_at == "2026-01-01T00:00:00+00:00"
