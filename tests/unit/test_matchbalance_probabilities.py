import math

import pandas as pd
import pytest

from scripts import backtest_tournament_cohort as cohort


def test_point_in_time_matchup_cost_preserves_zero_probabilities():
    prediction = cohort.TournamentMatchPrediction(
        predicted_winner="team_a",
        expected_score={"teamA": 4, "teamB": 0},
        expected_margin=4.0,
        win_probability_a=1.0,
        draw_probability=0.0,
        win_probability_b=0.0,
        blowout_3plus_probability=0.0,
        blowout_5plus_probability=0.0,
    )

    cost = cohort._point_in_time_matchup_cost(prediction)

    assert cost.blowout_3plus_probability == 0.0
    assert cost.blowout_5plus_probability == 0.0


def test_point_in_time_prediction_from_row_preserves_missing_probabilities():
    prediction = cohort._point_in_time_prediction_from_row(
        pd.Series({"predicted_outcome": "draw", "expected_goals_a": 1.0, "expected_goals_b": 1.0}),
        source="test",
    )

    assert prediction.win_probability_a is None
    assert prediction.draw_probability is None
    assert prediction.blowout_3plus_probability is None


@pytest.mark.parametrize(
    "field",
    [
        "win_probability_a",
        "draw_probability",
        "win_probability_b",
        "blowout_3plus_probability",
        "blowout_5plus_probability",
    ],
)
@pytest.mark.parametrize("bad_probability", [-0.01, 1.01, math.nan, math.inf, -math.inf])
def test_point_in_time_matchup_cost_rejects_invalid_probabilities(field, bad_probability):
    prediction = cohort.TournamentMatchPrediction(
        predicted_winner="team_a",
        expected_score={"teamA": 2, "teamB": 1},
        expected_margin=1.0,
        **{field: bad_probability},
    )

    with pytest.raises(ValueError, match=rf"{field} must be a finite probability"):
        cohort._point_in_time_matchup_cost(prediction)
