"""Calibration utilities for point-in-time match model probabilities."""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

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
DrawCalibrationMethod = Literal["none", "isotonic"]
EvaluationFramePostprocessor = Callable[[pd.DataFrame], pd.DataFrame]


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
    draw_method: DrawCalibrationMethod
    before_metrics: dict[str, object]
    after_metrics: dict[str, object]
    artifact_path: str
    metadata_path: str


class PointInTimeProbabilityCalibrator:
    def __init__(
        self,
        method: CalibrationMethod = "temperature",
        draw_method: DrawCalibrationMethod = "none",
    ):
        self.method = method
        self.draw_method = draw_method
        self.temperature = 1.0
        self.isotonic_models: list[IsotonicRegression] = []
        self.draw_isotonic_model: IsotonicRegression | None = None

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

    def _transform_overall_probabilities(self, probabilities: np.ndarray) -> np.ndarray:
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

    def _fit_draw_isotonic(self, probabilities: np.ndarray, labels: np.ndarray) -> None:
        self.draw_isotonic_model = IsotonicRegression(out_of_bounds="clip")
        self.draw_isotonic_model.fit(
            probabilities[:, OUTCOME_ORDER.index("draw")],
            (labels == OUTCOME_ORDER.index("draw")).astype(float),
        )

    def _apply_draw_calibration(self, probabilities: np.ndarray) -> np.ndarray:
        if self.draw_method == "none":
            return probabilities
        if self.draw_method != "isotonic":
            raise ValueError(f"Unsupported draw calibration method: {self.draw_method}")
        if self.draw_isotonic_model is None:
            raise ValueError("Draw calibrator has not been fit")

        draw_index = OUTCOME_ORDER.index("draw")
        calibrated = probabilities.copy()
        calibrated_draw = np.clip(
            self.draw_isotonic_model.predict(calibrated[:, draw_index]),
            1e-6,
            0.98,
        )
        non_draw_indices = [index for index in range(calibrated.shape[1]) if index != draw_index]
        non_draw_mass = calibrated[:, non_draw_indices].sum(axis=1, keepdims=True)
        remaining_mass = 1.0 - calibrated_draw.reshape(-1, 1)
        scaled_non_draw = np.divide(
            calibrated[:, non_draw_indices] * remaining_mass,
            non_draw_mass,
            out=np.full((len(calibrated), len(non_draw_indices)), 0.5) * remaining_mass,
            where=non_draw_mass > 0,
        )
        calibrated[:, draw_index] = calibrated_draw
        calibrated[:, non_draw_indices] = scaled_non_draw
        return _normalize_probabilities(calibrated)

    def fit(self, evaluation_frame: pd.DataFrame) -> None:
        probabilities = self._probabilities_from_frame(evaluation_frame)
        labels = self._labels_from_frame(evaluation_frame)

        if self.method == "temperature":
            self._fit_temperature(probabilities, labels)
        elif self.method == "isotonic":
            self._fit_isotonic(probabilities, labels)
        else:
            raise ValueError(f"Unsupported calibration method: {self.method}")

        if self.draw_method == "isotonic":
            overall_calibrated = self._transform_overall_probabilities(probabilities)
            self._fit_draw_isotonic(overall_calibrated, labels)
        elif self.draw_method != "none":
            raise ValueError(f"Unsupported draw calibration method: {self.draw_method}")

    def transform_probabilities(self, probabilities: np.ndarray) -> np.ndarray:
        overall_calibrated = self._transform_overall_probabilities(probabilities)
        return self._apply_draw_calibration(overall_calibrated)

    def transform_frame(
        self,
        evaluation_frame: pd.DataFrame,
        prediction_postprocessor: EvaluationFramePostprocessor | None = None,
    ) -> pd.DataFrame:
        standardized = build_standardized_evaluation_frame(evaluation_frame)
        probabilities = standardized[list(PROBABILITY_COLUMNS.values())].to_numpy(dtype=float)
        calibrated = self.transform_probabilities(probabilities)
        calibrated_frame = standardized.copy()
        calibrated_frame["prob_team_a_win"] = calibrated[:, 0]
        calibrated_frame["prob_draw"] = calibrated[:, 1]
        calibrated_frame["prob_team_b_win"] = calibrated[:, 2]
        if prediction_postprocessor is not None:
            calibrated_frame = prediction_postprocessor(calibrated_frame.copy())
        else:
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
                    "draw_method": self.draw_method,
                    "temperature": self.temperature,
                    "isotonic_models": self.isotonic_models,
                    "draw_isotonic_model": self.draw_isotonic_model,
                },
                handle,
            )

        metadata = {
            "method": self.method,
            "draw_method": self.draw_method,
            "temperature": self.temperature,
            "isotonic_model_count": len(self.isotonic_models),
            "has_draw_isotonic_model": self.draw_isotonic_model is not None,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return str(artifact_path), str(metadata_path)

    @classmethod
    def load(cls, artifact_path: str) -> "PointInTimeProbabilityCalibrator":
        with open(artifact_path, "rb") as handle:
            payload = pickle.load(handle)

        calibrator = cls(
            method=payload["method"],
            draw_method=payload.get("draw_method", "none"),
        )
        calibrator.temperature = float(payload.get("temperature", 1.0))
        calibrator.isotonic_models = payload.get("isotonic_models", [])
        calibrator.draw_isotonic_model = payload.get("draw_isotonic_model")
        return calibrator


def calibrate_evaluation_frame(
    evaluation_frame: pd.DataFrame,
    output_dir: str,
    method: CalibrationMethod = "temperature",
    draw_method: DrawCalibrationMethod = "none",
    prefix: str = "point_in_time_model_calibration",
    prediction_postprocessor: EvaluationFramePostprocessor | None = None,
) -> CalibrationResult:
    calibrator = PointInTimeProbabilityCalibrator(method=method, draw_method=draw_method)
    standardized = build_standardized_evaluation_frame(evaluation_frame)
    before_metrics = compute_evaluation_summary(standardized)
    calibrator.fit(standardized)
    calibrated_frame = calibrator.transform_frame(
        standardized,
        prediction_postprocessor=prediction_postprocessor,
    )
    after_metrics = compute_evaluation_summary(calibrated_frame)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    calibrated_csv_path = output_path / f"{prefix}_evaluation.csv"
    calibrated_frame.to_csv(calibrated_csv_path, index=False)

    artifact_path, metadata_path = calibrator.save(output_dir, prefix=prefix)
    metadata = {
        "method": method,
        "draw_method": draw_method,
        "before_metrics": before_metrics,
        "after_metrics": after_metrics,
        "temperature": calibrator.temperature,
        "isotonic_model_count": len(calibrator.isotonic_models),
        "has_draw_isotonic_model": calibrator.draw_isotonic_model is not None,
        "calibrated_evaluation_csv": str(calibrated_csv_path),
    }
    Path(metadata_path).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return CalibrationResult(
        method=method,
        draw_method=draw_method,
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        artifact_path=artifact_path,
        metadata_path=metadata_path,
    )
