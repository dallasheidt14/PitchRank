"""Calibration that preserves one coherent score-distribution contract."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

NEUTRAL_PARAMETERS: Mapping[str, float] = {
    "temperature": 1.0,
    "absolute_margin_tilt": 0.0,
    "total_goals_tilt": 0.0,
}


def _history_band(frame: pd.DataFrame) -> pd.Series:
    if not {"team_a_games_played", "team_b_games_played"}.issubset(frame.columns):
        return pd.Series("unknown", index=frame.index, dtype="string")
    minimum = pd.concat(
        [
            pd.to_numeric(frame["team_a_games_played"], errors="coerce"),
            pd.to_numeric(frame["team_b_games_played"], errors="coerce"),
        ],
        axis=1,
    ).min(axis=1)
    return (
        pd.cut(
            minimum,
            bins=[-np.inf, 2, 5, 10, 20, np.inf],
            labels=["0-2", "3-5", "6-10", "11-20", "21+"],
        )
        .astype("string")
        .fillna("unknown")
    )


def _age_gender(frame: pd.DataFrame) -> pd.Series:
    age_source = frame.get(
        "age_group_numeric",
        pd.Series(0, index=frame.index, dtype=float),
    )
    age = pd.to_numeric(age_source, errors="coerce").fillna(0).astype(int)
    if {"team_a_is_female", "team_b_is_female"}.issubset(frame.columns):
        team_a = pd.to_numeric(frame["team_a_is_female"], errors="coerce")
        team_b = pd.to_numeric(frame["team_b_is_female"], errors="coerce")
        gender = pd.Series("mixed_or_unknown", index=frame.index, dtype="string")
        gender.loc[team_a.ge(0.5) & team_b.ge(0.5)] = "girls"
        gender.loc[team_a.lt(0.5) & team_b.lt(0.5)] = "boys"
    else:
        gender = pd.Series("unknown", index=frame.index, dtype="string")
    return pd.Series(
        [f"u{age_value}:{gender_value}" for age_value, gender_value in zip(age, gender, strict=True)],
        index=frame.index,
        dtype="string",
    )


def _segment_labels(frame: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "age_gender": _age_gender(frame),
        "history_coverage": _history_band(frame),
    }


def apply_score_distribution_parameters(
    score_matrices: np.ndarray,
    parameters: Mapping[str, float],
) -> np.ndarray:
    """Exponentially tilt score mass while preserving normalization and nesting."""

    matrices = np.asarray(score_matrices, dtype=float)
    if matrices.ndim != 3 or matrices.shape[1] != matrices.shape[2]:
        raise ValueError("score_matrices must have shape (examples, goals, goals)")
    temperature = float(parameters.get("temperature", 1.0))
    margin_tilt = float(parameters.get("absolute_margin_tilt", 0.0))
    total_tilt = float(parameters.get("total_goals_tilt", 0.0))
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    if not math.isfinite(margin_tilt) or not math.isfinite(total_tilt):
        raise ValueError("score-distribution tilts must be finite")
    if temperature == 1.0 and margin_tilt == 0.0 and total_tilt == 0.0:
        return matrices.copy()

    goals = np.arange(matrices.shape[1], dtype=float)
    absolute_margin = np.abs(goals[:, None] - goals[None, :])
    total_goals = goals[:, None] + goals[None, :]
    log_mass = np.log(np.clip(matrices, 1e-12, None)) / temperature
    log_mass += margin_tilt * absolute_margin[None, :, :]
    log_mass += total_tilt * total_goals[None, :, :]
    log_mass -= np.max(log_mass, axis=(1, 2), keepdims=True)
    calibrated = np.exp(log_mass)
    return calibrated / calibrated.sum(axis=(1, 2), keepdims=True)


def score_distribution_calibration_loss(
    score_matrices: np.ndarray,
    frame: pd.DataFrame,
) -> float:
    """Blend proper probability scores with Backtest's margin target."""

    matrices = np.asarray(score_matrices, dtype=float)
    score_a = np.clip(
        pd.to_numeric(frame["actual_score_a"], errors="raise").astype(int).to_numpy(),
        0,
        matrices.shape[1] - 1,
    )
    score_b = np.clip(
        pd.to_numeric(frame["actual_score_b"], errors="raise").astype(int).to_numpy(),
        0,
        matrices.shape[2] - 1,
    )
    exact_probability = matrices[np.arange(len(matrices)), score_a, score_b]
    exact_log_loss = float(-np.log(np.clip(exact_probability, 1e-12, 1.0)).mean())

    goals = np.arange(matrices.shape[1], dtype=float)
    margin = goals[:, None] - goals[None, :]
    absolute_margin = np.abs(margin)
    outcome_probabilities = np.column_stack(
        [
            matrices[:, margin > 0].sum(axis=1),
            matrices[:, margin == 0].sum(axis=1),
            matrices[:, margin < 0].sum(axis=1),
        ]
    )
    actual_margin = pd.to_numeric(frame["actual_margin"], errors="raise").to_numpy(dtype=float)
    actual_outcome = np.where(actual_margin > 0, 0, np.where(actual_margin < 0, 2, 1))
    outcome_log_loss = float(
        -np.log(
            np.clip(
                outcome_probabilities[np.arange(len(matrices)), actual_outcome],
                1e-12,
                1.0,
            )
        ).mean()
    )
    blowout_probability = matrices[:, absolute_margin >= 4].sum(axis=1)
    actual_blowout = (np.abs(actual_margin) >= 4).astype(float)
    blowout_brier = float(np.mean((blowout_probability - actual_blowout) ** 2))
    expected_absolute_margin = (matrices * absolute_margin[None, :, :]).sum(axis=(1, 2))
    margin_mae = float(np.mean(np.abs(expected_absolute_margin - np.abs(actual_margin))))
    return (
        0.25 * exact_log_loss
        + 0.55 * outcome_log_loss
        + 1.50 * blowout_brier
        + 0.05 * margin_mae
    )


def _fit_parameters(score_matrices: np.ndarray, frame: pd.DataFrame) -> tuple[dict[str, float], float]:
    best_parameters = dict(NEUTRAL_PARAMETERS)
    best_loss = score_distribution_calibration_loss(score_matrices, frame)
    for temperature, margin_tilt, total_tilt in itertools.product(
        (0.85, 1.0, 1.15),
        (-0.18, -0.09, 0.0, 0.09, 0.18),
        (-0.08, 0.0, 0.08),
    ):
        parameters = {
            "temperature": temperature,
            "absolute_margin_tilt": margin_tilt,
            "total_goals_tilt": total_tilt,
        }
        calibrated = apply_score_distribution_parameters(score_matrices, parameters)
        loss = score_distribution_calibration_loss(calibrated, frame)
        if loss + 1e-12 < best_loss:
            best_loss = loss
            best_parameters = parameters
    return best_parameters, best_loss


def fit_score_distribution_calibration(
    score_matrices: np.ndarray,
    frame: pd.DataFrame,
    *,
    minimum_segment_examples: int = 150,
    shrinkage_examples: int = 300,
) -> dict[str, Any]:
    """Fit global and partially pooled segment calibration on calibration data only."""

    if len(frame) != len(score_matrices):
        raise ValueError("score matrices and calibration frame must have equal length")
    canonical_mask = np.ones(len(frame), dtype=bool)
    if "example_orientation" in frame.columns:
        canonical_mask = frame["example_orientation"].astype(str).eq("original").to_numpy()
    canonical_frame = frame.loc[canonical_mask].reset_index(drop=True)
    canonical_matrices = np.asarray(score_matrices, dtype=float)[canonical_mask]
    if canonical_frame.empty:
        raise ValueError("No canonical calibration examples are available")

    neutral_loss = score_distribution_calibration_loss(canonical_matrices, canonical_frame)
    global_parameters, global_loss = _fit_parameters(canonical_matrices, canonical_frame)
    segments: dict[str, dict[str, dict[str, Any]]] = {}
    for segment_type, labels in _segment_labels(canonical_frame).items():
        segment_results: dict[str, dict[str, Any]] = {}
        for label in sorted(labels.dropna().unique()):
            mask = labels.eq(label).to_numpy()
            examples = int(mask.sum())
            if examples < minimum_segment_examples:
                continue
            raw_parameters, _raw_loss = _fit_parameters(
                canonical_matrices[mask],
                canonical_frame.loc[mask].reset_index(drop=True),
            )
            weight = examples / (examples + max(1, shrinkage_examples))
            parameters = {
                key: float(global_parameters[key] + weight * (raw_parameters[key] - global_parameters[key]))
                for key in NEUTRAL_PARAMETERS
            }
            global_segment_loss = score_distribution_calibration_loss(
                apply_score_distribution_parameters(canonical_matrices[mask], global_parameters),
                canonical_frame.loc[mask].reset_index(drop=True),
            )
            segment_loss = score_distribution_calibration_loss(
                apply_score_distribution_parameters(canonical_matrices[mask], parameters),
                canonical_frame.loc[mask].reset_index(drop=True),
            )
            if segment_loss <= global_segment_loss + 1e-12:
                segment_results[str(label)] = {
                    "examples": examples,
                    "shrinkage_weight": weight,
                    "parameters": parameters,
                    "loss": segment_loss,
                    "global_loss_on_segment": global_segment_loss,
                }
        segments[segment_type] = segment_results
    return {
        "version": "coherent-exponential-tilt-v1",
        "examples": int(len(canonical_frame)),
        "neutral_loss": neutral_loss,
        "calibrated_loss": global_loss,
        "global": global_parameters,
        "segments": segments,
        "minimum_segment_examples": minimum_segment_examples,
        "shrinkage_examples": shrinkage_examples,
    }


def apply_score_distribution_calibration(
    score_matrices: np.ndarray,
    frame: pd.DataFrame,
    calibration: Mapping[str, Any] | None,
) -> np.ndarray:
    """Apply global plus available partially pooled segment adjustments."""

    if not calibration or calibration.get("version") != "coherent-exponential-tilt-v1":
        return np.asarray(score_matrices, dtype=float).copy()
    global_parameters = {
        key: float((calibration.get("global") or NEUTRAL_PARAMETERS).get(key, neutral))
        for key, neutral in NEUTRAL_PARAMETERS.items()
    }
    labels = _segment_labels(frame)
    calibrated_rows = []
    for row_index in range(len(frame)):
        adjustments = []
        for segment_type, segment_labels in labels.items():
            segment = (
                calibration.get("segments", {})
                .get(segment_type, {})
                .get(str(segment_labels.iloc[row_index]))
            )
            if segment:
                adjustments.append(segment["parameters"])
        parameters = dict(global_parameters)
        if adjustments:
            for key in NEUTRAL_PARAMETERS:
                parameters[key] = float(
                    global_parameters[key]
                    + np.mean(
                        [
                            float(adjustment[key]) - global_parameters[key]
                            for adjustment in adjustments
                        ]
                    )
                )
        calibrated_rows.append(
            apply_score_distribution_parameters(
                np.asarray(score_matrices[row_index : row_index + 1], dtype=float),
                parameters,
            )[0]
        )
    return np.asarray(calibrated_rows, dtype=float)
