"""Opponent exposure alone does not earn connectivity ceiling relief."""

import pandas as pd
import pytest

from src.rankings.calculator import _publication_cap_rank


def exposure_profile(**changes):
    return pd.Series({
        "age_num": 10,
        "same_age_games": 15,
        "same_age_unique_opponents": 13,
        "same_age_top100_opp_count": 2,
        "same_age_top100_non_loss_opp_count": 0,
        "same_age_top500_opp_count": 3,
        "same_age_top500_non_loss_opp_count": 1,
        "same_age_top1000_non_loss_opp_count": 2,
        "same_age_avg_opp_power_adj": 0.467,
        "same_age_quality_opp_power_adj": 0.457,
        "repeat_opponent_share": 0.19,
        "unique_opp_states": 1,
        "scf": 0.233,
        "bridge_games": 1,
        "games_last_180_days": 17,
        "days_since_last": 14,
        "play_up_game_share": 0.0,
        "play_up_top500_non_loss_opp_count": 0,
        "play_up_top1000_non_loss_opp_count": 0,
        "play_up_avg_opp_power_adj": None,
    } | changes)


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
def test_top100_losses_do_not_grant_connectivity_relief(age):
    assert _publication_cap_rank(exposure_profile(age_num=age)) == 400


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
def test_one_top100_non_loss_retains_connectivity_relief(age):
    row = exposure_profile(age_num=age, same_age_top100_non_loss_opp_count=1)
    assert _publication_cap_rank(row) == 250


@pytest.mark.parametrize("value", [None, float("nan"), pd.NA])
def test_unknown_top100_results_do_not_grant_relief(value):
    row = exposure_profile(same_age_top100_non_loss_opp_count=value)
    assert _publication_cap_rank(row) == 400


def test_missing_top100_results_do_not_grant_relief():
    row = exposure_profile().drop("same_age_top100_non_loss_opp_count")
    assert _publication_cap_rank(row) == 400


def test_result_supported_relief_keeps_freshness_limit():
    row = exposure_profile(
        same_age_top100_non_loss_opp_count=1,
        games_last_180_days=0,
        days_since_last=200,
    )
    assert _publication_cap_rank(row) == 400


def test_supported_play_up_exception_survives_top100_losses():
    row = exposure_profile(
        play_up_game_share=0.70,
        play_up_top500_non_loss_opp_count=4,
        play_up_top1000_non_loss_opp_count=6,
        play_up_avg_opp_power_adj=0.65,
    )
    assert _publication_cap_rank(row) == 250


def test_earlier_stricter_restriction_still_wins():
    row = exposure_profile(same_age_top100_opp_count=1)
    assert _publication_cap_rank(row) == 1800
