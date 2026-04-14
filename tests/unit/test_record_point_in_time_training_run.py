import json
from pathlib import Path

from scripts.record_point_in_time_training_run import build_training_run_record


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_training_run_record_extracts_training_and_calibration_metrics(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "dataset_summary.json",
        {
            "games_seen": 1000,
            "games_used": 600,
            "examples_built": 1200,
            "unique_snapshot_dates_used": 24,
        },
    )
    _write_json(
        tmp_path / "training_metrics.json",
        {
            "requested_probability_strategy": "hybrid",
            "probability_strategy": "hybrid",
            "winner_accuracy": 0.61,
            "draw_recall": 0.12,
            "predicted_draw_rate": 0.1,
            "log_loss": 0.91,
            "margin_mae": 2.15,
            "exact_score_accuracy": 0.07,
        },
    )
    _write_json(
        tmp_path / "point_in_time_model_calibration_summary.json",
        {
            "method": "temperature",
            "draw_method": "none",
            "after_metrics": {
                "log_loss": 0.89,
                "draw_recall": 0.11,
                "brier_score": 0.52,
            },
        },
    )

    record = build_training_run_record(
        workflow_run_id=24414774665,
        workflow_run_attempt=1,
        git_sha="abcdef123456",
        model_dir=tmp_path,
        lookback_days=267,
        limit_value=None,
        test_ratio=0.2,
        min_examples=100,
        requested_probability_strategy="hybrid",
        calibration_enabled=True,
        calibration_method="temperature",
        draw_calibration_method="none",
    )

    assert record["model_version"] == "pitm_24414774665_hybrid"
    assert record["games_used"] == 600
    assert record["winner_accuracy"] == 0.61
    assert record["calibrated_log_loss"] == 0.89
    assert record["calibration_enabled"] is True
