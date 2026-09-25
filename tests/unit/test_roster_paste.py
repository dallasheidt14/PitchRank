"""Unit tests for ``src.tournaments.roster_paste``.

Pins the heading-carries-down contract, the ``-c`` / ``*`` marker split,
and the warning path for rows the parser cannot place. Fixtures are taken
verbatim from a real GotSport "Teams Accepted" paste, including the club
string that reads like two clubs and the non-ASCII team name.
"""

from __future__ import annotations

import pytest

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


def test_u18_heading_folds_into_the_u19_board():
    """PitchRank files U18 into U19 and holds zero `u18` teams.

    An unfolded `u18` matches an empty cohort everywhere downstream: the exact
    lookup filters `.eq("age_group", "u18")` and the upstream search sends
    `search[age]=18`, so a whole U18 division resolves against nothing.
    """
    parsed = parse_roster("Male U18\nA Club\tA Team\tTX")

    assert [r.section_age_group for r in parsed.rows] == ["u19"]


def test_u18_and_u19_headings_land_in_one_cohort():
    parsed = parse_roster("Male U18\nA Club\tA Team\tTX\nMale U19\nB Club\tB Team\tTX")

    assert [r.section_age_group for r in parsed.rows] == ["u19", "u19"]


def test_a_cohort_that_is_not_merged_is_left_alone():
    parsed = parse_roster("Male U17\nA Club\tA Team\tTX")

    assert [r.section_age_group for r in parsed.rows] == ["u17"]


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


def test_an_internal_asterisk_is_part_of_the_registered_name_not_a_play_up_marker():
    parsed = parse_roster("Male U13\nA Club\tA*B Academy\tTX")

    row = parsed.rows[0]
    assert row.team_name_stripped == "A*B Academy"
    assert row.registered_name == "A*B Academy"
    assert row.has_star_marker is False


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
    assert parsed.rows[0].requested_flight == ""
    assert parsed.rows[0].listed_division == ""


def test_fourth_column_preserves_the_requested_flight():
    parsed = parse_roster(
        "Male U14\nClub\tTeam\tState\tRequested flight\n"
        "A Club\tA Team\tTX\t Gold "
    )

    assert parsed.rows[0].requested_flight == "Gold"
    assert parsed.rows[0].listed_division == ""


def test_source_index_is_sequential_across_cohorts():
    parsed = parse_roster(
        "Male U14\nA Club\tA Team\tTX\nMale U13\nB Club\tB Team\tTX\nC Club\tC Team\tTX",
    )

    assert [r.source_index for r in parsed.rows] == [0, 1, 2]


# -------- warnings --------------------------------------------------------


def test_row_before_any_heading_is_kept_for_cohort_review():
    parsed = parse_roster("A Club\tA Team\tTX\nMale U14\nB Club\tB Team\tTX")

    assert [r.team_name_raw for r in parsed.rows] == ["A Team", "B Team"]
    assert parsed.rows[0].section_age_group == ""


def test_single_column_line_is_kept_for_input_review():
    parsed = parse_roster("Male U14\nA Club\tA Team\tTX\nstray text with no tabs")

    assert len(parsed.rows) == 2
    assert parsed.rows[1].team_name_raw == "stray text with no tabs"
    assert parsed.rows[1].intake_issue


def test_blank_lines_produce_neither_rows_nor_warnings():
    parsed = parse_roster("Male U14\n\n   \nA Club\tA Team\tTX\n")

    assert len(parsed.rows) == 1
    assert parsed.warnings == ()


# -------- heading forms directors send ------------------------------------


@pytest.fixture
def season_2026(monkeypatch):
    from src.utils import team_utils

    monkeypatch.setattr(team_utils, "_soccer_season_year", lambda now=None: 2026)


@pytest.mark.parametrize(
    ("heading", "cohort"),
    [
        ("Boys 2012", ("u15", "Male")),
        ("Male 2013", ("u14", "Male")),
        ("B2013", ("u14", "Male")),
        ("BU14", ("u14", "Male")),
        ("U14B", ("u14", "Male")),
        ("GU12", ("u12", "Female")),
        ("Under 15 Boys", ("u15", "Male")),
        ("Female U14\t\t", ("u14", "Female")),
        ("Boys 2013/2014", ("u13", "Male")),
        ("U14 Boys Gold Division", ("u14", "Male")),
        ("U12 Girls Flight 1 Bracket 2", ("u12", "Female")),
        ("U14 Boys Gold Flight Division", ("u14", "Male")),
        ("Girls U13 M\u00e9xico", ("u13", "Female")),
    ],
)
def test_a_heading_in_any_form_directors_send_sets_the_cohort(season_2026, heading, cohort):
    parsed = parse_roster(f"{heading}\nA Club\tA Team\tTX")

    assert len(parsed.rows) == 1
    assert (parsed.rows[0].section_age_group, parsed.rows[0].section_gender) == cohort


@pytest.mark.parametrize("heading", ["Boys/Girls U13", "Coed U13", "U13B/G"])
def test_a_heading_naming_both_genders_leaves_gender_for_review(season_2026, heading):
    parsed = parse_roster(f"Male U12\nA Club\tA Team\tTX\n{heading}\nB Club\tB Team\tTX")

    assert (parsed.rows[1].section_age_group, parsed.rows[1].section_gender) == ("u13", "")


@pytest.mark.parametrize(
    "line",
    [
        "Tyler FC Boys U14 Black",
        "Sting 12G Black",
        "FC Dallas 2013B",
        "Solar SC U14",
        "Boys FC",
        "Lady Hawks Girls",
        "U13",
        "Boys",
        "Girls Division",
        "Solar 14G",
        "Liverpool B2014",
        "Arsenal 2013 Girls",
        "Crossfire 2012 Boys",
        "U12G B Black",
        "Barca U13 B",
        "Boys 2013 Spring 2026",
    ],
)
def test_a_line_without_both_an_age_and_a_gender_or_with_club_words_is_a_team(season_2026, line):
    parsed = parse_roster(f"Male U12\nA Club\tA Team\tTX\n{line}\nB Club\tB Team\tTX")

    assert [row.team_name_raw for row in parsed.rows] == ["A Team", line, "B Team"]
    assert parsed.rows[1].intake_issue
    assert (parsed.rows[2].section_age_group, parsed.rows[2].section_gender) == ("u12", "Male")


def test_a_row_with_a_blank_team_cell_keeps_its_columns(season_2026):
    parsed = parse_roster("Male U12\nTyler FC\t")

    assert parsed.rows[0].club_raw == "Tyler FC"
    assert parsed.rows[0].intake_issue == "Team name is missing."


def test_a_mixed_birth_year_heading_keeps_its_label_and_bounds_its_rows(season_2026):
    from src.tournaments.seeding_assessment import could_belong

    row = parse_roster("Boys 2013/2015\nA Club\tA Team\tTX").rows[0]

    assert (row.section_age_group, row.section_gender, row.listed_division) == ("", "Male", "Boys 2013/2015")
    assert could_belong(row, "u14", "Male")
    assert could_belong(row, "u12", "Male")
    assert not could_belong(row, "u17", "Male")


def test_a_heading_naming_a_boarded_and_an_unboarded_year_keeps_its_label(season_2026):
    row = parse_roster("Boys 2013 1995\nA Club\tA Team\tTX").rows[0]

    assert (row.section_age_group, row.section_gender, row.listed_division) == ("", "Male", "Boys 2013 1995")


def test_a_mixed_age_heading_still_bounds_the_ages_its_rows_can_take(season_2026):
    from src.tournaments.seeding_assessment import could_belong

    row = parse_roster("Girls Under 13/14\nA Club\tA Team\tTX").rows[0]

    assert could_belong(row, "u13", "Female")
    assert could_belong(row, "u14", "Female")
    assert not could_belong(row, "u15", "Female")


def test_a_title_line_naming_only_a_season_is_not_a_heading(season_2026):
    parsed = parse_roster("Male U12\n2026 Spring Cup\nA Club\tA Team\tTX")

    assert parsed.rows[0].team_name_raw == "2026 Spring Cup"
    assert (parsed.rows[1].section_age_group, parsed.rows[1].section_gender) == ("u12", "Male")


def test_a_mixed_age_heading_keeps_its_label_for_the_operator(season_2026):
    parsed = parse_roster("Girls U9/U10 Mexico\nA Club\tA Team\tTX")

    assert parsed.rows[0].section_age_group == ""
    assert parsed.rows[0].section_gender == "Female"
    assert parsed.rows[0].listed_division == "Girls U9/U10 Mexico"
