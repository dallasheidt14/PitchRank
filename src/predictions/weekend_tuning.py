"""A sealed three-arm weekend diagnostic, independent of the registered form study."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from src.predictions.archive_inputs import RegisteredArchive
from src.predictions.forecast_archive import FORECAST_FIELDS
from src.predictions.form_archive_sources import FrozenSourceIndex
from src.predictions.form_dataset import _fixture, _selected_rows, grouped_members
from src.predictions.form_policy import PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.predictions.form_research import digest, finite, prediction_input_error, timestamp
from src.rankings.archive_storage import publish_archive
from src.rankings.input_archive import FORECAST_ARCHIVE_KIND, FORECAST_TABLE, InputArchive, encoded

ROOT = Path(__file__).resolve().parents[2]
ARMS = ("baseline", "calibration_075", "form_off")
EXTRA_SOURCES = ("scripts/compare_weekend_tuning.py", ".github/workflows/compare-weekend-tuning.yml")
DEFINITION = {
    "schema_version": 1,
    "study_id": "compare-weekend-2026-11-14",
    "match_start": "2026-11-14",
    "match_end": "2026-11-15",
    "registration_deadline": "2026-11-14T00:00:00+00:00",
    "results_open": "2026-11-16T00:00:00+00:00",
    "insufficient_data_deadline": "2026-11-23T00:00:00+00:00",
    "baseline_signature": PINNED_MODEL_SIGNATURE,
    "predictor_revision": PINNED_REVISION,
    "arms": {
        "baseline": "saved collecting forecast; outcome alpha 0.55",
        "calibration_075": "only change outcome calibration alpha to 0.75",
        "form_off": "only replace both recent-form scalar contributions with zero",
    },
    "minimum_paired_matches": 1000,
    "minimum_groups": 20,
    "primary_metric": "multiclass_log_loss",
    "secondary_metric": "multiclass_brier_score",
    "bootstrap": {
        "samples": 2000,
        "seed": 20261113,
        "comparison_interval": 0.975,
        "family_confidence": 0.95,
        "comparisons": 2,
        "unit": "frozen_event_or_inferred_group",
    },
    "report_policy": "first sufficient closed-window snapshot, otherwise insufficient-data report at deadline",
    "settlement": "exact source only; unchanged completed forecast; exclude conflicting physical duplicates",
    "decision": "preliminary diagnostic only; no selection, qualification, deployment, or parameter fitting",
    "existing_studies": "unchanged; no November 16 or later targets or outcomes",
}


def require_registration_time(server_time: str) -> None:
    if timestamp(server_time) >= timestamp(DEFINITION["registration_deadline"]):
        raise ValueError("Weekend registration deadline has passed")


def prediction_check(prediction: dict) -> None:
    values = [prediction.get(k) for k in ("winProbabilityA", "drawProbability", "winProbabilityB")]
    risk = prediction.get("blowout4PlusProbability")
    score = prediction.get("expectedScore", {})
    if (
        not all(finite(v) and 0 <= v <= 1 for v in values)
        or abs(sum(values) - 1) > 1e-8
        or not finite(risk)
        or not 0 <= risk <= 1
        or not finite(prediction.get("expectedMargin"))
        or prediction.get("predictedWinner") not in {"team_a", "team_b", "draw"}
        or not isinstance(score, dict)
        or not all(finite(score.get(k)) and score[k] >= 0 for k in ("teamA", "teamB"))
    ):
        raise ValueError("Incomplete weekend probability, score, margin, or risk output")


def eligible_inputs(sources):
    all_members = [
        m for m in sources.preferred_members() if DEFINITION["match_start"] <= m["game_date"] <= DEFINITION["match_end"]
    ]
    members, exclusions, _ = grouped_members(all_members)
    cases, retained = [], []
    for meta in members:
        case = sources.case_inputs(meta["binding"])
        case.update(predictor_revision=PINNED_REVISION, fixture=_fixture(meta, None))
        reason = prediction_input_error(case, meta["game_date"], sources)
        if reason:
            exclusions[reason] += 1
        else:
            prediction_check(case["frozenPrediction"])
            cases.append(case)
            retained.append(meta)
    return all_members, retained, cases, dict(exclusions)


def _checked_run(result, cases, *, baseline=True):
    expected = {c["fixture"]["source_game_id"] for c in cases}
    required = {"baseline", "form_off"} if baseline else {"baseline"}
    if (
        result.get("aa_parity") is not True
        or result.get("predictor_revision") != PINNED_REVISION
        or result.get("cases") != len(cases)
        or set(result.get("outputs", {})) != required
        or not finite(result.get("saved_replay_maximum_difference"))
        or result["saved_replay_maximum_difference"] > 1e-12
    ):
        raise ValueError("Weekend replay parity or complete arms not established")
    if hashlib.sha256(result["model_signature_payload"].encode()).hexdigest() != result["model_signature"]:
        raise ValueError("Replay model signature is inconsistent")
    if baseline and result["model_signature"] != PINNED_MODEL_SIGNATURE:
        raise ValueError("Weekend replay changed the collecting signature")
    for outputs in result["outputs"].values():
        if len(outputs) != len(expected) or {p["id"] for p in outputs} != expected:
            raise ValueError("Weekend replay does not cover the exact paired batch")
        for output in outputs:
            prediction_check(output["prediction"])


def replay_candidates(cases, runner, output: Path):
    """Replay the real predictor twice; no hand-written probability approximation."""
    if not cases:
        raise ValueError("No eligible weekend cases")
    records, receipts = [], []
    from src.predictions.form_dataset import CASE_BATCH_SIZE

    for start in range(0, len(cases), CASE_BATCH_SIZE):
        batch = deepcopy(cases[start : start + CASE_BATCH_SIZE])
        calibrations = batch[0]["calibrations"]
        if any(digest(c["calibrations"]) != digest(calibrations) for c in batch):
            raise ValueError("Weekend batch must share one verified collecting calibration")
        if calibrations["heuristic_outcome_calibration.json"].get("alpha") != 0.55:
            raise ValueError("Expected collecting calibration alpha 0.55")
        for case in batch:
            case["formOverrides"] = {"form_off": {case[t]["team_id_master"]: 0 for t in ("teamA", "teamB")}}
        folder = output / f"batch-{start:05d}"
        folder.mkdir()
        baseline_folder, alternative_folder = folder / "current", folder / "calibration-075"
        baseline_folder.mkdir()
        alternative_folder.mkdir()
        payload = {
            "schema_version": 1,
            "predictor_revision": PINNED_REVISION,
            "calibrations": calibrations,
            "cases": batch,
        }
        baseline = runner(payload, baseline_folder)
        _checked_run(baseline, batch)
        alternative_payload = deepcopy(payload)
        alternative_payload["calibrations"]["heuristic_outcome_calibration.json"]["alpha"] = 0.75
        for case in alternative_payload["cases"]:
            case.pop("frozenPrediction")
            case.pop("formOverrides")
            case["calibrations"] = deepcopy(alternative_payload["calibrations"])
        alternative = runner(alternative_payload, alternative_folder)
        _checked_run(alternative, batch, baseline=False)
        current_signature = json.loads(baseline["model_signature_payload"])
        expected_signature = deepcopy(current_signature)
        expected_signature["calibration"]["outcome"]["alpha"] = 0.75
        if json.loads(alternative["model_signature_payload"]) != expected_signature or any(
            alternative[k] != baseline[k]
            for k in ("algorithm_hash", "source_hashes", "research_script_sha256", "generated_source_sha256")
        ):
            raise ValueError("Calibration challenger changed more than the declared alpha")
        form_outputs = {p["id"]: p["prediction"] for p in baseline["outputs"]["form_off"]}
        calibration_outputs = {p["id"]: p["prediction"] for p in alternative["outputs"]["baseline"]}
        for case in batch:
            identity = case["fixture"]["source_game_id"]
            records.append(
                {
                    "fixture": case["fixture"],
                    "predictions": {
                        "baseline": case["frozenPrediction"],
                        "form_off": form_outputs[identity],
                        "calibration_075": calibration_outputs[identity],
                    },
                }
            )
        receipts.append(
            {
                "cases": len(batch),
                "runs": [
                    {
                        **{k: result[k] for k in result if k != "outputs"},
                        "input_sha256": hashlib.sha256((path / "runner-input.json").read_bytes()).hexdigest(),
                        "output_sha256": hashlib.sha256((path / "runner-output.json").read_bytes()).hexdigest(),
                    }
                    for path, result in ((baseline_folder, baseline), (alternative_folder, alternative))
                ],
            }
        )
    return records, receipts


def clean_revision(root: Path):
    changed = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root)
    if changed:
        raise ValueError("Weekend registration requires a clean committed checkout")


def register_bundle(client, root, sources, records, receipts, output, source_archives):
    clean_revision(root)
    all_members, members, cases, exclusions = eligible_inputs(sources)
    validate_records(records, members, cases, sources)
    if not records:
        raise ValueError("Cannot register an empty weekend diagnostic")
    archive = InputArchive(
        output,
        root,
        {
            "capture_kind": FORECAST_ARCHIVE_KIND,
            "window_start": DEFINITION["match_start"],
            "window_end": DEFINITION["match_end"],
            "database_writes_enabled": False,
        },
    )
    success = False
    try:
        live = _selected_rows(
            archive.wrap(client), FORECAST_TABLE, FORECAST_FIELDS, [m["id"] for m in all_members], "id"
        )
        for meta in all_members:
            if digest(live.get(meta["id"])) != digest(sources.record(meta["binding"])):
                raise ValueError("Completed forecast changed before weekend registration")
        for name in EXTRA_SOURCES:
            archive.manifest["source_files"][name] = archive.blob((root / name).read_bytes(), "source")
        archive.manifest["weekend_tuning"] = {
            "definition": deepcopy(DEFINITION),
            "source_archives": sorted(source_archives),
            "predictions": archive.blob(encoded(records), "weekend_predictions"),
            "receipts": archive.blob(encoded(receipts), "weekend_runner_receipts"),
            "excluded_inputs": exclusions,
            "raw_members": len(all_members),
            "paired_members": len(members),
            "groups": len({r["fixture"]["event_group"] for r in records}),
        }
        success = True
    finally:
        archive.finish(success)
    result = publish_archive(client, output, dry_run=False)
    require_registration_time(result["recorded_at"])
    # Publishing verifies every remote object. Rebuild membership from the new
    # archive too, since its query pages need not have the source's row order.
    load_bundle(
        RegisteredArchive(
            output.resolve(), result["manifest_sha256"], result["recorded_at"], deepcopy(archive.manifest)
        ),
        root,
    )
    return {
        **result,
        "paired_forecasts": len(records),
        "groups": archive.manifest["weekend_tuning"]["groups"],
        "public_model_changed": False,
        "existing_studies_changed": False,
    }


def validate_records(records, members, cases, sources):
    by_source = {m["source_game_id"]: m for m in members}
    by_case = {c["fixture"]["source_game_id"]: c for c in cases}
    if (
        not isinstance(records, list)
        or len(records) != len(by_source)
        or {r["fixture"]["source_game_id"] for r in records} != set(by_source)
    ):
        raise ValueError("Weekend records must cover every eligible paired fixture exactly once")
    for record in records:
        identity = record["fixture"]["source_game_id"]
        meta, case = by_source[identity], by_case[identity]
        if record["fixture"] != _fixture(meta, None) or set(record["predictions"]) != set(ARMS):
            raise ValueError("Weekend membership, grouping, or arms changed")
        if digest(record["predictions"]["baseline"]) != digest(case["frozenPrediction"]):
            raise ValueError("Weekend baseline is not the original frozen prediction")
        for prediction in record["predictions"].values():
            prediction_check(prediction)


def load_bundle(archive, root=ROOT):
    require_registration_time(archive.recorded_at)
    attachment = archive.manifest.get("weekend_tuning", {})
    if attachment.get("definition") != DEFINITION:
        raise ValueError("Weekend registered rules differ from the fixed protocol")
    sources = FrozenSourceIndex([archive], root)
    all_members, members, cases, exclusions = eligible_inputs(sources)
    records = archive.object_json(attachment["predictions"])
    validate_records(records, members, cases, sources)
    if (
        attachment.get("raw_members") != len(all_members)
        or attachment.get("paired_members") != len(members)
        or attachment.get("groups") != len({m["event_group"] for m in members})
        or attachment.get("excluded_inputs") != exclusions
    ):
        raise ValueError("Weekend registered coverage is inconsistent")
    clean_revision(root)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if revision != archive.manifest["source_revision"]:
        raise ValueError("Run the immutable registered weekend revision")
    for name in (*EXTRA_SOURCES, "src/predictions/weekend_tuning.py", "src/predictions/weekend_tuning_report.py"):
        archived = archive.object_bytes(archive.manifest["source_files"][name]).decode().replace("\r\n", "\n")
        if archived != (root / name).read_text(encoding="utf-8"):
            raise ValueError("Run the immutable registered weekend revision")
    return sources, all_members, members, records
