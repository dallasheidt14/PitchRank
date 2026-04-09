"""Calibrate point-in-time match model probabilities from an evaluation CSV."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.predictions.evaluation_reporting import write_evaluation_bundle
from src.predictions.point_in_time_calibration import calibrate_evaluation_frame
from src.predictions.point_in_time_match_model import PointInTimeMatchModel


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate point-in-time model probabilities")
    parser.add_argument(
        "--evaluation-csv",
        required=True,
        help="CSV produced by train_point_in_time_match_model.py (point_in_time_model_evaluation.csv)",
    )
    parser.add_argument(
        "--output-dir",
        default="models/point_in_time_match_predictor",
        help="Directory to write calibration artifacts and reports",
    )
    parser.add_argument(
        "--method",
        choices=["temperature", "isotonic"],
        default="temperature",
        help="Calibration method to use",
    )
    parser.add_argument(
        "--draw-method",
        choices=["none", "isotonic"],
        default="isotonic",
        help="Optional draw-specific calibration method to apply after overall calibration",
    )
    parser.add_argument(
        "--prefix",
        default="point_in_time_model_calibration",
        help="Artifact/report filename prefix",
    )
    parser.add_argument(
        "--model-artifact",
        default=None,
        help="Optional trained model pickle used to reapply draw/blowout decision policy",
    )
    args = parser.parse_args()

    evaluation_frame = pd.read_csv(args.evaluation_csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model_artifact_path = Path(args.model_artifact) if args.model_artifact else output_dir / "point_in_time_match_model.pkl"
    prediction_postprocessor = None
    if model_artifact_path.exists():
        model = PointInTimeMatchModel.load(str(model_artifact_path))
        prediction_postprocessor = model.relabel_evaluation_frame

    result = calibrate_evaluation_frame(
        evaluation_frame=evaluation_frame,
        output_dir=str(output_dir),
        method=args.method,
        draw_method=args.draw_method,
        prefix=args.prefix,
        prediction_postprocessor=prediction_postprocessor,
    )

    calibrated_frame_path = output_dir / f"{args.prefix}_evaluation.csv"
    if calibrated_frame_path.exists():
        calibrated_frame = pd.read_csv(calibrated_frame_path)
        write_evaluation_bundle(calibrated_frame, output_dir, prefix=f"{args.prefix}_report")

    summary_path = output_dir / f"{args.prefix}_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "method": result.method,
                "draw_method": result.draw_method,
                "before_metrics": result.before_metrics,
                "after_metrics": result.after_metrics,
                "artifact_path": result.artifact_path,
                "metadata_path": result.metadata_path,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Calibration complete. Summary written to {summary_path}")


if __name__ == "__main__":
    main()
