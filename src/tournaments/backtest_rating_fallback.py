"""Transparent rating fallback for reviewed entrants absent from PitchRank."""

from __future__ import annotations

from statistics import median
from typing import Any, Sequence

RATING_FALLBACK_POLICY = "division_then_cohort_median_surrogate"
DIVISION_MEDIAN_BASIS = "original_division_median_surrogate"
COHORT_MEDIAN_BASIS = "cohort_median_surrogate"


def needs_rating_fallback(entrant: dict[str, Any]) -> bool:
    return str(entrant.get("rating_fallback") or "") == RATING_FALLBACK_POLICY


def select_rating_surrogate(
    entrant: dict[str, Any],
    rated_rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Pick the rated peer closest to the division median, then cohort median."""

    eligible = [
        row
        for row in rated_rows
        if not needs_rating_fallback(row) and row.get("power_score") is not None
    ]
    division_key = str(entrant.get("actual_division_key") or "")
    division_peers = [
        row for row in eligible if str(row.get("actual_division_key") or "") == division_key
    ]
    candidates = division_peers or eligible
    if not candidates:
        raise ValueError(
            f"No eligible rated peer is available for not-found entrant "
            f"'{entrant.get('event_team_name') or entrant.get('entrant_id')}'"
        )
    middle = float(median(float(row["power_score"]) for row in candidates))
    selected = min(
        candidates,
        key=lambda row: (
            abs(float(row["power_score"]) - middle),
            float(row["power_score"]),
            str(row.get("ranking_source_team_id") or ""),
            str(row.get("entrant_id") or ""),
        ),
    )
    return selected, DIVISION_MEDIAN_BASIS if division_peers else COHORT_MEDIAN_BASIS
