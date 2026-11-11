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
from src.predictions.compare_benchmark import BenchmarkConfig, config_from_manifest, run_benchmark  # noqa: E402


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
    experiment = parser.add_mutually_exclusive_group()
    experiment.add_argument("--manifest", type=Path, help="Saved immutable experiment manifest")
    experiment.add_argument("--experiment-signature", help="Read this experiment's manifest from the database")
    parser.add_argument("--model-version", help="Legacy research mode only")
    parser.add_argument("--train-end", help="Legacy last development game date, YYYY-MM-DD")
    parser.add_argument("--test-start", help="Legacy first holdout game date, YYYY-MM-DD")
    parser.add_argument("--test-end", help="Legacy last holdout game date")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="New directory; existing results are never overwritten"
    )
    args = parser.parse_args()
    if args.manifest and not args.input:
        parser.error("A manifest file requires frozen --input; live ledger reads require --experiment-signature.")
    manifest = None
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    elif args.experiment_signature:
        manifest = (_supabase_client().table("compare_calibration_experiments").select("*")
                    .eq("model_signature", args.experiment_signature).single().execute().data)
    if manifest is not None:
        if any((args.model_version, args.train_end, args.test_start, args.test_end)):
            parser.error("Registered experiment settings cannot be overridden.")
        config = config_from_manifest(manifest)
    else:
        if not all((args.model_version, args.train_end, args.test_start, args.test_end)):
            parser.error("Choose a registered experiment, or supply all four legacy research arguments.")
        config = BenchmarkConfig(args.model_version, args.train_end, args.test_start, args.test_end)
    config.validate()
    rows = json.loads(args.input.read_text(encoding="utf-8")) if args.input else _fetch_rows(_supabase_client(), None)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Input must be an array of prospective prediction records.")
    report = run_benchmark(rows, config, args.output_dir, current_model_version=current_compare_version(),
                           experiment_manifest=manifest)
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
