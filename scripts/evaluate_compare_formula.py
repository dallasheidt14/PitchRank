"""Preview coverage or score formula replays against server-released results. No database writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if __name__ == "__main__":
    sys.dont_write_bytecode = True

from src.predictions.formula_diagnostics import formula_accuracy_report, released_formula_records  # noqa: E402
from src.predictions.private_research_output import private_output_path  # noqa: E402
from src.predictions.sos_monitoring import digest  # noqa: E402


def run(client, report, *, execute=False, output=None):
    output = private_output_path(execute, output)
    records, coverage = released_formula_records(client, report, preview=not execute)
    result = formula_accuracy_report(records, coverage)
    result["provenance"] = {
        "observed_at": client.rpc("compare_monitor_clock", {}).execute().data,
        "model_signature": report["model_signature"], "replay_report_sha256": digest(report),
        "input_sha256": report.get("input_sha256"), "input_cutoff": report.get("cutoff"),
        "configuration_sha256": report.get("configuration_sha256"),
        "research_source_hashes": report.get("research_source_hashes"),
        "baseline_revision": report.get("baseline_revision"),
        "evaluation_source_hashes": {
            str(filename.relative_to(ROOT)).replace("\\", "/"):
            hashlib.sha256(filename.read_text(encoding="utf-8").encode()).hexdigest()
            for filename in [Path(__file__), ROOT / "src/predictions/formula_diagnostics.py",
                             ROOT / "src/predictions/evaluation_reporting.py",
                             ROOT / "src/predictions/sos_monitoring.py",
                             ROOT / "src/predictions/compare_benchmark.py"]
        },
        "observations": [{key: row[key] for key in ("baseline_forecast_id", "actual_game_id", "scores",
                                                   "captured_at", "game_date", "group", "group_kind")}
                         for row in records],
    }
    if execute:
        with output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
    return {key: value for key, value in result.items() if key not in ("metrics", "limitations", "provenance")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    from supabase import create_client
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    report = json.loads(args.report.read_text(encoding="utf-8"))
    print(json.dumps(run(client, report, execute=args.execute, output=args.output), allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Formula evaluation failed; no live changes made.", file=sys.stderr)
        raise SystemExit(1)
