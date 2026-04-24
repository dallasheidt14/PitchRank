from scripts.optimize_tournament_seeding import (
    _build_projection_vs_actual_comparison,
    _summarize_actual_games,
    _summarize_projected_result,
)
from src.tournaments.seeding_optimizer import DivisionSpec, MatchupCost, SeedableTeam, optimize_tournament_format


def _team(index: int, power_score: float, rank_in_cohort: float) -> SeedableTeam:
    return SeedableTeam(
        team_id=f"team-{index}",
        team_name=f"Team {index}",
        age_group="u14",
        gender="Male",
        power_score=power_score,
        rank_in_cohort=rank_in_cohort,
    )


def test_summarize_actual_games_reports_goal_differential_rates():
    summary = _summarize_actual_games(
        [
            {"home_score": 3, "away_score": 2},
            {"home_score": 5, "away_score": 1},
            {"home_score": 1, "away_score": 1},
        ]
    )

    assert summary["actual_game_count"] == 3
    assert round(summary["average_goal_differential"], 4) == round(5 / 3, 4)
    assert summary["median_goal_differential"] == 1.0
    assert round(summary["close_game_rate"], 4) == round(2 / 3, 4)
    assert round(summary["blowout_3plus_rate"], 4) == round(1 / 3, 4)
    assert summary["blowout_5plus_rate"] == 0.0
    assert round(summary["draw_rate"], 4) == round(1 / 3, 4)


def test_summarize_projected_result_reports_pairwise_projection_metrics():
    teams = [
        _team(1, 0.95, 1),
        _team(2, 0.90, 2),
        _team(3, 0.85, 3),
        _team(4, 0.80, 4),
    ]
    divisions = [DivisionSpec(name="Gold", team_count=2), DivisionSpec(name="Silver", team_count=2)]

    preferred_pairs = {frozenset({"team-1", "team-4"}), frozenset({"team-2", "team-3"})}

    def custom_cost(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
        is_preferred = frozenset({team_a.team_id, team_b.team_id}) in preferred_pairs
        projected_margin = 1.0 if is_preferred else 4.0
        competitive_probability = 0.8 if is_preferred else 0.2
        blowout_3plus_probability = 0.1 if is_preferred else 0.9
        blowout_5plus_probability = 0.0 if is_preferred else 0.6
        return MatchupCost(
            projected_margin=projected_margin,
            competitive_probability=competitive_probability,
            blowout_3plus_probability=blowout_3plus_probability,
            blowout_5plus_probability=blowout_5plus_probability,
            total_cost=projected_margin,
        )

    result = optimize_tournament_format(teams, divisions, matchup_cost_fn=custom_cost, matchup_proxy="custom")
    summary = _summarize_projected_result(result, custom_cost)

    assert summary["projection_basis"] == "all_intra_pool_pairings"
    assert summary["projected_matchup_count"] == 2
    assert summary["average_goal_differential"] == 1.0
    assert summary["median_goal_differential"] == 1.0
    assert summary["close_game_probability"] == 0.8
    assert summary["blowout_3plus_probability"] == 0.1
    assert summary["blowout_5plus_probability"] == 0.0


def test_build_projection_vs_actual_comparison_reports_improvement():
    projected_summary = {
        "projected_matchup_count": 8,
        "average_goal_differential": 2.0,
        "median_goal_differential": 2.0,
        "close_game_probability": 0.55,
        "blowout_3plus_probability": 0.20,
        "blowout_5plus_probability": 0.05,
    }
    actual_summary = {
        "actual_game_count": 8,
        "average_goal_differential": 5.5,
        "median_goal_differential": 4.0,
        "close_game_rate": 0.20,
        "blowout_3plus_rate": 0.50,
        "blowout_5plus_rate": 0.25,
        "draw_rate": 0.0,
    }

    comparison = _build_projection_vs_actual_comparison(projected_summary, actual_summary)

    assert comparison is not None
    assert comparison["average_goal_differential_improvement"] == 3.5
    assert comparison["median_goal_differential_improvement"] == 2.0
    assert round(comparison["close_game_rate_delta"], 4) == 0.35
    assert round(comparison["blowout_3plus_rate_improvement"], 4) == 0.30
    assert round(comparison["blowout_5plus_rate_improvement"], 4) == 0.20
