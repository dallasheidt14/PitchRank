"""A birth year separates cohorts; an age label does not.

U19 holds 2008 and 2009 at once, so no age-token comparison at any strictness
separates "G09" from "2008". Every fuzzy team matcher in this repo scores names
by similarity and compares colors, directions, programs, squad numbers and coach
names -- none of them compared birth year, which is why "Stateline SC-2011G
Bears" was linked to "Stateline SC-2013G Bears" at 0.957.

This pins the two things that make the guard safe to run unattended:

  1. The extractor's semantics, notation by notation. It reads the RAW name --
     normalize_team_name's "<2 digits> boys|girls" rule rewrites "08/07 Girls" to
     "08/2007", turning a band label into a single wrong year.

  2. The false-refusal budget, measured against merges that were kept. Subset
     semantics refuse 6 of ~2,900 human-approved merges; requiring equality
     refuses 55. The budget test is what stops a future re-tightening to equality.
"""

import pytest

from src.utils.team_name_utils import birth_years, birth_years_conflict


@pytest.mark.parametrize(
    "name,expected",
    [
        # Plain and gender-affixed, both orders. "14B" is the house GotSport form.
        ("2011", {2011}),
        ("B2011", {2011}),
        ("2011B", {2011}),
        ("G2011", {2011}),
        ("11G", {2011}),
        ("14B", {2014}),
        ("Surf SC Elite '09", {2009}),
        # Band labels carry BOTH years -- the season runs Aug-Jul, so one band
        # straddles two calendar birth years and either end may name the team.
        ("B08/07", {2007, 2008}),
        ("2013/14", {2013, 2014}),
        ("B2016/17", {2016, 2017}),
        ("Team 08/07 Girls", {2007, 2008}),
        # U-ages are cohort labels, not birth years: what they mean depends on the
        # season that wrote them, so they must contribute nothing.
        ("GU18/19", set()),
        ("U14", set()),
        ("14U", set()),
        # A bare two-digit number is a squad number until something marks it a year.
        ("Arsenal 11 B", set()),
        ("6/7 Grinch Unit", set()),
    ],
)
def test_birth_years_notation(name, expected):
    assert birth_years(name) == expected


@pytest.mark.parametrize(
    "name_a,name_b,conflict",
    [
        # The links this guard exists to refuse.
        ("Stateline SC-2011G Bears", "Stateline SC-2013G Bears", True),
        ("Surf SC Elite '09", "Surf SC Elite '08", True),
        ("EPIC SC 2008 Dash", "EPIC SC 2009 Dash", True),
        # Subset, not equality: the same team written from one end of its band.
        ("Dallas Texans ECNL B08/07", "Dallas Texans ECNL 2008", False),
        ("2013/14 Lobos Rush Gold", "2013 Lobos Rush Gold", False),
        # Bands that merely OVERLAP are still distinct teams sharing one year.
        ("club 08/07", "club 06/07", True),
        # A club whose own name carries a year supplies a shared year for free;
        # subset still separates these, which is why overlap is not the test.
        ("Union 2010 FC 2009", "Union 2010 FC 2008", True),
        # Genuine formatting duplicates must survive.
        ("Rangers FC - 2017 White", "Rangers FC 2017 White", False),
        # Silent where it cannot see: no year stated on one side means no verdict.
        ("Rush U18", "Rush U19", False),
        ("FC Dallas Red", "FC Dallas 2009 Red", False),
    ],
)
def test_birth_years_conflict(name_a, name_b, conflict):
    assert birth_years_conflict(name_a, name_b) is conflict
    assert birth_years_conflict(name_b, name_a) is conflict


def test_conflict_is_silent_without_years_on_both_sides():
    """No year on either side is not evidence of agreement -- it is no evidence.

    26% of pending queue rows state no birth year. The guard must return False for
    them so it never becomes the only thing standing between those rows and a
    match; a separate check has to cover that population.
    """
    assert birth_years_conflict("Rangers FC White", "Rangers FC Blue") is False
    assert birth_years_conflict("", "FC Dallas 2009") is False
    assert birth_years_conflict(None, None) is False


def test_equality_semantics_would_break_the_band_convention():
    """Pins WHY this is subset rather than equality.

    Equality refuses 55 of 2,929 kept human merges against 6 for subset, because
    a band label and a single-year label for the same team are not equal sets.
    """
    band, single = birth_years("Dallas Texans ECNL B08/07"), birth_years("Dallas Texans ECNL 2008")
    assert band != single, "the two notations are genuinely different sets"
    assert single < band, "and the single year is a subset, which is what makes them compatible"
    assert birth_years_conflict("Dallas Texans ECNL B08/07", "Dallas Texans ECNL 2008") is False
