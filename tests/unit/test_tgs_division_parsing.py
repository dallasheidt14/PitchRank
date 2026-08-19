"""Division-name parsing for the TGS event scraper.

Regression cover for event 4125, where every flight was skipped because all 16
divisions were labelled 'BU11'/'GU18/19' instead of 'B2015'.

TGS relabelled from birth year to U-age at the 2026-08-01 rollover, so a U-age
label only resolves against the current season for events on or after it. These
tests pin an absolute season rather than deriving expectations from the live
CURRENT_YEAR, which would make every assertion move with the clock.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts import scrape_tgs_event as tgs
from scripts.scrape_tgs_event import extract_gender, extract_year, is_u_format_label

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
    monkeypatch.setattr(tgs, "NEWEST_PLAUSIBLE_BIRTH_YEAR", PINNED_SEASON - 7)


@pytest.mark.parametrize("division_name", EVENT_4125_DIVISIONS)
def test_event_4125_divisions_are_no_longer_skipped(division_name):
    assert extract_year(division_name) is not None


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
    assert extract_year(division_name) == expected


def test_u_age_beats_a_season_label_rather_than_being_masked_by_it():
    assert extract_year("2026 U13 Boys") == 2014
    assert extract_year("BU11 2026-27") == 2016
    assert extract_year("U12G - 9V9 (AUG 1, 2014 - JULY 31, 2015)") == 2015


def test_birth_year_labels_still_resolve_when_no_u_age_is_present():
    assert extract_year("B2015") == 2015
    assert extract_year("G2013") == 2013


@pytest.mark.parametrize("division_name", ["U18/19", "BU18/19", "GU18/19"])
def test_multi_age_labels_are_kept_when_every_age_is_one_cohort(division_name):
    """18 and 19 both collapse to U19, so the label still names one cohort."""
    assert extract_year(division_name) == 2008


@pytest.mark.parametrize("division_name", ["U13-U19", "U15 - U18 Boys", "U10-U11 Boys", "GU17/18", "BOYS U11/U12"])
def test_multi_age_labels_spanning_real_cohorts_are_rejected(division_name):
    """Stamping these with the first age filed the whole flight as the youngest."""
    assert extract_year(division_name) is None


def test_u_age_is_suppressed_for_events_before_the_relabel_cutover():
    assert extract_year("BU11", allow_u_format=False) is None
    assert extract_year("B2015", allow_u_format=False) == 2015


def test_case_is_normalized_before_matching():
    assert extract_year("bu11") == extract_year("BU11") == 2016


def test_window_edges_follow_the_pinned_season():
    assert extract_year("B2017") == 2017  # U10, wrongly rejected by the old 2007-2016 range
    assert extract_year("B2008") == 2008  # U19
    assert extract_year("B2018") is None  # U9, too young
    assert extract_year("B2007") is None  # aged out


@pytest.mark.parametrize(
    "division_name",
    ["U20", "U6/7 COED", "Boys High School", "Texas Shootout All Teams", "Super Black", ""],
)
def test_out_of_window_and_unlabelled_divisions_are_rejected(division_name):
    assert extract_year(division_name) is None


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [("BU11", True), ("GU18/19", True), ("2026 U13 Boys", True), ("B2015", False), ("Super Black", False)],
)
def test_u_format_labels_are_identified_for_the_cutover_gate(division_name, expected):
    assert is_u_format_label(division_name) is expected


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
    assert extract_year("SKU12 Super Black") is None


def test_cutover_date_is_the_documented_relabel_boundary():
    assert tgs.U_FORMAT_CUTOVER_DATE == "2026-08-01"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", tgs.U_FORMAT_CUTOVER_DATE)
