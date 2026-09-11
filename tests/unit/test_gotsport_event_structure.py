"""Tests for the GotSport division-structure parser."""

from __future__ import annotations

import collections
from dataclasses import replace
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
    summarize_structure_quality,
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
            home_label="Home FC",
            away_label="Away FC",
            result_status="unplayed",
            date_label="Feb 14, 2026",
        ),
    )


def test_parse_fixtures_keeps_a_real_game_with_a_blank_match_number():
    """A blank Match # cell with both team ids present is a real, published
    game -- not table furniture -- and must not be dropped silently."""
    html = """
    <table>
      <tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>
          <th>Away Team</th><th>Location</th></tr>
      <tr><td></td><td>Feb 14, 2026 9:00AM</td>
          <td><a href="/x?team=111">Home FC</a></td><td>2 - 1</td>
          <td><a href="/x?team=222">Away FC</a></td><td>Field 2</td></tr>
    </table>
    """
    fixtures = parse_fixtures(html)

    assert len(fixtures) == 1
    assert fixtures[0].match_number == ""
    assert fixtures[0].bracket_label == ""
    assert fixtures[0].kind == "unknown"
    assert fixtures[0].home_registration_id == "111"
    assert fixtures[0].away_registration_id == "222"


def test_parse_fixtures_keeps_a_labelled_game_with_no_match_number():
    """A Match # cell that reads a label rather than a digit (e.g. a
    knockout round named with no number) is still a labelled bracket game."""
    html = """
    <table>
      <tr><th>Match #</th><th>Home Team</th><th>Results</th><th>Away Team</th></tr>
      <tr><td>Final</td><td><a href="?team=1">A</a></td><td>1 - 0</td>
          <td><a href="?team=2">B</a></td></tr>
    </table>
    """
    fixtures = parse_fixtures(html)

    assert len(fixtures) == 1
    assert fixtures[0].match_number == ""
    assert fixtures[0].bracket_label == "Final"
    assert fixtures[0].kind == "bracket"


def test_parse_fixtures_still_skips_a_furniture_row_with_no_team_ids():
    """A row with neither a numeric match number nor any team id is table
    furniture (a spacer / sub-heading row), not a game, and stays skipped."""
    html = """
    <table>
      <tr><th>Match #</th><th>Home Team</th><th>Results</th><th>Away Team</th></tr>
      <tr><td colspan="4">Group B</td></tr>
    </table>
    """
    fixtures = parse_fixtures(html)

    assert fixtures == ()


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


def test_division_warns_how_many_fixtures_came_through_without_a_match_number():
    html = """
    <table>
      <tr><th>Match #</th><th>Home Team</th><th>Results</th><th>Away Team</th></tr>
      <tr><td></td><td><a href="?team=1">A</a></td><td>1 - 0</td>
          <td><a href="?team=2">B</a></td></tr>
      <tr><td>Final</td><td><a href="?team=1">A</a></td><td>2 - 1</td>
          <td><a href="?team=3">C</a></td></tr>
    </table>
    """
    structure = parse_division_structure(group_id="9", division_label="U13 Boys", html=html)

    assert any("2 fixture" in warning for warning in structure.warnings)


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


def test_a_division_carries_the_cohort_the_walk_resolved_for_it():
    """The walker resolves a cohort per division — it is what lets it skip an
    age nobody ranks — but the structure recorded none, so neither the screen
    nor the saved file could say which age group a division was."""
    division = parse_division_structure(
        group_id="1", division_label="9v9 U12B Gold", html="", age_group="u12", gender="Male"
    )

    assert (division.age_group, division.gender) == ("u12", "Male")


def test_a_division_whose_label_names_no_cohort_carries_none():
    """`Gold` names no board. Empty is the honest answer, and the display says
    so rather than leaving the operator to guess."""
    division = parse_division_structure(group_id="1", division_label="Gold", html="")

    assert (division.age_group, division.gender) == ("", "")


@pytest.mark.parametrize(
    "page,number,raw,regulation,shootout,winner",
    [
        ("event_42433__group_365850.html", "83", "0 - 0 PKS: 9 - 8", (0, 0), (9, 8), "home"),
        ("event_45394__group_469715.html", "120", "3 - 3 PKS: 4 - 3", (3, 3), (4, 3), "home"),
        ("event_46103__group_479440.html", "323", "3 - 3 PKS: 4 - 3", (3, 3), (4, 3), "home"),
        ("event_49407__group_436924.html", "267", "1 - 2 PKS: 1 - 4", (1, 2), (1, 4), "away"),
    ],
)
def test_real_shootout_results_keep_regulation_penalties_and_winner(
    page, number, raw, regulation, shootout, winner
):
    fixture = next(f for f in parse_fixtures(_html(page)) if f.match_number == number)

    assert fixture.result_text == raw
    assert (fixture.home_score, fixture.away_score) == regulation
    assert (fixture.home_shootout_score, fixture.away_shootout_score) == shootout
    assert fixture.result_status == "played"
    assert fixture.winner_side == winner
    assert fixture.winner_registration_id == (
        fixture.home_registration_id if winner == "home" else fixture.away_registration_id
    )


def _fixture_html(result="", *, home='Winner Semi-Final A', away='Winner Semi-Final B'):
    return f"""
    <table><tr><th>Match #</th><th>Time</th><th>Home Team</th><th>Results</th>
        <th>Away Team</th><th>Location</th></tr>
      <tr><td>Final</td><td>9:00 AM MST</td><td>{home}</td><td>{result}</td>
        <td>{away}</td><td>Field 2</td></tr>
    </table>
    """


def test_unlinked_published_slots_are_kept_even_without_a_match_number():
    division = parse_division_structure(
        group_id="9", division_label="U13 Boys Gold", html=_fixture_html()
    )
    assert len(division.fixtures) == 1
    fixture = division.fixtures[0]
    assert fixture.home_registration_id is None
    assert fixture.away_registration_id is None
    assert fixture.home_label == "Winner Semi-Final A"
    assert fixture.away_label == "Winner Semi-Final B"
    assert fixture.bracket_label == "Final"
    assert fixture.result_status == "unplayed"
    assert any("unidentified participant" in warning for warning in division.warnings)


@pytest.mark.parametrize("home,away", [("Team A", ""), ("", "Team B")])
def test_a_fixture_with_only_one_published_participant_still_survives(home, away):
    fixture, = parse_fixtures(_fixture_html(home=home, away=away))
    assert (fixture.home_label, fixture.away_label) == (home, away)


def test_unknown_nonempty_result_is_preserved_and_reported():
    division = parse_division_structure(
        group_id="9", division_label="U13 Boys Gold", html=_fixture_html("Abandoned at 2 - 1")
    )
    fixture, = division.fixtures
    assert fixture.result_text == "Abandoned at 2 - 1"
    assert fixture.result_status == "unrecognized"
    assert (fixture.home_score, fixture.away_score) == (None, None)
    assert fixture.winner_side == ""
    assert fixture.winner_registration_id is None
    assert any("1 fixture result(s) could not be interpreted" in w for w in division.warnings)


@pytest.mark.parametrize(
    "raw,status", [("", "unplayed"), ("-", "unplayed"), ("Cancelled", "cancelled"),
                   ("Postponed", "postponed"), ("Forfeit", "forfeit")],
)
def test_published_fixture_status_does_not_invent_a_score_or_winner(raw, status):
    fixture, = parse_fixtures(_fixture_html(raw))
    assert fixture.result_status == status
    assert fixture.result_text == raw
    assert (fixture.home_score, fixture.away_score) == (None, None)
    assert fixture.winner_side == ""


@pytest.mark.parametrize("raw,winner", [("1 - 0", "home"), ("0 - 1", "away"), ("1 - 1", "")])
def test_winner_side_survives_without_a_registration_link(raw, winner):
    fixture, = parse_fixtures(_fixture_html(raw))
    assert fixture.winner_side == winner
    assert fixture.winner_registration_id is None


def test_fixture_dates_keep_header_changes_without_turning_them_into_games():
    html = _fixture_html().replace(
        '<tr><td>Final', '<tr><td colspan="6">Saturday, February 14, 2026</td></tr><tr><td>Final'
    ).replace(
        '</table>', '<tr><td colspan="6">February 15, 2026</td></tr>'
        '<tr><td>12 Third Place</td><td>10:00 AM MST</td><td>Loser A</td><td>-</td>'
        '<td>Loser B</td><td>Field 3</td></tr></table>'
    )
    fixtures = parse_fixtures(html)
    assert len(fixtures) == 2
    assert [f.date_label for f in fixtures] == ["Saturday, February 14, 2026", "February 15, 2026"]
    assert [f.kickoff for f in fixtures] == ["9:00 AM MST", "10:00 AM MST"]


def test_a_date_heading_is_not_borrowed_from_the_previous_fixture_table():
    html = '<h3>February 14, 2026</h3>' + _fixture_html() + _fixture_html()
    fixtures = parse_fixtures(html)
    assert [f.date_label for f in fixtures] == ["February 14, 2026", ""]


def test_explicit_fixture_date_cell_is_retained():
    html = _fixture_html().replace('<th>Time</th>', '<th>Date</th><th>Time</th>').replace(
        '<td>9:00 AM MST</td>', '<td>2026-02-14</td><td>9:00 AM MST</td>'
    )
    fixture, = parse_fixtures(html)
    assert fixture.date_label == "2026-02-14"


def test_source_and_published_rules_links_survive_without_fetching_them():
    url = "https://system.gotsport.com/org_event/events/45394/schedules?group=469715"
    division = parse_division_structure(
        group_id="469715", division_label="U10 Blue",
        html=_html("event_45394__group_469715.html"), source_url=url,
    )
    fixture = next(f for f in division.fixtures if f.match_number == "120")
    assert division.source_url == url
    assert fixture.source_url == (
        "https://system.gotsport.com/org_event/events/45394/schedules?group=469715&match=23879879"
    )
    assert len(division.rules_links) == 1
    assert division.rules_links[0].label == "View Tiebreaker Information"
    assert "tiebreaker_breakdown?bracket_id=650214&group_id=469715" in division.rules_links[0].url


def test_named_pool_members_without_registration_links_are_not_dropped():
    html = """<table><tr><th>Team</th><th>PTS</th></tr>
        <tr><td>First FC</td><td>9</td></tr>
        <tr><td><a href="?team=2">Second FC</a></td><td>3</td></tr></table>"""
    division = parse_division_structure(group_id="1", division_label="Gold", html=html)
    assert [(m.team_name, m.registration_id, m.standings_position) for m in division.pools[0].members] == [
        ("First FC", "", 1), ("Second FC", "2", 2)
    ]
    assert any("1 pool member(s) had no registration link" in w for w in division.warnings)


def test_standings_table_furniture_is_not_mistaken_for_an_unlinked_team():
    html = """<table><tr><th>Team</th><th>PTS</th></tr>
        <tr><td colspan="2">No teams published yet</td></tr></table>"""
    pool, = parse_pools(html)
    assert pool.members == ()


def test_ambiguous_pool_membership_is_not_classified_by_last_seen_pool():
    pools = (
        Pool("a", "A", (PoolMember("1", "One", 1), PoolMember("2", "Two", 2))),
        Pool("b", "B", (PoolMember("1", "One", 1), PoolMember("3", "Three", 2))),
    )
    fixture = Fixture("1", "", "unknown", "1", "3", 0, 0, "", "")
    assert classify_fixtures((fixture,), pools)[0].kind == "unknown"


def test_quality_distinguishes_readable_tables_from_incomplete_rows_and_legacy_results():
    division = parse_division_structure(
        group_id="1", division_label="Gold", html=_fixture_html("Abandoned")
    )
    quality = summarize_structure_quality((division,))
    assert quality["tables_readable"] is False  # Fixture table read; standings absent.
    assert quality["fixture_count"] == 1
    assert quality["unreadable_pool_divisions"] == 1
    assert quality["unreadable_fixture_divisions"] == 0
    assert quality["missing_participant_ids"] == 1
    assert quality["unrecognized_results"] == 1
    assert quality["unplayed_fixtures"] == 0
    assert quality["uncaptured_results"] == 0
    assert summarize_structure_quality(())["tables_readable"] is False


@pytest.mark.parametrize("home,away", [(None, "2"), ("1", None)])
def test_quality_counts_each_missing_participant_side_independently(home, away):
    fixture = Fixture("1", "", "unknown", home, away, None, None, "", "")
    division = parse_division_structure(group_id="1", division_label="Gold", html="")
    quality = summarize_structure_quality((replace(division, fixtures=(fixture,)),))
    assert quality["missing_participant_ids"] == 1
    assert quality["uncaptured_results"] == 1
    assert quality["unplayed_fixtures"] == 0


def test_quality_flags_a_tied_knockout_without_inventing_who_advanced():
    division = parse_division_structure(group_id="1", division_label="Gold", html=_fixture_html("1 - 1"))
    assert summarize_structure_quality((division,))["unresolved_bracket_results"] == 1


def test_parser_preserves_supplied_event_cohort_and_published_label_without_derivation():
    division = parse_division_structure(
        group_id="1", division_label="Gold", html="", age_group="u13", gender="Female",
        published_age_group="u13", published_cohort_label="Female U13 - Gold",
    )
    assert (division.age_group, division.gender) == ("u13", "Female")
    assert division.published_age_group == "u13"
    assert division.published_cohort_label == "Female U13 - Gold"
