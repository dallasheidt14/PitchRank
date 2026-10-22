"""Score corrections on immutable games.

A games row cannot be updated in place: the prevent_game_updates trigger rejects it. The sanctioned
write files a game_corrections row and applies it through the apply_game_correction RPC, which
changes the score and leaves the old and new values on record.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def moves_both_sides(stored: Tuple[int, int], incoming: Tuple[int, int]) -> bool:
    """True when ``incoming`` differs from ``stored`` in both scores without being the stored pair swapped.

    Both are (home, away) of the same row.
    """
    return incoming[0] != stored[0] and incoming[1] != stored[1] and incoming != stored[::-1]


def apply_score_correction(
    supabase,
    *,
    game_uid: str,
    original: Dict[str, Any],
    corrected: Dict[str, Any],
    reason: str,
    submitted_by: str,
) -> bool:
    """Replace the stored score of one game; True when the correction was applied.

    ``original`` carries the stored home_score and away_score, ``corrected`` the new pair plus the
    result. A correction that fails to apply is rejected so it does not stay pending, unless the
    server had already approved it: apply_game_correction is one transaction that sets the status
    last, so an approved row means the score changed even when the response was lost.
    """
    correction_id = None
    try:
        correction = (
            supabase.table("game_corrections")
            .insert(
                {
                    "original_game_uid": game_uid,
                    "correction_type": "score",
                    "original_values": original,
                    "corrected_values": corrected,
                    "reason": reason,
                    "submitted_by": submitted_by,
                }
            )
            .execute()
        )
        correction_id = correction.data[0]["id"]
        supabase.rpc("apply_game_correction", {"correction_id": correction_id, "approver_name": submitted_by}).execute()
        return True
    except Exception as e:
        logger.warning(f"Could not correct the score on {game_uid}: {e}")
        return correction_id is not None and _settle_failed_correction(supabase, correction_id)


def _correction_status(supabase, correction_id: str) -> Optional[str]:
    try:
        rows = supabase.table("game_corrections").select("status").eq("id", correction_id).execute().data
    except Exception as e:
        logger.warning(f"Could not read the status of correction {correction_id}: {e}")
        return None
    return rows[0].get("status") if rows else None


def _settle_failed_correction(supabase, correction_id: str) -> bool:
    """True when the failed apply had in fact been approved; otherwise rejects the pending row."""
    if _correction_status(supabase, correction_id) == "approved":
        return True
    # apply_game_correction only takes pending rows; do not leave one pending
    try:
        supabase.table("game_corrections").update({"status": "rejected"}).eq("id", correction_id).eq(
            "status", "pending"
        ).execute()
    except Exception as reject_error:
        logger.warning(f"Could not reject correction {correction_id}: {reject_error}")
    return False
