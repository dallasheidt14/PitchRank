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
BLOWOUT_THRESHOLDS = (3, 5)
COMPETITIVE_MARGIN_MAX = 1.0


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


def _numeric_column(frame: pd.DataFrame, column_name: str) -> pd.Series:
    if column_name not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column_name], errors="coerce")


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
    predicted_margin = _numeric_column(standardized, "predicted_margin").fillna(0.0)
    actual_margin = _numeric_column(standardized, "actual_margin").fillna(0.0)
    standardized["predicted_margin"] = predicted_margin
    standardized["actual_margin"] = actual_margin
    standardized["margin_error"] = predicted_margin - actual_margin
    standardized["abs_margin_error"] = standardized["margin_error"].abs()
    standardized["predicted_abs_margin"] = predicted_margin.abs()
    standardized["actual_abs_margin"] = actual_margin.abs()

    predicted_score_a = _numeric_column(standardized, "predicted_score_a")
    predicted_score_b = _numeric_column(standardized, "predicted_score_b")
    actual_score_a = _numeric_column(standardized, "actual_score_a")
    actual_score_b = _numeric_column(standardized, "actual_score_b")
    standardized["predicted_score_a"] = predicted_score_a
    standardized["predicted_score_b"] = predicted_score_b
    standardized["actual_score_a"] = actual_score_a
    standardized["actual_score_b"] = actual_score_b
    standardized["predicted_score_a_rounded"] = predicted_score_a.round()
    standardized["predicted_score_b_rounded"] = predicted_score_b.round()
    standardized["score_a_error"] = predicted_score_a - actual_score_a
    standardized["score_b_error"] = predicted_score_b - actual_score_b
    standardized["abs_score_a_error"] = standardized["score_a_error"].abs()
    standardized["abs_score_b_error"] = standardized["score_b_error"].abs()
    standardized["predicted_total_goals"] = predicted_score_a + predicted_score_b
    standardized["actual_total_goals"] = actual_score_a + actual_score_b
    standardized["total_goals_error"] = standardized["predicted_total_goals"] - standardized["actual_total_goals"]
    standardized["abs_total_goals_error"] = standardized["total_goals_error"].abs()
    standardized["exact_score_hit"] = (
        standardized["predicted_score_a_rounded"].eq(actual_score_a)
        & standardized["predicted_score_b_rounded"].eq(actual_score_b)
    )
    standardized["score_within_one_goal_hit"] = (
        standardized["predicted_score_a_rounded"].sub(actual_score_a).abs().le(1.0)
        & standardized["predicted_score_b_rounded"].sub(actual_score_b).abs().le(1.0)
    )
    standardized["predicted_competitive_game"] = standardized["predicted_abs_margin"] <= COMPETITIVE_MARGIN_MAX
    standardized["actual_competitive_game"] = standardized["actual_abs_margin"] <= COMPETITIVE_MARGIN_MAX
    for threshold in BLOWOUT_THRESHOLDS:
        predicted_label_column = f"predicted_blowout_{threshold}plus"
        if predicted_label_column in standardized.columns:
            standardized[predicted_label_column] = (
                pd.to_numeric(standardized[predicted_label_column], errors="coerce")
                .fillna(0.0)
                .astype(int)
                .clip(0, 1)
                .astype(bool)
            )
        else:
            standardized[predicted_label_column] = standardized["predicted_abs_margin"] >= float(threshold)
        standardized[f"actual_blowout_{threshold}plus"] = standardized["actual_abs_margin"] >= float(threshold)
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
    score_rows = standardized[
        ["predicted_score_a", "predicted_score_b", "actual_score_a", "actual_score_b"]
    ].notna().all(axis=1)

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
    }

    if score_rows.any():
        score_frame = standardized.loc[score_rows]
        summary.update(
            {
                "score_a_mae": float(score_frame["abs_score_a_error"].mean()),
                "score_b_mae": float(score_frame["abs_score_b_error"].mean()),
                "total_goals_mae": float(score_frame["abs_total_goals_error"].mean()),
                "exact_score_accuracy": float(score_frame["exact_score_hit"].mean()),
                "score_within_one_goal_rate": float(score_frame["score_within_one_goal_hit"].mean()),
            }
        )
    else:
        summary.update(
            {
                "score_a_mae": None,
                "score_b_mae": None,
                "total_goals_mae": None,
                "exact_score_accuracy": None,
                "score_within_one_goal_rate": None,
            }
        )

    actual_competitive_mask = standardized["actual_competitive_game"]
    predicted_competitive_mask = standardized["predicted_competitive_game"]
    summary["competitive_game_recall"] = (
        float((standardized.loc[actual_competitive_mask, "predicted_competitive_game"]).mean())
        if actual_competitive_mask.any()
        else None
    )
    summary["competitive_game_precision"] = (
        float((standardized.loc[predicted_competitive_mask, "actual_competitive_game"]).mean())
        if predicted_competitive_mask.any()
        else None
    )
    summary["actual_competitive_game_rate"] = float(actual_competitive_mask.mean())
    summary["predicted_competitive_game_rate"] = float(predicted_competitive_mask.mean())

    for threshold in BLOWOUT_THRESHOLDS:
        actual_blowout_mask = standardized[f"actual_blowout_{threshold}plus"]
        predicted_blowout_mask = standardized[f"predicted_blowout_{threshold}plus"]
        summary[f"actual_blowout_{threshold}plus_rate"] = float(actual_blowout_mask.mean())
        summary[f"predicted_blowout_{threshold}plus_rate"] = float(predicted_blowout_mask.mean())
        summary[f"blowout_{threshold}plus_recall"] = (
            float(standardized.loc[actual_blowout_mask, f"predicted_blowout_{threshold}plus"].mean())
            if actual_blowout_mask.any()
            else None
        )
        summary[f"blowout_{threshold}plus_precision"] = (
            float(standardized.loc[predicted_blowout_mask, f"actual_blowout_{threshold}plus"].mean())
            if predicted_blowout_mask.any()
            else None
        )
        probability_column = f"blowout_{threshold}plus_probability"
        if probability_column in standardized.columns:
            blowout_probability = pd.to_numeric(
                standardized[probability_column],
                errors="coerce",
            ).clip(0.0, 1.0)
            valid_probability_mask = blowout_probability.notna()
            if valid_probability_mask.any():
                actual_binary = actual_blowout_mask.astype(float)
                summary[f"avg_blowout_{threshold}plus_probability"] = float(
                    blowout_probability.loc[valid_probability_mask].mean()
                )
                summary[f"blowout_{threshold}plus_brier"] = float(
                    np.mean(
                        (
                            blowout_probability.loc[valid_probability_mask].to_numpy(dtype=float)
                            - actual_binary.loc[valid_probability_mask].to_numpy(dtype=float)
                        )
                        ** 2
                    )
                )
            else:
                summary[f"avg_blowout_{threshold}plus_probability"] = None
                summary[f"blowout_{threshold}plus_brier"] = None

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
                "total_goals_mae": summary.get("total_goals_mae"),
                "exact_score_accuracy": summary.get("exact_score_accuracy"),
                "competitive_game_recall": summary.get("competitive_game_recall"),
                "competitive_game_precision": summary.get("competitive_game_precision"),
                "blowout_3plus_recall": summary.get("blowout_3plus_recall"),
                "blowout_3plus_precision": summary.get("blowout_3plus_precision"),
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


def build_margin_band_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    standardized = build_standardized_evaluation_frame(frame)
    if standardized.empty:
        return pd.DataFrame()

    rows = []
    actual_competitive_mask = standardized["actual_competitive_game"]
    predicted_competitive_mask = standardized["predicted_competitive_game"]
    rows.append(
        {
            "band": "competitive_1plus",
            "actual_rate": float(actual_competitive_mask.mean()),
            "predicted_rate": float(predicted_competitive_mask.mean()),
            "recall": float((standardized.loc[actual_competitive_mask, "predicted_competitive_game"]).mean())
            if actual_competitive_mask.any()
            else None,
            "precision": float((standardized.loc[predicted_competitive_mask, "actual_competitive_game"]).mean())
            if predicted_competitive_mask.any()
            else None,
        }
    )

    for threshold in BLOWOUT_THRESHOLDS:
        actual_mask = standardized[f"actual_blowout_{threshold}plus"]
        predicted_mask = standardized[f"predicted_blowout_{threshold}plus"]
        probability_column = f"blowout_{threshold}plus_probability"
        avg_probability = None
        brier = None
        if probability_column in standardized.columns:
            blowout_probability = pd.to_numeric(
                standardized[probability_column],
                errors="coerce",
            ).clip(0.0, 1.0)
            valid_probability_mask = blowout_probability.notna()
            if valid_probability_mask.any():
                avg_probability = float(blowout_probability.loc[valid_probability_mask].mean())
                brier = float(
                    np.mean(
                        (
                            blowout_probability.loc[valid_probability_mask].to_numpy(dtype=float)
                            - actual_mask.loc[valid_probability_mask].to_numpy(dtype=float)
                        )
                        ** 2
                    )
                )
        rows.append(
            {
                "band": f"blowout_{threshold}plus",
                "actual_rate": float(actual_mask.mean()),
                "predicted_rate": float(predicted_mask.mean()),
                "recall": float(standardized.loc[actual_mask, f"predicted_blowout_{threshold}plus"].mean())
                if actual_mask.any()
                else None,
                "precision": float(standardized.loc[predicted_mask, f"actual_blowout_{threshold}plus"].mean())
                if predicted_mask.any()
                else None,
                "avg_probability": avg_probability,
                "brier": brier,
            }
        )

    return pd.DataFrame(rows)


def write_evaluation_bundle(frame: pd.DataFrame, output_dir: Path, prefix: str = "benchmark") -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    standardized = build_standardized_evaluation_frame(frame)
    summary = compute_evaluation_summary(standardized)
    calibration_table = build_calibration_table(standardized)
    outcome_metrics = build_outcome_metrics(standardized)
    margin_band_metrics = build_margin_band_metrics(standardized)
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
        (
            f"- Total-goals MAE: {summary['total_goals_mae']:.4f}"
            if summary["total_goals_mae"] is not None
            else "- Total-goals MAE: n/a"
        ),
        (
            f"- Exact score accuracy: {summary['exact_score_accuracy']:.4f}"
            if summary["exact_score_accuracy"] is not None
            else "- Exact score accuracy: n/a"
        ),
        (
            f"- Competitive-game recall: {summary['competitive_game_recall']:.4f}"
            if summary["competitive_game_recall"] is not None
            else "- Competitive-game recall: n/a"
        ),
        (
            f"- Blowout 3+ recall: {summary['blowout_3plus_recall']:.4f}"
            if summary["blowout_3plus_recall"] is not None
            else "- Blowout 3+ recall: n/a"
        ),
    ]
    (output_dir / f"{prefix}_summary.md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    if not calibration_table.empty:
        calibration_table.to_csv(output_dir / f"{prefix}_calibration.csv", index=False)
    if not outcome_metrics.empty:
        outcome_metrics.to_csv(output_dir / f"{prefix}_outcomes.csv", index=False)
    if not margin_band_metrics.empty:
        margin_band_metrics.to_csv(output_dir / f"{prefix}_margin_bands.csv", index=False)
    if not age_metrics.empty:
        age_metrics.to_csv(output_dir / f"{prefix}_by_age.csv", index=False)
    if not feature_source_metrics.empty:
        feature_source_metrics.to_csv(output_dir / f"{prefix}_by_feature_source.csv", index=False)

    return summary
