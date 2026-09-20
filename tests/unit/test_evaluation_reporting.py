from __future__ import annotations

import pandas as pd
import pytest
from sklearn.metrics import log_loss

from src.predictions.evaluation_reporting import (
    build_calibration_table,
    build_margin_band_metrics,
    build_probability_calibration_table,
    build_standardized_evaluation_frame,
    compute_evaluation_summary,
)


def test_log_loss_matches_sklearn_at_zero_one_and_extreme_probabilities():
    probabilities = [[0, 0, 1], [1, 0, 0], [1e-16, 0.4, 0.6-1e-16], [0.2, 0.6, 0.2]]
    frame = pd.DataFrame(probabilities, columns=["prob_team_a_win", "prob_draw", "prob_team_b_win"])
    frame["actual_outcome"] = ["team_a", "team_a", "team_a", "draw"]
    assert compute_evaluation_summary(frame)["log_loss"] == pytest.approx(
        log_loss([0, 0, 0, 1], probabilities, labels=[0, 1, 2])
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
                "blowout_3plus_probability": 0.81,
                "blowout_4plus_probability": 0.63,
                "blowout_5plus_probability": 0.34,
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
                "blowout_3plus_probability": 0.08,
                "blowout_4plus_probability": 0.03,
                "blowout_5plus_probability": 0.02,
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
                "blowout_3plus_probability": 0.19,
                "blowout_4plus_probability": 0.10,
                "blowout_5plus_probability": 0.05,
            },
        ]
    )

    summary = compute_evaluation_summary(frame)
    margin_bands = build_margin_band_metrics(frame)

    assert summary["score_a_mae"] is not None
    assert summary["score_b_mae"] is not None
    assert summary["actual_average_abs_margin"] == pytest.approx(5 / 3)
    assert summary["predicted_average_abs_margin"] == pytest.approx(1.4)
    assert summary["total_goals_mae"] is not None
    assert summary["exact_score_accuracy"] == 1 / 3
    assert summary["score_within_one_goal_rate"] == 1.0
    assert summary["competitive_game_recall"] == 1.0
    assert summary["blowout_3plus_recall"] == 1.0
    assert summary["blowout_3plus_precision"] == 1.0
    assert summary["blowout_3plus_brier"] is not None
    assert summary["actual_blowout_4plus_rate"] == pytest.approx(1 / 3)
    assert summary["avg_blowout_4plus_probability"] is not None
    assert summary["blowout_5plus_brier"] is not None
    assert not margin_bands.empty
    assert set(margin_bands["band"]) == {
        "competitive_1plus",
        "blowout_3plus",
        "blowout_4plus",
        "blowout_5plus",
    }
    assert "avg_probability" in margin_bands.columns
    assert "brier" in margin_bands.columns


def test_blowout_metrics_use_explicit_probability_labels_when_present():
    frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_a",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.72,
                "prob_draw": 0.16,
                "prob_team_b_win": 0.12,
                "predicted_margin": 1.1,
                "actual_margin": 4,
                "blowout_3plus_probability": 0.77,
                "blowout_5plus_probability": 0.28,
                "predicted_blowout_3plus": 1,
                "predicted_blowout_5plus": 0,
            },
            {
                "game_id": "g2",
                "game_date": "2026-04-02",
                "actual_outcome": "team_b",
                "predicted_outcome": "team_b",
                "prob_team_a_win": 0.19,
                "prob_draw": 0.17,
                "prob_team_b_win": 0.64,
                "predicted_margin": -0.6,
                "actual_margin": -1,
                "blowout_3plus_probability": 0.18,
                "blowout_5plus_probability": 0.04,
                "predicted_blowout_3plus": 0,
                "predicted_blowout_5plus": 0,
            },
        ]
    )

    summary = compute_evaluation_summary(frame)
    margin_bands = build_margin_band_metrics(frame)

    assert summary["predicted_blowout_3plus_rate"] == 0.5
    assert summary["blowout_3plus_recall"] == 1.0
    assert summary["blowout_3plus_precision"] == 1.0
    blowout_row = margin_bands.loc[margin_bands["band"] == "blowout_3plus"].iloc[0]
    assert blowout_row["predicted_rate"] == 0.5
    assert blowout_row["precision"] == 1.0


def test_calibration_uses_the_probability_outcome_instead_of_draw_override():
    frame = pd.DataFrame([{
        "actual_outcome": "team_a", "predicted_outcome": "draw",
        "prob_team_a_win": 0.45, "prob_draw": 0.35, "prob_team_b_win": 0.2,
        "predicted_margin": 0.1, "actual_margin": 1,
    }])
    table = build_calibration_table(frame)
    assert table["games"].sum() == 1  # Three-way probabilities below 50% are included.
    assert table.iloc[0]["predicted_probability"] == 0.45
    assert table.iloc[0]["actual_accuracy"] == 1.0
    assert compute_evaluation_summary(frame)["winner_accuracy"] == 0.0


def test_four_goal_probability_metrics_use_only_rows_with_forecasts():
    frame = pd.DataFrame([
        {"actual_outcome": "team_a", "prob_team_a_win": 0.6, "prob_draw": 0.2, "prob_team_b_win": 0.2,
         "predicted_margin": 4.2, "actual_margin": 4, "blowout_4plus_probability": None,
         "predicted_blowout_4plus": None},
        {"actual_outcome": "draw", "prob_team_a_win": 0.2, "prob_draw": 0.6, "prob_team_b_win": 0.2,
         "predicted_margin": 0, "actual_margin": 0, "blowout_4plus_probability": 0,
         "predicted_blowout_4plus": None},
    ])
    summary = compute_evaluation_summary(frame)
    assert summary["blowout_4plus_probability_games"] == 1
    assert summary["actual_blowout_4plus_rate"] == 0.5
    assert summary["actual_blowout_4plus_rate_on_probability_rows"] == 0
    assert summary["avg_blowout_4plus_probability"] == 0
    assert summary["blowout_4plus_brier"] == 0
    assert summary["predicted_blowout_4plus_rate"] == 0.5
    calibration = build_probability_calibration_table(frame)
    risk = calibration[calibration["outcome"] == "blowout_4plus"]
    assert risk["games"].sum() == 1
    assert risk.iloc[0]["observed_rate"] == 0
    frame["blowout_4plus_probability"] = None
    assert compute_evaluation_summary(frame)["blowout_4plus_brier"] is None
