"""Freshness restrictions cannot grant relief from stronger evidence limits."""

import pandas as pd
import pytest

from src.rankings.calculator import _publication_cap_rank


def weak_results(**changes):
    values = {
        "age_num": 13,
        "same_age_games": 12,
        "same_age_unique_opponents": 12,
        "same_age_top100_opp_count": 0,
        "same_age_top100_non_loss_opp_count": 0,
        "same_age_top500_opp_count": 1,
        "same_age_top500_non_loss_opp_count": 1,
        "same_age_top1000_non_loss_opp_count": 1,
        "same_age_avg_opp_power_adj": 0.528,
        "same_age_quality_opp_power_adj": 0.527,
        "repeat_opponent_share": 0.0,
        "play_up_game_share": 0.06,
        "play_up_top500_non_loss_opp_count": 0,
        "play_up_top1000_non_loss_opp_count": 0,
        "play_up_avg_opp_power_adj": 0.837,
        "games_last_180_days": 4,
        "days_since_last": 10,
        "powerscore_adj": 0.755,
        "powerscore_ml": 0.791,
        "scf": 0.1,
        "unique_opp_states": 0.0,
        "bridge_games": 0.0,
    }
    return pd.Series(values | changes)


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
def test_low_recent_volume_cannot_bypass_stricter_weak_results_cap(age):
    # Recent last game isolates the low-volume branch from the stale branch.
    assert _publication_cap_rank(weak_results(age_num=age)) == 1800


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
def test_staleness_cannot_bypass_stricter_regional_cap(age):
    # Six recent games avoids the <=5 branch; staleness alone masked this limit.
    row = weak_results(
        age_num=age,
        same_age_games=4,
        same_age_unique_opponents=2,
        same_age_top1000_non_loss_opp_count=2,
        same_age_avg_opp_power_adj=0.642,
        same_age_quality_opp_power_adj=0.647,
        repeat_opponent_share=0.875,
        play_up_game_share=0.0,
        play_up_avg_opp_power_adj=None,
        games_last_180_days=6,
        days_since_last=115,
        powerscore_adj=0.849,
        powerscore_ml=0.885,
    )
    assert _publication_cap_rank(row) == 1800


@pytest.mark.parametrize("games, days", [(4, 10), (6, 115)])
def test_freshness_limit_survives_when_evidence_allows_soft_cap(games, days):
    row = weak_results(
        same_age_unique_opponents=15,
        same_age_top100_opp_count=2,
        same_age_top100_non_loss_opp_count=1,
        same_age_top500_opp_count=6,
        same_age_top500_non_loss_opp_count=3,
        same_age_top1000_non_loss_opp_count=5,
        same_age_avg_opp_power_adj=0.70,
        same_age_quality_opp_power_adj=0.71,
        games_last_180_days=games,
        days_since_last=days,
        unique_opp_states=2,
        scf=0.7,
    )
    assert _publication_cap_rank(row) == 400


def test_supported_play_up_relief_is_preserved_with_stale_local_schedule():
    row = weak_results(
        repeat_opponent_share=0.52,
        same_age_avg_opp_power_adj=0.49,
        same_age_quality_opp_power_adj=0.49,
        days_since_last=115,
        play_up_game_share=0.83,
        play_up_top500_non_loss_opp_count=2,
        play_up_top1000_non_loss_opp_count=4,
        play_up_avg_opp_power_adj=0.60,
    )
    assert _publication_cap_rank(row) == 250


def test_recent_weak_schedule_keeps_its_existing_strict_cap():
    assert _publication_cap_rank(weak_results(games_last_180_days=18, days_since_last=3)) == 1800
