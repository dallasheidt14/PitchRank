from __future__ import annotations

import pandas as pd

from src.rankings.calculator import (
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
    assert float(a["repeat_opponent_share"]) == 0.5


def test_positive_ml_evidence_scale_blocks_weak_u12_case():
    row = pd.Series(
        {
            "age_num": 12,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 7,
            "same_age_avg_opp_power_adj": 0.59,
            "repeat_opponent_share": 0.61,
        }
    )
    assert _positive_ml_evidence_scale(row) == 0.0


def test_positive_ml_evidence_scale_allows_partial_u15_case():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 0,
            "same_age_top500_opp_count": 5,
            "same_age_avg_opp_power_adj": 0.70,
            "repeat_opponent_share": 0.18,
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
        }
    )
    assert _publication_cap_rank(row) == 400


def test_publication_cap_rank_skips_team_with_same_age_top100():
    row = pd.Series(
        {
            "age_num": 15,
            "same_age_top100_opp_count": 1,
            "same_age_top500_opp_count": 6,
            "same_age_avg_opp_power_adj": 0.58,
            "repeat_opponent_share": 0.12,
        }
    )
    assert _publication_cap_rank(row) is None
