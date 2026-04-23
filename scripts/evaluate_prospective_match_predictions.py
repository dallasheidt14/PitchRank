"""
Evaluate prospective heuristic vs offline match predictions on settled fixtures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.predictions.evaluation_reporting import compute_evaluation_summary, write_evaluation_bundle  # noqa: E402
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


def _actual_outcome(home_score: Optional[int], away_score: Optional[int]) -> Optional[str]:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "team_a"
    if away_score > home_score:
        return "team_b"
    return "draw"


def _is_missing_table(error: Exception, table_name: str) -> bool:
    message = str(error).lower()
    return ("could not find the table" in message or "schema cache" in message) and table_name.lower() in message


def _extract_prediction_payload(row: Dict[str, Any], model_name: str) -> Optional[Dict[str, Any]]:
    if model_name == "heuristic":
        payload = _safe_json(row.get("heuristic_prediction"))
        prediction = _safe_json(_safe_json(payload.get("response")).get("prediction"))
        model_version = payload.get("modelVersion") or row.get("heuristic_model_version")
    else:
        payload = _safe_json(row.get("offline_prediction"))
        prediction = _safe_json(payload.get("prediction"))
        model_version = payload.get("modelVersion") or row.get("offline_model_version")

    if not prediction:
        return None

    win_a = prediction.get("winProbabilityA")
    win_b = prediction.get("winProbabilityB")
    draw = prediction.get("drawProbability")
    if draw is None and win_a is not None and win_b is not None:
        draw = max(0.0, 1.0 - float(win_a) - float(win_b))

    expected_score = _safe_json(prediction.get("expectedScore"))
    fixture_payload = _safe_json(row.get("fixture_payload"))
    home_row = _safe_json(fixture_payload.get("home_row"))

    actual_home_score = row.get("actual_home_score")
    actual_away_score = row.get("actual_away_score")
    return {
        "fixture_key": row.get("fixture_key"),
        "game_date": row.get("game_date"),
        "competition": row.get("competition"),
        "division_name": row.get("division_name"),
        "age_group": home_row.get("age_group"),
        "feature_source": model_name,
        "model_version": model_version,
        "actual_score_a": actual_home_score,
        "actual_score_b": actual_away_score,
        "actual_margin": (actual_home_score - actual_away_score)
        if actual_home_score is not None and actual_away_score is not None
        else None,
        "actual_outcome": _actual_outcome(actual_home_score, actual_away_score),
        "predicted_outcome": prediction.get("predictedWinner"),
        "prob_team_a_win": win_a,
        "prob_draw": draw,
        "prob_team_b_win": win_b,
        "predicted_score_a": expected_score.get("teamA"),
        "predicted_score_b": expected_score.get("teamB"),
        "predicted_margin": prediction.get("expectedMargin"),
        "blowout_3plus_probability": prediction.get("blowoutProbability3Plus"),
        "blowout_5plus_probability": prediction.get("blowoutProbability5Plus"),
        "predicted_blowout_3plus": prediction.get("predictedBlowout3Plus"),
        "predicted_blowout_5plus": prediction.get("predictedBlowout5Plus"),
    }


def _fetch_rows(supabase: Client, limit: Optional[int]) -> List[Dict[str, Any]]:
    select_fields = (
        "fixture_key, game_date, competition, division_name, fixture_payload, "
        "heuristic_prediction_status, heuristic_model_version, heuristic_prediction, "
        "offline_prediction_status, offline_model_version, offline_prediction, "
        "actual_home_score, actual_away_score, evaluation_status"
    )
    page_size = 1000
    rows: List[Dict[str, Any]] = []
    start = 0

    while True:
        remaining = None if limit is None else max(limit - len(rows), 0)
        if remaining == 0:
            break
        batch_size = page_size if remaining is None else min(page_size, remaining)
        query = (
            supabase.table("prospective_match_predictions")
            .select(select_fields)
            .eq("evaluation_status", "settled")
            .order("game_date", desc=False)
            .range(start, start + batch_size - 1)
        )
        try:
            response = query.execute()
        except Exception as error:
            if _is_missing_table(error, "prospective_match_predictions"):
                raise RuntimeError(
                    "prospective_match_predictions table is missing. "
                    "Apply the new Supabase migration before running evaluation."
                ) from error
            raise

        batch = list(response.data or [])
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < batch_size:
            break
        start += batch_size

    return rows


def evaluate_rows(rows: List[Dict[str, Any]], output_dir: Path) -> Dict[str, Any]:
    heuristic_rows: List[Dict[str, Any]] = []
    offline_rows: List[Dict[str, Any]] = []
    comparison_rows: List[Dict[str, Any]] = []

    for row in rows:
        heuristic_prediction = _extract_prediction_payload(row, "heuristic")
        offline_prediction = _extract_prediction_payload(row, "offline")

        if heuristic_prediction and row.get("heuristic_prediction_status") == "completed":
            heuristic_rows.append(heuristic_prediction)
        if offline_prediction and row.get("offline_prediction_status") == "completed":
            offline_rows.append(offline_prediction)

        if heuristic_prediction and offline_prediction:
            comparison_rows.append(
                {
                    "fixture_key": row.get("fixture_key"),
                    "game_date": row.get("game_date"),
                    "competition": row.get("competition"),
                    "division_name": row.get("division_name"),
                    "actual_outcome": heuristic_prediction.get("actual_outcome"),
                    "heuristic_predicted_outcome": heuristic_prediction.get("predicted_outcome"),
                    "offline_predicted_outcome": offline_prediction.get("predicted_outcome"),
                    "heuristic_draw_probability": heuristic_prediction.get("prob_draw"),
                    "offline_draw_probability": offline_prediction.get("prob_draw"),
                    "heuristic_expected_score_a": heuristic_prediction.get("predicted_score_a"),
                    "heuristic_expected_score_b": heuristic_prediction.get("predicted_score_b"),
                    "offline_expected_score_a": offline_prediction.get("predicted_score_a"),
                    "offline_expected_score_b": offline_prediction.get("predicted_score_b"),
                }
            )

    output_dir.mkdir(parents=True, exist_ok=True)

    heuristic_frame = pd.DataFrame(heuristic_rows)
    offline_frame = pd.DataFrame(offline_rows)
    heuristic_summary = (
        write_evaluation_bundle(heuristic_frame, output_dir, prefix="prospective_heuristic")
        if not heuristic_frame.empty
        else compute_evaluation_summary(heuristic_frame)
    )
    offline_summary = (
        write_evaluation_bundle(offline_frame, output_dir, prefix="prospective_offline")
        if not offline_frame.empty
        else compute_evaluation_summary(offline_frame)
    )

    comparison_frame = pd.DataFrame(comparison_rows)
    if not comparison_frame.empty:
        comparison_frame.to_csv(output_dir / "prospective_head_to_head.csv", index=False)

    head_to_head = {
        "fixtures_with_both_predictions": int(len(comparison_frame)),
        "winner_disagreement_rate": float(
            (
                comparison_frame["heuristic_predicted_outcome"]
                != comparison_frame["offline_predicted_outcome"]
            ).mean()
        )
        if not comparison_frame.empty
        else None,
        "avg_draw_probability_delta_offline_minus_heuristic": float(
            (
                pd.to_numeric(comparison_frame["offline_draw_probability"], errors="coerce")
                - pd.to_numeric(comparison_frame["heuristic_draw_probability"], errors="coerce")
            ).mean()
        )
        if not comparison_frame.empty
        else None,
    }

    summary = {
        "settled_rows": len(rows),
        "heuristic_rows": len(heuristic_frame),
        "offline_rows": len(offline_frame),
        "heuristic_summary": heuristic_summary,
        "offline_summary": offline_summary,
        "head_to_head": head_to_head,
    }
    (output_dir / "prospective_head_to_head_summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate prospective heuristic vs offline predictions")
    parser.add_argument("--output-dir", default="models/prospective_evaluation", help="Output directory for reports")
    parser.add_argument("--limit", type=int, default=None, help="Optional settled-row limit")
    parser.add_argument("--summary-path", default=None, help="Optional path to write JSON summary")
    args = parser.parse_args()

    rows = _fetch_rows(_supabase_client(), args.limit)
    summary = evaluate_rows(rows, Path(args.output_dir))
    if args.summary_path:
        summary_path = Path(args.summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
