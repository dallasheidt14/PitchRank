"""Run the offline MatchBalance champion/challenger model laboratory."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.predictions.model_laboratory import (  # noqa: E402
    DEFAULT_PROMOTION_BASELINE,
    build_feature_coverage_report,
    build_promotion_decisions,
    dataset_sha256,
    finite_json_records,
    report_digest,
    run_count_model_laboratory,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate MatchBalance and interpretable count models on expanding, "
            "event-blocked historical tournament folds. Reads a saved training CSV only."
        )
    )
    parser.add_argument("--dataset", required=True, help="Point-in-time training dataset CSV")
    parser.add_argument(
        "--output-dir",
        default="reports/matchbalance-model-laboratory",
        help="Local output directory",
    )
    parser.add_argument("--min-train-groups", type=int, default=8)
    parser.add_argument("--min-train-games", type=int, default=500)
    parser.add_argument("--test-group-count", type=int, default=1)
    parser.add_argument("--max-folds", type=int, default=12)
    parser.add_argument("--half-life-days", type=float, default=120.0)
    parser.add_argument("--prior-games", type=float, default=6.0)
    parser.add_argument(
        "--skip-learned",
        action="store_true",
        help="Evaluate only the transparent count-model challengers",
    )
    parser.add_argument(
        "--promotion-baseline",
        default=DEFAULT_PROMOTION_BASELINE,
        help="Existing baseline that every registrable candidate must beat",
    )
    parser.add_argument("--minimum-promotion-folds", type=int, default=3)
    parser.add_argument("--minimum-promotion-games", type=int, default=500)
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    if not dataset_path.is_file():
        parser.error(f"Dataset does not exist: {dataset_path}")
    dataset = pd.read_csv(dataset_path)
    result = run_count_model_laboratory(
        dataset,
        half_life_days=args.half_life_days,
        prior_games=args.prior_games,
        min_train_groups=args.min_train_groups,
        test_group_count=args.test_group_count,
        min_train_games=args.min_train_games,
        max_folds=args.max_folds,
        include_matchbalance_learned=not args.skip_learned,
    )

    output_dir = Path(args.output_dir).resolve()
    _write_csv(output_dir / "rolling_fold_metrics.csv", result.fold_metrics)
    _write_csv(output_dir / "aggregate_metrics.csv", result.aggregate_metrics)
    _write_csv(output_dir / "segment_metrics.csv", result.segment_metrics)
    _write_csv(output_dir / "frozen_predictions.csv", result.predictions)
    feature_coverage = build_feature_coverage_report(dataset)
    _write_json(output_dir / "feature_coverage.json", feature_coverage)

    candidates = sorted(result.fold_metrics.get("candidate", pd.Series(dtype=str)).unique())
    promotion = build_promotion_decisions(
        result.fold_metrics,
        promotion_baseline=args.promotion_baseline,
        minimum_folds=args.minimum_promotion_folds,
        minimum_shared_games=args.minimum_promotion_games,
        segment_metrics=result.segment_metrics,
    )

    manifest = {
        "schema_version": "matchbalance-model-laboratory-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_sha256(dataset_path),
            "rows": int(len(dataset)),
            "games": int(dataset["game_id"].astype(str).nunique()),
            "start_date": str(pd.to_datetime(dataset["game_date"]).min().date()),
            "end_date": str(pd.to_datetime(dataset["game_date"]).max().date()),
        },
        "configuration": {
            "min_train_groups": args.min_train_groups,
            "min_train_games": args.min_train_games,
            "test_group_count": args.test_group_count,
            "max_folds": args.max_folds,
            "half_life_days": args.half_life_days,
            "prior_games": args.prior_games,
            "include_matchbalance_learned": not args.skip_learned,
            "promotion_baseline": args.promotion_baseline,
        },
        "folds": [asdict(fold) for fold in result.folds],
        "failures": list(result.failures),
        "aggregate_metrics": finite_json_records(result.aggregate_metrics),
        "segment_metrics": finite_json_records(result.segment_metrics),
        "feature_coverage": feature_coverage,
        "promotion": promotion,
        "activation_policy": (
            "Evidence only. A promotion decision never replaces the production model "
            "without a separately reviewed artifact change."
        ),
    }
    manifest["report_sha256"] = report_digest(manifest)
    _write_json(output_dir / "laboratory_manifest.json", manifest)
    print(json.dumps({
        "output_dir": str(output_dir),
        "folds": len(result.folds),
        "candidates": candidates,
        "failures": len(result.failures),
        "promotion": {key: value["decision"] for key, value in promotion.items()},
        "report_sha256": manifest["report_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
