"""Calibration utilities for point-in-time match model probabilities."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss

from src.predictions.evaluation_reporting import (
    OUTCOME_ORDER,
    PROBABILITY_COLUMNS,
    build_standardized_evaluation_frame,
    compute_evaluation_summary,
)

CalibrationMethod = Literal["temperature", "isotonic"]


def _normalize_probabilities(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-9, 1.0)
    row_sums = clipped.sum(axis=1, keepdims=True)
    return np.divide(
        clipped,
        row_sums,
        out=np.full_like(clipped, 1.0 / clipped.shape[1]),
        where=row_sums > 0,
    )


def _brier_score(probabilities: np.ndarray, labels: np.ndarray) -> float:
    one_hot = np.zeros_like(probabilities)
    for row_index, class_index in enumerate(labels):
        one_hot[row_index, class_index] = 1.0
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


@dataclass
class CalibrationResult:
    method: CalibrationMethod
    before_metrics: dict[str, object]
    after_metrics: dict[str, object]
    artifact_path: str
    metadata_path: str


class PointInTimeProbabilityCalibrator:
    def __init__(self, method: CalibrationMethod = "temperature"):
        self.method = method
        self.temperature = 1.0
        self.isotonic_models: list[IsotonicRegression] = []

    def _labels_from_frame(self, frame: pd.DataFrame) -> np.ndarray:
        standardized = build_standardized_evaluation_frame(frame)
        return standardized["actual_outcome"].map(OUTCOME_ORDER.index).to_numpy(dtype=int)

    def _probabilities_from_frame(self, frame: pd.DataFrame) -> np.ndarray:
        standardized = build_standardized_evaluation_frame(frame)
        return standardized[list(PROBABILITY_COLUMNS.values())].to_numpy(dtype=float)

    def _apply_temperature(self, probabilities: np.ndarray, temperature: float) -> np.ndarray:
        logits = np.log(np.clip(probabilities, 1e-9, 1.0))
        scaled = logits / max(temperature, 1e-6)
        scaled -= scaled.max(axis=1, keepdims=True)
        exp_values = np.exp(scaled)
        return _normalize_probabilities(exp_values)

    def _fit_temperature(self, probabilities: np.ndarray, labels: np.ndarray) -> None:
        best_temperature = 1.0
        best_loss = float("inf")

        for temperature in np.linspace(0.6, 2.8, 111):
            calibrated = self._apply_temperature(probabilities, float(temperature))
            candidate_loss = float(log_loss(labels, calibrated, labels=[0, 1, 2]))
            if candidate_loss < best_loss:
                best_loss = candidate_loss
                best_temperature = float(temperature)

        self.temperature = best_temperature

    def _fit_isotonic(self, probabilities: np.ndarray, labels: np.ndarray) -> None:
        self.isotonic_models = []
        for class_index in range(len(OUTCOME_ORDER)):
            model = IsotonicRegression(out_of_bounds="clip")
            model.fit(probabilities[:, class_index], (labels == class_index).astype(float))
            self.isotonic_models.append(model)

    def fit(self, evaluation_frame: pd.DataFrame) -> None:
        probabilities = self._probabilities_from_frame(evaluation_frame)
        labels = self._labels_from_frame(evaluation_frame)

        if self.method == "temperature":
            self._fit_temperature(probabilities, labels)
            return
        if self.method == "isotonic":
            self._fit_isotonic(probabilities, labels)
            return
        raise ValueError(f"Unsupported calibration method: {self.method}")

    def transform_probabilities(self, probabilities: np.ndarray) -> np.ndarray:
        probabilities = _normalize_probabilities(probabilities)
        if self.method == "temperature":
            return self._apply_temperature(probabilities, self.temperature)
        if self.method == "isotonic":
            if not self.isotonic_models:
                raise ValueError("Isotonic calibrator has not been fit")
            calibrated_columns = [
                self.isotonic_models[class_index].predict(probabilities[:, class_index])
                for class_index in range(len(OUTCOME_ORDER))
            ]
            return _normalize_probabilities(np.column_stack(calibrated_columns))
        raise ValueError(f"Unsupported calibration method: {self.method}")

    def transform_frame(self, evaluation_frame: pd.DataFrame) -> pd.DataFrame:
        standardized = build_standardized_evaluation_frame(evaluation_frame)
        probabilities = standardized[list(PROBABILITY_COLUMNS.values())].to_numpy(dtype=float)
        calibrated = self.transform_probabilities(probabilities)
        calibrated_frame = standardized.copy()
        calibrated_frame["prob_team_a_win"] = calibrated[:, 0]
        calibrated_frame["prob_draw"] = calibrated[:, 1]
        calibrated_frame["prob_team_b_win"] = calibrated[:, 2]
        calibrated_frame["predicted_outcome"] = [
            OUTCOME_ORDER[class_index] for class_index in np.argmax(calibrated, axis=1)
        ]
        return build_standardized_evaluation_frame(calibrated_frame)

    def metrics_for_frame(self, evaluation_frame: pd.DataFrame) -> dict[str, object]:
        return compute_evaluation_summary(evaluation_frame)

    def save(self, output_dir: str, prefix: str = "point_in_time_model_calibration") -> tuple[str, str]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        artifact_path = output_path / f"{prefix}.pkl"
        metadata_path = output_path / f"{prefix}.json"

        with open(artifact_path, "wb") as handle:
            pickle.dump(
                {
                    "method": self.method,
                    "temperature": self.temperature,
                    "isotonic_models": self.isotonic_models,
                },
                handle,
            )

        metadata = {
            "method": self.method,
            "temperature": self.temperature,
            "isotonic_model_count": len(self.isotonic_models),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return str(artifact_path), str(metadata_path)

    @classmethod
    def load(cls, artifact_path: str) -> "PointInTimeProbabilityCalibrator":
        with open(artifact_path, "rb") as handle:
            payload = pickle.load(handle)

        calibrator = cls(method=payload["method"])
        calibrator.temperature = float(payload.get("temperature", 1.0))
        calibrator.isotonic_models = payload.get("isotonic_models", [])
        return calibrator


def calibrate_evaluation_frame(
    evaluation_frame: pd.DataFrame,
    output_dir: str,
    method: CalibrationMethod = "temperature",
    prefix: str = "point_in_time_model_calibration",
) -> CalibrationResult:
    calibrator = PointInTimeProbabilityCalibrator(method=method)
    standardized = build_standardized_evaluation_frame(evaluation_frame)
    before_metrics = compute_evaluation_summary(standardized)
    calibrator.fit(standardized)
    calibrated_frame = calibrator.transform_frame(standardized)
    after_metrics = compute_evaluation_summary(calibrated_frame)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    calibrated_csv_path = output_path / f"{prefix}_evaluation.csv"
    calibrated_frame.to_csv(calibrated_csv_path, index=False)

    artifact_path, metadata_path = calibrator.save(output_dir, prefix=prefix)
    metadata = {
        "method": method,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "temperature": calibrator.temperature,
        "isotonic_model_count": len(calibrator.isotonic_models),
        "calibrated_evaluation_csv": str(calibrated_csv_path),
    }
    Path(metadata_path).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return CalibrationResult(
        method=method,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        artifact_path=artifact_path,
        metadata_path=metadata_path,
    )
