from __future__ import annotations

import pandas as pd

from src.rankings.calculator import (
    _apply_publication_cap_band,
    _compute_same_age_evidence_metrics,
    _positive_ml_evidence_scale,
    _publication_cap_rank,
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
    assert int(a["same_age_top500_non_loss_opp_count"]) == 2
    assert int(a["same_age_top1000_non_loss_opp_count"]) == 2


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
    assert _positive_ml_evidence_scale(row) == 0.0


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
    assert _positive_ml_evidence_scale(row) == 0.25


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
    assert _positive_ml_evidence_scale(row) == 0.0


def test_positive_ml_evidence_scale_full_release_requires_multi_top100_depth():
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
    assert _positive_ml_evidence_scale(row) == 1.0


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
    assert _publication_cap_rank(row) == 400


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
    assert _publication_cap_rank(row) == 1500


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
    assert _publication_cap_rank(row) is None


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
