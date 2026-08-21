"""Unit tests for age-token handling in ``scripts.normalize_team_names``.

Pure-function tests — no fixtures, no network. The job runs weekly with
``--all-teams``, so every case here is also asserted to be a fixed point:
normalizing an already-normalized name must return it unchanged, or the table
churns every Monday.

Season-dependent by construction. ``calculate_age_group_from_birth_year`` reads
the wall clock, so the band table below is pinned to the 2026-27 season and these
tests are expected to be re-pinned at the next rollover.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))

from normalize_team_names import _resolve_band, normalize_team_name  # noqa: E402
from src.utils.team_utils import CURRENT_YEAR  # noqa: E402

pytestmark = pytest.mark.skipif(
    CURRENT_YEAR != 2026, reason="band table below is pinned to the 2026-27 season"
)

# The cohort table, as the maintainer states it: U_N = {SEASON+1-N, SEASON-N}.
BAND_TABLE = [
    ("2017/2016", "U10"),
    ("2016/2015", "U11"),
    ("2015/2014", "U12"),
    ("2014/2013", "U13"),
    ("2013/2012", "U14"),
    ("2012/2011", "U15"),
    ("2011/2010", "U16"),
    ("2010/2009", "U17"),
    # The maintainer's table names this band U18, but the codebase has no U18
    # bucket — config/settings.AGE_GROUPS omits it and
    # calculate_age_group_from_birth_year folds 18 into 19 — so both of the
    # oldest bands render U19. Changing that is a schema decision, not a
    # normalizer one.
    ("2009/2008", "U19"),
    ("2008/2007", "U19"),
]


def _normalized_twice(name, club=None, age_group=None, original=None):
    """(first pass, second pass) — the second sees what the first would store."""
    first = normalize_team_name(name, club, age_group, original)
    return first, normalize_team_name(first, club, age_group, original or name)


class TestBandTable:
    @pytest.mark.parametrize("band,expected", BAND_TABLE)
    def test_each_cohort(self, band, expected):
        assert _resolve_band(f"Rush {band} Red")[1] == expected

    def test_u18_folds_into_u19(self):
        # calculate_age_group_from_birth_year merges U18 into U19, so 2009/2008
        # and 2008/2007 both land on U19 in the rendered name.
        assert _resolve_band("Rush 2009/2008 Red")[0] == "Rush U19 Red"


class TestBandForms:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("13/14B Summer", "U13 Summer"),
            ("B14/15 Silver", "U12 Silver"),
            ("16/17 Girls Blue", "U10 Blue"),
            ("FC Dallas 2014-15 Red", "FC Dallas U12 Red"),
            ("Auburn SC 2013 - 2014 Girls White", "Auburn SC U13 White"),
            ("Diablo 2014G -2015G Wolves", "Diablo U12 Wolves"),
            ("2008/2007 Krush ECNL", "U19 Krush ECNL"),
        ],
    )
    def test_separators_spacing_and_gender_letters(self, name, expected):
        assert normalize_team_name(name, None, "u9") == expected

    def test_every_band_in_the_name_is_collapsed(self):
        # Leaving a trailing band means the next run finds it and the name moves
        # again. See "Cape Coral Soccer - 2007/2008 Cyclone RL B07/08".
        assert _resolve_band("Cape Coral 2007/2008 Cyclone RL B07/08")[0] == "Cape Coral U19 Cyclone RL U19"


class TestNotBands:
    @pytest.mark.parametrize(
        "name",
        [
            "Club 10-3 Red",  # a score, not consecutive years
            "1570 FC - 1570 FC G",  # equal years
            "Chaffee County United 07/08/09/10",  # four birth years, not a band
        ],
    )
    def test_left_alone(self, name):
        assert _resolve_band(name)[1] is None


class TestColumnDrivesOnlyStaleUAges:
    def test_stale_u_age_rolls_from_the_column(self):
        assert normalize_team_name("S5A KENDALL U12 Elite", None, "u13") == "S5A KENDALL U13 Elite"

    def test_u_age_after_a_birth_year_still_rolls(self):
        # The year corroborates the column from inside the same name, which makes
        # these the best-evidenced rewrites in the table.
        assert normalize_team_name("2014 U12 PRE MLS I", None, "u13") == "2014 U13 PRE MLS I"

    def test_lone_birth_year_is_never_overwritten(self):
        # A birth year re-derives its own cohort every Aug 1, so it cannot go
        # stale — and rendering a label over it would delete the only token in
        # the name that can be checked afterwards.
        assert normalize_team_name("2018 Clay", None, "u11") == "2018 Clay"

    def test_contradicting_birth_year_vetoes_the_column(self):
        # 2019 is U8; a u15 column disagrees with the one token that cannot have
        # rotted, so the column is the suspect side and the name is left alone.
        assert normalize_team_name("U08B Cook Inlet SC Navy 2019", None, "u15") == "U8 Cook Inlet SC Navy 2019"

    def test_band_outranks_the_column(self):
        assert normalize_team_name("13/14B Summer", None, "u15") == "U13 Summer"

    def test_club_founding_year_is_not_an_age(self):
        # parse_age_gender's bare-two-digit branch returns U{n} for anything
        # outside 6-18, which turned "Worthington United 94" into "U94".
        assert normalize_team_name("Worthington United 94 2018 Boys Red", None, "u11") == (
            "Worthington United 94 2018 Red"
        )

    def test_unusable_column_leaves_the_age_alone(self):
        assert normalize_team_name("Rush U12 Red", None, "u20") == "Rush U12 Red"


class TestIdempotence:
    @pytest.mark.parametrize(
        "name,age_group",
        [
            ("13/14B Summer", "u15"),
            ("16/17 Girls Blue", "u12"),
            ("FC Dallas 2014-15 Red", "u11"),
            ("Diablo 2014G -2015G Wolves", "u13"),
            ("Cape Coral 2007/2008 Cyclone RL B07/08", "u17"),
            ("S5A KENDALL U12 Elite", "u13"),
            ("2014 U12 PRE MLS I", "u13"),
            ("U08B Cook Inlet SC Navy 2019", "u15"),
            ("Worthington United 94 2018 Boys Red", "u11"),
        ],
    )
    def test_second_pass_changes_nothing(self, name, age_group):
        first, second = _normalized_twice(name, None, age_group)
        assert second == first

    def test_collapsed_band_is_not_rerolled_to_the_column(self):
        # The regression this suite exists for. Collapsing a band destroys the
        # evidence it was there, so without the original name the U13 reads as an
        # ordinary stale label and the column rolls it to U15 — the band's answer
        # surviving exactly one weekly run.
        first, second = _normalized_twice("13/14B Summer", None, "u15")
        assert first == "U13 Summer"
        assert second == "U13 Summer"

    def test_veto_survives_a_band_that_is_no_longer_in_the_name(self):
        assert normalize_team_name("U13 Summer", None, "u15", "13/14B Summer") == "U13 Summer"
