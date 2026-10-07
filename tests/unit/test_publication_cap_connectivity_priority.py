"""Connectivity restrictions must not grant relief from weak-schedule limits."""

import pandas as pd
import pytest

from src.rankings.calculator import _publication_cap_rank


def thin_profile(**changes):
    return pd.Series({
        "age_num": 13,
        "same_age_games": 18,
        "same_age_unique_opponents": 9,
        "same_age_top100_opp_count": 1,
        "same_age_top100_non_loss_opp_count": 0,
        "same_age_top500_opp_count": 3,
        "same_age_top500_non_loss_opp_count": 1,
        "same_age_top1000_non_loss_opp_count": 4,
        "same_age_avg_opp_power_adj": 0.53,
        "same_age_quality_opp_power_adj": 0.53,
        "repeat_opponent_share": 0.70,
        "unique_opp_states": 2,
        "scf": 0.4,
        "bridge_games": 0,
        "games_last_180_days": 18,
        "days_since_last": 3,
        "play_up_game_share": 0.0,
        "play_up_top500_non_loss_opp_count": 0,
        "play_up_top1000_non_loss_opp_count": 0,
        "play_up_avg_opp_power_adj": None,
    } | changes)


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
def test_severe_connectivity_keeps_stricter_thin_schedule_limit(age):
    row = thin_profile(age_num=age)
    # Increasing repetition must not relax the 1,800 cap.
    assert _publication_cap_rank(row) == 1800
    row["repeat_opponent_share"] = 0.07
    assert _publication_cap_rank(row) == 1800


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
def test_severe_connectivity_keeps_stricter_weak_results_limit(age):
    row = thin_profile(
        age_num=age,
        same_age_top500_opp_count=5,
        same_age_avg_opp_power_adj=0.627,
        same_age_quality_opp_power_adj=0.627,
    )
    assert _publication_cap_rank(row) == 1500


def test_severe_connectivity_fallback_remains_without_stricter_evidence_limit():
    row = thin_profile(
        same_age_top100_non_loss_opp_count=1,
        same_age_top500_opp_count=2,
        same_age_avg_opp_power_adj=0.62,
        same_age_quality_opp_power_adj=0.62,
    )
    assert _publication_cap_rank(row) == 400


def test_supported_play_up_exception_still_precedes_connectivity_restrictions():
    row = thin_profile(
        play_up_game_share=0.70,
        play_up_top500_non_loss_opp_count=2,
        play_up_top1000_non_loss_opp_count=4,
        play_up_avg_opp_power_adj=0.60,
    )
    assert _publication_cap_rank(row) == 250


def test_well_supported_in_state_exception_is_preserved():
    row = thin_profile(
        same_age_unique_opponents=24,
        same_age_top100_opp_count=4,
        same_age_top100_non_loss_opp_count=2,
        same_age_top500_opp_count=8,
        same_age_top500_non_loss_opp_count=6,
        same_age_top1000_non_loss_opp_count=8,
        same_age_avg_opp_power_adj=0.72,
        same_age_quality_opp_power_adj=0.74,
        repeat_opponent_share=0.1,
        unique_opp_states=1,
    )
    assert _publication_cap_rank(row) == 250
