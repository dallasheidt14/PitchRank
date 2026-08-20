"""The oldest and youngest cohorts, where the age formula runs out of band.

PitchRank age groups are BANDS, not single birth years, because the season runs
Aug 1 - Jul 31 and so straddles Jan 1. For the 2026-27 season:

    U9  (2018/17)   U10 (2017/16)   U11 (2016/15)   U12 (2015/14)
    U13 (2014/13)   U14 (2013/12)   U15 (2012/11)   U16 (2011/10)
    U17 (2010/09)   U18 (2009/08)   U19 (2008/07)

So a bare birth year belongs to TWO bands -- U(season-Y) and U(season+1-Y) -- and
calculate_age_group_from_birth_year returns the older of them. At the top of the
range that older band does not exist: 2007 computed U20, fell outside the valid
7..19 window, and returned None. Those teams then had no cohort at all, and the
matcher turned that None into an unmatchable sentinel, so 3,731 teams whose names
say 2007 could not be found by name.

2007 is the ONLY birth year that reaches age 20, so this correction moves exactly
one cohort and leaves every other year untouched. 2006 must keep returning None --
it sits in no band for this season and is genuinely aged out.
"""

import pytest

from src.utils.team_utils import calculate_age_group_from_birth_year

SEASON = 2026


@pytest.mark.parametrize(
    "birth_year,expected",
    [
        # Aged out -- no band contains them, so no cohort.
        (2004, None),
        (2005, None),
        (2006, None),
        # The top band. U19 is 2008/07, so 2007 belongs to it even though the
        # formula's older band (U20) does not exist.
        (2007, "U19"),
        (2008, "U19"),
        # Everything below is unchanged by the edge correction.
        (2010, "U17"),
        (2011, "U16"),
        (2012, "U15"),
        (2013, "U14"),
        (2014, "U13"),
        (2015, "U12"),
        (2016, "U11"),
        (2017, "U10"),
        (2018, "U9"),
    ],
)
def test_birth_year_maps_into_its_band(birth_year, expected):
    assert calculate_age_group_from_birth_year(birth_year, SEASON) == expected


def test_2006_stays_aged_out():
    """The guard against over-correcting the top edge.

    It would be easy to 'fix' the None by widening the valid range, which would
    pull 2006 and older back into U19 and re-rank teams that have aged out of
    youth soccer. Only age 20 folds; age 21 must still fall through.
    """
    assert calculate_age_group_from_birth_year(2006, SEASON) is None
    assert calculate_age_group_from_birth_year(2005, SEASON) is None


def test_only_one_birth_year_changed():
    """Pins the blast radius: exactly one cohort moves.

    Age 20 is reached only by season - 19. Any change that moves a second birth
    year is doing more than correcting the top band and needs its own decision.
    """
    moved = [
        y
        for y in range(1998, 2021)
        if (SEASON - y + 1) == 20 and calculate_age_group_from_birth_year(y, SEASON) is not None
    ]
    assert moved == [2007]


def test_the_band_rolls_with_the_season():
    """Next Aug 1 the top band moves on its own; nothing here is pinned to 2007."""
    assert calculate_age_group_from_birth_year(2008, 2027) == "U19"
    assert calculate_age_group_from_birth_year(2007, 2027) is None
