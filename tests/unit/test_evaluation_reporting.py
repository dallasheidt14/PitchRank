from __future__ import annotations

import pandas as pd

from src.predictions.evaluation_reporting import (
    build_calibration_table,
    build_standardized_evaluation_frame,
    compute_evaluation_summary,
)


def test_compute_evaluation_summary_handles_three_way_probabilities():
    frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_a",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.72,
                "prob_draw": 0.14,
                "prob_team_b_win": 0.14,
                "predicted_margin": 1.2,
                "actual_margin": 1,
            },
            {
                "game_id": "g2",
                "game_date": "2026-04-02",
                "actual_outcome": "draw",
                "predicted_outcome": "draw",
                "prob_team_a_win": 0.31,
                "prob_draw": 0.42,
                "prob_team_b_win": 0.27,
                "predicted_margin": 0.0,
                "actual_margin": 0,
            },
        ]
    )

    summary = compute_evaluation_summary(frame)

    assert summary["games"] == 2
    assert summary["winner_accuracy"] == 1.0
    assert summary["draw_recall"] == 1.0
    assert summary["draw_precision"] == 1.0
    assert summary["log_loss"] is not None
    assert summary["brier_score"] is not None


def test_build_standardized_evaluation_frame_normalizes_missing_rows():
    frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_b",
                "prob_team_a_win": 0.0,
                "prob_draw": 0.0,
                "prob_team_b_win": 0.0,
                "predicted_margin": -0.5,
                "actual_margin": -1,
            }
        ]
    )

    standardized = build_standardized_evaluation_frame(frame)

    assert standardized.loc[0, "predicted_outcome"] in {"team_a", "draw", "team_b"}
    assert abs(
        standardized.loc[0, ["prob_team_a_win", "prob_draw", "prob_team_b_win"]].sum() - 1.0
    ) < 1e-9


def test_build_calibration_table_groups_probability_buckets():
    frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_a",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.68,
                "prob_draw": 0.12,
                "prob_team_b_win": 0.20,
                "predicted_margin": 0.8,
                "actual_margin": 1,
            },
            {
                "game_id": "g2",
                "game_date": "2026-04-02",
                "actual_outcome": "team_b",
                "predicted_outcome": "team_b",
                "prob_team_a_win": 0.18,
                "prob_draw": 0.14,
                "prob_team_b_win": 0.68,
                "predicted_margin": -0.8,
                "actual_margin": -1,
            },
        ]
    )

    calibration = build_calibration_table(frame)

    assert not calibration.empty
    assert "probability_bucket" in calibration.columns
