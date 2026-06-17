"""Address verification + the per-slice invalid-rate gate via NeverBounce.

``verify_and_gate`` verifies the still-unverified rows in a slice (resumable:
already-verified rows are skipped so a crashed run never re-charges
NeverBounce), then gates on the hard-invalid fraction. A clean slice promotes
``valid`` rows to ``verified`` and holds the rest; a dirty slice (> threshold)
holds the whole slice and promotes nothing. ``held`` is terminal for the
automated pipeline, so bad rows never loop.
"""

import logging
import os

import requests

from src.outreach._db import TABLE, get_client
from src.scrapers._http import retry_session_get

logger = logging.getLogger(__name__)

NEVERBOUNCE_SINGLE = "https://api.neverbounce.com/v4/single/check"
INVALID_RATE_THRESHOLD = 0.03  # ~2-3% hard-invalid tolerance before holding the slice

# NeverBounce result -> our verification_status
NEVERBOUNCE_RESULT_MAP = {
    "valid": "valid",
    "invalid": "invalid",
    "disposable": "invalid",
    "catchall": "risky",
    "unknown": "risky",
}
VERIFIED_STATUSES = ("valid", "invalid", "risky")


def _neverbounce_key():
    key = os.getenv("NEVERBOUNCE_API_KEY")
    if not key:
        raise RuntimeError("NEVERBOUNCE_API_KEY is not set")
    return key


def _map_result(result):
    return NEVERBOUNCE_RESULT_MAP.get(result, "risky")


def verify_email(email):
    """Return a verification_status (valid|invalid|risky) for an address."""
    key = _neverbounce_key()
    session = requests.Session()
    resp = retry_session_get(
        session,
        NEVERBOUNCE_SINGLE,
        attempts=4,
        retry_delay=2.0,
        baseline_bytes=None,
        is_event_url=False,
        provider="neverbounce",
        params={"key": key, "email": email},
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json() or {}
    # NeverBounce signals auth/credit/throttle failures with HTTP 200 + a
    # non-"success" status (and no result). Fail loudly so a bad key doesn't
    # silently mark every address "risky" and hold the whole slice.
    if body.get("status") != "success":
        raise RuntimeError(f"NeverBounce check failed: status={body.get('status')!r} message={body.get('message')!r}")
    return _map_result(body.get("result", "unknown"))


def decide_gate(rows, threshold=INVALID_RATE_THRESHOLD):
    """Pure gate decision over already-verified rows.

    ``rows`` carry ``id`` and ``verification_status``. Returns the promote/hold
    id lists, the hard-invalid fraction (over rows with a verification result),
    and the gate outcome. The denominator is rows that actually have a result,
    so no-email/unverified rows neither dilute nor block the rate.
    """
    verified = [r for r in rows if r.get("verification_status") in VERIFIED_STATUSES]
    invalid_count = sum(1 for r in verified if r["verification_status"] == "invalid")
    invalid_fraction = (invalid_count / len(verified)) if verified else None

    if not verified or invalid_fraction > threshold:
        return {
            "gate": "held_slice",
            "promote_ids": [],
            "hold_ids": [r["id"] for r in rows],
            "invalid_fraction": invalid_fraction,
            "verified_count": len(verified),
            "slice_size": len(rows),
        }

    promote_ids = [r["id"] for r in verified if r["verification_status"] == "valid"]
    promote_set = set(promote_ids)
    hold_ids = [r["id"] for r in rows if r["id"] not in promote_set]
    return {
        "gate": "passed",
        "promote_ids": promote_ids,
        "hold_ids": hold_ids,
        "invalid_fraction": invalid_fraction,
        "verified_count": len(verified),
        "slice_size": len(rows),
    }


def verify_and_gate(*, segment=None, limit=None, client=None, threshold=INVALID_RATE_THRESHOLD):
    """Verify a slice of queued rows and apply the invalid-rate gate."""
    client = client or get_client()
    query = client.table(TABLE).select("id, contact, verification_status").eq("status", "queued")
    if segment:
        query = query.eq("segment", segment)
    if limit:
        query = query.limit(limit)
    rows = query.execute().data or []

    if not rows:
        return {
            "gate": "noop",
            "slice_size": 0,
            "verified_count": 0,
            "invalid_fraction": None,
            "promoted": 0,
            "held": 0,
        }

    for row in rows:
        if row.get("verification_status") in VERIFIED_STATUSES:
            continue
        email = row.get("contact")
        if not email:
            continue
        status = verify_email(email)
        client.table(TABLE).update({"verification_status": status}).eq("id", row["id"]).execute()
        row["verification_status"] = status

    decision = decide_gate(rows, threshold=threshold)
    _bulk_set_status(client, decision["promote_ids"], "verified")
    _bulk_set_status(client, decision["hold_ids"], "held")

    summary = {
        "gate": decision["gate"],
        "slice_size": decision["slice_size"],
        "verified_count": decision["verified_count"],
        "invalid_fraction": decision["invalid_fraction"],
        "promoted": len(decision["promote_ids"]),
        "held": len(decision["hold_ids"]),
    }
    logger.info("verify_and_gate: %s", summary)
    return summary


def _bulk_set_status(client, ids, status):
    if not ids:
        return
    client.table(TABLE).update({"status": status}).in_("id", ids).execute()
