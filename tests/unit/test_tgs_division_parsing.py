"""Division-name parsing for the TGS event scraper.

Regression cover for event 4125, where every flight was skipped because all 16
divisions were labelled 'BU11'/'GU18/19' instead of 'B2015'.

TGS relabelled from birth year to U-age at the 2026-08-01 rollover, so a U-age
label only resolves against the season that wrote it. These tests pass that
season explicitly rather than deriving expectations from the live CURRENT_YEAR,
which would make every assertion move with the clock.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts import scrape_tgs_event as tgs
from scripts.scrape_tgs_event import extract_gender, extract_year, resolve_u_age_season, season_year_of, u_age_of

PINNED_SEASON = 2026

# The 16 division names event 4125 actually returns from the TGS API.
EVENT_4125_DIVISIONS = ["BU11", "BU12", "BU13", "BU14", "BU15", "BU16", "BU17", "BU18/19"]
EVENT_4125_DIVISIONS += [name.replace("B", "G", 1) for name in EVENT_4125_DIVISIONS]


@pytest.fixture(autouse=True)
def pinned_season(monkeypatch):
    """Freeze the season so expectations are absolute, not clock-relative.

    CURRENT_YEAR is imported by value, so the module's own derived constants have
    to be replaced too — patching src.utils.team_utils alone would not reach them.
    """
    monkeypatch.setattr(tgs, "CURRENT_YEAR", PINNED_SEASON)
    monkeypatch.setattr(tgs, "YOUNGEST_TRACKED_BIRTH_YEAR", PINNED_SEASON - 10 + 1)
    monkeypatch.setattr(tgs, "OLDEST_TRACKED_BIRTH_YEAR", PINNED_SEASON - 19 + 1)


@pytest.mark.parametrize("division_name", EVENT_4125_DIVISIONS)
def test_event_4125_divisions_are_no_longer_skipped(division_name):
    assert extract_year(division_name, u_age_season=PINNED_SEASON) is not None


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [
        ("BU11", 2016),
        ("BU12", 2015),
        ("BU13", 2014),
        ("BU14", 2013),
        ("BU15", 2012),
        ("BU16", 2011),
        ("BU17", 2010),
        ("GU11", 2016),
        ("GU13", 2014),
        ("GU16", 2011),
    ],
)
def test_u_age_resolves_to_the_cohort_event_4125_team_names_carry(division_name, expected):
    """Pinned against the birth years found in event 4125's own team names."""
    assert extract_year(division_name, u_age_season=PINNED_SEASON) == expected


def test_u_age_beats_a_season_label_rather_than_being_masked_by_it():
    assert extract_year("2026 U13 Boys", u_age_season=PINNED_SEASON) == 2014
    assert extract_year("BU11 2026-27", u_age_season=PINNED_SEASON) == 2016
    assert extract_year("U12G - 9V9 (AUG 1, 2014 - JULY 31, 2015)", u_age_season=PINNED_SEASON) == 2015


def test_birth_year_labels_still_resolve_when_no_u_age_is_present():
    assert extract_year("B2015", u_age_season=PINNED_SEASON) == 2015
    assert extract_year("G2013", u_age_season=PINNED_SEASON) == 2013


@pytest.mark.parametrize("division_name", ["U18/19", "BU18/19", "GU18/19"])
def test_multi_age_labels_are_kept_when_every_age_is_one_cohort(division_name):
    """18 and 19 both collapse to U19, so the label still names one cohort."""
    assert extract_year(division_name, u_age_season=PINNED_SEASON) == 2008


@pytest.mark.parametrize("division_name", ["U13-U19", "U15 - U18 Boys", "U10-U11 Boys", "GU17/18", "BOYS U11/U12"])
def test_multi_age_labels_spanning_real_cohorts_are_rejected(division_name):
    """Stamping these with the first age filed the whole flight as the youngest."""
    assert extract_year(division_name, u_age_season=PINNED_SEASON) is None


def test_u_age_is_skipped_rather_than_guessed_without_a_season():
    assert extract_year("BU11") is None
    assert extract_year("B2015") == 2015


def test_case_is_normalized_before_matching():
    assert extract_year("bu11", u_age_season=PINNED_SEASON) == extract_year("BU11", u_age_season=PINNED_SEASON) == 2016


def test_window_edges_follow_the_pinned_season():
    assert extract_year("B2017", u_age_season=PINNED_SEASON) == 2017  # U10, wrongly rejected by the old 2007-2016 range
    assert extract_year("B2008", u_age_season=PINNED_SEASON) == 2008  # U19
    assert extract_year("B2018", u_age_season=PINNED_SEASON) is None  # U9, too young
    assert extract_year("B2007", u_age_season=PINNED_SEASON) is None  # aged out


@pytest.mark.parametrize(
    "division_name",
    ["U20", "U6/7 COED", "Boys High School", "Texas Shootout All Teams", "Super Black", ""],
)
def test_out_of_window_and_unlabelled_divisions_are_rejected(division_name):
    assert extract_year(division_name, u_age_season=PINNED_SEASON) is None


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [("BU11", 11), ("GU18/19", 19), ("2026 U13 Boys", 13), ("B2015", None), ("Super Black", None)],
)
def test_u_age_is_identified_independently_of_any_season(division_name, expected):
    assert u_age_of(division_name) == expected


def test_combined_birth_year_labels_survive_an_aged_out_half():
    """B2008/2007 must not be rejected because its older half aged out."""
    assert extract_year("B2008/2007") == 2008
    assert extract_year("B2011/2010") == 2010
    assert extract_year("B2007/2006") is None


@pytest.mark.parametrize(
    ("game_date", "expected"),
    [("2026-07-31", 2025), ("2026-08-01", 2026), ("2026-12-13", 2026), ("2027-03-27", 2026), ("2027-08-01", 2027)],
)
def test_season_year_rolls_on_august_first(game_date, expected):
    assert season_year_of(game_date) == expected


def test_post_cutover_events_read_against_their_own_season_not_the_clock():
    """A fixed historical event must resolve the same cohort on every re-scrape."""
    december_2026 = ["2026-12-13", "2026-12-14"]

    season = resolve_u_age_season(december_2026)

    assert season == 2026
    assert extract_year("BU11", u_age_season=season) == 2016
    # The chain rescans 3400-4600 forever, so this must not drift with CURRENT_YEAR.
    assert resolve_u_age_season(december_2026) == season


def test_pre_cutover_events_are_skipped_unless_an_operator_opts_in(monkeypatch):
    may_2026 = ["2026-05-23", "2026-05-25"]

    assert resolve_u_age_season(may_2026) is None

    monkeypatch.setattr(tgs, "U_FORMAT_BEFORE_CUTOVER", True)
    assert resolve_u_age_season(may_2026) == 2026
    assert extract_year("BU11", u_age_season=resolve_u_age_season(may_2026)) == 2016


def test_opting_in_reads_the_cutover_season_not_whatever_year_it_is_run(monkeypatch):
    """Backfilling event 4125 in a later season must still yield its 2026-27 cohorts."""
    monkeypatch.setattr(tgs, "U_FORMAT_BEFORE_CUTOVER", True)
    monkeypatch.setattr(tgs, "CURRENT_YEAR", 2031)

    assert resolve_u_age_season(["2026-05-23"]) == 2026


def test_undated_flights_never_resolve_a_u_age():
    assert resolve_u_age_season([]) is None


def test_gender_prefers_the_api_division_gender():
    assert extract_gender("U11 Girls", division_gender="f") == "Girls"
    assert extract_gender("Gold U12", division_gender="m") == "Boys"


def test_gender_reads_age_first_labels_that_have_no_prefix():
    """Returning None here lands the team as Male via normalize_gender()."""
    assert extract_gender("U10 GIRLS 7v7") == "Girls"
    assert extract_gender("U15 - U18 Boys") == "Boys"


def test_gender_still_reads_the_u_age_prefix():
    assert extract_gender("BU11") == "Boys"
    assert extract_gender("GU18/19") == "Girls"


def test_u_age_regex_requires_a_token_boundary():
    assert extract_year("SKU12 Super Black", u_age_season=PINNED_SEASON) is None


def test_cutover_date_is_the_documented_relabel_boundary():
    assert tgs.U_FORMAT_CUTOVER_DATE == "2026-08-01"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", tgs.U_FORMAT_CUTOVER_DATE)
