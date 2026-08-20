"""Division-name parsing for the TGS event scraper.

Regression cover for event 4125, where every flight was skipped because all 16
divisions were labelled 'BU11'/'GU18/19' instead of 'B2015'.

Cohorts are age groups. A U-age label already names one and is taken as
written; the only question is whether the label is current, since one written
before the 2026-08-01 relabel belongs to a season that has since moved on.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts import scrape_tgs_event as tgs
from scripts.scrape_tgs_event import extract_age_group, extract_gender, u_age_of, u_label_is_current

# The 16 division names event 4125 actually returns from the TGS API.
EVENT_4125_DIVISIONS = ["BU11", "BU12", "BU13", "BU14", "BU15", "BU16", "BU17", "BU18/19"]
EVENT_4125_DIVISIONS += [name.replace("B", "G", 1) for name in EVENT_4125_DIVISIONS]


@pytest.mark.parametrize("division_name", EVENT_4125_DIVISIONS)
def test_event_4125_divisions_are_no_longer_skipped(division_name):
    assert extract_age_group(division_name) is not None


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [
        ("BU11", "u11"),
        ("BU12", "u12"),
        ("BU13", "u13"),
        ("BU17", "u17"),
        ("GU11", "u11"),
        ("GU16", "u16"),
        ("bu11", "u11"),
        ("2026 U13 Boys", "u13"),
        ("BU11 2026-27", "u11"),
        ("U12G - 9V9 (AUG 1, 2014 - JULY 31, 2015)", "u12"),
    ],
)
def test_a_u_label_names_its_own_cohort(division_name, expected):
    """No season arithmetic: the label is the answer."""
    assert extract_age_group(division_name) == expected


@pytest.mark.parametrize("division_name", ["U18/19", "BU18/19", "GU18/19"])
def test_u18_files_into_u19(division_name):
    """PitchRank runs no U18 board; 18 and 19 are one cohort."""
    assert extract_age_group(division_name) == "u19"


@pytest.mark.parametrize("division_name", ["U13-U19", "U15 - U18 Boys", "U10-U11 Boys", "GU17/18", "BOYS U11/U12"])
def test_labels_spanning_real_cohorts_are_rejected(division_name):
    """Stamping these with the first age filed the whole flight as the youngest."""
    assert extract_age_group(division_name) is None


def test_a_stale_u_label_is_skipped_rather_than_taken_at_face_value():
    """Event 3430 (Apr 2025) files its 2012-born teams as U13; they are u15 now."""
    assert extract_age_group("U13 BOYS 11v11", allow_u_label=False) is None


@pytest.mark.parametrize(
    ("game_dates", "expected"),
    [
        (["2026-12-13"], True),
        (["2026-08-01"], True),
        (["2026-05-23", "2026-05-25"], False),
        (["2025-04-25"], False),
        ([], False),
    ],
)
def test_only_post_relabel_events_keep_their_u_labels(game_dates, expected):
    assert u_label_is_current(game_dates) is expected


def test_an_operator_can_opt_a_pre_relabel_event_in(monkeypatch):
    monkeypatch.setattr(tgs, "U_FORMAT_BEFORE_CUTOVER", True)

    assert u_label_is_current(["2026-05-23"]) is True


def test_legacy_birth_year_labels_still_convert():
    """Older TGS events label by birth year; a birth year is not a cohort."""
    assert extract_age_group("B2015") == "u12"
    assert extract_age_group("G2013") == "u14"


def test_legacy_labels_survive_an_aged_out_half():
    assert extract_age_group("B2008/2007") == "u19"
    assert extract_age_group("B2007/2006") is None


@pytest.mark.parametrize(
    "division_name",
    ["U20", "U6/7 COED", "Boys High School", "Texas Shootout All Teams", "Super Black", "SKU12 Super Black", ""],
)
def test_out_of_range_and_unlabelled_divisions_are_rejected(division_name):
    assert extract_age_group(division_name) is None


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [("BU11", 11), ("GU18/19", 19), ("2026 U13 Boys", 13), ("B2015", None), ("Super Black", None)],
)
def test_u_age_is_identified_for_the_staleness_gate(division_name, expected):
    assert u_age_of(division_name) == expected


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


def test_cutover_date_is_the_documented_relabel_boundary():
    assert tgs.U_FORMAT_CUTOVER_DATE == "2026-08-01"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", tgs.U_FORMAT_CUTOVER_DATE)
