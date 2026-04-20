"""
Tune post-calibration for the live heuristic using settled prospective rows.

This script does not retrain the heuristic itself. It evaluates a lightweight
post-processing layer over the existing three-way probabilities:

1. Blend the raw probabilities toward a prior outcome distribution.
2. Optionally keep the stored predicted winner or choose the argmax of the
   calibrated probabilities.

The main use case is to quantify whether a production-safe calibration pass can
improve winner accuracy and/or log loss before touching the live route.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.predictions.evaluation_reporting import compute_evaluation_summary  # noqa: E402
from supabase import Client, create_client  # noqa: E402


def _supabase_client() -> Client:
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY")
    return create_client(supabase_url, supabase_key)


def _safe_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _fetch_rows(supabase: Client, limit: Optional[int]) -> List[Dict[str, Any]]:
    select_fields = (
        "game_date, fixture_payload, heuristic_prediction, heuristic_prediction_status, "
        "actual_home_score, actual_away_score, actual_outcome, evaluation_status"
    )
    page_size = 1000
    rows: List[Dict[str, Any]] = []
    start = 0

    while True:
        remaining = None if limit is None else max(limit - len(rows), 0)
        if remaining == 0:
            break
        batch_size = page_size if remaining is None else min(page_size, remaining)
        response = (
            supabase.table("prospective_match_predictions")
            .select(select_fields)
            .eq("evaluation_status", "settled")
            .eq("heuristic_prediction_status", "completed")
            .order("game_date", desc=False)
            .range(start, start + batch_size - 1)
            .execute()
        )
        batch = list(response.data or [])
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        start += batch_size

    return rows


def _age_group_from_fixture(row: Dict[str, Any]) -> Optional[str]:
    fixture_payload = _safe_json(row.get("fixture_payload"))
    home_row = _safe_json(fixture_payload.get("home_row"))
    raw_age = home_row.get("age_group")
    try:
        return f"U{int(raw_age)}" if raw_age is not None else None
    except Exception:
        return str(raw_age) if raw_age is not None else None


def _build_frame(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    records: List[Dict[str, Any]] = []
    for row in rows:
        payload = _safe_json(row.get("heuristic_prediction"))
        prediction = _safe_json(_safe_json(payload.get("response")).get("prediction"))
        if not prediction:
            continue

        expected_score = _safe_json(prediction.get("expectedScore"))
        actual_home = row.get("actual_home_score")
        actual_away = row.get("actual_away_score")
        records.append(
            {
                "game_date": row.get("game_date"),
                "age_group": _age_group_from_fixture(row),
                "actual_score_a": actual_home,
                "actual_score_b": actual_away,
                "actual_margin": (actual_home - actual_away)
                if actual_home is not None and actual_away is not None
                else None,
                "actual_outcome": row.get("actual_outcome"),
                "predicted_outcome": prediction.get("predictedWinner"),
                "prob_team_a_win": float(prediction.get("winProbabilityA") or 0.0),
                "prob_draw": float(prediction.get("drawProbability") or 0.0),
                "prob_team_b_win": float(prediction.get("winProbabilityB") or 0.0),
                "predicted_score_a": expected_score.get("teamA"),
                "predicted_score_b": expected_score.get("teamB"),
                "predicted_margin": prediction.get("expectedMargin"),
            }
        )
    return pd.DataFrame(records)


def _prior_vector(train_frame: pd.DataFrame, mode: str) -> np.ndarray:
    draw_rate = float((train_frame["actual_outcome"] == "draw").mean())
    if mode == "uniform":
        return np.array([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0], dtype=float)
    if mode == "empirical":
        return np.array(
            [
                float((train_frame["actual_outcome"] == "team_a").mean()),
                draw_rate,
                float((train_frame["actual_outcome"] == "team_b").mean()),
            ],
            dtype=float,
        )
    if mode == "symmetric_draw":
        decisive_rate = max(0.0, 1.0 - draw_rate)
        return np.array([decisive_rate / 2.0, draw_rate, decisive_rate / 2.0], dtype=float)
    raise ValueError(f"Unsupported prior mode: {mode}")


def _calibrate_probabilities(frame: pd.DataFrame, alpha: float, prior: np.ndarray) -> np.ndarray:
    base = frame[["prob_team_a_win", "prob_draw", "prob_team_b_win"]].to_numpy(dtype=float)
    calibrated = alpha * base + (1.0 - alpha) * prior
    row_sums = calibrated.sum(axis=1, keepdims=True)
    row_sums[row_sums <= 0] = 1.0
    return calibrated / row_sums


def _evaluate_candidate(
    frame: pd.DataFrame,
    probabilities: np.ndarray,
    predicted_winner_mode: str,
) -> Dict[str, Any]:
    evaluation_frame = frame[
        [
            "game_date",
            "age_group",
            "actual_score_a",
            "actual_score_b",
            "actual_margin",
            "actual_outcome",
            "predicted_score_a",
            "predicted_score_b",
            "predicted_margin",
            "predicted_outcome",
        ]
    ].copy()
    evaluation_frame["prob_team_a_win"] = probabilities[:, 0]
    evaluation_frame["prob_draw"] = probabilities[:, 1]
    evaluation_frame["prob_team_b_win"] = probabilities[:, 2]
    if predicted_winner_mode == "argmax":
        labels = np.array(["team_a", "draw", "team_b"])
        evaluation_frame["predicted_outcome"] = labels[np.argmax(probabilities, axis=1)]
    summary = compute_evaluation_summary(evaluation_frame)
    return {"frame": evaluation_frame, "summary": summary}


def _summary_snapshot(summary: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "games",
        "winner_accuracy",
        "draw_recall",
        "draw_precision",
        "predicted_draw_rate",
        "actual_draw_rate",
        "log_loss",
        "brier_score",
    ]
    return {key: summary.get(key) for key in keys}


def tune(
    *,
    rows: List[Dict[str, Any]],
    holdout_start_date: Optional[str],
    holdout_end_date: Optional[str],
    alpha_min: float,
    alpha_max: float,
    alpha_step: float,
    prior_modes: List[str],
) -> Dict[str, Any]:
    frame = _build_frame(rows)
    if frame.empty:
        raise RuntimeError("No settled heuristic rows were available to tune")

    if holdout_start_date:
        holdout_mask = frame["game_date"] >= holdout_start_date
        if holdout_end_date:
            holdout_mask &= frame["game_date"] <= holdout_end_date
        train_frame = frame.loc[~holdout_mask].reset_index(drop=True)
        holdout_frame = frame.loc[holdout_mask].reset_index(drop=True)
    else:
        train_frame = frame.copy().reset_index(drop=True)
        holdout_frame = pd.DataFrame(columns=frame.columns)

    if train_frame.empty:
        raise RuntimeError("Training split is empty; adjust the holdout date range")

    baseline_train = compute_evaluation_summary(train_frame.copy())
    baseline_holdout = compute_evaluation_summary(holdout_frame.copy()) if not holdout_frame.empty else None
    baseline_all = compute_evaluation_summary(frame.copy())

    leaderboard_rows: List[Dict[str, Any]] = []
    alpha_values = np.arange(alpha_min, alpha_max + 1e-9, alpha_step)
    for prior_mode in prior_modes:
        prior = _prior_vector(train_frame, prior_mode)
        for alpha in alpha_values:
            probabilities_train = _calibrate_probabilities(train_frame, float(alpha), prior)
            for predicted_winner_mode in ("retain", "argmax"):
                train_result = _evaluate_candidate(train_frame, probabilities_train, predicted_winner_mode)
                train_summary = train_result["summary"]

                row: Dict[str, Any] = {
                    "prior_mode": prior_mode,
                    "alpha": float(round(alpha, 6)),
                    "predicted_winner_mode": predicted_winner_mode,
                    "train_winner_accuracy": train_summary.get("winner_accuracy"),
                    "train_draw_recall": train_summary.get("draw_recall"),
                    "train_predicted_draw_rate": train_summary.get("predicted_draw_rate"),
                    "train_log_loss": train_summary.get("log_loss"),
                    "train_brier_score": train_summary.get("brier_score"),
                    "prior_team_a": float(prior[0]),
                    "prior_draw": float(prior[1]),
                    "prior_team_b": float(prior[2]),
                }

                if not holdout_frame.empty:
                    probabilities_holdout = _calibrate_probabilities(holdout_frame, float(alpha), prior)
                    holdout_summary = _evaluate_candidate(
                        holdout_frame,
                        probabilities_holdout,
                        predicted_winner_mode,
                    )["summary"]
                    row.update(
                        {
                            "holdout_winner_accuracy": holdout_summary.get("winner_accuracy"),
                            "holdout_draw_recall": holdout_summary.get("draw_recall"),
                            "holdout_predicted_draw_rate": holdout_summary.get("predicted_draw_rate"),
                            "holdout_log_loss": holdout_summary.get("log_loss"),
                            "holdout_brier_score": holdout_summary.get("brier_score"),
                        }
                    )

                probabilities_all = _calibrate_probabilities(frame, float(alpha), prior)
                all_summary = _evaluate_candidate(frame, probabilities_all, predicted_winner_mode)["summary"]
                row.update(
                    {
                        "all_winner_accuracy": all_summary.get("winner_accuracy"),
                        "all_draw_recall": all_summary.get("draw_recall"),
                        "all_predicted_draw_rate": all_summary.get("predicted_draw_rate"),
                        "all_log_loss": all_summary.get("log_loss"),
                        "all_brier_score": all_summary.get("brier_score"),
                    }
                )
                leaderboard_rows.append(row)

    leaderboard = pd.DataFrame(leaderboard_rows)
    if leaderboard.empty:
        raise RuntimeError("No candidates were evaluated")

    sort_train_accuracy = [
        "train_winner_accuracy",
        "train_log_loss",
        "holdout_winner_accuracy" if "holdout_winner_accuracy" in leaderboard.columns else "train_winner_accuracy",
    ]
    sort_train_log_loss = [
        "train_log_loss",
        "train_winner_accuracy",
        "holdout_log_loss" if "holdout_log_loss" in leaderboard.columns else "train_log_loss",
    ]

    best_accuracy = leaderboard.sort_values(
        by=sort_train_accuracy,
        ascending=[False, True, False],
        kind="mergesort",
    ).iloc[0]
    best_log_loss = leaderboard.sort_values(
        by=sort_train_log_loss,
        ascending=[True, False, True],
        kind="mergesort",
    ).iloc[0]

    return {
        "row_count": int(len(frame)),
        "train_row_count": int(len(train_frame)),
        "holdout_row_count": int(len(holdout_frame)),
        "holdout_start_date": holdout_start_date,
        "holdout_end_date": holdout_end_date,
        "baseline": {
            "train": _summary_snapshot(baseline_train),
            "holdout": _summary_snapshot(baseline_holdout) if baseline_holdout else None,
            "all": _summary_snapshot(baseline_all),
        },
        "best_train_accuracy_candidate": best_accuracy.to_dict(),
        "best_train_log_loss_candidate": best_log_loss.to_dict(),
        "leaderboard": leaderboard,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune heuristic outcome calibration on settled prospective rows")
    parser.add_argument("--output-dir", default="reports/heuristic_tuning", help="Directory for report outputs")
    parser.add_argument("--summary-path", default=None, help="Optional JSON summary path")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for debugging")
    parser.add_argument("--holdout-start-date", default=None, help="Optional holdout start date (YYYY-MM-DD)")
    parser.add_argument("--holdout-end-date", default=None, help="Optional holdout end date (YYYY-MM-DD)")
    parser.add_argument("--alpha-min", type=float, default=0.4, help="Minimum blend weight")
    parser.add_argument("--alpha-max", type=float, default=0.95, help="Maximum blend weight")
    parser.add_argument("--alpha-step", type=float, default=0.025, help="Blend-weight step")
    parser.add_argument(
        "--prior-modes",
        nargs="+",
        default=["uniform", "symmetric_draw", "empirical"],
        choices=["uniform", "symmetric_draw", "empirical"],
        help="Prior families to evaluate",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = tune(
        rows=_fetch_rows(_supabase_client(), args.limit),
        holdout_start_date=args.holdout_start_date,
        holdout_end_date=args.holdout_end_date,
        alpha_min=args.alpha_min,
        alpha_max=args.alpha_max,
        alpha_step=args.alpha_step,
        prior_modes=args.prior_modes,
    )

    leaderboard = results.pop("leaderboard")
    leaderboard_path = output_dir / "leaderboard.csv"
    leaderboard.to_csv(leaderboard_path, index=False)

    summary = {
        **results,
        "leaderboard_path": str(leaderboard_path),
    }
    summary_path = Path(args.summary_path) if args.summary_path else output_dir / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
