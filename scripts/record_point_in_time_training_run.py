"""
Persist point-in-time training workflow summaries into Supabase for Mission Control.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from supabase import Client, create_client  # noqa: E402


def _supabase_client() -> Client:
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY")
    return create_client(supabase_url, supabase_key)


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_model_version(workflow_run_id: int, training_metrics: Dict[str, Any], requested_strategy: str) -> str:
    selected_strategy = str(
        training_metrics.get("probability_strategy")
        or training_metrics.get("requested_probability_strategy")
        or requested_strategy
        or "unknown"
    ).strip()
    return f"pitm_{workflow_run_id}_{selected_strategy}"


def build_training_run_record(
    *,
    workflow_run_id: int,
    workflow_run_attempt: int,
    git_sha: Optional[str],
    model_dir: Path,
    lookback_days: Optional[int],
    limit_value: Optional[int],
    test_ratio: Optional[float],
    min_examples: Optional[int],
    requested_probability_strategy: str,
    calibration_enabled: bool,
    calibration_method: Optional[str],
    draw_calibration_method: Optional[str],
) -> Dict[str, Any]:
    dataset_summary = _load_json(model_dir / "dataset_summary.json")
    training_metrics = _load_json(model_dir / "training_metrics.json")
    calibration_summary = _load_json(model_dir / "point_in_time_model_calibration_summary.json")

    if not training_metrics:
        raise FileNotFoundError(f"training_metrics.json not found in {model_dir}")

    after_metrics = calibration_summary.get("after_metrics") if isinstance(calibration_summary, dict) else {}
    after_metrics = after_metrics if isinstance(after_metrics, dict) else {}

    return {
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "git_sha": git_sha,
        "model_dir": str(model_dir),
        "model_version": _derive_model_version(workflow_run_id, training_metrics, requested_probability_strategy),
        "lookback_days": lookback_days,
        "limit_value": limit_value,
        "test_ratio": test_ratio,
        "min_examples": min_examples,
        "requested_probability_strategy": requested_probability_strategy,
        "selected_probability_strategy": training_metrics.get("probability_strategy"),
        "calibration_enabled": calibration_enabled,
        "calibration_method": calibration_method if calibration_enabled else None,
        "draw_calibration_method": draw_calibration_method if calibration_enabled else None,
        "dataset_summary": dataset_summary,
        "training_metrics": training_metrics,
        "calibration_summary": calibration_summary or None,
        "games_seen": _as_int(dataset_summary.get("games_seen")),
        "games_used": _as_int(dataset_summary.get("games_used")),
        "examples_built": _as_int(dataset_summary.get("examples_built")),
        "unique_snapshot_dates_used": _as_int(dataset_summary.get("unique_snapshot_dates_used")),
        "winner_accuracy": _as_float(training_metrics.get("winner_accuracy")),
        "draw_recall": _as_float(training_metrics.get("draw_recall")),
        "predicted_draw_rate": _as_float(training_metrics.get("predicted_draw_rate")),
        "log_loss": _as_float(training_metrics.get("log_loss")),
        "margin_mae": _as_float(training_metrics.get("margin_mae")),
        "exact_score_accuracy": _as_float(training_metrics.get("exact_score_accuracy")),
        "calibrated_log_loss": _as_float(after_metrics.get("log_loss")),
        "calibrated_draw_recall": _as_float(after_metrics.get("draw_recall")),
        "calibrated_brier_score": _as_float(after_metrics.get("brier_score")),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a point-in-time model training run in Supabase")
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--git-sha", default=None)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--lookback-days", type=int, default=None)
    parser.add_argument(
        "--limit",
        type=lambda value: None if str(value).lower() == "none" else int(value),
        default=None,
        help='Maximum number of games fetched during training (use "None" for no limit)',
    )
    parser.add_argument("--test-ratio", type=float, default=None)
    parser.add_argument("--min-examples", type=int, default=None)
    parser.add_argument("--requested-probability-strategy", required=True)
    parser.add_argument("--calibration-enabled", action="store_true")
    parser.add_argument("--calibration-method", default=None)
    parser.add_argument("--draw-calibration-method", default=None)
    args = parser.parse_args()

    record = build_training_run_record(
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        git_sha=args.git_sha,
        model_dir=Path(args.model_dir),
        lookback_days=args.lookback_days,
        limit_value=args.limit,
        test_ratio=args.test_ratio,
        min_examples=args.min_examples,
        requested_probability_strategy=args.requested_probability_strategy,
        calibration_enabled=args.calibration_enabled,
        calibration_method=args.calibration_method,
        draw_calibration_method=args.draw_calibration_method,
    )

    _supabase_client().table("model_training_runs").upsert(record, on_conflict="workflow_run_id").execute()
    print(json.dumps({"workflow_run_id": args.workflow_run_id, "model_version": record["model_version"]}, indent=2))


if __name__ == "__main__":
    main()
