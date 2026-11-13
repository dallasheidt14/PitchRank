"""Run the pinned TypeScript form experiment on a complete authenticated dataset."""

from __future__ import annotations

import hashlib
import platform
from collections import defaultdict
from importlib.metadata import version
from pathlib import Path

from src.predictions.form_dataset import CASE_BATCH_SIZE, _write_json, dataset_cases, verified_dataset
from src.predictions.form_policy import FORM_CANDIDATES, PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.predictions.form_research import _compare_eligible_outputs, digest, prediction_input_error, residual_form

METRIC_FIELDS = (
    "winProbabilityA", "drawProbability", "winProbabilityB", "blowout4PlusProbability",
    "predictedWinner", "expectedMargin", "expectedScore",
)


def benchmark_dataset(
    client, project_url: str, access_token: str, directory: Path, runner,
    output: Path | None = None, *, dry_run: bool = True,
) -> dict:
    """Preview verifies inputs; execute saves local artifacts and evaluates only a closed, sufficient study."""
    if not dry_run and output is None:
        raise ValueError("Dataset benchmarking requires a new output directory")
    report, verified = verified_dataset(client, project_url, access_token, directory)
    if dry_run:
        return {**report, "evaluation": "not_performed"}
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if verified is None or report["status"] != "eligible":
        _write_json(output / "report.json", {**report, "evaluation": "not_performed"})
        return {**report, "evaluation": "not_performed"}
    manifest, policy, sources, eligible = verified
    by_id = {case["fixture"]["source_game_id"]: case for case in eligible}
    outputs, batch, runs = defaultdict(list), [], []

    def run_batch():
        if not batch:
            return
        calibrations = batch[0]["calibrations"]
        if any(digest(case["calibrations"]) != digest(calibrations) for case in batch):
            raise ValueError("A paired baseline batch must share the pinned calibration")
        folder = output / f"batch-{len(runs):05d}"
        folder.mkdir()
        result = runner({"schema_version": 1, "predictor_revision": PINNED_REVISION,
                         "calibrations": calibrations, "cases": batch}, folder)
        if (result.get("aa_parity") is not True or result.get("model_signature") != PINNED_MODEL_SIGNATURE
                or result.get("predictor_revision") != PINNED_REVISION or result.get("cases") != len(batch)):
            raise ValueError("Dataset replay did not establish the registered collecting baseline")
        for name, predictions in result["outputs"].items():
            expected = {case["fixture"]["source_game_id"] for case in batch
                        if not name.endswith("_ml_off") or case["period"] == "development"}
            if len(predictions) != len(expected) or {p["id"] for p in predictions} != expected:
                raise ValueError("Dataset replay did not cover its complete paired batch")
            outputs[name].extend({"id": item["id"], "prediction": {
                key: item["prediction"][key] for key in METRIC_FIELDS
            }} for item in predictions)
        required = set(FORM_CANDIDATES)
        if any(case["period"] == "development" for case in batch):
            required.update(name + "_ml_off" for name in FORM_CANDIDATES[1:])
        if set(result["outputs"]) != required:
            raise ValueError("Dataset replay is missing a declared form candidate")
        runs.append({"directory": folder.name, "cases": len(batch), "aa_parity": True,
                     "runner_input_sha256": hashlib.sha256((folder / "runner-input.json").read_bytes()).hexdigest(),
                     "runner_output_sha256": hashlib.sha256((folder / "runner-output.json").read_bytes()).hexdigest()})
        batch.clear()

    for case in dataset_cases(directory, manifest):
        identity = case["fixture"]["source_game_id"]
        if identity not in by_id:
            continue
        retained = by_id[identity]
        if (digest(case["fixture"]) != digest(retained["fixture"])
                or prediction_input_error(case, case["fixture"]["game_date"], sources)):
            raise ValueError("Dataset changed after its complete cohort audit")
        case["period"] = retained["period"]
        diagnostics = {
            name: {case[team]["team_id_master"]: residual_form(
                case[team]["team_id_master"], case["games"], case["expectations"],
                case["fixture"]["game_date"], name, sources,
            ) for team in ("teamA", "teamB")} for name in FORM_CANDIDATES[1:]
        }
        retained["formDiagnostics"] = case["formDiagnostics"] = diagnostics
        case["formOverrides"] = {name: {team: value["value"] for team, value in values.items()}
                                 for name, values in diagnostics.items()}
        batch.append(case)
        if len(batch) == CASE_BATCH_SIZE:
            run_batch()
    run_batch()
    result = _compare_eligible_outputs(eligible, report["audit"], outputs, policy)
    result.update(study_manifest_sha256=report["study_manifest_sha256"],
                  server_observed_at=report["server_observed_at"], evaluation_status="performed",
                  dataset_sha256=hashlib.sha256((directory / "dataset.json").read_bytes()).hexdigest(),
                  aa_parity=True, batches=runs, production_promotion=False,
                  runtime={"python": platform.python_version(),
                           **{name: version(name) for name in ("numpy", "pandas", "scipy")}})
    _write_json(output / "report.json", result)
    return result
