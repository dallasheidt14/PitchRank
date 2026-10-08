"""Freshness evidence and explicit acknowledgment for immutable saved snapshots."""

import hashlib
import json
from datetime import datetime, timezone


def snapshot_identity(pack: dict) -> str:
    fields = ("generated_at", "predictor_sha256", "input_digests", "cohort_fingerprints",
              "selected_cohorts", "teams", "predictions", "policy", "manual_seed_orders",
              "operator_notes", "tier_names", "format_library", "format_profile_id",
              "ratings_as_of", "ratings", "unavailable", "unavailable_codes")
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
            "snapshot_identity": snapshot_identity(pack)}


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
