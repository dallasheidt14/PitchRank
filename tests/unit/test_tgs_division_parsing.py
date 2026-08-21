"""Division-name parsing for the TGS event scraper.

Regression cover for event 4125, where every flight was skipped because all 16
divisions were labelled 'BU11'/'GU18/19' instead of 'B2015'.

Cohorts are age groups. A U-age label names one as of the season that wrote it,
and that cohort ages a group every Aug 1 while the label stays fixed, so the
label is advanced by the seasons elapsed. Labels from before the 2026-08-01
relabel belong to a season we cannot pin, so they are skipped.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from scripts import scrape_tgs_event as tgs
from scripts.scrape_tgs_event import extract_age_group, extract_gender, u_age_of, u_label_season

# The 16 division names event 4125 actually returns from the TGS API.
EVENT_4125_DIVISIONS = ["BU11", "BU12", "BU13", "BU14", "BU15", "BU16", "BU17", "BU18/19"]
EVENT_4125_DIVISIONS += [name.replace("B", "G", 1) for name in EVENT_4125_DIVISIONS]

CURRENT_SEASON = 2026


@pytest.fixture(autouse=True)
def pinned_season(monkeypatch):
    """Hold the season still.

    extract_age_group answers relative to CURRENT_YEAR, so without this every
    expectation below would shift on Aug 1 and the file would start failing on
    correct code.
    """
    monkeypatch.setattr(tgs, "CURRENT_YEAR", CURRENT_SEASON)


@pytest.mark.parametrize("division_name", EVENT_4125_DIVISIONS)
def test_event_4125_divisions_are_no_longer_skipped(division_name):
    assert extract_age_group(division_name, label_season=CURRENT_SEASON) is not None


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
    """Read in the season that wrote it, the label is the cohort as written."""
    assert extract_age_group(division_name, label_season=CURRENT_SEASON) == expected


@pytest.mark.parametrize("division_name", ["U18/19", "BU18/19", "GU18/19"])
def test_u18_files_into_u19(division_name):
    """PitchRank runs no U18 board; 18 and 19 are one cohort."""
    assert extract_age_group(division_name, label_season=CURRENT_SEASON) == "u19"


@pytest.mark.parametrize("division_name", ["U13-U19", "U15 - U18 Boys", "U10-U11 Boys", "GU17/18", "BOYS U11/U12"])
def test_labels_spanning_real_cohorts_are_rejected(division_name):
    """Stamping these with the first age filed the whole flight as the youngest."""
    assert extract_age_group(division_name, label_season=CURRENT_SEASON) is None


def test_a_stale_u_label_is_skipped_rather_than_taken_at_face_value():
    """Event 3430 (Apr 2025) files its 2012-born teams as U13; they are u15 now."""
    assert extract_age_group("U13 BOYS 11v11", label_season=None) is None


def test_a_u_label_ages_one_cohort_every_rollover(monkeypatch):
    """The chain rescans a fixed id range forever, so a fixed label must not.

    Left as written, a Sept 2026 BU11 event still reads u11 in 2027-28 while its
    teams have moved to u12, and the stored alias is rejected on age mismatch.
    """
    labelled_2026 = u_label_season(["2026-09-15"])

    monkeypatch.setattr(tgs, "CURRENT_YEAR", 2026)
    assert extract_age_group("BU11", label_season=labelled_2026) == "u11"

    monkeypatch.setattr(tgs, "CURRENT_YEAR", 2027)
    assert extract_age_group("BU11", label_season=labelled_2026) == "u12"

    monkeypatch.setattr(tgs, "CURRENT_YEAR", 2029)
    assert extract_age_group("BU11", label_season=labelled_2026) == "u14"


@pytest.mark.parametrize(
    ("game_dates", "expected"),
    [
        (["2026-12-13"], 2026),
        (["2026-08-01"], 2026),
        (["2027-03-27"], 2026),
        (["2027-09-02"], 2027),
        (["2026-05-23", "2026-05-25"], None),
        (["2025-04-25"], None),
        ([], None),
    ],
)
def test_the_label_season_comes_from_the_event_dates(game_dates, expected):
    assert u_label_season(game_dates) == expected


def test_an_operator_opting_in_gets_the_cutover_season_not_the_run_year(monkeypatch):
    monkeypatch.setattr(tgs, "U_FORMAT_BEFORE_CUTOVER", True)
    monkeypatch.setattr(tgs, "CURRENT_YEAR", 2031)

    assert u_label_season(["2026-05-23"]) == 2026


def test_legacy_birth_year_labels_still_convert():
    """Older TGS events label by birth year; a birth year is not a cohort."""
    assert extract_age_group("B2015") == "u12"
    assert extract_age_group("G2013") == "u14"


def test_a_season_stamp_is_not_a_birth_year():
    """TGS appends the season to a division name, and it is not a cohort.

    The single-year branch counts every four-digit number in the string, so the
    2026 in "B2015 (2026-27)" made a one-cohort label look like two and the
    flight was rejected before it was ever fetched. The band branch was never
    affected: it reads an adjacent pair.
    """
    assert extract_age_group("B2015 (2026-27)") == "u12"
    assert extract_age_group("B2015 (2026-2027)") == "u12"
    assert extract_age_group("2015 Boys (2026-27)") == "u12"
    assert extract_age_group("B2016/2015 (2026-27)") == "u11"


def test_two_real_cohorts_in_one_label_are_still_rejected():
    """The season strip must not turn a genuinely ambiguous label into a guess."""
    assert extract_age_group("B2016/2014") is None
    assert extract_age_group("2015 2013") is None


def test_legacy_labels_survive_an_aged_out_half():
    assert extract_age_group("B2008/2007") == "u19"
    assert extract_age_group("B2007/2006") is None


def test_a_dual_year_label_is_one_band_not_two_cohorts():
    """Pins WHY the band is read from its younger year.

    The season runs Aug 1 - Jul 31, so a band straddles Jan 1 and gets written
    from either end. "B2008/2007" and "B2007/2006" are adjacent bands, not
    overlapping sets of birth years: the first is U19 (2008/07), the second is
    the band above it and has aged out.

    Deriving each year independently and keeping the oldest COHORT gets the
    second wrong, because a bare 2007 maps into U19 -- U19 *is* 2008/07 -- while
    the 2007/06 band does not. The pair below is the one place the older year
    happens to identify the band too, because 2007 folds back into U19; that
    coincidence is why this passed for the wrong reason while 2007 was
    unmappable, and why the U12 case at the bottom is the one that actually
    pins the rule.

    Season-dependent: the expected values are for 2026-27 and want re-pinning at
    the next rollover, at which point they fail loudly rather than drift.
    """
    assert extract_age_group("B2008/2007") == extract_age_group("B2008")
    assert extract_age_group("B2007") == "u19", "a bare 2007 is U19; only the BAND 2007/06 is aged out"
    assert extract_age_group("B2007/2006") is None
    # And the same shape lower down the range, where nothing is near aging out.
    # U12 is 2015/14, so the band reads from 2015 -- its YOUNGER year.
    assert extract_age_group("B2015/2014") == "u12"
    assert extract_age_group("B2014") == "u13"


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


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [
        # U9 is outside the tracked U10-U19 range and is dropped, not mislabelled.
        # The previous code read the older year and filed it as u10.
        ("B2018/2017", None),
        ("B2017/2016", "u10"),
        ("B2016/2015", "u11"),
        ("B2015/2014", "u12"),
        ("B2014/2013", "u13"),
        ("B2013/2012", "u14"),
        ("B2012/2011", "u15"),
        ("B2011/2010", "u16"),
        ("B2010/2009", "u17"),
        # The published band is U18, but _tracked_age_group folds 18 into 19 and
        # NO team is stored as u18, so ingestion must meet storage where it is.
        ("B2009/2008", "u19"),
        ("B2008/2007", "u19"),
    ],
)
def test_every_band_matches_the_published_table(division_name, expected):
    """The full 2026-27 band table, so an off-by-one cannot hide behind one case.

    Every band satisfies U_N = {SEASON+1-N, SEASON-N}, so N is SEASON+1 minus the
    YOUNGER year. An earlier version read the OLDER year and was wrong on 10 of
    these 11 rows -- and shipped, because the single case it was tested against
    ("B2008/2007") is correct under either rule by coincidence: 2007 falls out of
    range and folds back to U19.
    """
    assert extract_age_group(division_name) == expected


def test_the_aged_out_band_is_not_folded_back():
    """A lone 2007 is U19; the BAND 2007/06 is the group above and has aged out.

    calculate_age_group_from_birth_year folds age 20 to 19 so a bare 2007 lands in
    U19, which is right -- U19 (2008/07) is the only band containing 2007. That
    fold must not reach the band path, or an aged-out band files as U19.
    """
    assert extract_age_group("B2007") == "u19"
    assert extract_age_group("B2007/2006") is None
    assert extract_age_group("B2006/2005") is None


@pytest.mark.parametrize(
    ("division_name", "expected"),
    [
        # A season suffix must not join the band -- taking every four-digit number
        # in the label derived from 2026 here and rejected a valid U11 flight.
        ("B2016/2015 (2026-27)", "u11"),
        ("2026-27 B2016/2015", "u11"),
        # Non-consecutive years are not a band at all.
        ("B2016/2014", None),
        ("B2016/2012", None),
        # Single years still route through the bare-year path, fold included.
        ("B2015", "u12"),
        ("B2007", "u19"),
        ("B2006", None),
    ],
)
def test_only_an_adjacent_consecutive_pair_is_a_band(division_name, expected):
    """A band is two ADJACENT consecutive years, not every year in the string."""
    assert extract_age_group(division_name) == expected


def test_no_division_ever_yields_an_untracked_cohort():
    """Nothing may emit a label the teams table does not use.

    _tracked_age_group folds 18 to 19 and rejects anything outside U10-U19, and
    the database holds zero rows at u18 or u9. A band that derives U18 must come
    back as u19 or ingestion files teams under a cohort nothing can match.
    """
    tracked = {f"u{n}" for n in range(10, 20)} - {"u18"}
    for first in range(2004, 2021):
        got = extract_age_group(f"B{first}/{first - 1}")
        assert got is None or got in tracked, f"B{first}/{first - 1} produced {got!r}"
