import pytest

from src.tournaments.modelled_comparison import (
    compare_modelled_arrangements,
    project_matchup_pairs,
    summarize_modelled_matchups,
)
from src.tournaments.seeding_optimizer import MatchupCost, SeedableTeam


def _team(team_id: str, score: float) -> SeedableTeam:
    return SeedableTeam(team_id, team_id.title(), "u14", "Male", score)


def _cost(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
    gap = abs(team_a.power_score - team_b.power_score)
    return MatchupCost(
        projected_margin=gap * 10,
        competitive_probability=1.0 - gap,
        blowout_3plus_probability=gap,
        blowout_5plus_probability=gap / 2,
        total_cost=gap * 10,
    )


def _summary(pairs, basis):
    return summarize_modelled_matchups(
        project_matchup_pairs(pairs, _cost),
        projection_basis=basis,
    )


def test_identical_arrangements_report_zero_effect_and_zero_delta_uncertainty():
    alpha = _team("alpha", 0.9)
    bravo = _team("bravo", 0.5)
    original = _summary([(alpha, bravo)], "original")
    proposed = _summary([(bravo, alpha)], "proposed")

    comparison = compare_modelled_arrangements(original, proposed)

    assert comparison["status"] == "comparable"
    assert comparison["arrangements_identical"] is True
    assert comparison["average_goal_differential_improvement"] == 0.0
    assert comparison["close_game_probability_delta"] == 0.0
    assert comparison["blowout_3plus_probability_improvement"] == 0.0
    assert comparison["uncertainty"]["metrics"]["close_game_probability_delta"]["standard_error"] == 0.0


def test_changed_arrangement_compares_modelled_pairs_and_includes_uncertainty():
    alpha = _team("alpha", 0.9)
    bravo = _team("bravo", 0.5)
    charlie = _team("charlie", 0.8)
    delta = _team("delta", 0.4)
    original = _summary([(alpha, delta), (charlie, bravo)], "original")
    proposed = _summary([(alpha, charlie), (bravo, delta)], "proposed")

    comparison = compare_modelled_arrangements(original, proposed)

    assert comparison["status"] == "comparable"
    assert comparison["arrangements_identical"] is False
    assert comparison["average_goal_differential_improvement"] == pytest.approx(3.0)
    assert comparison["close_game_probability_delta"] == pytest.approx(0.3)
    interval = comparison["uncertainty"]["metrics"]["close_game_probability_delta"]
    assert interval["confidence_95_lower"] < comparison["close_game_probability_delta"]
    assert interval["confidence_95_upper"] > comparison["close_game_probability_delta"]
    assert interval["confidence_95_lower"] < 0.0


def test_different_matchup_counts_are_not_comparable():
    alpha = _team("alpha", 0.9)
    bravo = _team("bravo", 0.5)
    charlie = _team("charlie", 0.8)

    comparison = compare_modelled_arrangements(
        _summary([(alpha, bravo)], "original"),
        _summary([(alpha, bravo), (alpha, charlie)], "proposed"),
    )

    assert comparison == {
        "status": "unavailable",
        "reason": "Original and proposed arrangements contain different matchup counts",
        "comparison_basis": "same_model_original_vs_proposed_matchups",
        "original_matchup_count": 1,
        "proposed_matchup_count": 2,
    }
