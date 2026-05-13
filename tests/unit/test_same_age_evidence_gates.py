from __future__ import annotations

import pandas as pd

from src.rankings.calculator import (
    _apply_publication_cap_band,
    _collect_top_tier_weak_uncapped,
    _compute_publication_cap_scores,
    _compute_same_age_evidence_metrics,
    _play_up_bonus,
    _positive_ml_evidence_scale,
    _same_age_raw_shrink,
    _same_age_publish_penalty,
    _publication_cap_rank,
    _validate_publication_caps,
)


def test_compute_same_age_evidence_metrics_uses_unique_same_age_opponents():
    teams = pd.DataFrame(
        {
            "team_id": ["A", "B", "C", "D"],
            "age": ["12", "12", "12", "13"],
            "gender": ["Male", "Male", "Male", "Male"],
            "powerscore_adj": [0.95, 0.90, 0.70, 0.60],
            "status": ["Active", "Active", "Active", "Active"],
        }
    )
    games_used = pd.DataFrame(
        [
            {"team_id": "A", "opp_id": "B", "age": "12", "gender": "Male", "opp_age": "12", "opp_gender": "Male"},
            {"team_id": "A", "opp_id": "B", "age": "12", "gender": "Male", "opp_age": "12", "opp_gender": "Male"},
            {"team_id": "A", "opp_id": "C", "age": "12", "gender": "Male", "opp_age": "12", "opp_gender": "Male"},
            {"team_id": "A", "opp_id": "D", "age": "12", "gender": "Male", "opp_age": "13", "opp_gender": "Male"},
        ]
    )

    result = _compute_same_age_evidence_metrics(games_used, teams).set_index("team_id")
    a = result.loc["A"]

    assert int(a["same_age_games"]) == 3
    assert int(a["same_age_unique_opponents"]) == 2
    assert int(a["same_age_top100_opp_count"]) == 2
    assert int(a["same_age_top100_non_loss_opp_count"]) == 0
    assert int(a["same_age_top500_opp_count"]) == 2
    assert int(a["same_age_top500_non_loss_opp_count"]) == 0
    assert int(a["same_age_top1000_non_loss_opp_count"]) == 0
    assert float(a["repeat_opponent_share"]) == 0.5


def test_compute_same_age_evidence_metrics_counts_quality_non_loss_results():
    teams = pd.DataFrame(
        {
            "team_id": ["A", "B", "C", "D"],
            "age": ["12", "12", "12", "12"],
            "gender": ["Male", "Male", "Male", "Male"],
            "powerscore_adj": [0.95, 0.92, 0.81, 0.79],
            "status": ["Active", "Active", "Active", "Active"],
        }
    )
    games_used = pd.DataFrame(
        [
            {
                "team_id": "A",
                "opp_id": "B",
                "age": "12",
                "gender": "Male",
                "opp_age": "12",
                "opp_gender": "Male",
                "gf": 2,
                "ga": 2,
            },
            {
                "team_id": "A",
                "opp_id": "C",
                "age": "12",
                "gender": "Male",
                "opp_age": "12",
                "opp_gender": "Male",
                "gf": 1,
                "ga": 0,
            },
            {
                "team_id": "A",
                "opp_id": "D",
                "age": "12",
                "gender": "Male",
                "opp_age": "12",
                "opp_gender": "Male",
                "gf": 0,
                "ga": 3,
            },
        ]
    )

    result = _compute_same_age_evidence_metrics(games_used, teams).set_index("team_id")
    a = result.loc["A"]

    assert int(a["same_age_top500_opp_count"]) == 3
    assert int(a["same_age_top100_non_loss_opp_count"]) == 2
    assert int(a["same_age_top500_non_loss_opp_count"]) == 2
    assert int(a["same_age_top1000_non_loss_opp_count"]) == 2
    assert float(a["same_age_quality_opp_power_adj"]) > float(a["same_age_avg_opp_power_adj"])


def test_compute_same_age_evidence_metrics_tracks_exact_one_year_play_up_results():
    teams = pd.DataFrame(
        {
            "team_id": ["A", "B", "C", "D", "E"],
            "age": ["12", "13", "13", "14", "12"],
            "gender": ["Male", "Male", "Male", "Male", "Female"],
            "powerscore_adj": [0.70, 0.94, 0.88, 0.92, 0.90],
            "status": ["Active", "Active", "Active", "Active", "Active"],
        }
    )
    games_used = pd.DataFrame(
        [
            {
                "team_id": "A",
                "opp_id": "B",
                "age": "12",
                "gender": "Male",
                "opp_age": "13",
                "opp_gender": "Male",
                "gf": 2,
                "ga": 2,
            },
            {
                "team_id": "A",
                "opp_id": "C",
                "age": "12",
                "gender": "Male",
                "opp_age": "13",
                "opp_gender": "Male",
                "gf": 3,
                "ga": 1,
            },
            {
                "team_id": "A",
                "opp_id": "D",
                "age": "12",
                "gender": "Male",
                "opp_age": "14",
                "opp_gender": "Male",
                "gf": 1,
                "ga": 1,
            },
            {
                "team_id": "A",
                "opp_id": "E",
                "age": "12",
                "gender": "Male",
                "opp_age": "12",
                "opp_gender": "Female",
                "gf": 5,
                "ga": 0,
            },
        ]
    )

    result = _compute_same_age_evidence_metrics(games_used, teams).set_index("team_id")
    a = result.loc["A"]

    assert int(a["play_up_games"]) == 2
    assert int(a["play_up_unique_opponents"]) == 2
    assert int(a["play_up_top100_opp_count"]) == 2
    assert int(a["play_up_top500_opp_count"]) == 2
    assert int(a["play_up_top500_non_loss_opp_count"]) == 2
    assert int(a["play_up_top1000_non_loss_opp_count"]) == 2


def test_positive_ml_evidence_scale_blocks_weak_u12_case():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 7,
            "same_age_avg_opp_power_adj": 0.59,
            "repeat_opponent_share": 0.61,
            "unique_opp_states": 4,
        }
    )
    assert _positive_ml_evidence_scale(row) < 0.10


def test_positive_ml_evidence_scale_allows_partial_zero_top100_case():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 5,
            "same_age_avg_opp_power_adj": 0.70,
            "repeat_opponent_share": 0.18,
            "unique_opp_states": 5,
        }
    )
    assert 0.15 < _positive_ml_evidence_scale(row) < 0.30


def test_positive_ml_evidence_scale_blocks_single_top100_with_thin_depth():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 1,
            "same_age_top500_opp_count": 2,
            "same_age_avg_opp_power_adj": 0.57,
            "repeat_opponent_share": 0.30,
            "unique_opp_states": 6,
        }
    )
    assert _positive_ml_evidence_scale(row) < 0.10


def test_positive_ml_evidence_scale_keeps_multi_top100_weak_field_team_partial():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 2,
            "same_age_top500_opp_count": 7,
            "same_age_avg_opp_power_adj": 0.55,
            "repeat_opponent_share": 0.13,
            "unique_opp_states": 8,
        }
    )
    assert _positive_ml_evidence_scale(row) < 0.20


def test_positive_ml_evidence_scale_stale_elite_profile_is_not_full_release():
    row = pd.Series(
        {
            "age_num": 13,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 2,
            "same_age_top500_opp_count": 6,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.721,
            "same_age_quality_opp_power_adj": 0.724,
            "repeat_opponent_share": 0.10,
            "unique_opp_states": 7,
            "games_last_180_days": 4,
            "days_since_last": 101,
        }
    )
    scale = _positive_ml_evidence_scale(row)
    assert 0.20 < scale < 0.40


def test_positive_ml_evidence_scale_allows_recent_zero_top100_bridge_profile_partial_ml():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 36,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_avg_opp_power_adj": 0.576,
            "same_age_quality_opp_power_adj": 0.622,
            "repeat_opponent_share": 0.50,
            "unique_opp_states": 5,
            "scf": 0.82,
            "games_last_180_days": 25,
            "days_since_last": 3,
            "powerscore_adj": 0.749,
            "powerscore_ml": 0.788,
        }
    )
    assert 0.20 < _positive_ml_evidence_scale(row) < 0.40


def test_positive_ml_evidence_scale_allows_volume_bridge_profile_partial_ml():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 34,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.576,
            "same_age_quality_opp_power_adj": 0.588,
            "repeat_opponent_share": 0.50,
            "unique_opp_states": 4,
            "scf": 0.70,
            "games_last_180_days": 25,
            "days_since_last": 3,
            "powerscore_adj": 0.749,
            "powerscore_ml": 0.788,
        }
    )
    assert 0.20 < _positive_ml_evidence_scale(row) < 0.40


def test_positive_ml_evidence_scale_allows_results_volume_bridge_profile_partial_ml():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 31,
            "same_age_unique_opponents": 22,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.590,
            "same_age_quality_opp_power_adj": 0.584,
            "repeat_opponent_share": 0.39,
            "unique_opp_states": 2,
            "games_last_180_days": 24,
            "days_since_last": 3,
            "powerscore_adj": 0.749,
            "powerscore_ml": 0.788,
            "scf": 0.46,
        }
    )
    assert 0.20 < _positive_ml_evidence_scale(row) < 0.40


def test_positive_ml_evidence_scale_allows_supported_play_up_team():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_avg_opp_power_adj": 0.49,
            "repeat_opponent_share": 0.30,
            "unique_opp_states": 1,
            "play_up_game_share": 0.80,
            "play_up_top500_non_loss_opp_count": 3,
            "play_up_top1000_non_loss_opp_count": 5,
            "play_up_avg_opp_power_adj": 0.62,
        }
    )
    assert _positive_ml_evidence_scale(row) == 0.5


def test_positive_ml_evidence_scale_connectivity_override_only_allows_partial():
    row = pd.Series(
        {
            "age_num": 16,
            "same_age_top100_opp_count": 5,
            "same_age_top500_opp_count": 8,
            "same_age_avg_opp_power_adj": 0.54,
            "repeat_opponent_share": 0.36,
            "unique_opp_states": 1,
        }
    )
    assert _positive_ml_evidence_scale(row) == 0.25


def test_positive_ml_evidence_scale_severe_connectivity_blocks_ml():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 3,
            "same_age_top500_opp_count": 3,
            "same_age_avg_opp_power_adj": 0.51,
            "repeat_opponent_share": 0.55,
            "unique_opp_states": 2,
        }
    )
    assert _positive_ml_evidence_scale(row) == 0.0


def test_positive_ml_evidence_scale_releases_elite_repetitive_quality_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 34,
            "same_age_unique_opponents": 21,
            "same_age_top100_opp_count": 5,
            "same_age_top100_non_loss_opp_count": 6,
            "same_age_top500_opp_count": 11,
            "same_age_top500_non_loss_opp_count": 12,
            "same_age_top1000_non_loss_opp_count": 14,
            "same_age_avg_opp_power_adj": 0.699,
            "same_age_quality_opp_power_adj": 0.699,
            "repeat_opponent_share": 0.558,
            "unique_opp_states": 2,
            "bridge_games": 4.78,
            "scf": 0.73,
            "games_last_180_days": 27,
            "days_since_last": 9,
            "powerscore_adj": 0.935,
            "powerscore_ml": 0.975,
        }
    )
    assert _positive_ml_evidence_scale(row) >= 0.75


def test_positive_ml_evidence_scale_keeps_non_elite_repetitive_profile_partial():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 34,
            "same_age_unique_opponents": 21,
            "same_age_top100_opp_count": 5,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 11,
            "same_age_top500_non_loss_opp_count": 8,
            "same_age_top1000_non_loss_opp_count": 10,
            "same_age_avg_opp_power_adj": 0.699,
            "same_age_quality_opp_power_adj": 0.699,
            "repeat_opponent_share": 0.558,
            "unique_opp_states": 2,
            "bridge_games": 4.78,
            "scf": 0.73,
            "games_last_180_days": 27,
            "days_since_last": 9,
            "powerscore_adj": 0.935,
            "powerscore_ml": 0.975,
        }
    )
    assert _positive_ml_evidence_scale(row) == 0.25


def test_publication_cap_rank_hits_weak_u12_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 7,
            "same_age_avg_opp_power_adj": 0.59,
            "repeat_opponent_share": 0.61,
            "unique_opp_states": 4,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_hits_thin_single_top100_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 1,
            "same_age_top500_opp_count": 2,
            "same_age_avg_opp_power_adj": 0.57,
            "repeat_opponent_share": 0.30,
            "unique_opp_states": 6,
        }
    )
    assert _publication_cap_rank(row) == 800


def test_publication_cap_rank_soft_caps_connectivity_constrained_team():
    row = pd.Series(
        {
            "age_num": 16,
            "same_age_top100_opp_count": 5,
            "same_age_top500_opp_count": 8,
            "same_age_avg_opp_power_adj": 0.54,
            "repeat_opponent_share": 0.36,
            "unique_opp_states": 1,
        }
    )
    assert _publication_cap_rank(row) == 250


def test_publication_cap_rank_hits_severe_connectivity_team():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 3,
            "same_age_top500_opp_count": 3,
            "same_age_avg_opp_power_adj": 0.51,
            "repeat_opponent_share": 0.55,
            "unique_opp_states": 2,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_releases_elite_repetitive_quality_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 34,
            "same_age_unique_opponents": 21,
            "same_age_top100_opp_count": 5,
            "same_age_top100_non_loss_opp_count": 6,
            "same_age_top500_opp_count": 11,
            "same_age_top500_non_loss_opp_count": 12,
            "same_age_top1000_non_loss_opp_count": 14,
            "same_age_avg_opp_power_adj": 0.699,
            "same_age_quality_opp_power_adj": 0.699,
            "repeat_opponent_share": 0.558,
            "unique_opp_states": 2,
            "bridge_games": 4.78,
            "scf": 0.73,
            "games_last_180_days": 27,
            "days_since_last": 9,
            "powerscore_adj": 0.935,
            "powerscore_ml": 0.975,
        }
    )
    assert _publication_cap_rank(row) is None


def test_same_age_publish_penalty_relieves_proven_repetitive_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 34,
            "same_age_unique_opponents": 21,
            "same_age_top100_opp_count": 5,
            "same_age_top100_non_loss_opp_count": 6,
            "same_age_top500_opp_count": 11,
            "same_age_top500_non_loss_opp_count": 12,
            "same_age_top1000_non_loss_opp_count": 14,
            "same_age_avg_opp_power_adj": 0.699,
            "same_age_quality_opp_power_adj": 0.699,
            "repeat_opponent_share": 0.558,
            "unique_opp_states": 2,
            "bridge_games": 4.78,
            "scf": 0.73,
            "games_last_180_days": 27,
            "days_since_last": 9,
            "powerscore_adj": 0.935,
            "powerscore_ml": 0.975,
        }
    )
    assert _same_age_publish_penalty(row) < 0.01


def test_publication_cap_rank_hits_severe_empty_schedule_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 0,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.47,
            "repeat_opponent_share": 0.13,
            "unique_opp_states": 3,
        }
    )
    assert _publication_cap_rank(row) == 2000


def test_publication_cap_rank_hits_thin_schedule_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 1,
            "same_age_avg_opp_power_adj": 0.49,
            "repeat_opponent_share": 0.33,
            "unique_opp_states": 5,
            "scf": 1.0,
        }
    )
    assert _publication_cap_rank(row) == 1000


def test_publication_cap_rank_hits_mid_thin_quality_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_top500_non_loss_opp_count": 1,
            "same_age_top1000_non_loss_opp_count": 3,
            "same_age_avg_opp_power_adj": 0.553,
            "repeat_opponent_share": 0.43,
            "unique_opp_states": 4,
            "scf": 0.70,
        }
    )
    assert _publication_cap_rank(row) == 1000


def test_publication_cap_rank_hits_regional_thin_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 2,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 2,
            "same_age_avg_opp_power_adj": 0.548,
            "repeat_opponent_share": 0.13,
            "unique_opp_states": 3,
            "scf": 0.80,
        }
    )
    assert _publication_cap_rank(row) == 800


def test_publication_cap_rank_hits_regional_thin_escalator_bucket():
    row = pd.Series(
        {
            "age_num": 14,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 3,
            "same_age_top1000_non_loss_opp_count": 3,
            "same_age_avg_opp_power_adj": 0.645,
            "repeat_opponent_share": 0.15,
            "unique_opp_states": 1,
            "scf": 0.80,
        }
    )
    assert _publication_cap_rank(row) == 1800


def test_publication_cap_rank_hits_severe_local_loop_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.499,
            "repeat_opponent_share": 0.647,
            "unique_opp_states": 1,
            "scf": 0.40,
            "play_up_game_share": 0.0,
            "play_up_top500_non_loss_opp_count": 0,
            "play_up_top1000_non_loss_opp_count": 0,
            "play_up_avg_opp_power_adj": None,
        }
    )
    assert _publication_cap_rank(row) == 2000


def test_publication_cap_rank_thin_isolated_team_hits_severe_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 2,
            "same_age_top500_non_loss_opp_count": 1,
            "same_age_top1000_non_loss_opp_count": 1,
            "same_age_avg_opp_power_adj": 0.46,
            "repeat_opponent_share": 0.21,
            "unique_opp_states": 2,
            "scf": 0.50,
        }
    )
    assert _publication_cap_rank(row) == 2000


def test_publication_cap_rank_hits_one_top100_thin_bucket():
    row = pd.Series(
        {
            "age_num": 14,
            "same_age_top100_opp_count": 1,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.487,
            "repeat_opponent_share": 0.07,
            "unique_opp_states": 5,
            "scf": 0.80,
        }
    )
    assert _publication_cap_rank(row) == 800


def test_publication_cap_rank_hits_one_top100_thin_escalator_bucket():
    row = pd.Series(
        {
            "age_num": 14,
            "same_age_top100_opp_count": 1,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.487,
            "repeat_opponent_share": 0.07,
            "unique_opp_states": 2,
            "scf": 0.80,
        }
    )
    assert _publication_cap_rank(row) == 1800


def test_publication_cap_rank_hits_weak_quality_results_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 1,
            "same_age_top100_non_loss_opp_count": 0,
            "same_age_top500_opp_count": 5,
            "same_age_top500_non_loss_opp_count": 1,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.627,
            "repeat_opponent_share": 0.33,
            "unique_opp_states": 6,
        }
    )
    assert _publication_cap_rank(row) == 1500


def test_publication_cap_rank_hits_zero_top100_weak_results_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 18,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 1,
            "same_age_top1000_non_loss_opp_count": 1,
            "same_age_avg_opp_power_adj": 0.539,
            "repeat_opponent_share": 0.12,
            "unique_opp_states": 5,
            "scf": 0.82,
        }
    )
    assert _publication_cap_rank(row) == 1500


def test_publication_cap_rank_escalates_zero_top100_weak_results_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 16,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_top500_non_loss_opp_count": 1,
            "same_age_top1000_non_loss_opp_count": 1,
            "same_age_avg_opp_power_adj": 0.533,
            "repeat_opponent_share": 0.19,
            "unique_opp_states": 4,
            "scf": 0.78,
        }
    )
    assert _publication_cap_rank(row) == 1800


def test_publication_cap_rank_skips_weak_quality_results_bucket_when_supported():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 1,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 5,
            "same_age_top500_non_loss_opp_count": 1,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.627,
            "repeat_opponent_share": 0.33,
            "unique_opp_states": 6,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_skips_multi_top100_team_with_depth():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 2,
            "same_age_top500_opp_count": 7,
            "same_age_avg_opp_power_adj": 0.55,
            "repeat_opponent_share": 0.13,
            "unique_opp_states": 8,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_releases_strong_broad_low_raw_avg_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 31,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 2,
            "same_age_top500_opp_count": 9,
            "same_age_top500_non_loss_opp_count": 6,
            "same_age_top1000_non_loss_opp_count": 8,
            "same_age_avg_opp_power_adj": 0.572,
            "same_age_quality_opp_power_adj": 0.668,
            "repeat_opponent_share": 0.275,
            "unique_opp_states": 10,
            "games_last_180_days": 10,
            "days_since_last": 3,
        }
    )
    assert _publication_cap_rank(row) is None


def test_publication_cap_rank_releases_strong_broad_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 2,
            "same_age_top500_opp_count": 9,
            "same_age_top500_non_loss_opp_count": 6,
            "same_age_top1000_non_loss_opp_count": 8,
            "same_age_avg_opp_power_adj": 0.658,
            "repeat_opponent_share": 0.10,
            "unique_opp_states": 10,
        }
    )
    assert _publication_cap_rank(row) is None


def test_publication_cap_rank_soft_caps_strong_but_mixed_field_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 2,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 8,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.635,
            "same_age_quality_opp_power_adj": 0.650,
            "repeat_opponent_share": 0.133,
            "unique_opp_states": 6,
        }
    )
    assert _publication_cap_rank(row) == 250


def test_publication_cap_rank_relieves_recent_high_raw_zero_top100_bridge_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 36,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_avg_opp_power_adj": 0.576,
            "same_age_quality_opp_power_adj": 0.622,
            "repeat_opponent_share": 0.50,
            "unique_opp_states": 5,
            "games_last_180_days": 25,
            "days_since_last": 3,
            "powerscore_adj": 0.749,
            "powerscore_ml": 0.788,
            "scf": 0.82,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_relieves_volume_bridge_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 34,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.576,
            "same_age_quality_opp_power_adj": 0.588,
            "repeat_opponent_share": 0.50,
            "unique_opp_states": 4,
            "games_last_180_days": 25,
            "days_since_last": 3,
            "powerscore_adj": 0.749,
            "powerscore_ml": 0.788,
            "scf": 0.70,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_relieves_results_volume_bridge_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_games": 31,
            "same_age_unique_opponents": 22,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.590,
            "same_age_quality_opp_power_adj": 0.584,
            "repeat_opponent_share": 0.39,
            "unique_opp_states": 2,
            "games_last_180_days": 24,
            "days_since_last": 3,
            "powerscore_adj": 0.749,
            "powerscore_ml": 0.788,
            "scf": 0.46,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_caps_hard_recent_low_volume_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 2,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 11,
            "same_age_top500_non_loss_opp_count": 5,
            "same_age_top1000_non_loss_opp_count": 8,
            "same_age_avg_opp_power_adj": 0.669,
            "same_age_quality_opp_power_adj": 0.686,
            "repeat_opponent_share": 0.17,
            "unique_opp_states": 6,
            "games_last_180_days": 5,
            "days_since_last": 4,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_caps_stale_elite_profile():
    row = pd.Series(
        {
            "age_num": 13,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 2,
            "same_age_top500_opp_count": 6,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.721,
            "same_age_quality_opp_power_adj": 0.724,
            "repeat_opponent_share": 0.10,
            "unique_opp_states": 7,
            "games_last_180_days": 4,
            "days_since_last": 101,
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_softens_for_supported_play_up_team():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.49,
            "repeat_opponent_share": 0.52,
            "unique_opp_states": 1,
            "play_up_game_share": 0.83,
            "play_up_top500_non_loss_opp_count": 2,
            "play_up_top1000_non_loss_opp_count": 4,
            "play_up_avg_opp_power_adj": 0.60,
        }
    )
    assert _publication_cap_rank(row) == 250


def test_publication_cap_rank_releases_alt_strong_broad_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 31,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 8,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.571,
            "same_age_quality_opp_power_adj": 0.618,
            "repeat_opponent_share": 0.28,
            "unique_opp_states": 8,
            "games_last_180_days": 10,
            "days_since_last": 3,
        }
    )
    assert _publication_cap_rank(row) is None


def test_publication_cap_rank_releases_broad_exposure_strong_sheet_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 0,
            "same_age_top500_opp_count": 7,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.598,
            "same_age_quality_opp_power_adj": 0.580,
            "repeat_opponent_share": 0.154,
            "unique_opp_states": 6,
            "games_last_180_days": 16,
            "days_since_last": 5,
        }
    )
    assert _publication_cap_rank(row) is None


def test_publication_cap_rank_soft_caps_low_connectivity_weak_field_profile():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_unique_opponents": 20,
            "same_age_top100_opp_count": 1,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 3,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.510,
            "same_age_quality_opp_power_adj": 0.521,
            "repeat_opponent_share": 0.095,
            "unique_opp_states": 2,
            "games_last_180_days": 14,
            "days_since_last": 4,
        }
    )
    assert _publication_cap_rank(row) == 250


def test_play_up_bonus_is_bounded_and_requires_quality():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "repeat_opponent_share": 0.35,
            "unique_opp_states": 1,
            "play_up_game_share": 0.90,
            "play_up_top500_non_loss_opp_count": 4,
            "play_up_top1000_non_loss_opp_count": 6,
            "play_up_avg_opp_power_adj": 0.63,
        }
    )
    assert _play_up_bonus(row) == 0.06


def test_same_age_publish_penalty_hits_weak_field_multi_top100_profile():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_unique_opponents": 30,
            "same_age_top100_opp_count": 3,
            "same_age_top500_opp_count": 5,
            "same_age_avg_opp_power_adj": 0.496,
            "repeat_opponent_share": 0.18,
            "unique_opp_states": 8,
            "games_last_180_days": 10,
            "days_since_last": 3,
        }
    )
    assert _same_age_publish_penalty(row) > 0.02


def test_same_age_publish_penalty_hits_stale_elite_profile():
    row = pd.Series(
        {
            "age_num": 13,
            "same_age_unique_opponents": 12,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 2,
            "same_age_top500_opp_count": 6,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.721,
            "same_age_quality_opp_power_adj": 0.724,
            "repeat_opponent_share": 0.10,
            "unique_opp_states": 7,
            "games_last_180_days": 4,
            "days_since_last": 101,
        }
    )
    assert _same_age_publish_penalty(row) > 0.015


def test_same_age_publish_penalty_spares_strong_broad_quality_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 31,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 2,
            "same_age_top500_opp_count": 9,
            "same_age_top500_non_loss_opp_count": 6,
            "same_age_top1000_non_loss_opp_count": 8,
            "same_age_avg_opp_power_adj": 0.572,
            "same_age_quality_opp_power_adj": 0.668,
            "repeat_opponent_share": 0.275,
            "unique_opp_states": 10,
            "games_last_180_days": 10,
            "days_since_last": 3,
        }
    )
    assert _same_age_publish_penalty(row) < 0.015


def test_same_age_publish_penalty_spares_alt_strong_broad_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 31,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 8,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.571,
            "same_age_quality_opp_power_adj": 0.618,
            "repeat_opponent_share": 0.28,
            "unique_opp_states": 8,
            "games_last_180_days": 10,
            "days_since_last": 3,
        }
    )
    assert _same_age_publish_penalty(row) < 0.02


def test_same_age_publish_penalty_spares_broad_exposure_strong_sheet_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 0,
            "same_age_top500_opp_count": 7,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.598,
            "same_age_quality_opp_power_adj": 0.580,
            "repeat_opponent_share": 0.154,
            "unique_opp_states": 6,
            "games_last_180_days": 16,
            "days_since_last": 5,
        }
    )
    assert _same_age_publish_penalty(row) < 0.02


def test_same_age_publish_penalty_hits_low_connectivity_weak_field_profile():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_unique_opponents": 20,
            "same_age_top100_opp_count": 1,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 3,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.510,
            "same_age_quality_opp_power_adj": 0.521,
            "repeat_opponent_share": 0.095,
            "unique_opp_states": 2,
            "games_last_180_days": 14,
            "days_since_last": 4,
        }
    )
    assert _same_age_publish_penalty(row) > 0.035


def test_same_age_raw_shrink_hits_weak_field_high_exposure_profile():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_unique_opponents": 30,
            "same_age_top100_opp_count": 3,
            "same_age_top500_opp_count": 5,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.495,
            "same_age_quality_opp_power_adj": 0.515,
            "repeat_opponent_share": 0.18,
            "unique_opp_states": 8,
            "games_last_180_days": 9,
            "days_since_last": 3,
        }
    )
    assert _same_age_raw_shrink(row) > 0.015


def test_same_age_raw_shrink_spares_broad_exposure_strong_sheet_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 23,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 0,
            "same_age_top500_opp_count": 7,
            "same_age_top500_non_loss_opp_count": 2,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.598,
            "same_age_quality_opp_power_adj": 0.580,
            "repeat_opponent_share": 0.154,
            "unique_opp_states": 6,
            "games_last_180_days": 16,
            "days_since_last": 5,
        }
    )
    assert _same_age_raw_shrink(row) == 0.0


def test_same_age_raw_shrink_hits_low_connectivity_weak_field_profile():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_unique_opponents": 20,
            "same_age_top100_opp_count": 1,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 3,
            "same_age_top500_non_loss_opp_count": 3,
            "same_age_top1000_non_loss_opp_count": 4,
            "same_age_avg_opp_power_adj": 0.510,
            "same_age_quality_opp_power_adj": 0.521,
            "repeat_opponent_share": 0.095,
            "unique_opp_states": 2,
            "games_last_180_days": 14,
            "days_since_last": 4,
        }
    )
    assert _same_age_raw_shrink(row) > 0.02


def test_same_age_raw_shrink_spares_alt_strong_broad_profile():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_unique_opponents": 31,
            "same_age_top100_opp_count": 4,
            "same_age_top100_non_loss_opp_count": 1,
            "same_age_top500_opp_count": 8,
            "same_age_top500_non_loss_opp_count": 4,
            "same_age_top1000_non_loss_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.571,
            "same_age_quality_opp_power_adj": 0.618,
            "repeat_opponent_share": 0.28,
            "unique_opp_states": 8,
            "games_last_180_days": 10,
            "days_since_last": 3,
        }
    )
    assert _same_age_raw_shrink(row) == 0.0


def test_apply_publication_cap_band_preserves_relative_order():
    base_scores = pd.Series([0.7745, 0.8595, 0.7698], index=[10, 20, 30], dtype=float)
    teams_age = pd.DataFrame(
        {
            "team_id": ["5a", "69", "ff"],
            "age_num": [12, 12, 12],
            "publication_cap_rank": [400, 400, 400],
            "publication_cap_score": [0.73320145, 0.73320145, 0.73320145],
        },
        index=[10, 20, 30],
    )

    adjusted = _apply_publication_cap_band(base_scores, teams_age)

    assert adjusted.loc[20] > adjusted.loc[10] > adjusted.loc[30]
    assert adjusted.nunique() == 3
    assert (adjusted < 0.73320145).all()


def test_compute_publication_cap_scores_uses_pre_cap_base_scale():
    teams_age = pd.DataFrame(
        {
            "team_id": ["A", "B", "C"],
            "status": ["Active", "Active", "Active"],
            "publication_cap_rank": [2, 2, pd.NA],
            "powerscore_adj": [0.95, 0.40, 0.20],
        },
        index=[1, 2, 3],
    )
    pre_cap_base = pd.Series([0.40, 0.70, 0.20], index=[1, 2, 3], dtype=float)

    cap_scores = _compute_publication_cap_scores(teams_age, pre_cap_base)

    assert round(float(cap_scores.loc[1]), 6) == round(0.40 - 1e-6, 6)
    assert round(float(cap_scores.loc[2]), 6) == round(0.40 - 1e-6, 6)
    assert pd.isna(cap_scores.loc[3])


def test_apply_publication_cap_band_leaves_uncapped_and_below_cap_scores_alone():
    base_scores = pd.Series([0.7800, 0.7100, 0.6900], index=[1, 2, 3], dtype=float)
    teams_age = pd.DataFrame(
        {
            "team_id": ["A", "B", "C"],
            "age_num": [12, 12, 12],
            "publication_cap_rank": [400, 400, pd.NA],
            "publication_cap_score": [0.73320145, 0.73320145, pd.NA],
        },
        index=[1, 2, 3],
    )

    adjusted = _apply_publication_cap_band(base_scores, teams_age)

    assert adjusted.loc[1] < 0.73320145
    assert adjusted.loc[2] == base_scores.loc[2]
    assert adjusted.loc[3] == base_scores.loc[3]


def test_validate_publication_caps_raises_when_score_finishes_above_cap():
    teams_age = pd.DataFrame(
        {
            "team_id": ["A", "B"],
            "team_name": ["Alpha", "Beta"],
            "publication_cap_score": [0.70, pd.NA],
        },
        index=[1, 2],
    )
    capped_scores = pd.Series([0.71, 0.65], index=[1, 2], dtype=float)

    try:
        _validate_publication_caps(teams_age, capped_scores)
    except ValueError as exc:
        assert "Alpha(A)" in str(exc)
    else:
        raise AssertionError("Expected cap validation to fail")


def test_collect_top_tier_weak_uncapped_flags_surf_type_profile():
    teams_age = pd.DataFrame(
        {
            "team_id": ["surf", "elite", "capped"],
            "team_name": ["Surf", "Elite", "Capped"],
            "age_num": [13, 13, 13],
            "publication_cap_rank": [pd.NA, pd.NA, 400],
            "same_age_top100_opp_count": [0, 3, 0],
            "same_age_top500_opp_count": [2, 7, 1],
            "same_age_top500_non_loss_opp_count": [1, 6, 0],
            "same_age_avg_opp_power_adj": [0.514, 0.71, 0.49],
            "repeat_opponent_share": [0.22, 0.12, 0.40],
            "unique_opp_states": [3, 8, 2],
            "scf": [0.80, 1.00, 0.50],
        }
    )
    base_scores = pd.Series([0.90, 0.89, 0.88], index=teams_age.index, dtype=float)

    flagged = _collect_top_tier_weak_uncapped(teams_age, base_scores)

    assert flagged["team_id"].tolist() == ["surf"]

def test_publication_cap_rank_hits_quality_result_void_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 2,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.56,
            "repeat_opponent_share": 0.18,
            "unique_opp_states": 3,
            "scf": 0.72,
        }
    )
    assert _publication_cap_rank(row) == 1500


def test_publication_cap_rank_escalates_severe_quality_result_void_bucket():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 1,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": 0.47,
            "repeat_opponent_share": 0.12,
            "unique_opp_states": 3,
            "scf": 0.74,
        }
    )
    assert _publication_cap_rank(row) == 2000

