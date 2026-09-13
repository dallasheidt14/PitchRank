import pytest

from src.tournaments.backtest_rating_fallback import (
    COHORT_MEDIAN_BASIS,
    DIVISION_MEDIAN_BASIS,
    select_rating_surrogate,
)


def _row(entrant_id: str, division: str, score: float) -> dict:
    return {
        "entrant_id": entrant_id,
        "actual_division_key": division,
        "power_score": score,
        "ranking_source_team_id": f"team-{entrant_id}",
    }


def test_fallback_prefers_the_original_division_median():
    selected, basis = select_rating_surrogate(
        {"entrant_id": "missing", "actual_division_key": "silver"},
        (
            _row("gold", "gold", 0.95),
            _row("silver-low", "silver", 0.4),
            _row("silver-high", "silver", 0.6),
        ),
    )

    assert selected["entrant_id"] == "silver-low"
    assert basis == DIVISION_MEDIAN_BASIS


def test_fallback_uses_cohort_median_when_no_division_peer_is_rated():
    selected, basis = select_rating_surrogate(
        {"entrant_id": "missing", "actual_division_key": "bronze"},
        (_row("low", "gold", 0.25), _row("middle", "silver", 0.5), _row("high", "gold", 0.9)),
    )

    assert selected["entrant_id"] == "middle"
    assert basis == COHORT_MEDIAN_BASIS


def test_fallback_refuses_to_invent_a_rating_without_any_rated_peer():
    with pytest.raises(ValueError, match="No eligible rated peer"):
        select_rating_surrogate(
            {"entrant_id": "missing", "event_team_name": "Unknown FC"},
            (),
        )
