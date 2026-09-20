"""Read-only benchmark of frozen Compare forecasts; never deploys a calibrator."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_prospective_match_predictions import _fetch_rows, _supabase_client  # noqa: E402
from src.predictions.compare_benchmark import BenchmarkConfig, run_benchmark  # noqa: E402


def current_compare_version() -> str:
    source = (ROOT / "frontend/lib/matchPredictionService.ts").read_text(encoding="utf-8")
    versions = re.findall(r"export const MATCH_PREDICTION_VERSION = ['\"]([^'\"]+)['\"]", source)
    if len(versions) != 1:
        raise ValueError("Cannot identify the current canonical Compare version.")
    return versions[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, help="Frozen prospective rows as JSON; otherwise reads settled database rows"
    )
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--train-end", required=True, help="Last development game date, YYYY-MM-DD")
    parser.add_argument("--test-start", required=True, help="First untouched holdout game date, YYYY-MM-DD")
    parser.add_argument("--test-end", required=True)
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="New directory; existing results are never overwritten"
    )
    args = parser.parse_args()
    config = BenchmarkConfig(args.model_version, args.train_end, args.test_start, args.test_end)
    config.validate()
    rows = json.loads(args.input.read_text(encoding="utf-8")) if args.input else _fetch_rows(_supabase_client(), None)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Input must be an array of prospective prediction records.")
    report = run_benchmark(rows, config, args.output_dir, current_model_version=current_compare_version())
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
