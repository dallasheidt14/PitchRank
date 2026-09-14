import pytest

from scripts import optimize_tournament_seeding as seeding_script
from scripts.optimize_tournament_seeding import (
    _project_original_pool_arrangement,
    _summarize_actual_games,
    _summarize_projected_result,
)
from src.tournaments.modelled_comparison import compare_modelled_arrangements
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


def test_identical_original_and_proposed_pools_have_zero_improvement():
    alpha = _team(1, 0.8, 1)
    bravo = _team(2, 0.4, 2)

    def cost(_team_a, _team_b):
        return MatchupCost(2.0, 0.5, 0.25, 0.1, 2.0)

    proposed_result = optimize_tournament_format(
        [alpha, bravo],
        [DivisionSpec("Gold", 2)],
        matchup_cost_fn=cost,
    )
    proposed = _summarize_projected_result(proposed_result, cost)
    original, issues = _project_original_pool_arrangement(
        [{"name": "Gold", "team_ids": [alpha.team_id, bravo.team_id]}],
        [alpha, bravo],
        cost,
    )

    assert issues == ()
    assert original is not None
    comparison = compare_modelled_arrangements(original, proposed)
    assert comparison["arrangements_identical"] is True
    assert comparison["average_goal_differential_improvement"] == 0.0
    assert comparison["blowout_3plus_probability_improvement"] == 0.0


def test_standalone_comparison_requires_exact_original_pools():
    projection, issues = _project_original_pool_arrangement(
        None,
        [_team(1, 0.8, 1), _team(2, 0.4, 2)],
        lambda _a, _b: MatchupCost(1.0, 0.5, 0.2, 0.1, 1.0),
    )

    assert projection is None
    assert issues == ("Exact original pool membership was not supplied",)


def test_standalone_division_parser_accepts_integer_strings():
    divisions = seeding_script._build_division_specs(
        {"format": {"divisions": [{"name": "Gold", "team_count": "7", "pool_sizes": ["4", "3"]}]}}
    )

    assert divisions == [DivisionSpec("Gold", 7, (4, 3))]


@pytest.mark.parametrize("invalid_count", [0, -1, 1.5, True, "1.5"])
def test_standalone_division_parser_rejects_invalid_capacities(invalid_count):
    with pytest.raises(ValueError, match="positive integer"):
        seeding_script._build_division_specs(
            {"format": {"divisions": [{"name": "Gold", "team_count": invalid_count}]}}
        )


@pytest.mark.parametrize("invalid_pool_count", [0, -1, 1.5, True, "1.5"])
def test_standalone_division_parser_rejects_invalid_pool_counts(invalid_pool_count):
    with pytest.raises(ValueError, match="positive integer"):
        seeding_script._build_division_specs(
            {
                "format": {
                    "divisions": [
                        {"name": "Gold", "team_count": 4, "pool_count": invalid_pool_count},
                    ]
                }
            }
        )


@pytest.mark.parametrize("invalid_name", [None, "", "  ", 42])
def test_standalone_division_parser_rejects_invalid_names(invalid_name):
    with pytest.raises(ValueError, match="non-empty string name"):
        seeding_script._build_division_specs(
            {"format": {"divisions": [{"name": invalid_name, "team_count": 2}]}}
        )
