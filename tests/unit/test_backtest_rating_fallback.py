import pytest

from src.tournaments.backtest_rating_fallback import (
    COHORT_AVERAGE_BASIS,
    DIVISION_AVERAGE_BASIS,
    DIVISION_MISSING_HISTORY_AVERAGE_BASIS,
    MISSING_HISTORY_FALLBACK_POLICY,
    build_average_rating_estimate,
)


def _row(entrant_id: str, division: str, score: float, **fields) -> dict:
    return {
        "entrant_id": entrant_id,
        "actual_division_key": division,
        "power_score": score,
        "ranking_source_team_id": f"team-{entrant_id}",
        **fields,
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


def test_fallback_averages_the_complete_compare_profile():
    estimate, _basis = build_average_rating_estimate(
        {"entrant_id": "missing", "actual_division_key": "silver"},
        (
            _row(
                "low",
                "silver",
                0.4,
                wins=4,
                win_percentage=40,
                exp_margin=-0.4,
                same_age_games=6,
                same_age_game_share=0.6,
                publication_cap_score=0.39,
            ),
            _row(
                "high",
                "silver",
                0.6,
                wins=8,
                win_percentage=60,
                exp_margin=0.4,
                same_age_games=10,
                same_age_game_share=1.0,
                publication_cap_score=0.59,
            ),
        ),
    )

    assert estimate["wins"] == pytest.approx(6)
    assert estimate["win_percentage"] == pytest.approx(50)
    assert estimate["exp_margin"] == pytest.approx(0)
    assert estimate["same_age_games"] == pytest.approx(8)
    assert estimate["same_age_game_share"] == pytest.approx(0.8)
    assert estimate["publication_cap_score"] == pytest.approx(0.49)


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
