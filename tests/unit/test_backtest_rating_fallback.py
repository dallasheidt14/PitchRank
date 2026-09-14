import pytest

from src.tournaments.backtest_rating_fallback import (
    COHORT_AVERAGE_BASIS,
    DIVISION_AVERAGE_BASIS,
    DIVISION_MISSING_HISTORY_AVERAGE_BASIS,
    MISSING_HISTORY_FALLBACK_POLICY,
    build_average_rating_estimate,
)


def _row(entrant_id: str, division: str, score: float) -> dict:
    return {
        "entrant_id": entrant_id,
        "actual_division_key": division,
        "power_score": score,
        "ranking_source_team_id": f"team-{entrant_id}",
    }


def test_fallback_uses_the_original_division_arithmetic_average():
    estimate, basis = build_average_rating_estimate(
        {"entrant_id": "missing", "actual_division_key": "silver"},
        (
            _row("gold", "gold", 0.95),
            _row("silver-low", "silver", 0.4),
            _row("silver-high", "silver", 0.6),
        ),
    )

    assert estimate["ranking_source_team_id"] == "average-estimate:missing"
    assert estimate["power_score"] == pytest.approx(0.5)
    assert estimate["average_source_count"] == 2
    assert estimate["average_source_entrant_ids"] == ("silver-high", "silver-low")
    assert basis == DIVISION_AVERAGE_BASIS


def test_fallback_uses_cohort_average_when_no_division_peer_is_rated():
    estimate, basis = build_average_rating_estimate(
        {"entrant_id": "missing", "actual_division_key": "bronze"},
        (_row("low", "gold", 0.25), _row("middle", "silver", 0.5), _row("high", "gold", 0.9)),
    )

    assert estimate["power_score"] == pytest.approx(0.55)
    assert estimate["average_source_count"] == 3
    assert basis == COHORT_AVERAGE_BASIS


def test_fallback_refuses_to_invent_a_rating_without_any_rated_peer():
    with pytest.raises(ValueError, match="No eligible pre-event rating"):
        build_average_rating_estimate(
            {"entrant_id": "missing", "event_team_name": "Unknown FC"},
            (),
        )


def test_missing_history_fallback_has_a_distinct_evidence_basis():
    estimate, basis = build_average_rating_estimate(
        {
            "entrant_id": "known-without-history",
            "actual_division_key": "silver",
            "rating_fallback": MISSING_HISTORY_FALLBACK_POLICY,
        },
        (_row("rated", "silver", 0.64),),
    )

    assert estimate["power_score"] == pytest.approx(0.64)
    assert basis == DIVISION_MISSING_HISTORY_AVERAGE_BASIS


def test_average_strength_does_not_inherit_peer_evidence_or_certainty():
    peer = {
        **_row("rated", "silver", 0.64),
        "games_played": 24,
        "glicko_rd": 45.0,
        "glicko_volatility": 0.04,
    }

    estimate, _basis = build_average_rating_estimate(
        {"entrant_id": "unknown", "actual_division_key": "silver"},
        (peer,),
    )

    assert estimate["power_score"] == pytest.approx(0.64)
    assert estimate["games_played"] == 0
    assert estimate["glicko_rd"] == 350.0
    assert estimate["glicko_volatility"] is None
