"""One private, immutable result snapshot for the sealed weekend diagnostic."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter

import numpy as np
from storage3.exceptions import StorageApiError

from src.predictions.archive_inputs import _object_bytes
from src.predictions.evaluation_reporting import (
    build_probability_calibration_table,
    compute_evaluation_summary,
    outcome_log_losses,
)
from src.predictions.form_dataset import RESULT_FIELDS, SETTLEMENT_FIELDS, _result_error, _selected_rows
from src.predictions.form_research import evaluation_frame, timestamp
from src.predictions.weekend_tuning import ARMS, DEFINITION
from src.rankings.archive_storage import BUCKET
from src.rankings.input_archive import FORECAST_TABLE, encoded


def results_open(server_time):
    return timestamp(server_time) >= timestamp(DEFINITION["results_open"])


def read_final(client, study_sha):
    bucket = client.storage.from_(BUCKET)
    try:
        marker = json.loads(bucket.download(f"weekend-tuning/{study_sha}/report.json"))
    except StorageApiError as error:
        if error.status == 404 or error.code in {"NoSuchKey", "not_found"}:
            return None
        raise
    if marker.get("study_manifest_sha256") != study_sha or marker.get("status") not in {
        "preliminary_diagnostic",
        "insufficient_data",
    }:
        raise ValueError("Invalid immutable weekend report marker")
    report = json.loads(_object_bytes(bucket.download(marker["report"]["object"]), marker["report"]))
    if (
        report.get("study_manifest_sha256") != study_sha
        or report.get("definition") != DEFINITION
        or report.get("status") != marker["status"]
        or not results_open(report["server_observed_at"])
    ):
        raise ValueError("Immutable weekend report does not match its registration")
    return report


def save_final(client, report):
    """First valid marker wins, including a lost acknowledgement or a concurrent run."""
    sha = report["study_manifest_sha256"]
    raw = encoded(report)
    identity = hashlib.sha256(raw).hexdigest()
    reference = {"object": f"objects/{identity}.gz", "sha256": identity, "bytes": len(raw)}
    bucket = client.storage.from_(BUCKET)
    try:
        bucket.upload(
            reference["object"], gzip.compress(raw, mtime=0), {"content-type": "application/gzip", "upsert": "false"}
        )
    except Exception:
        # An uncertain upload is never repeated blindly; verify its exact content first.
        if _object_bytes(bucket.download(reference["object"]), reference) != raw:
            raise ValueError("Private weekend result upload could not be verified") from None
    _object_bytes(bucket.download(reference["object"]), reference)
    marker = {"study_manifest_sha256": sha, "status": report["status"], "report": reference}
    try:
        bucket.upload(
            f"weekend-tuning/{sha}/report.json",
            encoded(marker),
            {"content-type": "application/json", "upsert": "false"},
        )
    except Exception:
        existing = read_final(client, sha)
        if existing is None:
            raise
        return existing
    return read_final(client, sha)


def paired_interval(groups, differences):
    keys = sorted(set(groups))
    sums = np.array([sum(d for g, d in zip(groups, differences) if g == key) for key in keys])
    counts = np.array([groups.count(key) for key in keys])
    policy = DEFINITION["bootstrap"]
    draws = np.random.default_rng(policy["seed"]).integers(0, len(keys), (policy["samples"], len(keys)))
    estimates = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lower, upper = np.quantile(estimates, [0.0125, 0.9875])
    return {
        "candidate_minus_baseline": float(np.mean(differences)),
        "lower": float(lower),
        "upper": float(upper),
        "confidence": policy["comparison_interval"],
        "family_confidence": policy["family_confidence"],
        "groups": len(keys),
    }


def final_summary(report):
    return {
        "status": report["status"],
        "report_saved": True,
        "reused_final_report": True,
        "paired_settled_matches": report["paired_settled_matches"],
        "outcomes_read": False,
    }


def _metrics(cases, records):
    selected = {c["fixture"]["source_game_id"] for c in cases}
    frames = {
        arm: evaluation_frame(
            cases,
            [
                {"id": r["fixture"]["source_game_id"], "prediction": r["predictions"][arm]}
                for r in records
                if r["fixture"]["source_game_id"] in selected
            ],
        )
        for arm in ARMS
    }
    summaries = {arm: compute_evaluation_summary(frame) for arm, frame in frames.items()}
    comparisons = {
        arm: {
            "log_loss": paired_interval(
                frames["baseline"]["event_group"].tolist(),
                outcome_log_losses(frames[arm]) - outcome_log_losses(frames["baseline"]),
            ),
            "brier_difference": summaries[arm]["brier_score"] - summaries["baseline"]["brier_score"],
        }
        for arm in ARMS[1:]
    }
    slices = {}
    for column in ("provider", "cohort", "history_band"):
        slices[column] = {
            str(value): {
                arm: compute_evaluation_summary(frame[frame[column] == value]) for arm, frame in frames.items()
            }
            for value in sorted(frames["baseline"][column].unique())
        }
    return {
        "metrics": summaries,
        "comparisons": comparisons,
        "slices": slices,
        "probability_calibration": {
            arm: build_probability_calibration_table(frame).to_dict("records") for arm, frame in frames.items()
        },
    }


def evaluate(client, study_sha, loaded, server_time, *, dry_run=True):
    # Deliberately precedes any settlement/result read, even in a preview.
    if not results_open(server_time):
        return {
            "status": "waiting_for_window_close",
            "server_observed_at": server_time,
            "results_open": DEFINITION["results_open"],
            "outcomes_read": False,
        }
    existing = read_final(client, study_sha)
    if existing:
        return final_summary(existing)
    sources, all_members, members, records = loaded
    ledger = _selected_rows(client, FORECAST_TABLE, SETTLEMENT_FIELDS, [m["id"] for m in all_members], "id")
    games = _selected_rows(client, "games", RESULT_FIELDS, [m["source_game_id"] for m in all_members], "id")
    by_source = {m["source_game_id"]: m for m in all_members}
    cases, exclusions, coverage = [], Counter(), Counter()
    for meta in members:
        source = meta["source_game_id"]
        settled = ledger.get(meta["id"])
        reason = _result_error(sources.record(meta["binding"]), settled, games.get(source))
        scores = set()
        for duplicate in meta["duplicate_sources"]:
            other = by_source[duplicate["source_game_id"]]
            other_settled = ledger.get(other["id"])
            if (
                _result_error(sources.record(other["binding"]), other_settled, games.get(other["source_game_id"]))
                is None
            ):
                score = (other_settled["actual_home_score"], other_settled["actual_away_score"])
                scores.add(score if duplicate["home_first"] else score[::-1])
        if len(scores) > 1:
            reason = "conflicting_duplicate_result"
        label = "|".join(meta["coverage"][k] for k in ("provider", "cohort", "history_band"))
        coverage[(label, reason or "paired_settled")] += 1
        if reason:
            exclusions[reason] += 1
        else:
            from src.predictions.form_dataset import _fixture

            cases.append({"fixture": _fixture(meta, settled)})
    groups = len({c["fixture"]["event_group"] for c in cases})
    enough = len(cases) >= DEFINITION["minimum_paired_matches"] and groups >= DEFINITION["minimum_groups"]
    expired = timestamp(server_time) >= timestamp(DEFINITION["insufficient_data_deadline"])
    summary = {
        "status": "preliminary_diagnostic" if enough else "insufficient_data" if expired else "awaiting_results",
        "server_observed_at": server_time,
        "paired_forecasts": len(records),
        "paired_settled_matches": len(cases),
        "settled_groups": groups,
        "settled_fraction": len(cases) / len(records),
        "exclusions": dict(exclusions),
        "coverage": [
            {"slice": label, "status": status, "matches": n} for (label, status), n in sorted(coverage.items())
        ],
        "outcomes_read": True,
        "report_saved": False,
        "public_model_changed": False,
    }
    if dry_run or not (enough or expired):
        return summary
    report = {
        **summary,
        "study_manifest_sha256": study_sha,
        "definition": DEFINITION,
        "report_saved": True,
        "interpretation": DEFINITION["decision"],
        "limitations": [
            "Results apply to this weekend and the settled subset only.",
            "Inferred groups are proxies for events, not verified independent events.",
            "Subgroup differences are descriptive; no subgroup significance claims.",
        ],
        "group_kinds": dict(Counter(m["group_kind"] for m in members)),
        "outcome_snapshot": {"ledger": ledger, "games": games},
    }
    if enough:
        report.update(_metrics(cases, records))
    saved = save_final(client, report)
    return {
        key: saved[key]
        for key in (
            "status",
            "paired_forecasts",
            "paired_settled_matches",
            "settled_groups",
            "settled_fraction",
            "report_saved",
            "public_model_changed",
        )
    }
