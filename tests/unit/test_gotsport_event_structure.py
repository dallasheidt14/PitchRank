"""Tests for the GotSport division-structure parser."""

from __future__ import annotations

from pathlib import Path

from src.tournaments.gotsport_event_structure import (
    Fixture,
    fixture_table_found,
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


def test_standings_table_found_separates_an_empty_pool_from_unreadable_markup():
    assert standings_table_found(_html("event_42433__group_365847.html")) is True
    assert standings_table_found("<html><body><table></table></body></html>") is False


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
