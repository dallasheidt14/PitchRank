"""Register and capture immutable score-only pairs through restricted server functions."""

from collections import Counter
from pathlib import Path

from src.predictions.score_study import (
    digest,
    score_payload,
    serialized,
    source_identity,
    validate_definition,
    verified_fit,
)
from src.rankings.archive_storage import _retry_transport


def registered_study(client, signature):
    record = _retry_transport(lambda: client.table("compare_score_studies").select("*")
                              .eq("signature", signature).single().execute()).data
    manifest = record["manifest"]
    validate_definition(manifest, registered_at=record["registered_at"])
    if digest(serialized(manifest).encode()) != signature:
        raise ValueError("Study manifest signature differs")
    return manifest


def model_from_storage(client, manifest):
    artifact = manifest["artifact"]
    bundle = _retry_transport(lambda: client.storage.from_(artifact["bucket"]).download(artifact["object"]))
    return verified_fit(bundle, manifest)


def register_study(client, manifest, root: Path, *, dry_run=True):
    validate_definition(manifest)
    identity = source_identity(root)
    if any(identity[key] != manifest[key] for key in identity):
        raise ValueError("Registration source differs from the committed research code")
    model_from_storage(client, manifest)
    monitor = _retry_transport(lambda: client.table("compare_monitoring_models").select("manifest")
                              .eq("signature", manifest["monitor_signature"]).single().execute()).data
    if monitor["manifest"]["model_signature"] != manifest["baseline_model_signature"]:
        raise ValueError("Wrong registered current Compare baseline")
    signature = digest(serialized(manifest).encode())
    if not dry_run:
        result = _retry_transport(lambda: client.rpc("register_compare_score_study", {
            "p_manifest": serialized(manifest),
        }).execute()).data
        if result != signature or registered_study(client, signature) != manifest:
            raise ValueError("Registration readback differs")
    return {"dry_run": dry_run, "study_signature": signature, "registered": not dry_run,
            "capture_start": manifest["capture_start"], "capture_end": manifest["capture_end"],
            "review_not_before": manifest["review_not_before"]}


def capture_scores(client, signature: str, root: Path, *, dry_run=True, limit=500):
    if not 1 <= limit <= 500:
        raise ValueError("Capture limit must be between 1 and 500")
    manifest = registered_study(client, signature)
    identity = source_identity(root)
    if any(identity[key] != manifest[key] for key in identity):
        raise ValueError("Capture source differs from the registered research code")
    # Queue retrieval and coverage never read target outcomes. Preview performs no writes, including files.
    rows = _retry_transport(lambda: client.rpc("compare_score_capture_queue", {
        "p_signature": signature, "p_limit": limit,
    }).execute()).data or []
    summary = {"dry_run": dry_run, "study_signature": signature, "selected": len(rows),
               "captured": 0, "already_captured": 0, "errors": {}, "eligibility": {}}
    counts, errors = Counter(), Counter()
    fit = model_from_storage(client, manifest) if rows else None
    for row in rows:
        try:
            payload = score_payload(row, manifest, fit, signature)
            counts[payload["eligibility"]] += 1
            if not dry_run:
                saved = _retry_transport(lambda: client.rpc("freeze_compare_score_forecast", {
                    "p_signature": signature, "p_baseline": row["baseline_forecast_id"],
                    "p_payload": serialized(payload),
                }).execute()).data
                stored = _retry_transport(lambda: client.table("compare_score_forecasts")
                    .select("payload_sha256,payload,captured_at")
                    .eq("study_signature", signature).eq("baseline_forecast_id", row["baseline_forecast_id"])
                    .single().execute()).data
                if stored["payload"] != payload or stored["payload_sha256"] != digest(serialized(payload).encode()):
                    raise ValueError("Captured score readback differs")
                summary["captured" if saved else "already_captured"] += 1
        except Exception as error:
            # Report error classes rather than request bodies, frozen inputs, or credential-bearing exceptions.
            errors[type(error).__name__] += 1
    summary.update(eligibility=dict(counts), errors=dict(errors))
    summary["coverage"] = _retry_transport(lambda: client.rpc("compare_score_coverage", {
        "p_signature": signature,
    }).execute()).data or []
    return summary
