"""Unit tests for division-label parsing in scripts/scrape_affinity_wa_tournament.py.

Scope is the birth-year parenthetical, which is what silently misfiled the
26-27 season. Affinity renamed its divisions between seasons:

- 25-26 wrote ``Boys Under 12 Div 1 (2014)`` — one year, the band's younger
- 26-27 writes ``Boys Under 12 (2014/15) Div 1`` — the two-year window

Reading the leading year off the second form stamps every team one cohort too
old. The flight/game HTTP plumbing is covered by the end-to-end scrape+import
verification, not by unit tests (matches the TGS/PlayMetrics convention).
"""

import pytest

from scripts.scrape_affinity_wa_tournament import (
    _extract_age_gender_from_division,
    _parse_band_birth_year,
)
from src.utils import team_utils

PINNED_SEASON = 2026


class TestParseBandBirthYear:
    """The parenthetical resolves to the band's younger year, never the older."""

    @pytest.mark.parametrize(
        "div_name, expected",
        [
            # 26-27 form: two-digit suffix is the younger year
            ("Boys Under 12 (2014/15) Div 1", 2015),
            ("Girls Under 10 (2016/17) Div 2 North", 2017),
            ("Spring Boys U8 North (2018/19)", 2019),
            # Four-digit suffix, as U19 has always been written
            ("Boys Under 19 (2008/2009) Div 1", 2009),
            ("Boys Under 19 Div 1 (2007/2008)", 2008),
            # 25-26 form: a lone year is already the younger one
            ("Boys Under 12 Div 1 (2014)", 2014),
            # Century rollover must not read backwards
            ("Boys Under 12 (1999/00) Div 1", 2000),
            # No parenthetical at all — South Sound labels its divisions this way
            ("Boys U9 North", None),
            ("Girls Under 11", None),
        ],
    )
    def test_returns_younger_year(self, div_name, expected):
        assert _parse_band_birth_year(div_name) == expected


class TestDivisionCohortAgreement:
    """A label's U-number and its parsed birth year must name the same cohort."""

    @pytest.mark.parametrize(
        "div_name",
        [
            "Boys Under 10 (2016/17) Div 1",
            "Boys Under 11 (2015/16) Div 2 South",
            "Boys Under 12 (2014/15) Div 1",
            "Boys Under 13 (2013/14) Div 3",
            "Boys Under 14 (2012/13) Div 2 North",
            "Boys Under 15 (2011/12) Div 1",
            "Boys Under 16 (2010/11) Div 2",
            "Boys Under 17 (2009/10) Div 1",
            "Girls Under 12 (2014/15) Div 2 South",
            "Girls Under 14 (2012/13) Div 1",
        ],
    )
    def test_birth_year_resolves_to_the_labelled_age(self, div_name):
        _, age_u, birth_year = _extract_age_gender_from_division(div_name)

        age_group = team_utils.calculate_age_group_from_birth_year(birth_year, PINNED_SEASON)

        assert age_group == f"U{age_u}"

    def test_u17_would_regress_to_u19_on_the_older_year(self):
        """The U17 band is the one whose off-by-one skips a cohort entirely.

        2009 is U18 by the formula and U18 collapses into U19, so reading the
        older year moves U17 two boards rather than one. Pinning it keeps the
        merge from hiding a future regression.
        """
        older_year_result = team_utils.calculate_age_group_from_birth_year(2009, PINNED_SEASON)

        assert older_year_result == "U19"
        assert _parse_band_birth_year("Boys Under 17 (2009/10) Div 1") == 2010


class TestGenderAndAgeExtraction:
    """The label's own U-number drives flight filtering and must survive the rename."""

    @pytest.mark.parametrize(
        "div_name, gender, age_u",
        [
            ("Boys Under 12 (2014/15) Div 1", "Male", 12),
            ("Girls Under 10 (2016/17) Div 2 North", "Female", 10),
            ("Boys U9 North", "Male", 9),
            ("Girls U11/12", "Female", 11),
            ("Boys Under 15 8th G Spring", "Male", 15),
        ],
    )
    def test_gender_and_age_come_from_the_label(self, div_name, gender, age_u):
        parsed_gender, parsed_age, _ = _extract_age_gender_from_division(div_name)

        assert (parsed_gender, parsed_age) == (gender, age_u)
