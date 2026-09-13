"""Leakage-safe benchmark models for point-in-time match prediction.

These models are deliberately simple and interpretable. They establish whether
the learned MatchBalance model improves on cohort scoring rates and a
recency-weighted team attack/defence model on the exact same frozen holdout.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Mapping

import numpy as np
import pandas as pd

from src.predictions.evaluation_reporting import compute_evaluation_summary

BENCHMARK_METRICS: tuple[tuple[str, bool], ...] = (
    ("log_loss", False),
    ("brier_score", False),
    ("margin_mae", False),
    ("blowout_4plus_brier", False),
    ("competitive_game_recall", True),
    ("competitive_game_precision", True),
)


def _canonical_games(frame: pd.DataFrame) -> pd.DataFrame:
    """Return one orientation per game so mirrored examples are not double counted."""

    if frame.empty:
        return frame.copy()
    ordered = frame.copy()
    if "example_orientation" in ordered.columns:
        ordered["_orientation_order"] = (
            ordered["example_orientation"].astype(str).ne("original").astype(int)
        )
        ordered = ordered.sort_values(["game_date", "game_id", "_orientation_order"])
    else:
        ordered = ordered.sort_values(["game_date", "game_id"])
    return ordered.drop_duplicates("game_id", keep="first").drop(
        columns=["_orientation_order"], errors="ignore"
    )


def _gender_key(row: Mapping[str, object]) -> str:
    team_a_value = pd.to_numeric(row.get("team_a_is_female"), errors="coerce")
    team_b_value = pd.to_numeric(row.get("team_b_is_female"), errors="coerce")
    if pd.isna(team_a_value) or pd.isna(team_b_value):
        return "mixed_or_unknown"
    team_a = float(team_a_value) >= 0.5
    team_b = float(team_b_value) >= 0.5
    if team_a and team_b:
        return "girls"
    if not team_a and not team_b:
        return "boys"
    return "mixed"


def _cohort_key(row: Mapping[str, object]) -> tuple[int, str]:
    age = pd.to_numeric(row.get("age_group_numeric"), errors="coerce")
    return (int(age) if pd.notna(age) else 0, _gender_key(row))


def _poisson_vector(rate: float, max_goals: int) -> np.ndarray:
    rate = float(np.clip(rate, 0.05, 8.0))
    values = np.zeros(max_goals + 1, dtype=float)
    values[0] = math.exp(-rate)
    for goals in range(1, max_goals):
        values[goals] = values[goals - 1] * rate / goals
    values[max_goals] = max(0.0, 1.0 - float(values[:max_goals].sum()))
    return values / values.sum()


def _score_summary(rate_a: float, rate_b: float, max_goals: int) -> dict[str, float]:
    matrix = np.outer(_poisson_vector(rate_a, max_goals), _poisson_vector(rate_b, max_goals))
    goal_axis = np.arange(max_goals + 1, dtype=float)
    margin_grid = goal_axis[:, None] - goal_axis[None, :]
    absolute_margin_grid = np.abs(margin_grid)
    flat_mode = int(np.argmax(matrix))
    return {
        "prob_team_a_win": float(matrix[margin_grid > 0].sum()),
        "prob_draw": float(matrix[margin_grid == 0].sum()),
        "prob_team_b_win": float(matrix[margin_grid < 0].sum()),
        "predicted_margin": float(rate_a - rate_b),
        "predicted_absolute_margin": float((matrix * absolute_margin_grid).sum()),
        "predicted_score_a": float(flat_mode // (max_goals + 1)),
        "predicted_score_b": float(flat_mode % (max_goals + 1)),
        "expected_goals_a": float(rate_a),
        "expected_goals_b": float(rate_b),
        "blowout_3plus_probability": float(matrix[absolute_margin_grid >= 3].sum()),
        "blowout_4plus_probability": float(matrix[absolute_margin_grid >= 4].sum()),
        "blowout_5plus_probability": float(matrix[absolute_margin_grid >= 5].sum()),
    }


def build_historical_poisson_benchmark(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    *,
    hierarchical: bool,
    half_life_days: float = 120.0,
    prior_games: float = 6.0,
    max_goals: int = 8,
) -> pd.DataFrame:
    """Predict a frozen holdout from training-only goal histories.

    The hierarchical variant estimates recency-weighted team attack and defence
    strengths and shrinks them to the team's age/gender scoring environment.
    The cohort-only variant is a useful no-team-information floor.
    """

    if train_frame.empty or test_frame.empty:
        return pd.DataFrame()
    games = _canonical_games(train_frame)
    cutoff = pd.to_datetime(games["game_date"], errors="coerce").max()
    global_goals = float(
        pd.concat(
            [
                pd.to_numeric(games["actual_score_a"], errors="coerce"),
                pd.to_numeric(games["actual_score_b"], errors="coerce"),
            ],
            ignore_index=True,
        ).mean()
    )
    if not math.isfinite(global_goals):
        global_goals = 1.5

    cohort_goals: dict[tuple[int, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    team_stats: dict[tuple[tuple[int, str], str], list[float]] = defaultdict(
        lambda: [0.0, 0.0, 0.0]
    )
    for row in games.to_dict(orient="records"):
        score_a = float(row["actual_score_a"])
        score_b = float(row["actual_score_b"])
        game_date = pd.to_datetime(row.get("game_date"), errors="coerce")
        age_days = max(0.0, float((cutoff - game_date).days)) if pd.notna(game_date) else 0.0
        weight = 0.5 ** (age_days / max(1.0, half_life_days))
        cohort = _cohort_key(row)
        cohort_goals[cohort][0] += weight * (score_a + score_b)
        cohort_goals[cohort][1] += 2.0 * weight
        for team_id, goals_for, goals_against in (
            (str(row["team_a_id"]), score_a, score_b),
            (str(row["team_b_id"]), score_b, score_a),
        ):
            stats = team_stats[(cohort, team_id)]
            stats[0] += weight * goals_for
            stats[1] += weight * goals_against
            stats[2] += weight

    cohort_means = {
        key: totals[0] / totals[1] if totals[1] > 0 else global_goals
        for key, totals in cohort_goals.items()
    }

    rows: list[dict[str, object]] = []
    for row in test_frame.to_dict(orient="records"):
        cohort = _cohort_key(row)
        mean_goals = float(np.clip(cohort_means.get(cohort, global_goals), 0.25, 5.0))

        def factors(team_id: object) -> tuple[float, float]:
            if not hierarchical:
                return 1.0, 1.0
            goals_for, goals_against, exposure = team_stats.get(
                (cohort, str(team_id)), (0.0, 0.0, 0.0)
            )
            denominator = exposure + prior_games
            attack_rate = (goals_for + prior_games * mean_goals) / denominator
            defence_rate = (goals_against + prior_games * mean_goals) / denominator
            return attack_rate / mean_goals, defence_rate / mean_goals

        attack_a, defence_a = factors(row.get("team_a_id"))
        attack_b, defence_b = factors(row.get("team_b_id"))
        rate_a = float(np.clip(mean_goals * attack_a * defence_b, 0.05, 8.0))
        rate_b = float(np.clip(mean_goals * attack_b * defence_a, 0.05, 8.0))
        prediction = _score_summary(rate_a, rate_b, max_goals)
        rows.append(
            {
                **row,
                **prediction,
                "predicted_outcome": (
                    "team_a"
                    if prediction["prob_team_a_win"] >= max(
                        prediction["prob_draw"], prediction["prob_team_b_win"]
                    )
                    else "draw"
                    if prediction["prob_draw"] >= prediction["prob_team_b_win"]
                    else "team_b"
                ),
                "model_name": (
                    "historical_hierarchical_poisson"
                    if hierarchical
                    else "cohort_average_poisson"
                ),
            }
        )
    return pd.DataFrame(rows)


def build_frozen_holdout_benchmark(
    candidates: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Score candidates on identical fixtures and rank without peeking at training data."""

    if not candidates:
        return pd.DataFrame()
    fixture_sets = {
        name: set(frame["game_id"].astype(str)) if not frame.empty else set()
        for name, frame in candidates.items()
    }
    common_fixture_ids = set.intersection(*fixture_sets.values()) if fixture_sets else set()
    rows: list[dict[str, object]] = []
    for name, frame in candidates.items():
        common_frame = frame[frame["game_id"].astype(str).isin(common_fixture_ids)].copy()
        summary = compute_evaluation_summary(common_frame)
        rows.append({"candidate": name, "shared_examples": len(common_frame), **summary})
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    rank_columns: list[str] = []
    for metric, higher_is_better in BENCHMARK_METRICS:
        if metric not in table.columns or table[metric].isna().all():
            continue
        rank_column = f"rank_{metric}"
        table[rank_column] = table[metric].rank(
            ascending=not higher_is_better,
            method="min",
            na_option="bottom",
        )
        rank_columns.append(rank_column)
    table["mean_metric_rank"] = table[rank_columns].mean(axis=1) if rank_columns else np.nan
    table["benchmark_rank"] = table["mean_metric_rank"].rank(method="min").astype("Int64")
    return table.sort_values(["benchmark_rank", "candidate"]).reset_index(drop=True)
