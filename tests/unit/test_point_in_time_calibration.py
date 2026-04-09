from __future__ import annotations

import pandas as pd

from src.predictions.point_in_time_calibration import calibrate_evaluation_frame


def test_calibrate_evaluation_frame_writes_improved_artifacts(tmp_path):
    evaluation_frame = pd.DataFrame(
        [
            {
                "game_id": "g1",
                "game_date": "2026-04-01",
                "actual_outcome": "team_a",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.80,
                "prob_draw": 0.10,
                "prob_team_b_win": 0.10,
                "predicted_margin": 1.1,
                "actual_margin": 1,
            },
            {
                "game_id": "g2",
                "game_date": "2026-04-02",
                "actual_outcome": "draw",
                "predicted_outcome": "team_a",
                "prob_team_a_win": 0.60,
                "prob_draw": 0.20,
                "prob_team_b_win": 0.20,
                "predicted_margin": 0.6,
                "actual_margin": 0,
            },
            {
                "game_id": "g3",
                "game_date": "2026-04-03",
                "actual_outcome": "team_b",
                "predicted_outcome": "team_b",
                "prob_team_a_win": 0.15,
                "prob_draw": 0.15,
                "prob_team_b_win": 0.70,
                "predicted_margin": -1.0,
                "actual_margin": -1,
            },
        ]
    )

    result = calibrate_evaluation_frame(
        evaluation_frame=evaluation_frame,
        output_dir=str(tmp_path),
        method="temperature",
        prefix="calibration_test",
    )

    assert result.method == "temperature"
    assert tmp_path.joinpath("calibration_test.pkl").exists()
    assert tmp_path.joinpath("calibration_test.json").exists()
    assert tmp_path.joinpath("calibration_test_evaluation.csv").exists()
    assert result.before_metrics["games"] == 3
    assert result.after_metrics["games"] == 3
