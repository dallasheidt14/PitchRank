"""Tests for the GotSport division-structure parser."""

from __future__ import annotations

import collections
from pathlib import Path

import pytest

from src.tournaments.gotsport_event_structure import (
    Fixture,
    Pool,
    PoolMember,
    classify_fixtures,
    fixture_table_found,
    parse_division_structure,
    parse_fixtures,
    parse_pools,
    standings_table_found,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gotsport"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="replace")


def test_parse_pools_reads_two_labelled_brackets():
    pools = parse_pools(_html("event_42433__group_365847.html"))

    assert [pool.label for pool in pools] == ["Bracket A", "Bracket B"]
    assert [pool.pool_id for pool in pools] == ["501350", "501351"]
    assert [len(pool.members) for pool in pools] == [4, 4]


def test_parse_pools_numbers_members_from_one_in_table_order():
    pools = parse_pools(_html("event_42433__group_365847.html"))

    positions = [member.standings_position for member in pools[0].members]
    assert positions == [1, 2, 3, 4]
    assert pools[0].members[0].team_name == "Rush Soccer Global 2013B Rush Select Blue"
    assert pools[0].members[0].registration_id.isdigit()


def test_parse_pools_keeps_a_label_that_is_not_a_bracket_letter():
    pools = parse_pools(_html("event_49371__group_485301.html"))

    assert [pool.label for pool in pools] == ["U-12 GOLD"]


def test_parse_pools_returns_nothing_when_there_is_no_standings_table():
    assert parse_pools("<html><body><p>no tables here</p></body></html>") == ()


def test_parse_pools_finds_a_heading_row_a_title_row_pushed_down():
    """``standings_table_found`` scans every row, so reading only ``rows[0]``
    here would report ``pools_readable=True`` with no pools — "publishes no
    pools yet" said confidently about pools that were actually lost."""
    html = """
    <table>
      <tr><td colspan="3">Bracket A Standings</td></tr>
      <tr><th>Team</th><th>PTS</th></tr>
      <tr><td><a href="/x?team=111">Home FC</a></td><td>9</td></tr>
      <tr><td><a href="/x?team=222">Away FC</a></td><td>6</td></tr>
    </table>
    """
    pools = parse_pools(html)

    assert standings_table_found(html) is True
    assert len(pools) == 1
    assert [member.registration_id for member in pools[0].members] == ["111", "222"]
    assert [member.standings_position for member in pools[0].members] == [1, 2]


def test_standings_table_found_separates_an_empty_pool_from_unreadable_markup():
    assert standings_table_found(_html("event_42433__group_365847.html")) is True
    assert standings_table_found("<html><body><table></table></body></html>") is False


def test_a_team_heading_alone_is_not_enough_to_read_a_table_as_standings():
    """``Team`` without ``PTS`` is some other kind of table (a roster, a coach
    list) — not a standings table. Requiring both is what keeps a table like
    that from being misread as an empty pool."""
    html = """
    <table>
      <tr><th>Team</th><th>Coach</th></tr>
      <tr><td>Team A</td><td>Coach A</td></tr>
    </table>
    """
    assert parse_pools(html) == ()
    assert standings_table_found(html) is False


def test_parse_fixtures_reads_every_row_on_the_page():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))

    assert len(fixtures) == 16


def test_parse_fixtures_labels_the_knockout_games_verbatim():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))

    labelled = [f.bracket_label for f in fixtures if f.bracket_label]
    assert sorted(labelled) == ["Consolation A", "Consolation B", "Final", "Third Place"]
    assert all(f.kind == "bracket" for f in fixtures if f.bracket_label)


def test_parse_fixtures_leaves_a_pool_game_unlabelled_and_unclassified():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))

    plain = [f for f in fixtures if not f.bracket_label]
    assert len(plain) == 12
    assert all(f.kind == "unknown" for f in plain)
    assert all(f.match_number.isdigit() for f in plain)


def test_parse_fixtures_reads_both_team_ids_and_the_score():
    fixtures = parse_fixtures(_html("event_42433__group_365847.html"))
    final = next(f for f in fixtures if f.bracket_label == "Final")

    assert final.home_registration_id is not None
    assert final.away_registration_id is not None
    assert final.home_score == 3
    assert final.away_score == 4
    assert final.location != ""


def test_parse_fixtures_returns_no_score_when_none_was_published():
    html = """
    <table>
      <tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>
          <th>Away Team</th><th>Location</th></tr>
      <tr><td>7</td><td>Feb 14, 2026 9:00AM</td>
          <td><a href="/x?team=111">Home FC</a></td><td></td>
          <td><a href="/x?team=222">Away FC</a></td><td>Field 2</td></tr>
    </table>
    """
    fixtures = parse_fixtures(html)

    assert fixtures == (
        Fixture(
            match_number="7",
            bracket_label="",
            kind="unknown",
            home_registration_id="111",
            away_registration_id="222",
            home_score=None,
            away_score=None,
            kickoff="Feb 14, 2026 9:00AM",
            location="Field 2",
        ),
    )


def test_fixture_table_found_separates_no_fixtures_from_unreadable_markup():
    assert fixture_table_found(_html("event_42433__group_365847.html")) is True
    assert fixture_table_found("<html><body><table></table></body></html>") is False


REAL_PAGES = sorted(
    path
    for path in FIXTURES.glob("event_*__group_*.html")
    if "synthetic" not in path.name
)


def _structure(name: str):
    return parse_division_structure(
        group_id=name.split("__group_")[1].removesuffix(".html"),
        division_label="Test Division",
        html=_html(name),
    )


def _kinds(structure) -> dict[str, int]:
    return collections.Counter(fixture.kind for fixture in structure.fixtures)


def test_every_real_page_yields_readable_pools_and_fixtures():
    assert len(REAL_PAGES) == 39
    for path in REAL_PAGES:
        structure = _structure(path.name)
        assert structure.pools_readable, path.name
        assert structure.fixtures_readable, path.name
        assert structure.pools, path.name
        # Without this, a regression in the fixture row loop yields zero
        # fixtures on all 39 pages and both golden tests stay green —
        # `_kinds()["unknown"] == 0` is true of an empty tuple.
        assert structure.fixtures, path.name


def test_no_real_page_leaves_a_fixture_unclassified():
    for path in REAL_PAGES:
        structure = _structure(path.name)
        assert _kinds(structure)["unknown"] == 0, path.name


def test_two_pools_of_four_with_a_full_knockout():
    structure = _structure("event_42433__group_365847.html")

    assert [len(pool.members) for pool in structure.pools] == [4, 4]
    assert _kinds(structure) == {"pool": 12, "bracket": 4}
    assert sorted(f.bracket_label for f in structure.fixtures if f.bracket_label) == [
        "Consolation A",
        "Consolation B",
        "Final",
        "Third Place",
    ]


def test_two_pools_that_only_ever_played_each_other():
    """Nine games, none inside a pool. Game-count inference calls this pool play."""
    structure = _structure("event_49371__group_485425.html")

    assert [len(pool.members) for pool in structure.pools] == [3, 3]
    assert _kinds(structure) == {"cross_pool": 9, "bracket": 1}


def test_a_pool_of_six_that_played_nine_games_not_fifteen():
    structure = _structure("event_44692__group_391315.html")

    assert [len(pool.members) for pool in structure.pools] == [6]
    assert _kinds(structure) == {"pool": 9, "bracket": 1}


def test_a_pool_of_four_with_no_knockout_at_all():
    structure = _structure("event_49371__group_485294.html")

    assert [len(pool.members) for pool in structure.pools] == [4]
    assert _kinds(structure) == {"pool": 6}


def test_pools_are_never_reconstructed_when_the_standings_table_is_unreadable():
    html = """
    <table>
      <tr><th>Match #</th><th>Home Team</th><th>Results</th><th>Away Team</th></tr>
      <tr><td>1</td><td><a href="?team=1">A</a></td><td>1 - 0</td>
          <td><a href="?team=2">B</a></td></tr>
    </table>
    """
    structure = parse_division_structure(group_id="9", division_label="U13 Boys", html=html)

    assert structure.pools == ()
    assert structure.pools_readable is False
    assert structure.fixtures_readable is True
    assert structure.fixtures[0].kind == "unknown"
    assert any("pools could not be read" in warning for warning in structure.warnings)


@pytest.mark.parametrize(
    "home,away,expected",
    [("1", "2", "pool"), ("1", "3", "cross_pool"), ("1", "99", "unknown"), (None, "2", "unknown")],
)
def test_classify_fixtures_is_pure_lookup(home, away, expected):
    pools = (
        Pool(pool_id="a", label="Bracket A", members=(
            PoolMember(registration_id="1", team_name="One", standings_position=1),
            PoolMember(registration_id="2", team_name="Two", standings_position=2),
        )),
        Pool(pool_id="b", label="Bracket B", members=(
            PoolMember(registration_id="3", team_name="Three", standings_position=1),
        )),
    )
    fixture = Fixture(
        match_number="1", bracket_label="", kind="unknown",
        home_registration_id=home, away_registration_id=away,
        home_score=None, away_score=None, kickoff="", location="",
    )

    assert classify_fixtures((fixture,), pools)[0].kind == expected


def test_classify_fixtures_never_reclassifies_a_labelled_knockout_game():
    pools = (
        Pool(pool_id="a", label="Bracket A", members=(
            PoolMember(registration_id="1", team_name="One", standings_position=1),
            PoolMember(registration_id="2", team_name="Two", standings_position=2),
        )),
    )
    fixture = Fixture(
        match_number="9", bracket_label="Final", kind="bracket",
        home_registration_id="1", away_registration_id="2",
        home_score=None, away_score=None, kickoff="", location="",
    )

    assert classify_fixtures((fixture,), pools)[0].kind == "bracket"
