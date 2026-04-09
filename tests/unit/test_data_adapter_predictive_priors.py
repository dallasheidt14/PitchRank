from __future__ import annotations

import pandas as pd

from src.rankings.data_adapter import v53e_to_rankings_full_format


def test_v53e_to_rankings_full_format_derives_predictive_priors_when_missing():
    teams_df = pd.DataFrame(
        [
            {
                "team_id": "team-1",
                "age": "13",
                "gender": "Male",
                "status": "Active",
                "powerscore_adj": 0.72,
                "power_score_final": 0.72,
                "sos_norm": 0.61,
                "off_norm": 0.68,
                "def_norm": 0.62,
                "wins": 9,
                "losses": 2,
                "draws": 2,
                "games_played": 13,
                "glicko_rating": 1592.0,
                "glicko_rd": 62.0,
                "same_age_games": 10,
                "same_age_game_share": 0.77,
                "same_age_unique_opponents": 6,
                "same_age_top100_opp_count": 2,
                "same_age_top500_opp_count": 5,
                "same_age_avg_opp_power_adj": 0.7,
                "repeat_opponent_share": 0.1,
                "positive_ml_evidence_scale": 0.88,
            }
        ]
    )

    result = v53e_to_rankings_full_format(teams_df)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["exp_margin"] is not None
    assert row["exp_margin"] > 0
    assert row["exp_win_rate"] is not None
    assert 0.5 < row["exp_win_rate"] < 1.0
    assert row["exp_goals_for"] is not None
    assert row["exp_goals_against"] is not None
