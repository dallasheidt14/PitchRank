from __future__ import annotations

import pandas as pd
import pytest

from src.predictions.match_model_benchmarks import (
    build_frozen_holdout_benchmark,
    build_historical_poisson_benchmark,
)


def _example(
    game_id: str,
    game_date: str,
    team_a: str,
    team_b: str,
    score_a: int,
    score_b: int,
    *,
    orientation: str = "original",
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "game_date": game_date,
        "team_a_id": team_a,
        "team_b_id": team_b,
        "team_a_is_female": 0.0,
        "team_b_is_female": 0.0,
        "age_group_numeric": 14.0,
        "example_orientation": orientation,
        "actual_score_a": score_a,
        "actual_score_b": score_b,
        "actual_margin": score_a - score_b,
        "actual_outcome": "team_a" if score_a > score_b else "team_b" if score_b > score_a else "draw",
    }


def test_hierarchical_poisson_uses_training_only_team_signal_and_is_symmetric():
    train = pd.DataFrame(
        [
            _example("g1", "2026-01-01", "strong", "weak", 5, 0),
            _example("g1", "2026-01-01", "weak", "strong", 0, 5, orientation="mirrored"),
            _example("g2", "2026-01-08", "strong", "average", 4, 1),
            _example("g3", "2026-01-09", "average", "weak", 3, 0),
        ]
    )
    test = pd.DataFrame(
        [
            _example("g4", "2026-02-01", "strong", "weak", 2, 0),
            _example("g4", "2026-02-01", "weak", "strong", 0, 2, orientation="mirrored"),
        ]
    )

    predictions = build_historical_poisson_benchmark(train, test, hierarchical=True)

    forward, reverse = predictions.iloc[0], predictions.iloc[1]
    assert forward["expected_goals_a"] > forward["expected_goals_b"]
    assert forward["prob_team_a_win"] == pytest.approx(reverse["prob_team_b_win"])
    assert forward["prob_team_b_win"] == pytest.approx(reverse["prob_team_a_win"])
    assert forward["predicted_absolute_margin"] == pytest.approx(
        reverse["predicted_absolute_margin"]
    )


def test_frozen_holdout_benchmark_uses_only_shared_fixture_examples():
    first = build_historical_poisson_benchmark(
        pd.DataFrame([_example("train", "2026-01-01", "a", "b", 2, 0)]),
        pd.DataFrame(
            [
                _example("shared", "2026-02-01", "a", "b", 1, 0),
                _example("first-only", "2026-02-02", "a", "b", 0, 0),
            ]
        ),
        hierarchical=False,
    )
    second = first[first["game_id"] == "shared"].copy()

    table = build_frozen_holdout_benchmark({"first": first, "second": second})

    assert set(table["shared_examples"]) == {1}
    assert set(table["candidate"]) == {"first", "second"}
    assert table["benchmark_rank"].notna().all()
