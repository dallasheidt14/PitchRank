"""Leakage-safe benchmark models for point-in-time match prediction.

These models are deliberately simple and interpretable. They establish whether
the learned MatchBalance model improves on cohort scoring rates and a
recency-weighted team attack/defence model on the exact same frozen holdout.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Literal, Mapping

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

COUNT_MODEL_FAMILIES = frozenset(
    {
        "poisson",
        "negative_binomial",
        "bivariate_poisson",
    }
)
CountModelFamily = Literal["poisson", "negative_binomial", "bivariate_poisson"]


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


def _negative_binomial_vector(rate: float, dispersion: float, max_goals: int) -> np.ndarray:
    """Return a mean/dispersion negative-binomial PMF with a folded tail."""

    rate = float(np.clip(rate, 0.05, 8.0))
    dispersion = max(0.0, float(dispersion))
    if dispersion <= 1e-8:
        return _poisson_vector(rate, max_goals)
    shape = 1.0 / dispersion
    success_probability = shape / (shape + rate)
    values = np.zeros(max_goals + 1, dtype=float)
    values[0] = success_probability**shape
    for goals in range(1, max_goals):
        values[goals] = (
            values[goals - 1]
            * (goals - 1 + shape)
            / goals
            * (1.0 - success_probability)
        )
    values[max_goals] = max(0.0, 1.0 - float(values[:max_goals].sum()))
    return values / values.sum()


def _bivariate_poisson_matrix(
    rate_a: float,
    rate_b: float,
    shared_rate: float,
    max_goals: int,
) -> np.ndarray:
    """Return the score PMF for two Poisson counts with one shared component."""

    rate_a = float(np.clip(rate_a, 0.05, 8.0))
    rate_b = float(np.clip(rate_b, 0.05, 8.0))
    shared_rate = float(np.clip(shared_rate, 0.0, 0.8 * min(rate_a, rate_b)))
    independent_a = max(0.001, rate_a - shared_rate)
    independent_b = max(0.001, rate_b - shared_rate)
    # A wider internal grid makes the max_goals cell a genuine overflow bucket.
    internal_max = max(max_goals + 8, 16)
    component_a = _poisson_vector(independent_a, internal_max)
    component_b = _poisson_vector(independent_b, internal_max)
    shared = (
        _poisson_vector(shared_rate, internal_max)
        if shared_rate > 0
        else np.concatenate(([1.0], np.zeros(internal_max, dtype=float)))
    )
    matrix = np.zeros((max_goals + 1, max_goals + 1), dtype=float)
    for common_goals, common_probability in enumerate(shared):
        if common_probability <= 0:
            continue
        for goals_a, probability_a in enumerate(component_a):
            if probability_a <= 0:
                continue
            output_a = min(max_goals, common_goals + goals_a)
            for goals_b, probability_b in enumerate(component_b):
                output_b = min(max_goals, common_goals + goals_b)
                matrix[output_a, output_b] += (
                    common_probability * probability_a * probability_b
                )
    return matrix / matrix.sum()


def _score_summary_from_matrix(
    matrix: np.ndarray,
    rate_a: float,
    rate_b: float,
) -> dict[str, float]:
    max_goals = int(matrix.shape[0] - 1)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("score matrix must be square")
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


def _score_summary(
    rate_a: float,
    rate_b: float,
    max_goals: int,
    *,
    family: CountModelFamily = "poisson",
    dispersion: float = 0.0,
    shared_rate: float = 0.0,
) -> dict[str, float]:
    if family == "poisson":
        matrix = np.outer(
            _poisson_vector(rate_a, max_goals),
            _poisson_vector(rate_b, max_goals),
        )
    elif family == "negative_binomial":
        matrix = np.outer(
            _negative_binomial_vector(rate_a, dispersion, max_goals),
            _negative_binomial_vector(rate_b, dispersion, max_goals),
        )
    elif family == "bivariate_poisson":
        matrix = _bivariate_poisson_matrix(
            rate_a,
            rate_b,
            shared_rate,
            max_goals,
        )
    else:  # pragma: no cover - guarded by the public entrypoint
        raise ValueError(f"Unsupported count model family: {family}")
    return _score_summary_from_matrix(matrix, rate_a, rate_b)


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

    return build_historical_count_benchmark(
        train_frame,
        test_frame,
        family="poisson",
        hierarchical=hierarchical,
        half_life_days=half_life_days,
        prior_games=prior_games,
        max_goals=max_goals,
    )


def build_historical_count_benchmark(
    train_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    *,
    family: CountModelFamily,
    hierarchical: bool = True,
    half_life_days: float = 120.0,
    prior_games: float = 6.0,
    max_goals: int = 8,
) -> pd.DataFrame:
    """Predict a holdout with an interpretable historical count model."""

    if family not in COUNT_MODEL_FAMILIES:
        raise ValueError(
            f"Unsupported count model family '{family}'. Expected one of "
            f"{sorted(COUNT_MODEL_FAMILIES)}"
        )
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

    cohort_goals: dict[tuple[int, str], list[float]] = defaultdict(
        lambda: [0.0, 0.0, 0.0]
    )
    cohort_pairs: dict[tuple[int, str], list[float]] = defaultdict(
        lambda: [0.0, 0.0, 0.0, 0.0]
    )
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
        cohort_goals[cohort][1] += weight * (score_a**2 + score_b**2)
        cohort_goals[cohort][2] += 2.0 * weight
        pair_stats = cohort_pairs[cohort]
        pair_stats[0] += weight * score_a
        pair_stats[1] += weight * score_b
        pair_stats[2] += weight * score_a * score_b
        pair_stats[3] += weight
        for team_id, goals_for, goals_against in (
            (str(row["team_a_id"]), score_a, score_b),
            (str(row["team_b_id"]), score_b, score_a),
        ):
            stats = team_stats[(cohort, team_id)]
            stats[0] += weight * goals_for
            stats[1] += weight * goals_against
            stats[2] += weight

    cohort_means = {
        key: totals[0] / totals[2] if totals[2] > 0 else global_goals
        for key, totals in cohort_goals.items()
    }
    global_score_values = pd.concat(
        [
            pd.to_numeric(games["actual_score_a"], errors="coerce"),
            pd.to_numeric(games["actual_score_b"], errors="coerce"),
        ],
        ignore_index=True,
    ).dropna()
    global_variance = float(global_score_values.var(ddof=0)) if not global_score_values.empty else global_goals
    global_dispersion = max(
        0.0,
        (global_variance - global_goals) / max(global_goals**2, 1e-6),
    )
    cohort_dispersion = {}
    for key, totals in cohort_goals.items():
        mean = cohort_means[key]
        variance = max(0.0, totals[1] / totals[2] - mean**2) if totals[2] > 0 else global_variance
        cohort_dispersion[key] = float(
            np.clip((variance - mean) / max(mean**2, 1e-6), 0.0, 2.0)
        )
    cohort_shared_rate = {}
    for key, totals in cohort_pairs.items():
        if totals[3] <= 0:
            cohort_shared_rate[key] = 0.0
            continue
        mean_a = totals[0] / totals[3]
        mean_b = totals[1] / totals[3]
        covariance = totals[2] / totals[3] - mean_a * mean_b
        cohort_shared_rate[key] = float(np.clip(covariance, 0.0, 1.5))

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
        prediction = _score_summary(
            rate_a,
            rate_b,
            max_goals,
            family=family,
            dispersion=cohort_dispersion.get(cohort, global_dispersion),
            shared_rate=cohort_shared_rate.get(cohort, 0.0),
        )
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
                    f"historical_hierarchical_{family}"
                    if hierarchical
                    else f"cohort_average_{family}"
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
