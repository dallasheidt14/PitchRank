"""Shared evaluation and reporting utilities for match prediction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss

OUTCOME_ORDER = ["team_a", "draw", "team_b"]
PROBABILITY_COLUMNS = {
    "team_a": "prob_team_a_win",
    "draw": "prob_draw",
    "team_b": "prob_team_b_win",
}
OUTCOME_ALIASES = {
    "team_a": "team_a",
    "team_a_win": "team_a",
    "draw": "draw",
    "team_b": "team_b",
    "team_b_win": "team_b",
}


def _normalize_probabilities(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column_name in PROBABILITY_COLUMNS.values():
        if column_name not in normalized.columns:
            normalized[column_name] = 0.0
        normalized[column_name] = pd.to_numeric(normalized[column_name], errors="coerce").fillna(0.0).clip(0.0, 1.0)

    row_sums = normalized[list(PROBABILITY_COLUMNS.values())].sum(axis=1)
    valid_rows = row_sums > 0
    normalized.loc[valid_rows, list(PROBABILITY_COLUMNS.values())] = normalized.loc[
        valid_rows, list(PROBABILITY_COLUMNS.values())
    ].div(row_sums[valid_rows], axis=0)
    normalized.loc[~valid_rows, list(PROBABILITY_COLUMNS.values())] = [1.0 / len(OUTCOME_ORDER)] * len(OUTCOME_ORDER)
    return normalized


def _outcome_to_index(outcome: str) -> int:
    normalized = OUTCOME_ALIASES.get(str(outcome), str(outcome))
    return OUTCOME_ORDER.index(normalized)


def _brier_score(probabilities: np.ndarray, labels: np.ndarray) -> float:
    one_hot = np.zeros_like(probabilities)
    for row_index, label_index in enumerate(labels):
        one_hot[row_index, label_index] = 1.0
    return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))


def build_standardized_evaluation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    standardized = _normalize_probabilities(frame)
    if "predicted_outcome" not in standardized.columns:
        probability_values = standardized[list(PROBABILITY_COLUMNS.values())].to_numpy()
        predicted_indices = np.argmax(probability_values, axis=1)
        standardized["predicted_outcome"] = [OUTCOME_ORDER[index] for index in predicted_indices]

    standardized["actual_outcome"] = (
        standardized["actual_outcome"].astype(str).map(lambda outcome: OUTCOME_ALIASES.get(outcome, outcome))
    )
    standardized["predicted_outcome"] = (
        standardized["predicted_outcome"].astype(str).map(lambda outcome: OUTCOME_ALIASES.get(outcome, outcome))
    )
    standardized["top_probability"] = standardized[list(PROBABILITY_COLUMNS.values())].max(axis=1)
    standardized["correct_prediction"] = standardized["actual_outcome"] == standardized["predicted_outcome"]
    standardized["margin_error"] = pd.to_numeric(standardized["predicted_margin"], errors="coerce").fillna(0.0) - (
        pd.to_numeric(standardized["actual_margin"], errors="coerce").fillna(0.0)
    )
    standardized["abs_margin_error"] = standardized["margin_error"].abs()
    return standardized


def compute_evaluation_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {
            "games": 0,
            "winner_accuracy": None,
            "draw_recall": None,
            "draw_precision": None,
            "log_loss": None,
            "brier_score": None,
            "margin_mae": None,
            "margin_rmse": None,
        }

    standardized = build_standardized_evaluation_frame(frame)
    labels = standardized["actual_outcome"].map(_outcome_to_index).to_numpy(dtype=int)
    probabilities = standardized[list(PROBABILITY_COLUMNS.values())].to_numpy(dtype=float)

    draw_mask = standardized["actual_outcome"] == "draw"
    predicted_draw_mask = standardized["predicted_outcome"] == "draw"
    margin_errors = standardized["margin_error"].to_numpy(dtype=float)
    actual_draw_rate = float(draw_mask.mean())
    predicted_draw_rate = float(predicted_draw_mask.mean())

    summary: dict[str, object] = {
        "games": int(len(standardized)),
        "winner_accuracy": float(standardized["correct_prediction"].mean()),
        "draw_recall": float((standardized.loc[draw_mask, "predicted_outcome"] == "draw").mean())
        if draw_mask.any()
        else None,
        "draw_precision": float((standardized.loc[predicted_draw_mask, "actual_outcome"] == "draw").mean())
        if predicted_draw_mask.any()
        else None,
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1, 2])),
        "brier_score": _brier_score(probabilities, labels),
        "margin_mae": float(np.mean(np.abs(margin_errors))),
        "margin_rmse": float(np.sqrt(np.mean(margin_errors**2))),
        "actual_draw_rate": actual_draw_rate,
        "predicted_draw_rate": predicted_draw_rate,
        "draw_rate_gap": float(abs(predicted_draw_rate - actual_draw_rate)),
    }

    if "feature_source" in standardized.columns:
        summary["feature_source_counts"] = (
            standardized["feature_source"].value_counts(dropna=False).sort_index().to_dict()
        )
    if "age_group" in standardized.columns:
        summary["age_group_counts"] = standardized["age_group"].value_counts(dropna=False).sort_index().to_dict()

    return summary


def build_calibration_table(frame: pd.DataFrame, bucket_edges: Iterable[float] | None = None) -> pd.DataFrame:
    standardized = build_standardized_evaluation_frame(frame)
    if standardized.empty:
        return pd.DataFrame()

    bucket_edges = list(bucket_edges or [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.01])
    bucket_labels = [
        f"{int(bucket_edges[index] * 100)}-{int(min(bucket_edges[index + 1], 1.0) * 100)}%"
        for index in range(len(bucket_edges) - 1)
    ]
    standardized["probability_bucket"] = pd.cut(
        standardized["top_probability"],
        bins=bucket_edges,
        labels=bucket_labels,
        right=False,
        include_lowest=True,
    )

    grouped = standardized.groupby("probability_bucket", observed=True)
    rows = []
    for bucket_name, bucket_df in grouped:
        if bucket_df.empty:
            continue
        rows.append(
            {
                "probability_bucket": str(bucket_name),
                "games": int(len(bucket_df)),
                "predicted_probability": float(bucket_df["top_probability"].mean()),
                "actual_accuracy": float(bucket_df["correct_prediction"].mean()),
                "calibration_gap": float(bucket_df["top_probability"].mean() - bucket_df["correct_prediction"].mean()),
                "draw_rate": float((bucket_df["actual_outcome"] == "draw").mean()),
            }
        )

    return pd.DataFrame(rows)


def build_group_metrics(frame: pd.DataFrame, group_column: str) -> pd.DataFrame:
    standardized = build_standardized_evaluation_frame(frame)
    if standardized.empty or group_column not in standardized.columns:
        return pd.DataFrame()

    rows = []
    for group_value, group_df in standardized.groupby(group_column, dropna=False):
        if group_df.empty:
            continue
        summary = compute_evaluation_summary(group_df)
        rows.append(
            {
                group_column: group_value,
                "games": summary["games"],
                "winner_accuracy": summary["winner_accuracy"],
                "draw_recall": summary["draw_recall"],
                "draw_precision": summary["draw_precision"],
                "log_loss": summary["log_loss"],
                "brier_score": summary["brier_score"],
                "margin_mae": summary["margin_mae"],
                "margin_rmse": summary["margin_rmse"],
            }
        )

    return pd.DataFrame(rows)


def build_outcome_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    standardized = build_standardized_evaluation_frame(frame)
    if standardized.empty:
        return pd.DataFrame()

    rows = []
    for outcome in OUTCOME_ORDER:
        actual_mask = standardized["actual_outcome"] == outcome
        predicted_mask = standardized["predicted_outcome"] == outcome
        rows.append(
            {
                "outcome": outcome,
                "actual_games": int(actual_mask.sum()),
                "predicted_games": int(predicted_mask.sum()),
                "recall": float((standardized.loc[actual_mask, "predicted_outcome"] == outcome).mean())
                if actual_mask.any()
                else None,
                "precision": float((standardized.loc[predicted_mask, "actual_outcome"] == outcome).mean())
                if predicted_mask.any()
                else None,
                "avg_probability": float(standardized.loc[:, PROBABILITY_COLUMNS[outcome]].mean()),
            }
        )
    return pd.DataFrame(rows)


def write_evaluation_bundle(frame: pd.DataFrame, output_dir: Path, prefix: str = "benchmark") -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    standardized = build_standardized_evaluation_frame(frame)
    summary = compute_evaluation_summary(standardized)
    calibration_table = build_calibration_table(standardized)
    outcome_metrics = build_outcome_metrics(standardized)
    age_metrics = build_group_metrics(standardized, "age_group")
    feature_source_metrics = build_group_metrics(standardized, "feature_source")

    summary_path = output_dir / f"{prefix}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    markdown_lines = [
        f"# {prefix.replace('_', ' ').title()} Summary",
        "",
        f"- Games: {summary['games']}",
        (
            f"- Winner accuracy: {summary['winner_accuracy']:.4f}"
            if summary["winner_accuracy"] is not None
            else "- Winner accuracy: n/a"
        ),
        f"- Draw recall: {summary['draw_recall']:.4f}" if summary["draw_recall"] is not None else "- Draw recall: n/a",
        (
            f"- Draw precision: {summary['draw_precision']:.4f}"
            if summary["draw_precision"] is not None
            else "- Draw precision: n/a"
        ),
        f"- Log loss: {summary['log_loss']:.4f}" if summary["log_loss"] is not None else "- Log loss: n/a",
        f"- Brier score: {summary['brier_score']:.4f}" if summary["brier_score"] is not None else "- Brier score: n/a",
        f"- Margin MAE: {summary['margin_mae']:.4f}" if summary["margin_mae"] is not None else "- Margin MAE: n/a",
        f"- Margin RMSE: {summary['margin_rmse']:.4f}" if summary["margin_rmse"] is not None else "- Margin RMSE: n/a",
    ]
    (output_dir / f"{prefix}_summary.md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    if not calibration_table.empty:
        calibration_table.to_csv(output_dir / f"{prefix}_calibration.csv", index=False)
    if not outcome_metrics.empty:
        outcome_metrics.to_csv(output_dir / f"{prefix}_outcomes.csv", index=False)
    if not age_metrics.empty:
        age_metrics.to_csv(output_dir / f"{prefix}_by_age.csv", index=False)
    if not feature_source_metrics.empty:
        feature_source_metrics.to_csv(output_dir / f"{prefix}_by_feature_source.csv", index=False)

    return summary
