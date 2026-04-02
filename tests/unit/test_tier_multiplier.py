"""Tests for league tier multiplier system."""

import pytest
from src.rankings.constants import (
    LEAGUE_TO_TIER_MALE,
    LEAGUE_TO_TIER_FEMALE,
    TIER_MULTIPLIERS,
    UNAFFILIATED_MULTIPLIER,
    get_tier_multiplier,
)


class TestTierConstants:
    """Verify tier mapping and multiplier lookups."""

    def test_ecnl_is_tier_1_male(self):
        assert LEAGUE_TO_TIER_MALE["ECNL"] == 1

    def test_ecnl_rl_is_tier_2_male(self):
        assert LEAGUE_TO_TIER_MALE["ECNL_RL"] == 2

    def test_mls_next_hd_is_tier_1_male(self):
        assert LEAGUE_TO_TIER_MALE["MLS_NEXT_HD"] == 1

    def test_mls_next_ad_is_tier_2_male(self):
        assert LEAGUE_TO_TIER_MALE["MLS_NEXT_AD"] == 2

    def test_ga_is_tier_1_female(self):
        assert LEAGUE_TO_TIER_FEMALE["GA"] == 1

    def test_ga_not_in_male_tiers(self):
        assert "GA" not in LEAGUE_TO_TIER_MALE

    def test_tier_1_multiplier_is_1(self):
        assert TIER_MULTIPLIERS[1] == 1.0

    def test_tier_2_multiplier(self):
        assert TIER_MULTIPLIERS[2] == 0.85

    def test_tier_3_multiplier(self):
        assert TIER_MULTIPLIERS[3] == 0.70


class TestGetTierMultiplier:
    """Verify the lookup function."""

    def test_ecnl_male_returns_1(self):
        assert get_tier_multiplier("ECNL", "Male") == 1.0

    def test_ecnl_rl_male_returns_085(self):
        assert get_tier_multiplier("ECNL_RL", "Male") == 0.85

    def test_dpl_female_returns_085(self):
        assert get_tier_multiplier("DPL", "Female") == 0.85

    def test_ga_female_returns_1(self):
        assert get_tier_multiplier("GA", "Female") == 1.0

    def test_none_league_returns_unaffiliated(self):
        assert get_tier_multiplier(None, "Male") == UNAFFILIATED_MULTIPLIER

    def test_unknown_league_returns_unaffiliated(self):
        assert get_tier_multiplier("SOME_RANDOM_LEAGUE", "Male") == UNAFFILIATED_MULTIPLIER

    def test_unaffiliated_multiplier_is_1(self):
        assert UNAFFILIATED_MULTIPLIER == 1.0
