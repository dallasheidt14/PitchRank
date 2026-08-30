"""The one age-group normalizer the unknown-opponent chain shares.

Four stages derive a cohort and then compare their answers, so a divergence here
reads as a mismatch and rejects a correct link. The value also reaches a
`teams.age_group` write and a PostgREST `.or_()` filter, so the shape guard is a
trust boundary, not a formatting nicety.
"""

import pytest

from config.settings import AGE_GROUPS
from src.utils.age_group import normalize_age_group

BOARDED = ("u10", "u11", "u12", "u13", "u14", "u15", "u16", "u17", "u19")


def test_boarded_set_matches_the_canonical_keyset():
    """If AGE_GROUPS gains or loses a cohort, this file's fixtures go stale."""
    assert set(AGE_GROUPS) == set(BOARDED)


@pytest.mark.parametrize("value", BOARDED)
def test_boarded_cohorts_pass_through(value):
    assert normalize_age_group(value) == value


@pytest.mark.parametrize("value", ["u18", "U18", "18", 18, "u20", "U20", "20", 20])
def test_both_boundary_ages_fold_into_u19(value):
    """team_utils folds age 18 and age 20 into U19, and GotSport labels that
    cohort U18 or U20 far more often than U19."""
    assert normalize_age_group(value) == "u19"


@pytest.mark.parametrize(
    "value,expected",
    [("u8", "u8"), ("U8", "u8"), ("u9", "u9"), ("8", "u8"), (9, "u9"), ("u21", "u21"), ("u3", "u3")],
)
def test_cohorts_off_the_boards_are_recorded_not_discarded(value, expected):
    """Discarding them sends the caller back to the opponent's cohort, which is
    the bug this chain exists to close. GotSport reports real U8 and U9 teams."""
    assert normalize_age_group(value) == expected


@pytest.mark.parametrize("value,expected", [("14", "u14"), (14, "u14"), (" u14 ", "u14"), ("U14", "u14")])
def test_provider_spellings_reach_the_stored_form(value, expected):
    assert normalize_age_group(value) == expected


@pytest.mark.parametrize("value", [None, "", "   ", "abc", "Open", "u99x", "U-14", "u", "uu12"])
def test_labels_that_name_no_cohort_fail_closed(value):
    assert normalize_age_group(value) is None


@pytest.mark.parametrize("value", ["U٣٢", "u１２", "u²", "u۱۴"])
def test_non_ascii_digits_are_refused(value):
    """str.isdigit() is Unicode-aware, so a bare shape check would store these."""
    assert normalize_age_group(value) is None


@pytest.mark.parametrize("value", ["u" + "1" * 5000, "u007", "u1000000", "u123"])
def test_out_of_range_widths_are_refused(value):
    """The value is written to teams.age_group; an unbounded label lands verbatim."""
    assert normalize_age_group(value) is None


@pytest.mark.parametrize(
    "value",
    ["u12,age_group.eq.u13", "u12)", "u12*", "u12\x00", "u12 or 1=1"],
)
def test_filter_metacharacters_are_refused(value):
    """The result is interpolated into a PostgREST .or_() filter."""
    assert normalize_age_group(value) is None
