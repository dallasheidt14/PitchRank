"""Qualifying older results must not lose relief when connectivity improves."""

import pandas as pd
import pytest

from src.rankings.calculator import _publication_cap_rank, _publication_cap_rank_with_connectivity


def supported_profile(**changes):
    return pd.Series({
        "team_id": "supported",
        "age_num": 15,
        "gender": "female",
        "same_age_games": 0,
        "same_age_unique_opponents": 0,
        "same_age_top100_opp_count": 0,
        "same_age_top100_non_loss_opp_count": 0,
        "same_age_top500_opp_count": 0,
        "same_age_top500_non_loss_opp_count": 0,
        "same_age_top1000_non_loss_opp_count": 0,
        "same_age_avg_opp_power_adj": None,
        "repeat_opponent_share": .10,
        "unique_opp_states": 5.0,
        "scf": 1.0,
        "bridge_games": 5.0,
        "is_isolated": False,
        "play_up_game_share": .40,
        "play_up_top500_non_loss_opp_count": 2,
        "play_up_top1000_non_loss_opp_count": 4,
        "play_up_avg_opp_power_adj": .58,
        "games_last_180_days": 18,
        "days_since_last": 5,
    } | changes)


@pytest.mark.parametrize("age", [10, 11, 12, 13, 14, 15, 16, 17, 19])
@pytest.mark.parametrize("gender", ["male", "female"])
def test_supported_older_results_keep_relief_after_connectivity_improves(age, gender):
    row = supported_profile(age_num=age, gender=gender, scf=.1, unique_opp_states=0., bridge_games=0.)
    assert _publication_cap_rank(row) == 250
    row.update(pd.Series({"scf": 1., "unique_opp_states": 5., "bridge_games": 5.}))
    assert _publication_cap_rank(row) == 250


@pytest.mark.parametrize("field,value", [
    ("play_up_game_share", .399),
    ("play_up_top500_non_loss_opp_count", 1),
    ("play_up_top1000_non_loss_opp_count", 3),
    ("play_up_avg_opp_power_adj", .579),
    ("play_up_avg_opp_power_adj", None),
    ("play_up_avg_opp_power_adj", float("nan")),
])
def test_each_existing_play_up_requirement_remains_necessary(field, value):
    assert _publication_cap_rank(supported_profile(**{field: value})) == 2000


@pytest.mark.parametrize("field", [
    "play_up_game_share", "play_up_top500_non_loss_opp_count",
    "play_up_top1000_non_loss_opp_count", "play_up_avg_opp_power_adj",
])
def test_missing_older_evidence_cannot_grant_relief(field):
    assert _publication_cap_rank(supported_profile().drop(field)) == 2000


def test_supported_team_with_full_release_does_not_gain_a_new_ceiling():
    row = supported_profile(
        same_age_games=24,
        same_age_unique_opponents=24,
        same_age_top100_opp_count=4,
        same_age_top100_non_loss_opp_count=2,
        same_age_top500_opp_count=9,
        same_age_top500_non_loss_opp_count=6,
        same_age_top1000_non_loss_opp_count=8,
        same_age_avg_opp_power_adj=.70,
        same_age_quality_opp_power_adj=.72,
    )
    assert _publication_cap_rank(row) is None


def test_stale_supported_schedule_retains_the_existing_play_up_exception():
    assert _publication_cap_rank(supported_profile(games_last_180_days=2, days_since_last=140)) == 250


def test_private_connectivity_overlay_keeps_relief_without_mutating_the_shared_row():
    row = supported_profile().drop(["scf", "unique_opp_states", "bridge_games", "is_isolated"])
    row["_ceiling_source_cohort"] = 0
    original = row.copy(deep=True)
    diagnostics = pd.DataFrame([{
        "_ceiling_source_cohort": 0, "team_id": "supported",
        "scf": 1., "unique_opp_states": 5., "bridge_games": 5., "is_isolated": False,
    }]).set_index(["_ceiling_source_cohort", "team_id"])
    assert _publication_cap_rank_with_connectivity(row, diagnostics) == 250
    pd.testing.assert_series_equal(row, original)
