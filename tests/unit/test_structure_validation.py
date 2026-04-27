"""Pin Shell 05's knockout-template validation map + simulator parity.

The validation table at ``tournament_intake._KNOCKOUT_VALIDATION`` encodes the
``(extra_games, allowed_pool_counts)`` pairs that each v1 template accepts.
The simulator-parity tests re-run ``infer_division_schedule_template`` and
assert the resulting ``playoff_format`` matches our table — this catches a
drift between the table and the simulator without coupling at runtime.
"""

from __future__ import annotations

import pytest

from src.tournaments.schedule_simulator import infer_division_schedule_template
from tournament_intake import (
    _serpentine_assign,
    _validate_division,
    _validate_knockout_format,
)

# -------- _validate_knockout_format ---------------------------------------


def test_sf_f_two_pools_of_four_is_valid():
    assert _validate_knockout_format("SF_F", (4, 4)) is None


def test_sf_f_three_pools_is_rejected():
    error = _validate_knockout_format("SF_F", (4, 4, 4))
    assert error is not None
    assert "pool count" in error.lower()


def test_round_robin_accepts_any_pool_count():
    assert _validate_knockout_format("ROUND_ROBIN", (4, 4, 4, 4)) is None
    assert _validate_knockout_format("ROUND_ROBIN", (8,)) is None
    assert _validate_knockout_format("ROUND_ROBIN", (3, 3, 3)) is None


def test_f_only_accepts_two_pools():
    assert _validate_knockout_format("F_ONLY", (4, 4)) is None


def test_f_only_accepts_one_pool():
    assert _validate_knockout_format("F_ONLY", (8,)) is None


def test_f_only_rejects_three_pools():
    error = _validate_knockout_format("F_ONLY", (4, 4, 4))
    assert error is not None


def test_sf_f_3p_two_pools_of_four_is_valid():
    assert _validate_knockout_format("SF_F_3P", (4, 4)) is None


def test_v2_template_qf_sf_f_is_rejected():
    error = _validate_knockout_format("QF_SF_F", (4, 4, 4, 4))
    assert error is not None
    assert "v2 template" in error


def test_v2_template_custom_is_rejected():
    error = _validate_knockout_format("CUSTOM", (4, 4))
    assert error is not None
    assert "v2 template" in error


# -------- Simulator parity ------------------------------------------------


@pytest.mark.parametrize(
    "template, pool_sizes, extras, expected_format",
    [
        ("ROUND_ROBIN", (4, 4, 4), 0, "none"),
        ("ROUND_ROBIN", (8,), 0, "none"),
        ("F_ONLY", (4, 4), 1, "pool_winners_final"),
        ("F_ONLY", (8,), 1, "one_pool_final"),
        ("SF_F", (4, 4), 3, "cross_semis_final"),
        ("SF_F_3P", (4, 4), 4, "cross_semis_final_third"),
    ],
)
def test_simulator_parity_for_v1_templates(
    template: str,
    pool_sizes: tuple[int, ...],
    extras: int,
    expected_format: str,
):
    """Every v1 (template, pool_sizes) pair the validator accepts must match
    the simulator's inferred ``playoff_format`` when given the corresponding
    ``actual_game_count`` (round-robin games + ``extras``).
    """
    assert _validate_knockout_format(template, pool_sizes) is None
    pool_round_robin_games = sum(size * (size - 1) // 2 for size in pool_sizes)
    actual_game_count = pool_round_robin_games + extras
    inferred = infer_division_schedule_template(
        division_name="Premier",
        pool_sizes=pool_sizes,
        actual_game_count=actual_game_count,
    )
    assert inferred.playoff_format == expected_format


# -------- _validate_division blocker rules --------------------------------


def test_validate_division_passes_with_consistent_inputs():
    errors = _validate_division(
        team_count=8,
        pool_sizes=(4, 4),
        knockout="SF_F",
        assigned_team_count=8,
    )
    assert errors == []


def test_validate_division_blocks_team_count_below_assigned():
    errors = _validate_division(
        team_count=6,
        pool_sizes=(3, 3),
        knockout="ROUND_ROBIN",
        assigned_team_count=8,
    )
    assert any("Reassign excess teams" in msg for msg in errors)


def test_validate_division_blocks_pool_sum_mismatch():
    errors = _validate_division(
        team_count=8,
        pool_sizes=(3, 3),
        knockout="ROUND_ROBIN",
        assigned_team_count=0,
    )
    assert any("Pool sizes sum" in msg for msg in errors)


def test_validate_division_propagates_knockout_error():
    errors = _validate_division(
        team_count=12,
        pool_sizes=(4, 4, 4),
        knockout="SF_F",
        assigned_team_count=0,
    )
    assert any("v1" in msg or "pool count" in msg.lower() for msg in errors)


# -------- _serpentine_assign distribution invariants ----------------------


def test_serpentine_assign_empty_seeds_returns_empty_pools():
    pools = _serpentine_assign([], 3)
    assert pools == [[], [], []]


def test_serpentine_assign_single_pool_concatenates():
    seeds = [(f"team{i}", float(i)) for i in range(5)]
    pools = _serpentine_assign(seeds, 1)
    assert len(pools) == 1
    assert pools[0] == seeds


def test_serpentine_assign_distributes_snake_order():
    """8 seeds across 4 pools snake to [[0,7],[1,6],[2,5],[3,4]]."""
    seeds = [(f"t{i}", float(8 - i)) for i in range(8)]
    pools = _serpentine_assign(seeds, 4)
    assert [team for team, _ in pools[0]] == ["t0", "t7"]
    assert [team for team, _ in pools[1]] == ["t1", "t6"]
    assert [team for team, _ in pools[2]] == ["t2", "t5"]
    assert [team for team, _ in pools[3]] == ["t3", "t4"]


def test_serpentine_assign_more_pools_than_seeds_leaves_trailing_empty():
    seeds = [("alpha", 10.0), ("beta", 9.0)]
    pools = _serpentine_assign(seeds, 4)
    assert pools[0] == [("alpha", 10.0)]
    assert pools[1] == [("beta", 9.0)]
    assert pools[2] == []
    assert pools[3] == []
