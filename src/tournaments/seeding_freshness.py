"""Freshness evidence and explicit acknowledgment for immutable saved snapshots."""

import hashlib
import json
from datetime import datetime, timezone


def snapshot_identity(pack: dict) -> str:
    fields = ("generated_at", "predictor_sha256", "input_digests", "cohort_fingerprints",
              "selected_cohorts", "teams", "predictions", "policy", "manual_seed_orders",
              "operator_notes", "tier_names", "format_library", "format_profile_id",
              "format_preferences", "cohort_format_preferences",
              "ratings_as_of", "ratings", "unavailable", "unavailable_codes",
              "prediction_model", "ordering_method", "input_evidence", "calibration_inputs", "sensitivity_predictions")
    return hashlib.sha256(json.dumps({key: pack.get(key) for key in fields},
                                   sort_keys=True, allow_nan=False).encode()).hexdigest()


def check_freshness(pack: dict, batch) -> dict:
    captured = pack.get("input_digests", {})
    current = batch.input_digests
    selected = set(pack["selected_cohorts"])
    status = "not_checked"
    if captured and set(captured) == selected and set(current) == selected:
        status = ("verified_current" if captured == current and pack["predictor_sha256"] == batch.predictor_sha256
                  else "newer_inputs_available")
    return {"status": status, "checked_at": datetime.now(timezone.utc).isoformat(),
            "changes": _input_changes(pack, batch),
            "snapshot_identity": snapshot_identity(pack)}


def _input_changes(pack, batch):
    changes = []
    if pack.get("predictor_sha256") != batch.predictor_sha256:
        changes.append("Prediction code or calibration files changed.")
    for cohort in sorted(pack["selected_cohorts"]):
        if pack.get("input_digests", {}).get(cohort) == batch.input_digests.get(cohort):
            continue
        old = pack.get("input_evidence", {}).get(cohort, {}).get("canonical_json")
        new = getattr(batch, "evidence", {}).get(cohort, {}).get("canonical_json")
        if not old or not new:
            changes.append(f"{cohort}: exact field comparison unavailable for this older snapshot.")
            continue
        before, after = json.loads(old), json.loads(new)
        for field in sorted(set(before) | set(after)):
            if before.get(field) == after.get(field):
                continue
            if field == "games":
                saved = {row["id"]: row for row in before.get(field, [])}
                current = {row["id"]: row for row in after.get(field, [])}
                modified = sum(saved[key] != current[key] for key in saved.keys() & current.keys())
                summary = (f"game history: {len(current.keys() - saved.keys())} added, "
                           f"{len(saved.keys() - current.keys())} removed, {modified} changed")
            elif field in {"teams", "opponents"}:
                saved, current = before.get(field, {}), after.get(field, {})
                names = sorted({name for team in saved.keys() | current.keys()
                                for name in saved.get(team, {}).keys() | current.get(team, {}).keys()
                                if saved.get(team, {}).get(name) != current.get(team, {}).get(name)})
                summary = f"{field}: changed fields " + ", ".join(names)
            elif field in {"as_of", "window_start", "model"}:
                summary = f"{field}: {before.get(field)} → {after.get(field)}"
            else:
                summary = f"{field.replace('_', ' ')} changed"
            changes.append(f"{cohort}: {summary}.")
    return changes


def acknowledge_freshness(pack: dict, reason: str) -> dict:
    if not reason.strip():
        raise ValueError("Record why this dated snapshot is suitable for delivery.")
    return {"snapshot_identity": snapshot_identity(pack), "reason": reason.strip(),
            "acknowledged_at": datetime.now(timezone.utc).isoformat()}


def freshness_ready(pack: dict, verified_identity: str | None = None) -> bool:
    identity = snapshot_identity(pack)
    check = pack.get("freshness_check") or {}
    check = check if isinstance(check, dict) else {}
    verified = (verified_identity == identity and check.get("snapshot_identity") == identity
                and check.get("status") == "verified_current")
    acknowledgment = pack.get("freshness_acknowledgment") or {}
    acknowledgment = acknowledgment if isinstance(acknowledgment, dict) else {}
    return verified or bool(acknowledgment.get("snapshot_identity") == identity
                            and isinstance(acknowledgment.get("reason"), str)
                            and acknowledgment["reason"].strip()
                            and acknowledgment.get("acknowledged_at"))


def freshness_note(pack: dict, verified_identity: str | None = None) -> str:
    identity = snapshot_identity(pack)
    check = pack.get("freshness_check") or {}
    check = check if isinstance(check, dict) else {}
    acknowledgment = pack.get("freshness_acknowledgment") or {}
    acknowledgment = acknowledgment if isinstance(acknowledgment, dict) else {}
    if acknowledgment.get("snapshot_identity") == identity and freshness_ready(pack):
        return (f"Dated snapshot accepted by operator on {acknowledgment['acknowledged_at']}: "
                f"{acknowledgment['reason']}")
    if check.get("snapshot_identity") == identity and check.get("checked_at"):
        status = check.get("status") if verified_identity == identity else "not_checked"
        label = {"verified_current": "Verified current", "newer_inputs_available": "Newer inputs available",
                 "not_checked": "Not checked in this session"}.get(status, "Not checked")
        return f"{label}. Last freshness check: {check['checked_at']}."
    return "Freshness not checked. This is a dated saved snapshot."
