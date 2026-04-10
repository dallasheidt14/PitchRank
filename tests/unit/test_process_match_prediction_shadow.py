import pandas as pd

from scripts.process_match_prediction_shadow import (
    _build_shadow_payload,
    _winner_consistent_expected_margin,
    _winner_consistent_expected_score,
)


def test_winner_consistent_expected_score_breaks_team_a_rounding_ties():
    assert _winner_consistent_expected_score("team_a", 1.47, 0.95) == {
        "teamA": 2,
        "teamB": 1,
    }


def test_winner_consistent_expected_score_breaks_team_b_rounding_ties():
    assert _winner_consistent_expected_score("team_b", 1.54, 1.62) == {
        "teamA": 2,
        "teamB": 3,
    }


def test_winner_consistent_expected_score_forces_draw_when_requested():
    assert _winner_consistent_expected_score("draw", 1.8, 1.1) == {
        "teamA": 1,
        "teamB": 1,
    }


def test_winner_consistent_expected_margin_matches_predicted_outcome_sign():
    assert _winner_consistent_expected_margin("team_a", 1.47, 0.95) > 0.0
    assert _winner_consistent_expected_margin("team_b", 1.54, 1.62) < 0.0
    assert _winner_consistent_expected_margin("draw", 1.8, 1.1) == 0.0


def test_build_shadow_payload_uses_display_score_and_preserves_modal_score():
    row = pd.Series(
        {
            "predicted_outcome": "team_a",
            "prob_team_a_win": 0.47704715175775714,
            "prob_draw": 0.2954344812878684,
            "prob_team_b_win": 0.22751836695437444,
            "predicted_score_a": 1.0,
            "predicted_score_b": 1.0,
            "predicted_margin": 0.7082579731941223,
            "probability_strategy": "poisson_draw_gate",
            "blowout_3plus_probability": 0.26231986294467396,
            "blowout_5plus_probability": 0.09890575024836547,
            "predicted_blowout_3plus": 0,
            "predicted_blowout_5plus": 0,
            "stalemate_signal": 0.4963766155165165,
            "projected_total_goals": 1.2574358867852915,
            "expected_goals_a": 1.474945352180432,
            "expected_goals_b": 0.9507100470258216,
            "poisson_prob_team_a_win": 0.4781175029552596,
            "poisson_prob_draw": 0.2938536468904849,
            "poisson_prob_team_b_win": 0.22802885015425547,
            "draw_model_probability": 0.225744701128555,
        }
    )

    payload = _build_shadow_payload(
        row,
        model_version="pitm_test",
        calibrated=False,
    )

    assert payload["prediction"]["predictedWinner"] == "team_a"
    assert payload["prediction"]["expectedScore"] == {
        "teamA": 2,
        "teamB": 1,
    }
    assert payload["prediction"]["expectedMargin"] > 0.0
    assert payload["diagnostics"]["mostLikelyExactScore"] == {
        "teamA": 1,
        "teamB": 1,
    }
    assert payload["diagnostics"]["modelPredictedMargin"] == 0.7082579731941223
