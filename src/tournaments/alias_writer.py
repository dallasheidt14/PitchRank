"""Alias-map + match-review-queue writers for tournament-event intake.

Lifts the persistence logic out of ``src.models.game_matcher`` so the scraper
pipeline can write aliases and queue review rows without depending on the
game-import path. Adds three things the original ``_create_alias`` /
``_create_review_queue_entry`` helpers did not:

1. Typed return contracts — callers can gate the JSONL journal on durable
   terminal state (see Shell 01 Step 4).
2. Conflict detection — an approved alias pointing at a different
   ``team_id_master`` routes to the review queue instead of being silently
   overwritten. Human-curated rows (``manual`` / ``manual_review`` /
   ``manual_queue``) are never downgraded by scraper writes.
3. Clamp-aware review queue inserts — ``team_match_review_queue.confidence_score``
   has a ``DECIMAL(3,2) CHECK < 0.90`` constraint that collides with the
   classifier's ``>= 0.90`` review threshold. We clamp to ``Decimal("0.89")``
   and preserve the unclamped value in the new ``priority_score`` column
   (migration ``20260424000000_add_priority_score_to_review_queue.sql``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from config.settings import MATCHING_CONFIG

logger = logging.getLogger(__name__)


__all__ = [
    "METHOD_TIER",
    "REVIEW_QUEUE_CLAMP",
    "enqueue_match_review",
    "upsert_team_alias",
]


METHOD_TIER: dict[str, int] = {
    "manual": 7,
    "manual_review": 6,
    "manual_queue": 5,
    "import": 4,
    "direct_id": 3,
    "fuzzy_auto": 2,
    "fuzzy_review": 1,
}
"""Priority ordering for ``team_alias_map.match_method`` — higher wins.

Human-verified rows (``manual`` / ``manual_review`` / ``manual_queue``) must
never be downgraded by scraper-written ``fuzzy_auto`` / ``direct_id`` rows.
Unknown methods fall through to tier 0.
"""


REVIEW_QUEUE_CLAMP = Decimal("0.89")
"""Largest 2-decimal value that survives the ``< 0.90`` CHECK on confidence_score."""


def _tier(method: str | None) -> int:
    return METHOD_TIER.get(method or "", 0)


def _resolve_provider_identity(
    supabase: Any,
    *,
    provider_uuid: str | None,
    provider_code: str | None,
) -> tuple[str, str]:
    """Return ``(uuid, code)`` for a provider given at least one of them."""
    if provider_uuid and provider_code:
        return provider_uuid, provider_code
    if provider_code and not provider_uuid:
        result = supabase.table("providers").select("id, code").eq("code", provider_code).single().execute()
        if not result.data:
            raise ValueError(f"Provider code not found: {provider_code}")
        return result.data["id"], provider_code
    if provider_uuid and not provider_code:
        result = supabase.table("providers").select("id, code").eq("id", provider_uuid).single().execute()
        if not result.data:
            raise ValueError(f"Provider uuid not found: {provider_uuid}")
        return provider_uuid, result.data["code"]
    raise ValueError("Either provider_uuid or provider_code must be supplied")


def _apply_ceiling_clamp(match_method: str, confidence: float) -> float:
    ceiling = float(MATCHING_CONFIG.get("fuzzy_confidence_ceiling", 0.99))
    if match_method not in ("direct_id", "import"):
        return min(ceiling, confidence)
    return confidence


def _db_error(exc: Exception, action_prefix: str = "") -> dict[str, Any]:
    return {
        "action": f"{action_prefix}db_error" if action_prefix else "db_error",
        "error": str(exc),
        "exc_type": type(exc).__name__,
    }


def upsert_team_alias(
    supabase: Any,
    *,
    provider_uuid: str | None = None,
    provider_code: str | None = None,
    provider_team_id: str,
    team_id_master: str,
    provider_team_name: str,
    confidence: float,
    match_method: str,
    priority_score: float,
) -> dict[str, Any]:
    """Insert or update a ``team_alias_map`` row, protecting approved / human-curated rows.

    Returns one of: ``created``, ``updated``, ``conflict``,
    ``conflict_skipped_rejected``, ``conflict_loop_detected``,
    ``skipped_weaker_metadata``, ``db_error``.

    ``priority_score`` is the true, pre-clamp classifier score. It is NOT
    written to ``team_alias_map`` (that table has no priority_score column);
    it is only used when the alias upsert falls through to
    ``enqueue_match_review`` under the conflict branch.
    """
    try:
        uuid, code = _resolve_provider_identity(
            supabase, provider_uuid=provider_uuid, provider_code=provider_code
        )
    except Exception as exc:  # noqa: BLE001 — surface as typed error dict for caller
        return _db_error(exc)

    clamped_confidence = _apply_ceiling_clamp(match_method, confidence)

    try:
        existing_result = (
            supabase.table("team_alias_map")
            .select("id, team_id_master, match_confidence, match_method, review_status")
            .eq("provider_id", uuid)
            .eq("provider_team_id", provider_team_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        return _db_error(exc)

    existing_rows = existing_result.data or []

    alias_payload = {
        "provider_id": uuid,
        "provider_team_id": provider_team_id,
        "team_id_master": team_id_master,
        "match_method": match_method,
        "match_confidence": clamped_confidence,
        "review_status": "approved",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not existing_rows:
        try:
            supabase.table("team_alias_map").insert(alias_payload).execute()
        except Exception as exc:  # noqa: BLE001
            return _db_error(exc)
        return {
            "action": "created",
            "provider_id": uuid,
            "provider_team_id": provider_team_id,
            "team_id_master": team_id_master,
            "match_method": match_method,
            "match_confidence": clamped_confidence,
        }

    existing = existing_rows[0]
    existing_id = existing["id"]
    existing_master = existing.get("team_id_master")
    existing_method = existing.get("match_method") or ""
    existing_confidence = existing.get("match_confidence") or 0.0
    existing_status = existing.get("review_status")

    if existing_status == "approved" and existing_master and existing_master != team_id_master:
        conflict_detail = {
            "prior_master": existing_master,
            "candidate_master": team_id_master,
            "prior_method": existing_method,
            "candidate_method": match_method,
        }
        queue_result = enqueue_match_review(
            supabase,
            provider_uuid=uuid,
            provider_code=code,
            provider_team_id=provider_team_id,
            provider_team_name=provider_team_name,
            suggested_master_team_id=team_id_master,
            confidence=confidence,
            priority_score=priority_score,
            match_details={
                "conflict": conflict_detail,
                "reason": "approved_alias_conflict",
            },
        )
        nested_action = queue_result.get("action")
        if nested_action in ("queued", "deduped_pending"):
            return {"action": "conflict", "queue_result": queue_result}
        if nested_action == "skipped_rejected":
            return {"action": "conflict_skipped_rejected", "queue_result": queue_result}
        if nested_action == "skipped_already_approved":
            logger.warning(
                "[conflict_loop_detected] provider_team_id=%s prior_master=%s candidate_master=%s",
                provider_team_id,
                existing_master,
                team_id_master,
            )
            return {"action": "conflict_loop_detected", "queue_result": queue_result}
        if nested_action == "db_error":
            return {"action": "db_error", "queue_result": queue_result, "error": queue_result.get("error")}
        return {"action": "conflict", "queue_result": queue_result}

    if existing_status == "approved" and existing_master == team_id_master:
        if (
            clamped_confidence > existing_confidence
            and _tier(match_method) >= _tier(existing_method)
        ):
            try:
                supabase.table("team_alias_map").update(alias_payload).eq("id", existing_id).execute()
            except Exception as exc:  # noqa: BLE001
                return _db_error(exc)
            return {
                "action": "updated",
                "provider_id": uuid,
                "provider_team_id": provider_team_id,
                "team_id_master": team_id_master,
                "match_method": match_method,
                "match_confidence": clamped_confidence,
            }
        logger.debug(
            "[skipped_weaker_metadata] provider_team_id=%s existing_method=%s (tier %d) "
            "incoming_method=%s (tier %d) existing_confidence=%s incoming_confidence=%s",
            provider_team_id,
            existing_method,
            _tier(existing_method),
            match_method,
            _tier(match_method),
            existing_confidence,
            clamped_confidence,
        )
        return {
            "action": "skipped_weaker_metadata",
            "provider_id": uuid,
            "provider_team_id": provider_team_id,
            "existing_method": existing_method,
            "existing_confidence": existing_confidence,
            "incoming_method": match_method,
            "incoming_confidence": clamped_confidence,
        }

    try:
        supabase.table("team_alias_map").update(alias_payload).eq("id", existing_id).execute()
    except Exception as exc:  # noqa: BLE001
        return _db_error(exc)
    return {
        "action": "updated",
        "provider_id": uuid,
        "provider_team_id": provider_team_id,
        "team_id_master": team_id_master,
        "match_method": match_method,
        "match_confidence": clamped_confidence,
    }


def enqueue_match_review(
    supabase: Any,
    *,
    provider_uuid: str | None = None,
    provider_code: str | None = None,
    provider_team_id: str,
    provider_team_name: str,
    suggested_master_team_id: str | None,
    confidence: float,
    priority_score: float,
    match_details: dict[str, Any],
) -> dict[str, Any]:
    """Insert a row into ``team_match_review_queue``, clamping confidence past the CHECK.

    Returns one of: ``queued``, ``deduped_pending``, ``skipped_rejected``,
    ``skipped_already_approved``, ``db_error``.
    """
    try:
        _uuid, code = _resolve_provider_identity(
            supabase, provider_uuid=provider_uuid, provider_code=provider_code
        )
    except Exception as exc:  # noqa: BLE001
        return _db_error(exc)

    try:
        confidence_decimal = min(Decimal(str(confidence)), REVIEW_QUEUE_CLAMP)
    except Exception as exc:  # noqa: BLE001
        return _db_error(exc)
    clamped_confidence_float = float(confidence_decimal)
    if confidence_decimal < Decimal(str(confidence)):
        logger.info(
            "[clamped_review_confidence] provider_team_id=%s true=%s clamped=%s",
            provider_team_id,
            confidence,
            clamped_confidence_float,
        )

    incoming_conflict = match_details.get("conflict") if isinstance(match_details, dict) else None
    incoming_candidate = (
        incoming_conflict.get("candidate_master") if isinstance(incoming_conflict, dict) else None
    )

    try:
        existing_result = (
            supabase.table("team_match_review_queue")
            .select("id, status, match_details, suggested_master_team_id")
            .eq("provider_id", code)
            .eq("provider_team_id", str(provider_team_id))
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        return _db_error(exc)

    existing_rows = existing_result.data or []
    pending_rows = [r for r in existing_rows if r.get("status") == "pending"]

    base_insert = {
        "provider_id": code,
        "provider_team_id": str(provider_team_id),
        "provider_team_name": provider_team_name,
        "suggested_master_team_id": suggested_master_team_id,
        "confidence_score": clamped_confidence_float,
        "priority_score": float(priority_score),
        "match_details": match_details,
        "status": "pending",
    }

    if pending_rows:
        pending = pending_rows[0]
        pending_id = pending["id"]
        pending_details = pending.get("match_details") or {}
        pending_conflict = pending_details.get("conflict") if isinstance(pending_details, dict) else None
        pending_candidate = (
            pending_conflict.get("candidate_master") if isinstance(pending_conflict, dict) else None
        )

        if incoming_conflict and pending_conflict and incoming_candidate != pending_candidate:
            logger.info(
                "[multi_conflict] provider_team_id=%s existing_candidate=%s new_candidate=%s",
                provider_team_id,
                pending_candidate,
                incoming_candidate,
            )
            try:
                supabase.table("team_match_review_queue").insert(base_insert).execute()
            except Exception as exc:  # noqa: BLE001
                return _db_error(exc)
            return {
                "action": "queued",
                "provider_id": code,
                "provider_team_id": str(provider_team_id),
                "confidence_score": clamped_confidence_float,
                "priority_score": float(priority_score),
                "multi_conflict": True,
            }

        merged_details = dict(pending_details)
        if incoming_conflict and not pending_conflict:
            merged_details["conflict"] = incoming_conflict
        if "also_appears_in_brackets" in match_details:
            merged_details["also_appears_in_brackets"] = match_details["also_appears_in_brackets"]
        if "reason" in match_details and "reason" not in merged_details:
            merged_details["reason"] = match_details["reason"]
        if "candidates" in match_details:
            merged_details["candidates"] = match_details["candidates"]
        if "true_confidence" in match_details:
            merged_details["true_confidence"] = match_details["true_confidence"]
        for extra_key in ("age_group", "gender", "division", "provider_event_id", "source_url"):
            if extra_key in match_details and extra_key not in merged_details:
                merged_details[extra_key] = match_details[extra_key]

        update_payload = {
            "confidence_score": clamped_confidence_float,
            "priority_score": float(priority_score),
            "match_details": merged_details,
            "provider_team_name": provider_team_name,
        }
        if suggested_master_team_id is not None:
            update_payload["suggested_master_team_id"] = suggested_master_team_id
        try:
            supabase.table("team_match_review_queue").update(update_payload).eq("id", pending_id).execute()
        except Exception as exc:  # noqa: BLE001
            return _db_error(exc)
        return {
            "action": "deduped_pending",
            "provider_id": code,
            "provider_team_id": str(provider_team_id),
            "id": pending_id,
            "priority_score": float(priority_score),
        }

    for row in existing_rows:
        status = row.get("status")
        if status not in ("approved", "rejected"):
            continue
        row_details = row.get("match_details") or {}
        row_conflict = row_details.get("conflict") if isinstance(row_details, dict) else None
        row_candidate = row_conflict.get("candidate_master") if isinstance(row_conflict, dict) else None
        if incoming_conflict:
            if row_candidate != incoming_candidate:
                continue
        if status == "rejected":
            return {
                "action": "skipped_rejected",
                "provider_id": code,
                "provider_team_id": str(provider_team_id),
                "existing_status": "rejected",
            }
        if status == "approved":
            return {
                "action": "skipped_already_approved",
                "provider_id": code,
                "provider_team_id": str(provider_team_id),
                "existing_status": "approved",
            }

    try:
        supabase.table("team_match_review_queue").insert(base_insert).execute()
    except Exception as exc:  # noqa: BLE001
        return _db_error(exc)
    return {
        "action": "queued",
        "provider_id": code,
        "provider_team_id": str(provider_team_id),
        "confidence_score": clamped_confidence_float,
        "priority_score": float(priority_score),
    }
