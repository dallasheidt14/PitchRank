"""Review live Compare and qualify SOS experiments. Preview writes and reads no outcomes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.predictions.sos_monitoring import (  # noqa: E402
    collect_review,
    coverage_rows,
    evaluate_sos,
    models,
    weekly_report,
)


def run(client, *, execute=False, output=None, register=False):
    if execute and output is None:
        raise ValueError("Execution requires a new private output directory")
    if register and not execute:
        raise ValueError("Selection registration requires --execute")
    if execute:
        output.mkdir(parents=True, exist_ok=False)
    summary = {
        "models": 0,
        "captured": 0,
        "sealed_or_future": 0,
        "settled": 0,
        "errors": 0,
        "production_promotion": False,
        "execute": execute,
    }
    for model in models(client):
        signature = model["signature"]
        records, coverage, metadata = collect_review(client, signature, dry_run=not execute)
        coverage["paired_capture"] = coverage_rows(client, signature)
        summary["models"] += 1
        for key in ("captured", "sealed_or_future", "settled"):
            summary[key] += coverage["counts"].get(key, 0)
        if not execute:
            continue
        selection_rows = (
            client.table("compare_sos_selections").select("*").eq("monitor_signature", signature).execute().data
        )
        selection = selection_rows[0] if selection_rows else None
        # Database clock, never the caller's clock, decides study closure.
        clock = client.rpc("compare_monitor_clock", {}).execute().data
        report = weekly_report(records, coverage, clock)
        report["monitor_signature"] = signature
        profile = model["manifest"].get("runtime_profile")
        report["runtime_profile"] = profile
        report["baseline_configuration"] = (
            "verified_website_runtime" if profile else "repository_files_unverified_against_website"
        )
        benchmark = evaluate_sos(records, metadata, model, selection, clock)
        if register and benchmark["status"] == "selected_for_confirmation" and not selection:
            client.rpc(
                "register_compare_sos_selection",
                {"p_signature": signature, "p_multiplier": float(benchmark["selected"]), "p_report": benchmark},
            ).execute()
        folder = output / signature
        folder.mkdir()
        for name, content in (("review.json", report), ("sos-benchmark.json", benchmark)):
            (folder / name).write_text(json.dumps(content, indent=2, allow_nan=False), encoding="utf-8")
        metrics = report["cumulative"]
        (folder / "review.md").write_text(
            f"# Compare weekly review\n\nModel: `{model['manifest']['model_version']}`\n\n"
            f"Baseline configuration: {report['baseline_configuration']}. "
            "Different configurations are reported separately.\n\n"
            f"Status: {report['status']}. Scored games: {metrics['games']}. "
            f"Sealed or future: {coverage['counts'].get('sealed_or_future', 0)}.\n\n"
            f"Outcome accuracy: {metrics['winner_accuracy']}. Log loss: {metrics['log_loss']}. "
            f"Brier score: {metrics['brier_score']}.\n\n"
            f"SOS experiment: {benchmark['status']}. Live formula changes: none.\n\n"
            "The JSON report includes wins, misses, draws, coverage and schedule-strength slices. "
            "Patterns are hypotheses for testing; small samples do not establish causes.\n",
            encoding="utf-8",
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--register-selection", action="store_true", help="Freeze a qualified development selection; never deploy"
    )
    args = parser.parse_args()
    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    result = run(client, execute=args.execute, output=args.output_dir, register=args.register_selection)
    print(json.dumps(result, allow_nan=False))  # Operational totals only; detailed reports remain private.


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Compare monitoring review failed; no deployment performed.", file=sys.stderr)
        raise SystemExit(1)
