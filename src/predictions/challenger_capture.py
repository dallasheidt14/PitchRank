"""Private paired form forecasts. Registration and capture are separate, explicit writes."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.predictions.archive_inputs import _object_bytes, _registered_manifest
from src.predictions.challenger_sources import candidate_execution_paths
from src.predictions.form_archive_sources import FrozenSourceIndex
from src.predictions.form_policy import FORM_CANDIDATES, PINNED_MODEL_SIGNATURE, PINNED_REVISION
from src.predictions.form_research import (
    digest,
    finite,
    match_start,
    prediction_input_error,
    residual_form,
    timestamp,
)
from src.predictions.form_study import committed_research_sources, research_hashes
from src.predictions.form_study_contract import (
    CONFIRMATION,
    FORM_CONFIGURATION,
    FORM_STUDY_KIND,
    validate_study_definition,
)
from src.predictions.prospective_fixtures import paged
from src.rankings.archive_storage import BUCKET

MANIFESTS = "compare_challenger_manifests"
FORECASTS = "compare_challenger_forecasts"
ROOT = Path(__file__).resolve().parents[2]


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def source_identity(root: Path):
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, timeout=30).strip():
        raise ValueError("Use a clean committed candidate checkout")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=30).strip()
    sources = research_hashes(committed_research_sources(root, revision))
    for name in candidate_execution_paths(root) - sources.keys():
        raw = subprocess.check_output(["git", "show", revision + ":" + name], cwd=root, timeout=30)
        sources[name] = hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").encode()).hexdigest()
    # A committed revision alone cannot identify an edited working tree.
    for name, sha in sources.items():
        raw = (root / name).read_text(encoding="utf-8").replace("\r\n", "\n").encode()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise ValueError("Research checkout differs from its committed sources: " + name)
    return revision, sources


def qualified_execution_sources(client, archive, paths, root=ROOT):
    result = {}
    for name in sorted(paths):
        reference = archive["source_files"].get(name)
        if reference is None:
            # A clean study registration also binds the entire immutable Git tree, including uncopied code.
            raw = subprocess.check_output(["git", "show", archive["source_revision"] + ":" + name],
                                          cwd=root, timeout=30)
        else:
            raw = _object_bytes(client.storage.from_(BUCKET).download(reference["object"]), reference)
        result[name] = hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").encode()).hexdigest()
    return result


def candidate_definition(report, revision, sources, *, reviewed=False, qualified_sources=None):
    """A qualification report is necessary; explicit release review remains a separate decision."""
    if not reviewed:
        raise ValueError("Register only after the qualification report has been separately reviewed")
    try:
        if (report["status"] != "qualifies_for_confirmation" or report["production_promotion"] is not False
                or report["aa_parity"] is not True or report["evaluation_status"] != "performed"
                or report["selected_candidate"] not in FORM_CANDIDATES[1:]
                or report["policy"]["predictor_revision"] != PINNED_REVISION
                or report["log_loss_delta_95"][1] >= 0
                or report["evaluation"]["candidate"]["brier_score"] >= report["evaluation"]["baseline"]["brier_score"]):
            raise ValueError("Report does not qualify a form challenger")
        evaluation_closed_at = match_start(report["policy"]["evaluation_end"]) + timedelta(days=1)
        if timestamp(report["server_observed_at"]) < evaluation_closed_at:
            raise ValueError("Qualification evaluation is still sealed")
        periods = report["audit"]["periods"]
        if any(periods[period]["games"] < 1000 or periods[period]["groups"] < 20
               for period in ("development", "evaluation")):
            raise ValueError("Qualification coverage is insufficient")
        for key in ("dataset_sha256", "study_manifest_sha256"):
            if not re.fullmatch(r"[a-f0-9]{64}", report[key]):
                raise ValueError("Qualification requires frozen dataset and study hashes")
        if not re.fullmatch(r"[a-f0-9]{40}", revision) or not sources:
            raise ValueError("Missing committed research identity")
        if not qualified_sources or any(sources.get(name) != sha for name, sha in qualified_sources.items()):
            raise ValueError("Candidate execution sources differ from the qualified study")
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError("Incomplete qualification report") from error
    return {
        "schema_version": 1, "kind": "compare_form_confirmation", "candidate": report["selected_candidate"],
        "baseline_model_signature": PINNED_MODEL_SIGNATURE, "predictor_revision": PINNED_REVISION,
        "research_revision": revision, "research_sources": sources,
        "qualified_execution_sources": deepcopy(qualified_sources),
        "form_configuration": deepcopy(FORM_CONFIGURATION), "confirmation_policy": deepcopy(CONFIRMATION),
        "training_provenance": {"kind": "fixed_form_rules", "trained": False,
                                "baseline_learned_inputs": "unchanged_frozen_baseline_inputs"},
        "qualification": {"status": report["status"], "reviewed": True, "report_sha256": digest(report),
                          "dataset_sha256": report["dataset_sha256"],
                          "study_manifest_sha256": report["study_manifest_sha256"],
                          "evaluation_end": report["policy"]["evaluation_end"], "periods": periods},
        "production_promotion": False,
    }


def register_candidate(client, report, *, reviewed=False, dry_run=True, root=ROOT):
    revision, sources = source_identity(root)
    record, archive, _ = _registered_manifest(client, report["study_manifest_sha256"])
    configuration = archive["configuration"]
    study = configuration["study_definition"]
    policy = validate_study_definition(study, registered_at=record["recorded_at"])
    if (configuration.get("capture_kind") != FORM_STUDY_KIND or vars(policy) != report.get("policy")
            or study.get("form_configuration") != FORM_CONFIGURATION):
        raise ValueError("Qualification report does not match its authenticated registered study")
    qualified = qualified_execution_sources(client, archive, candidate_execution_paths(root), root)
    definition = candidate_definition(report, revision, sources, reviewed=reviewed, qualified_sources=qualified)
    definition["qualification"]["execution_source_revision"] = archive["source_revision"]
    signature = digest(definition)
    if not dry_run:
        saved = client.rpc("register_compare_challenger", {"p_manifest": canonical_json(definition)}).execute().data
        if saved != signature:
            raise ValueError("Server registered a different candidate")
    return {"dry_run": dry_run, "candidate_signature": signature, "definition": definition,
            "registered": not dry_run, "production_promotion": False}


def validate_prediction(prediction):
    probabilities = [prediction.get(key) for key in (
        "winProbabilityA", "drawProbability", "winProbabilityB", "blowout4PlusProbability",
    )]
    if any(not finite(value) or not 0 <= value <= 1 for value in probabilities):
        raise ValueError("Complete finite outcome and four-goal-risk probabilities are required")
    if abs(sum(probabilities[:3]) - 1) > 1e-9 or not finite(prediction.get("expectedMargin")):
        raise ValueError("Invalid outcome probabilities or expected margin")
    scores = prediction.get("expectedScore", {})
    if any(type(scores.get(key)) is not int or scores[key] < 0 for key in ("teamA", "teamB")):
        raise ValueError("Complete nonnegative integer scores are required")


def registered_candidate(client, signature, root=ROOT):
    if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise ValueError("Expected a registered candidate signature")
    record = client.table(MANIFESTS).select("*").eq("candidate_signature", signature).single().execute().data
    definition = record["manifest"]
    revision, hashes = source_identity(root)
    if (digest(definition) != signature or definition.get("research_revision") != revision
            or definition.get("research_sources") != hashes
            or definition.get("form_configuration") != FORM_CONFIGURATION
            or definition.get("confirmation_policy") != CONFIRMATION
            or definition.get("baseline_model_signature") != PINNED_MODEL_SIGNATURE
            or definition.get("candidate") not in FORM_CANDIDATES[1:]):
        raise ValueError("Capture must use the exact registered candidate checkout and configuration")
    return record, revision, hashes


def candidate_queue(client, signature, record, now=None):
    today = (now or datetime.now(timezone.utc)).date().isoformat()
    rows = list(paged(lambda: client.table("prospective_match_predictions").select(
        "id,source_game_id,game_date,provider_code,heuristic_prediction,heuristic_prediction_status"
    ).gte("game_date", record["confirmation_start"]).lte("game_date", record["confirmation_end"])
        .eq("heuristic_prediction_status", "completed").order("id")))
    saved = {row["baseline_forecast_id"] for row in paged(lambda: client.table(FORECASTS)
             .select("baseline_forecast_id").eq("candidate_signature", signature).order("baseline_forecast_id"))}
    rows = [row for row in rows if row["heuristic_prediction"].get("modelSignature") == PINNED_MODEL_SIGNATURE]
    return rows, saved, today


def capture_preflight(client, signature, *, root=ROOT, now=None):
    record, _, _ = registered_candidate(client, signature, root)
    rows, saved, today = candidate_queue(client, signature, record, now)
    eligible = sum(row["id"] not in saved and row["game_date"] > today for row in rows)
    return {"candidate_signature": signature, "baseline_forecasts": len(rows),
            "already_captured": sum(row["id"] in saved for row in rows), "eligible_prematch": eligible,
            "missing_challenger_forecasts": sum(row["id"] not in saved for row in rows),
            "confirmation_start": record["confirmation_start"], "confirmation_end": record["confirmation_end"],
            "status": "ready" if eligible else "confirmation_window_closed" if today > record["confirmation_end"]
            else "no_pending_prematch_forecasts", "production_promotion": False}


def capture_candidate(client, signature, sources: FrozenSourceIndex, runner, *, dry_run=True, limit=500,
                      root=ROOT, now=None):
    """Use authenticated baseline inputs only; the server rechecks deadlines and exact source identity."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    record, revision, hashes = registered_candidate(client, signature, root)
    definition = record["manifest"]
    rows, saved, today = candidate_queue(client, signature, record, now)
    members = {meta["id"]: meta for meta in sources.preferred_members()}
    summary = {"dry_run": dry_run, "candidate_signature": signature, "baseline_forecasts": 0,
               "already_captured": 0, "eligible": 0, "captured": 0, "skipped": Counter(), "errors": Counter(),
               "confirmation_start": record["confirmation_start"], "confirmation_end": record["confirmation_end"],
               "production_promotion": False}
    selected = definition["candidate"]
    for row in sorted(rows, key=lambda item: (item["game_date"], item["id"])):
        if row["heuristic_prediction"].get("modelSignature") != PINNED_MODEL_SIGNATURE:
            continue
        summary["baseline_forecasts"] += 1
        if row["id"] in saved:
            summary["already_captured"] += 1
            continue
        if row["game_date"] <= today:
            summary["skipped"]["prematch_deadline_passed"] += 1
            continue
        if summary["eligible"] >= limit:
            summary["skipped"]["capture_limit"] += 1
            continue
        meta = members.get(row["id"])
        if meta is None or sources.record(meta["binding"])["heuristic_prediction"] != row["heuristic_prediction"]:
            summary["skipped"]["missing_or_conflicting_authenticated_baseline"] += 1
            continue
        case = sources.case_inputs(meta["binding"])
        case.update(predictor_revision=PINNED_REVISION, fixture={key: meta[key] for key in (
            "source_game_id", "game_date", "home_team_master_id", "away_team_master_id",
        )})
        reason = prediction_input_error(case, meta["game_date"], sources)
        if reason:
            summary["skipped"][reason] += 1
            continue
        diagnostics = {case[team]["team_id_master"]: residual_form(
            case[team]["team_id_master"], case["games"], case["expectations"], meta["game_date"], selected, sources,
        ) for team in ("teamA", "teamB")}
        case["formOverrides"] = {selected: {team: value["value"] for team, value in diagnostics.items()}}
        summary["eligible"] += 1
        if dry_run:
            continue  # Preview creates neither temporary files nor database records.
        try:
            with TemporaryDirectory(prefix="compare-challenger-") as workspace:
                result = runner({"schema_version": 1, "predictor_revision": PINNED_REVISION,
                                 "calibrations": case["calibrations"], "cases": [case]}, Path(workspace))
            if (result.get("aa_parity") is not True or result.get("model_signature") != PINNED_MODEL_SIGNATURE
                    or result.get("cases") != 1 or result.get("predictor_revision") != PINNED_REVISION):
                raise ValueError("Pinned baseline parity failed")
            outputs = result["outputs"][selected]
            if len(outputs) != 1 or outputs[0]["id"] != row["source_game_id"]:
                raise ValueError("Challenger output did not match the exact baseline fixture")
            prediction = outputs[0]["prediction"]
            validate_prediction(prediction)
            payload = {
                "frozen_inputs": {"baseline_prediction": row["heuristic_prediction"], "case": case,
                                  "form_diagnostics": diagnostics},
                "prediction": prediction,
                "provenance": {"candidate_signature": signature, "predictor_revision": PINNED_REVISION,
                               "research_revision": revision, "research_sources": hashes, "aa_parity": True,
                               "baseline_archive": meta["binding"], "runner_input_sha256": digest(case),
                               "runner_receipt": {key: value for key, value in result.items() if key != "outputs"},
                               "training_provenance": definition["training_provenance"]},
            }
            inserted = client.rpc("freeze_compare_challenger", {"p_baseline_forecast_id": row["id"],
                "p_candidate_signature": signature, "p_payload": canonical_json(payload)}).execute().data
            if inserted is True:
                summary["captured"] += 1
            elif inserted is False:
                summary["already_captured"] += 1
            else:
                raise ValueError("Unexpected challenger capture result")
        except Exception as error:
            # Count failures without exposing frozen inputs or credentials.
            summary["errors"][type(error).__name__] += 1
    summary["skipped"], summary["errors"] = dict(summary["skipped"]), dict(summary["errors"])
    return summary
