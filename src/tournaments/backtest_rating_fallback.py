"""Transparent average-strength estimates for reviewed entrants absent from PitchRank."""

from __future__ import annotations

import math
from typing import Any, Sequence

RATING_FALLBACK_POLICY = "division_then_cohort_average_estimate"
LEGACY_RATING_FALLBACK_POLICIES = frozenset({"division_then_cohort_median_surrogate"})
DIVISION_AVERAGE_BASIS = "original_division_average_estimate"
COHORT_AVERAGE_BASIS = "cohort_average_estimate"
AVERAGE_ESTIMATE_SOURCE_PREFIX = "average-estimate:"

_AVERAGED_FIELDS = (
    "power_score",
    "rank_in_cohort",
    "games_played",
    "sos_norm",
    "off_norm",
    "def_norm",
    "glicko_rating",
    "glicko_rd",
    "glicko_volatility",
)


def needs_rating_fallback(entrant: dict[str, Any]) -> bool:
    policy = str(entrant.get("rating_fallback") or "")
    return policy == RATING_FALLBACK_POLICY or policy in LEGACY_RATING_FALLBACK_POLICIES


def _finite_average(rows: Sequence[dict[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if value is None or isinstance(value, bool):
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric):
            values.append(numeric)
    if not values:
        return None
    return float(sum(values) / len(values))


def build_average_rating_estimate(
    entrant: dict[str, Any],
    rated_rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Build an anonymous average profile from rated division peers, then the cohort."""

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
            "No eligible rated team is available to calculate an average for not-found "
            f"'{entrant.get('event_team_name') or entrant.get('entrant_id')}'"
        )

    entrant_id = str(entrant.get("entrant_id") or "unknown")
    estimate: dict[str, Any] = {
        "entrant_id": entrant_id,
        "ranking_source_team_id": f"{AVERAGE_ESTIMATE_SOURCE_PREFIX}{entrant_id}",
        "average_source_count": len(candidates),
        "average_source_entrant_ids": tuple(
            sorted(str(row.get("entrant_id") or "") for row in candidates)
        ),
        "average_source_team_ids": tuple(
            sorted(
                {
                    str(row.get("ranking_source_team_id") or "")
                    for row in candidates
                    if row.get("ranking_source_team_id")
                }
            )
        ),
    }
    for field in _AVERAGED_FIELDS:
        estimate[field] = _finite_average(candidates, field)
    if estimate["power_score"] is None:
        raise ValueError(
            "No eligible rated team is available to calculate an average for not-found "
            f"entrant '{entrant.get('event_team_name') or entrant_id}'"
        )
    return estimate, DIVISION_AVERAGE_BASIS if division_peers else COHORT_AVERAGE_BASIS
