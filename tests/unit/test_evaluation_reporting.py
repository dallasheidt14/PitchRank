from __future__ import annotations

import pandas as pd

from src.predictions.evaluation_reporting import (
    build_calibration_table,
    build_margin_band_metrics,
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


def test_compute_evaluation_summary_normalizes_trainer_outcome_aliases():
    frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_a_win",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.61,
                "prob_draw": 0.20,
                "prob_team_b_win": 0.19,
                "predicted_margin": 0.7,
                "actual_margin": 1,
            },
            {
                "game_id": "g2",
                "game_date": "2026-04-02",
                "actual_outcome": "team_b_win",
                "predicted_outcome": "team_b",
                "prob_team_a_win": 0.21,
                "prob_draw": 0.18,
                "prob_team_b_win": 0.61,
                "predicted_margin": -0.8,
                "actual_margin": -1,
            },
        ]
    )

    summary = compute_evaluation_summary(frame)

    assert summary["games"] == 2
    assert summary["winner_accuracy"] == 1.0


def test_compute_evaluation_summary_tracks_score_and_blowout_metrics():
    frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_a",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.74,
                "prob_draw": 0.12,
                "prob_team_b_win": 0.14,
                "predicted_margin": 3.2,
                "actual_margin": 4,
                "predicted_score_a": 4.1,
                "predicted_score_b": 1.0,
                "actual_score_a": 4,
                "actual_score_b": 0,
            },
            {
                "game_id": "g2",
                "game_date": "2026-04-02",
                "actual_outcome": "draw",
                "predicted_outcome": "draw",
                "prob_team_a_win": 0.28,
                "prob_draw": 0.46,
                "prob_team_b_win": 0.26,
                "predicted_margin": 0.2,
                "actual_margin": 0,
                "predicted_score_a": 1.2,
                "predicted_score_b": 1.0,
                "actual_score_a": 1,
                "actual_score_b": 1,
            },
            {
                "game_id": "g3",
                "game_date": "2026-04-03",
                "actual_outcome": "team_b",
                "predicted_outcome": "team_b",
                "prob_team_a_win": 0.18,
                "prob_draw": 0.19,
                "prob_team_b_win": 0.63,
                "predicted_margin": -0.8,
                "actual_margin": -1,
                "predicted_score_a": 1.0,
                "predicted_score_b": 2.0,
                "actual_score_a": 0,
                "actual_score_b": 2,
            },
        ]
    )

    summary = compute_evaluation_summary(frame)
    margin_bands = build_margin_band_metrics(frame)

    assert summary["score_a_mae"] is not None
    assert summary["score_b_mae"] is not None
    assert summary["total_goals_mae"] is not None
    assert summary["exact_score_accuracy"] == 1 / 3
    assert summary["score_within_one_goal_rate"] == 1.0
    assert summary["competitive_game_recall"] == 1.0
    assert summary["blowout_3plus_recall"] == 1.0
    assert summary["blowout_3plus_precision"] == 1.0
    assert not margin_bands.empty
    assert set(margin_bands["band"]) == {"competitive_1plus", "blowout_3plus", "blowout_5plus"}
