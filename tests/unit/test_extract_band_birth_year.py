"""A two-year band in a team name is named by its younger year, however it is spelled.

CLAUDE.md's label key: 2013/2014, 2013/14, 13/14, 14/13, 2013-2014 and B13/14 all
name one band.
"""

import time

import pytest

from src.utils import team_utils
from src.utils.team_utils import (
    calculate_age_group_from_band,
    calculate_age_group_from_birth_year,
    extract_band_birth_year,
)


@pytest.fixture(autouse=True)
def _pin_season(monkeypatch):
    """Both functions read CURRENT_YEAR at call time when no season is passed."""
    monkeypatch.setattr(team_utils, "CURRENT_YEAR", 2026)


@pytest.mark.parametrize(
    "name",
    [
        "2013/2014",
        "2013/14",
        "13/14",
        "14/13",
        "2013-2014",
        "2013 - 2014",
        "2013–2014",
        "B13/14",
        "b13/14",
        "13/14B",
        "G2013/14",
        "M13/14",
        "FC Chicago 2013/14 Elite",
        # Ordinary punctuation or a word touching the band does not continue it.
        "FC Academy-2013/2014 Boys",
        "Club 2013/2014-Red",
        "Pink Ninjas -13/14",
        "2013/14B_Black",
        "Eternal 2013/2014Black",
        "Boys (2013/2014)",
        "B2013-2014/U15-16",
        "2013-2014-7 Smith AYDP",
        # "under" inside a word is not the U-age range "Under 14/15".
        "Thunder 2013/2014 Boys",
        # A four-digit year may start right after another number and a separator.
        "EYSC BU11 - 2013/2014 Silverlake",
        "Lenawee Girls U14/15 - 2013/2014",
        "ISC Galaxy 1-2013/2014 Boys",
    ],
)
def test_every_spelling_of_a_band_names_its_younger_year(name):
    assert extract_band_birth_year(name) == 2014


def test_a_gender_letter_on_both_years_is_still_a_band():
    assert extract_band_birth_year("Cape Coral RL B07/B08") == 2008


@pytest.mark.parametrize(
    "name",
    [
        # A run of three or more years names no single band, and a word touching its
        # last year must not cut it back to the first two.
        "CSC 2014 / 2015 / 2016 Boys",
        "CSC 2014 / 2015 / 2016Boys",
        "B2014/B2015/B2016U",  # cut back to two years, "/B2016U" would not refuse it
        "CSC 2014/2015/2016",
        "07/08/09/10",
        # Numbers that are not two consecutive years are not a band.
        "Club 2012/2015 Girls",
        "1570 FC - 1570",
        "10-3 Red",
        # Each edge that would extend a number run, one condition per row.
        "12013/14",  # a digit before
        "13/145",  # a digit after
        "U13/14/15",  # a two-digit restart just after "digit, slash"
        "U13-14-15",  # ...just after "digit, hyphen"
        "U13–14–15",  # ...just after "digit, en dash"
        "U13 / 14 / 15",  # ...and after the separator's spaces
        "'11/12 Red",  # an apostrophe before
        "11/12' Red",  # an apostrophe after
        # Each edge that makes it a U-age range.
        "U13/14",
        "13/14U",
        "U-13/14",
        "Erie FC Under 14/15 Girls",
        "GU18/19",
        "",
    ],
)
def test_not_a_band(name):
    assert extract_band_birth_year(name) is None


def test_a_season_written_into_a_name_is_passed_over_for_a_later_band():
    assert extract_band_birth_year("Club 2025-26 Boys") is None
    assert extract_band_birth_year("Orange County B08 FC 22/23") is None
    assert extract_band_birth_year("Club 2025-26 Boys 2013/14") == 2014


def test_u7_is_the_youngest_pair_read_as_a_band():
    assert extract_band_birth_year("2019/2020") == 2020
    assert extract_band_birth_year("2020/2021") is None


def test_the_season_can_be_passed_in():
    assert extract_band_birth_year("2020/2021", current_year=2027) == 2021


def test_an_aged_out_band_still_reports_its_year():
    # The caller has to know a band was there, or it falls back to a single year
    # from the same name and files 2007 as U19.
    assert extract_band_birth_year("FC 2006/2007") == 2007


def test_a_crafted_long_name_is_not_scanned():
    # Every four-digit restart in this run rescans it to the end: seconds uncapped.
    started = time.perf_counter()
    assert extract_band_birth_year("FC " + "2013/" * 10000 + "2013U") is None
    assert time.perf_counter() - started < 1.0


def test_the_scan_limit_is_above_any_real_name():
    padded = "FC 2013/2014 " + "x" * 180
    assert len(padded) < 200 and extract_band_birth_year(padded) == 2014


@pytest.mark.parametrize(
    "younger_year,expected",
    [
        (2014, "U13"),
        (2016, "U11"),
        (2009, "U19"),  # U18 files into U19
        (2008, "U19"),
        (2007, None),  # the band 2007/06 has aged out
        (2020, "U7"),
        (2021, None),
    ],
)
def test_calculate_age_group_from_band(younger_year, expected):
    assert calculate_age_group_from_band(younger_year) == expected


def test_a_band_does_not_take_the_single_year_fold():
    assert calculate_age_group_from_birth_year(2007, 2026) == "U19"
    assert calculate_age_group_from_band(2007, 2026) is None
