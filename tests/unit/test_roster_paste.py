"""Unit tests for ``src.tournaments.roster_paste``.

Pins the heading-carries-down contract, the ``-c`` / ``*`` marker split,
and the warning path for rows the parser cannot place. Fixtures are taken
verbatim from a real GotSport "Teams Accepted" paste, including the club
string that reads like two clubs and the non-ASCII team name.
"""

from __future__ import annotations

from src.tournaments.roster_paste import parse_roster

# -------- heading handling ------------------------------------------------


def test_heading_sets_cohort_for_following_rows():
    parsed = parse_roster("Male U14\nClub\tTeam\tState\nBarcelona Soccer Club\tBarcelona SC 13B Aztecas\tTX")

    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row.section_age_group == "u14"
    assert row.section_gender == "Male"


def test_second_heading_switches_cohort():
    parsed = parse_roster(
        "Male U14\nA Club\tA Team\tTX\nMale U13\nB Club\tB Team\tTX",
    )

    assert [r.section_age_group for r in parsed.rows] == ["u14", "u13"]


def test_female_heading_normalizes_to_canonical_gender():
    parsed = parse_roster("Female U12\nA Club\tA Team\tTX")

    assert parsed.rows[0].section_gender == "Female"


def test_counter_line_and_column_header_are_not_rows():
    parsed = parse_roster(
        "Teams Accepted (16 of 331)\nMale U14\nClub\tTeam\tState\nA Club\tA Team\tTX",
    )

    assert len(parsed.rows) == 1
    assert parsed.rows[0].team_name_raw == "A Team"


# -------- markers ---------------------------------------------------------


def test_trailing_c_marker_is_stripped_and_flagged():
    parsed = parse_roster("Male U14\nVictoria Youth Soccer Organization\tFire 13B-c\tTX")

    row = parsed.rows[0]
    assert row.team_name_raw == "Fire 13B-c"
    assert row.team_name_stripped == "Fire 13B"
    assert row.has_c_marker is True
    assert row.has_star_marker is False


def test_star_marker_is_stripped_and_flagged():
    parsed = parse_roster("Male U13\nTyler FC\tTyler FC 15B*\tTX")

    row = parsed.rows[0]
    assert row.team_name_stripped == "Tyler FC 15B"
    assert row.has_star_marker is True
    assert row.has_c_marker is False


def test_both_markers_are_stripped():
    parsed = parse_roster("Male U13\nDallas Texans\tDallas Texans Pre ECNL B2014/15 Mitchell*-c\tTX")

    row = parsed.rows[0]
    assert row.team_name_stripped == "Dallas Texans Pre ECNL B2014/15 Mitchell"
    assert row.has_star_marker is True
    assert row.has_c_marker is True


def test_interior_hyphen_c_is_not_treated_as_a_marker():
    parsed = parse_roster("Male U13\nSoccer Evolution RGV\tRGV Rush Blue 2014c\tTX")

    row = parsed.rows[0]
    assert row.team_name_stripped == "RGV Rush Blue 2014c"
    assert row.has_c_marker is False


# -------- row shape -------------------------------------------------------


def test_club_string_containing_two_club_names_stays_one_field():
    parsed = parse_roster(
        "Male U14\nMortega Soccer Club Laredo Youth Soccer Academy\tRayados Pflugerville 12/13 STXCL WC\tTX",
    )

    assert parsed.rows[0].club_raw == "Mortega Soccer Club Laredo Youth Soccer Academy"


def test_non_ascii_team_name_is_preserved():
    parsed = parse_roster("Male U12\nFenomenos FC\tFenómenos 2015\tTX")

    assert parsed.rows[0].team_name_raw == "Fenómenos 2015"


def test_state_column_is_optional():
    parsed = parse_roster("Male U14\nA Club\tA Team")

    assert parsed.rows[0].state == ""


def test_source_index_is_sequential_across_cohorts():
    parsed = parse_roster(
        "Male U14\nA Club\tA Team\tTX\nMale U13\nB Club\tB Team\tTX\nC Club\tC Team\tTX",
    )

    assert [r.source_index for r in parsed.rows] == [0, 1, 2]


# -------- warnings --------------------------------------------------------


def test_row_before_any_heading_is_warned_not_parsed():
    parsed = parse_roster("A Club\tA Team\tTX\nMale U14\nB Club\tB Team\tTX")

    assert [r.team_name_raw for r in parsed.rows] == ["B Team"]
    assert any("heading" in w for w in parsed.warnings)


def test_single_column_line_is_warned_not_parsed():
    parsed = parse_roster("Male U14\nA Club\tA Team\tTX\nstray text with no tabs")

    assert len(parsed.rows) == 1
    assert any("stray text" in w for w in parsed.warnings)


def test_blank_lines_produce_neither_rows_nor_warnings():
    parsed = parse_roster("Male U14\n\n   \nA Club\tA Team\tTX\n")

    assert len(parsed.rows) == 1
    assert parsed.warnings == ()
