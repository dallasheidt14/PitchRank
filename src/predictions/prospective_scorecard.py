"""Long-run evidence for strictly prospective match prediction versions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from src.predictions.evaluation_reporting import compute_evaluation_summary
from src.predictions.model_laboratory import finite_json_records, report_digest

PRIMARY_METRICS = (
    "log_loss",
    "brier_score",
    "margin_mae",
    "blowout_4plus_brier",
)
NONINFERIORITY_TOLERANCES = {
    "log_loss": 0.01,
    "brier_score": 0.01,
    "margin_mae": 0.05,
    "blowout_4plus_brier": 0.01,
}


def _metric_delta(
    heuristic_summary: Mapping[str, Any],
    offline_summary: Mapping[str, Any],
    metric: str,
) -> float | None:
    heuristic = heuristic_summary.get(metric)
    offline = offline_summary.get(metric)
    if heuristic is None or offline is None:
        return None
    return float(offline) - float(heuristic)


def build_prospective_scorecard(
    paired_predictions: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    minimum_games: int = 500,
    minimum_months: int = 3,
    required_improved_metrics: int = 2,
    required_monthly_win_rate: float = 0.60,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Evaluate every exact version pair and require repeated prospective wins."""

    if minimum_games < 1 or minimum_months < 1:
        raise ValueError("Prospective evidence minimums must be positive")
    grouped: dict[tuple[str, str], list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    for heuristic, offline in paired_predictions:
        pair = (
            str(heuristic.get("model_version") or ""),
            str(offline.get("model_version") or ""),
        )
        if pair[0] and pair[1]:
            grouped[pair].append((heuristic, offline))

    score_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for (heuristic_version, offline_version), pairs in sorted(grouped.items()):
        heuristic_frame = pd.DataFrame([heuristic for heuristic, _offline in pairs])
        offline_frame = pd.DataFrame([offline for _heuristic, offline in pairs])
        dates = pd.to_datetime(heuristic_frame["game_date"], errors="coerce")
        months = dates.dt.to_period("M").astype("string")
        heuristic_summary = compute_evaluation_summary(heuristic_frame)
        offline_summary = compute_evaluation_summary(offline_frame)
        aggregate_deltas = {
            metric: _metric_delta(heuristic_summary, offline_summary, metric)
            for metric in PRIMARY_METRICS
        }

        pair_monthly_rows = []
        for month in sorted(months.dropna().unique()):
            mask = months.eq(month).fillna(False).to_numpy()
            month_heuristic = compute_evaluation_summary(heuristic_frame.loc[mask])
            month_offline = compute_evaluation_summary(offline_frame.loc[mask])
            row = {
                "heuristic_version": heuristic_version,
                "offline_version": offline_version,
                "month": str(month),
                "games": int(mask.sum()),
            }
            for metric in PRIMARY_METRICS:
                row[f"heuristic_{metric}"] = month_heuristic.get(metric)
                row[f"offline_{metric}"] = month_offline.get(metric)
                row[f"offline_minus_heuristic_{metric}"] = _metric_delta(
                    month_heuristic,
                    month_offline,
                    metric,
                )
            monthly_rows.append(row)
            pair_monthly_rows.append(row)

        monthly_win_rates = {}
        for metric in PRIMARY_METRICS:
            deltas = [
                row[f"offline_minus_heuristic_{metric}"]
                for row in pair_monthly_rows
                if row[f"offline_minus_heuristic_{metric}"] is not None
            ]
            monthly_win_rates[metric] = (
                sum(delta < 0 for delta in deltas) / len(deltas) if deltas else None
            )
        compared_metrics = [metric for metric, delta in aggregate_deltas.items() if delta is not None]
        noninferior = all(
            aggregate_deltas[metric] <= NONINFERIORITY_TOLERANCES[metric]
            for metric in compared_metrics
        )
        improved_metrics = [
            metric for metric in compared_metrics if aggregate_deltas[metric] < 0
        ]
        consistent_metrics = [
            metric
            for metric, rate in monthly_win_rates.items()
            if rate is not None and rate >= required_monthly_win_rate
        ]
        games = len(pairs)
        month_count = len(pair_monthly_rows)
        coverage_complete = games >= minimum_games and month_count >= minimum_months
        sufficient_metrics = len(compared_metrics) >= 3
        eligible = (
            coverage_complete
            and sufficient_metrics
            and noninferior
            and len(improved_metrics) >= required_improved_metrics
            and len(consistent_metrics) >= required_improved_metrics
        )
        reasons = []
        if not coverage_complete:
            reasons.append("Prospective game or month coverage is below the required minimum.")
        if not sufficient_metrics:
            reasons.append("Fewer than three primary metrics have shared probability evidence.")
        if not noninferior:
            reasons.append("At least one primary metric regressed beyond tolerance.")
        if len(improved_metrics) < required_improved_metrics:
            reasons.append("Too few primary metrics improved overall.")
        if len(consistent_metrics) < required_improved_metrics:
            reasons.append("Improvements did not repeat across enough calendar months.")

        score_row = {
            "heuristic_version": heuristic_version,
            "offline_version": offline_version,
            "games": games,
            "months": month_count,
            "start_date": str(dates.min().date()) if dates.notna().any() else None,
            "end_date": str(dates.max().date()) if dates.notna().any() else None,
            "decision": "eligible_for_review" if eligible else "hold",
        }
        for metric in PRIMARY_METRICS:
            score_row[f"heuristic_{metric}"] = heuristic_summary.get(metric)
            score_row[f"offline_{metric}"] = offline_summary.get(metric)
            score_row[f"offline_minus_heuristic_{metric}"] = aggregate_deltas[metric]
            score_row[f"offline_monthly_win_rate_{metric}"] = monthly_win_rates[metric]
        score_rows.append(score_row)
        decisions.append(
            {
                **score_row,
                "compared_metrics": compared_metrics,
                "improved_metrics": improved_metrics,
                "consistent_monthly_wins": consistent_metrics,
                "reasons": reasons,
                "automatic_activation": False,
            }
        )

    scorecard = pd.DataFrame(score_rows)
    monthly = pd.DataFrame(monthly_rows)
    report = {
        "schema_version": "matchbalance-prospective-scorecard-v1",
        "eligibility_policy": "exact_version_pair_and_prediction_date_before_game_date",
        "requirements": {
            "minimum_games": minimum_games,
            "minimum_months": minimum_months,
            "required_improved_metrics": required_improved_metrics,
            "required_monthly_win_rate": required_monthly_win_rate,
            "noninferiority_tolerances": NONINFERIORITY_TOLERANCES,
        },
        "version_pairs": decisions,
        "scorecard": finite_json_records(scorecard),
        "monthly_scorecard": finite_json_records(monthly),
        "automatic_activation": False,
    }
    report["report_sha256"] = report_digest(report)
    return scorecard, monthly, report
