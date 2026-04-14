"""
Point-in-time match model training harness.

This module is intentionally offline-only for now. It builds a leakage-safe
training frame from `prediction_feature_history` snapshots plus historical games,
then trains a 3-way match outcome model and score regressors. The live compare
predictor remains unchanged until the backfill is large enough to validate a swap.
"""

from __future__ import annotations

import json
import logging
import math
import os
import pickle
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.isotonic import IsotonicRegression

try:
    from xgboost import XGBClassifier, XGBRegressor

    HAS_XGBOOST = True
except ImportError:  # pragma: no cover - exercised only when xgboost is missing
    HAS_XGBOOST = False

from scripts.predictor_python import (
    COMMON_OPPONENT_RECENCY_DAYS,
    _latest_game_timestamp,
    calculate_common_opponent_signal,
    calculate_head_to_head,
    calculate_recent_form,
)
from scripts.predictor_python import (
    Game as PredictorGame,
)
from src.predictions.evaluation_reporting import (
    OUTCOME_ORDER,
    PROBABILITY_COLUMNS,
    build_standardized_evaluation_frame,
    compute_evaluation_summary,
    write_evaluation_bundle,
)

logger = logging.getLogger(__name__)


OUTCOME_TEAM_A_WIN = 0
OUTCOME_DRAW = 1
OUTCOME_TEAM_B_WIN = 2

OUTCOME_LABELS = {
    OUTCOME_TEAM_A_WIN: "team_a_win",
    OUTCOME_DRAW: "draw",
    OUTCOME_TEAM_B_WIN: "team_b_win",
}

FEATURE_EXCLUDE_COLUMNS = {
    "game_id",
    "game_date",
    "team_a_id",
    "team_b_id",
    "team_a_name",
    "team_b_name",
    "team_a_snapshot_date",
    "team_b_snapshot_date",
    "example_orientation",
    "actual_score_a",
    "actual_score_b",
    "actual_margin",
    "actual_outcome",
    "actual_outcome_label",
}

SNAPSHOT_NUMERIC_FIELDS = [
    "power_score_final",
    "sos_norm",
    "offense_norm",
    "defense_norm",
    "glicko_rating",
    "glicko_rd",
    "glicko_volatility",
    "games_played",
    "wins",
    "losses",
    "draws",
    "win_percentage",
    "rank_in_cohort_final",
    "same_age_games",
    "same_age_game_share",
    "same_age_unique_opponents",
    "same_age_top100_opp_count",
    "same_age_top500_opp_count",
    "same_age_avg_opp_power_adj",
    "repeat_opponent_share",
    "positive_ml_evidence_scale",
    "publication_cap_rank",
    "publication_cap_score",
    "exp_margin",
    "exp_win_rate",
    "exp_goals_for",
    "exp_goals_against",
]

PREDICTIVE_PRIOR_FIELDS = [
    "exp_margin",
    "exp_win_rate",
    "exp_goals_for",
    "exp_goals_against",
]

POISSON_MAX_GOALS = 8
DRAW_CLASS_WEIGHT_BOOST = 1.6
DRAW_BINARY_WEIGHT_CAP = 4.0
DRAW_MODEL_SHRINK_FACTOR = 0.3
BLOWOUT_CLASS_WEIGHT_CAP = 5.0
DEFAULT_PROBABILITY_STRATEGY = "auto"
AUTO_PROBABILITY_STRATEGY = "auto"
POISSON_DRAW_GATE_PROBABILITY_MIN = 0.25
POISSON_DRAW_GATE_TOTAL_GOALS_MAX = 2.2
POISSON_DRAW_GATE_STALEMATE_MIN = 0.60
POISSON_DRAW_GATE_EXPECTED_GOAL_GAP_MAX = 0.45
BLOWOUT_THRESHOLDS = (3, 5)
LOW_SCORE_CORRELATION_BASE = -0.035
LOW_SCORE_CORRELATION_MAX = -0.18
BLOWOUT_THRESHOLD_GRID = np.linspace(0.05, 0.85, 81)
BLOWOUT_RATE_TOLERANCE_SHARE = 0.08
BLOWOUT_RATE_TOLERANCE_MIN = 0.02
BLOWOUT_RATE_OVERSHOOT_PENALTY = 0.9
BLOWOUT_RATE_UNDERSHOOT_PENALTY = 0.45
BLOWOUT_RATE_GAP_PENALTY = 0.25
DRAW_POLICY_MIN_PROBABILITY_GRID = np.array([0.16, 0.18, 0.20, 0.22, 0.24, 0.26])
DRAW_POLICY_MAX_GAP_GRID = np.array([0.00, 0.02, 0.04, 0.06, 0.08])
DRAW_POLICY_MAX_TOTAL_GOALS_GRID = np.array([2.2, 2.4, 2.6])
DRAW_POLICY_MIN_STALEMATE_GRID = np.array([0.52, 0.60, 0.68])
DRAW_POLICY_BETA = 1.35
DRAW_POLICY_RATE_TOLERANCE_SHARE = 0.18
DRAW_POLICY_RATE_TOLERANCE_MIN = 0.025
DRAW_POLICY_OVERSHOOT_PENALTY = 0.9
DRAW_POLICY_UNDERSHOOT_PENALTY = 0.4
DRAW_POLICY_RATE_GAP_PENALTY = 0.35
COHORT_POSTPROCESSING_MIN_SAMPLES = 750
DEFAULT_AUTO_STRATEGY_CONSTRAINTS = {
    "min_draw_recall": 0.08,
    "max_draw_rate_gap": 0.08,
    "winner_accuracy_tolerance": 0.015,
    "log_loss_tolerance": 0.003,
}
AUTO_STRATEGY_RANK_WEIGHTS = {
    "winner_accuracy": 3.0,
    "log_loss": 4.0,
    "brier_score": 3.0,
    "draw_recall": 2.5,
    "draw_rate_gap": 1.75,
    "exact_score_accuracy": 1.5,
    "score_within_one_goal_rate": 1.5,
    "total_goals_mae": 1.5,
    "blowout_3plus_brier": 1.0,
    "blowout_5plus_brier": 1.0,
}
PROBABILITY_STRATEGIES = {"hybrid", "poisson_primary", "poisson_draw_gate"}
TRAINING_PROBABILITY_STRATEGIES = PROBABILITY_STRATEGIES | {AUTO_PROBABILITY_STRATEGY}


@dataclass
class DatasetBuildResult:
    dataset: pd.DataFrame
    summary: Dict[str, object]


@dataclass
class StrategyOutputs:
    probabilities: np.ndarray
    poisson_probabilities: np.ndarray
    draw_model_probability: np.ndarray
    expected_goals_a: np.ndarray
    expected_goals_b: np.ndarray
    predicted_score_a: np.ndarray
    predicted_score_b: np.ndarray
    blowout_3plus_probability: np.ndarray
    blowout_5plus_probability: np.ndarray


@dataclass
class BlowoutPostprocessing:
    calibrator_3plus: Optional[IsotonicRegression]
    calibrator_5plus: Optional[IsotonicRegression]
    thresholds: Dict[int, float]
    thresholds_by_age: Dict[int, Dict[int, float]]


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: object, default: int = 0) -> int:
    if value is None or pd.isna(value):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _snapshot_age_days(snapshot_row: dict, game_date: str) -> float:
    snapshot_date = snapshot_row.get("snapshot_date")
    if not snapshot_date:
        return 0.0
    try:
        return max(
            0.0,
            float((pd.Timestamp(game_date).normalize() - pd.Timestamp(snapshot_date).normalize()).days),
        )
    except Exception:
        return 0.0


def _is_active_status(status_value: object) -> float:
    return 1.0 if str(status_value or "").strip().lower() == "active" else 0.0


def _is_female_gender(gender_value: object) -> float:
    normalized = str(gender_value or "").strip().lower()
    return 1.0 if normalized in {"female", "f", "girls", "girl", "g"} else 0.0


def _extract_age_numeric(age_value: object) -> int:
    if age_value is None or pd.isna(age_value):
        return 0
    try:
        return int(age_value)
    except (TypeError, ValueError):
        pass

    match = re.search(r"\d+", str(age_value))
    return int(match.group()) if match else 0


def _age_group_numeric_array(dataset_df: pd.DataFrame) -> np.ndarray:
    age_source = dataset_df.get("age_group_numeric")
    if age_source is None:
        age_source = dataset_df.get("age_group")
    if age_source is None:
        return np.zeros(len(dataset_df), dtype=int)
    if not isinstance(age_source, pd.Series):
        age_source = pd.Series(age_source, index=dataset_df.index)
    return pd.to_numeric(age_source.map(_extract_age_numeric), errors="coerce").fillna(0).astype(int).to_numpy()


def _snapshot_as_of(snapshot_index: Dict[str, List[dict]], team_id: str, target_date: str) -> Optional[dict]:
    entries = snapshot_index.get(team_id)
    if not entries:
        return None

    target_ts = pd.Timestamp(target_date).normalize()
    candidate = None

    for entry in entries:
        snapshot_ts = entry.get("snapshot_ts")
        if snapshot_ts is None or pd.isna(snapshot_ts):
            snapshot_date = entry.get("snapshot_date")
            if not snapshot_date:
                continue
            try:
                snapshot_ts = pd.Timestamp(snapshot_date).normalize()
            except Exception:
                continue

        if snapshot_ts <= target_ts:
            candidate = entry
            continue
        break

    return candidate


def _paired_snapshot_features(team_a_snapshot: dict, team_b_snapshot: dict) -> Dict[str, float]:
    features: Dict[str, float] = {}

    for field_name in SNAPSHOT_NUMERIC_FIELDS:
        team_a_value = _to_float(team_a_snapshot.get(field_name))
        team_b_value = _to_float(team_b_snapshot.get(field_name))
        features[f"team_a_{field_name}"] = team_a_value
        features[f"team_b_{field_name}"] = team_b_value
        features[f"{field_name}_diff"] = team_a_value - team_b_value
        features[f"{field_name}_sum"] = team_a_value + team_b_value

    features.update(
        {
            "team_a_is_active": _is_active_status(team_a_snapshot.get("status")),
            "team_b_is_active": _is_active_status(team_b_snapshot.get("status")),
            "both_active": _is_active_status(team_a_snapshot.get("status"))
            * _is_active_status(team_b_snapshot.get("status")),
            "team_a_is_female": _is_female_gender(team_a_snapshot.get("gender")),
            "team_b_is_female": _is_female_gender(team_b_snapshot.get("gender")),
            "same_gender_matchup": 1.0
            if str(team_a_snapshot.get("gender") or "").lower() == str(team_b_snapshot.get("gender") or "").lower()
            else 0.0,
            "snapshot_age_days_team_a": _snapshot_age_days(team_a_snapshot, team_a_snapshot.get("_game_date", "")),
            "snapshot_age_days_team_b": _snapshot_age_days(team_b_snapshot, team_b_snapshot.get("_game_date", "")),
            "age_group_numeric": max(
                _extract_age_numeric(team_a_snapshot.get("age_group")),
                _extract_age_numeric(team_b_snapshot.get("age_group")),
            ),
        }
    )

    offense_diff = _to_float(team_a_snapshot.get("offense_norm")) - _to_float(team_b_snapshot.get("offense_norm"))
    defense_diff = _to_float(team_a_snapshot.get("defense_norm")) - _to_float(team_b_snapshot.get("defense_norm"))
    team_a_games = max(_to_float(team_a_snapshot.get("games_played")), 1.0)
    team_b_games = max(_to_float(team_b_snapshot.get("games_played")), 1.0)
    team_a_draw_rate = _safe_rate(_to_float(team_a_snapshot.get("draws")), team_a_games)
    team_b_draw_rate = _safe_rate(_to_float(team_b_snapshot.get("draws")), team_b_games)

    prior_goal_a_inputs = [
        _to_float(team_a_snapshot.get("exp_goals_for"), default=float("nan")),
        _to_float(team_b_snapshot.get("exp_goals_against"), default=float("nan")),
        1.25
        + 2.2 * (_to_float(team_a_snapshot.get("offense_norm")) - 0.5)
        - 1.6 * (_to_float(team_b_snapshot.get("defense_norm")) - 0.5),
    ]
    prior_goal_b_inputs = [
        _to_float(team_b_snapshot.get("exp_goals_for"), default=float("nan")),
        _to_float(team_a_snapshot.get("exp_goals_against"), default=float("nan")),
        1.25
        + 2.2 * (_to_float(team_b_snapshot.get("offense_norm")) - 0.5)
        - 1.6 * (_to_float(team_a_snapshot.get("defense_norm")) - 0.5),
    ]
    projected_goals_team_a = float(np.clip(np.nanmean(prior_goal_a_inputs), 0.15, 6.0))
    projected_goals_team_b = float(np.clip(np.nanmean(prior_goal_b_inputs), 0.15, 6.0))
    projected_total_goals = projected_goals_team_a + projected_goals_team_b
    projected_goal_gap_abs = abs(projected_goals_team_a - projected_goals_team_b)

    snapshot_closeness_components = [
        math.exp(
            -5.5
            * abs(
                _to_float(team_a_snapshot.get("power_score_final"))
                - _to_float(team_b_snapshot.get("power_score_final"))
            )
        ),
        math.exp(
            -abs(_to_float(team_a_snapshot.get("glicko_rating")) - _to_float(team_b_snapshot.get("glicko_rating")))
            / 140.0
        ),
        math.exp(
            -abs(_to_float(team_a_snapshot.get("exp_margin")) - _to_float(team_b_snapshot.get("exp_margin"))) / 1.25
        ),
        math.exp(
            -6.0 * abs(_to_float(team_a_snapshot.get("exp_win_rate")) - _to_float(team_b_snapshot.get("exp_win_rate")))
        ),
    ]
    snapshot_strength_closeness = float(np.mean(snapshot_closeness_components))
    low_total_goal_signal = float(math.exp(-max(projected_total_goals - 2.4, 0.0) / 1.25))
    goal_balance_signal = float(math.exp(-projected_goal_gap_abs / 0.85))
    features.update(
        {
            "offense_vs_defense_edge": _to_float(team_a_snapshot.get("offense_norm"))
            - _to_float(team_b_snapshot.get("defense_norm")),
            "defense_vs_offense_edge": _to_float(team_a_snapshot.get("defense_norm"))
            - _to_float(team_b_snapshot.get("offense_norm")),
            "rank_advantage": _to_float(team_b_snapshot.get("rank_in_cohort_final"), default=9999.0)
            - _to_float(team_a_snapshot.get("rank_in_cohort_final"), default=9999.0),
            "glicko_confidence_gap": _to_float(team_b_snapshot.get("glicko_rd"))
            - _to_float(team_a_snapshot.get("glicko_rd")),
            "power_sos_interaction_diff": (
                _to_float(team_a_snapshot.get("power_score_final")) * _to_float(team_a_snapshot.get("sos_norm"))
            )
            - (_to_float(team_b_snapshot.get("power_score_final")) * _to_float(team_b_snapshot.get("sos_norm"))),
            "offense_defense_balance_diff": offense_diff - defense_diff,
            "team_a_has_predictive_prior": 1.0
            if any(pd.notna(team_a_snapshot.get(field_name)) for field_name in PREDICTIVE_PRIOR_FIELDS)
            else 0.0,
            "team_b_has_predictive_prior": 1.0
            if any(pd.notna(team_b_snapshot.get(field_name)) for field_name in PREDICTIVE_PRIOR_FIELDS)
            else 0.0,
            "team_a_draw_rate": team_a_draw_rate,
            "team_b_draw_rate": team_b_draw_rate,
            "draw_rate_diff": team_a_draw_rate - team_b_draw_rate,
            "draw_rate_sum": team_a_draw_rate + team_b_draw_rate,
            "draw_rate_gap_abs": abs(team_a_draw_rate - team_b_draw_rate),
            "combined_draw_rate": (team_a_draw_rate + team_b_draw_rate) / 2.0,
            "projected_goals_team_a": projected_goals_team_a,
            "projected_goals_team_b": projected_goals_team_b,
            "projected_total_goals": projected_total_goals,
            "projected_goal_gap_abs": projected_goal_gap_abs,
            "low_total_goal_signal": low_total_goal_signal,
            "goal_balance_signal": goal_balance_signal,
            "snapshot_strength_closeness": snapshot_strength_closeness,
        }
    )

    return features


def _poisson_probability_matrix(lambdas: np.ndarray, max_goals: int = POISSON_MAX_GOALS) -> np.ndarray:
    clipped = np.clip(np.asarray(lambdas, dtype=float), 0.05, 8.0)
    matrix = np.zeros((clipped.shape[0], max_goals + 1), dtype=float)
    matrix[:, 0] = np.exp(-clipped)
    for goal_count in range(1, max_goals):
        matrix[:, goal_count] = matrix[:, goal_count - 1] * clipped / float(goal_count)
    matrix[:, max_goals] = np.clip(1.0 - matrix[:, :max_goals].sum(axis=1), 0.0, 1.0)
    return matrix


def _poisson_outcome_probabilities(
    team_a_expected_goals: np.ndarray,
    team_b_expected_goals: np.ndarray,
    max_goals: int = POISSON_MAX_GOALS,
) -> np.ndarray:
    probs_a = _poisson_probability_matrix(team_a_expected_goals, max_goals=max_goals)
    probs_b = _poisson_probability_matrix(team_b_expected_goals, max_goals=max_goals)

    draw_prob = np.sum(probs_a * probs_b, axis=1)
    team_b_cumulative_less = np.cumsum(probs_b, axis=1) - probs_b
    team_a_cumulative_less = np.cumsum(probs_a, axis=1) - probs_a
    team_a_win_prob = np.sum(probs_a * team_b_cumulative_less, axis=1)
    team_b_win_prob = np.sum(probs_b * team_a_cumulative_less, axis=1)

    probability_frame = np.column_stack([team_a_win_prob, draw_prob, team_b_win_prob])
    row_sums = probability_frame.sum(axis=1, keepdims=True)
    return np.divide(
        probability_frame,
        row_sums,
        out=np.full_like(probability_frame, 1.0 / 3.0),
        where=row_sums > 0,
    )


def _dixon_coles_rho(
    draw_model_probability: np.ndarray,
    stalemate_signal: np.ndarray,
    projected_total_goals: np.ndarray,
    expected_goal_gap_abs: np.ndarray,
) -> np.ndarray:
    draw_component = np.clip((np.asarray(draw_model_probability, dtype=float) - 0.12) / 0.22, 0.0, 1.0)
    stalemate_component = np.clip(np.asarray(stalemate_signal, dtype=float), 0.0, 1.0)
    low_total_component = np.exp(-np.maximum(np.asarray(projected_total_goals, dtype=float) - 2.2, 0.0) / 0.75)
    closeness_component = np.exp(-np.asarray(expected_goal_gap_abs, dtype=float) / 0.65)
    rho_strength = (
        0.20 * draw_component + 0.35 * stalemate_component + 0.25 * low_total_component + 0.20 * closeness_component
    )
    return np.clip(
        LOW_SCORE_CORRELATION_BASE + (LOW_SCORE_CORRELATION_MAX - LOW_SCORE_CORRELATION_BASE) * rho_strength,
        LOW_SCORE_CORRELATION_MAX,
        -0.01,
    )


def _poisson_score_matrix(
    team_a_expected_goals: np.ndarray,
    team_b_expected_goals: np.ndarray,
    rho: Optional[np.ndarray] = None,
    max_goals: int = POISSON_MAX_GOALS,
) -> np.ndarray:
    probs_a = _poisson_probability_matrix(team_a_expected_goals, max_goals=max_goals)
    probs_b = _poisson_probability_matrix(team_b_expected_goals, max_goals=max_goals)
    score_matrix = probs_a[:, :, None] * probs_b[:, None, :]

    if rho is not None:
        rho = np.asarray(rho, dtype=float)
        lambda_vals = np.clip(np.asarray(team_a_expected_goals, dtype=float), 0.05, 8.0)
        mu_vals = np.clip(np.asarray(team_b_expected_goals, dtype=float), 0.05, 8.0)
        score_matrix[:, 0, 0] *= np.clip(1.0 - lambda_vals * mu_vals * rho, 0.5, 1.5)
        score_matrix[:, 0, 1] *= np.clip(1.0 + lambda_vals * rho, 0.5, 1.5)
        score_matrix[:, 1, 0] *= np.clip(1.0 + mu_vals * rho, 0.5, 1.5)
        score_matrix[:, 1, 1] *= np.clip(1.0 - rho, 0.5, 1.5)

    row_sums = score_matrix.sum(axis=(1, 2), keepdims=True)
    return np.divide(
        score_matrix,
        row_sums,
        out=np.full_like(score_matrix, 1.0 / ((max_goals + 1) ** 2)),
        where=row_sums > 0,
    )


def _score_matrix_outcome_probabilities(score_matrix: np.ndarray) -> np.ndarray:
    team_a_win = np.tril(score_matrix, k=-1).sum(axis=(1, 2))
    draw = np.diagonal(score_matrix, axis1=1, axis2=2).sum(axis=1)
    team_b_win = np.triu(score_matrix, k=1).sum(axis=(1, 2))
    outcomes = np.column_stack([team_a_win, draw, team_b_win])
    row_sums = outcomes.sum(axis=1, keepdims=True)
    return np.divide(
        outcomes,
        row_sums,
        out=np.full_like(outcomes, 1.0 / 3.0),
        where=row_sums > 0,
    )


def _score_matrix_summary(score_matrix: np.ndarray) -> Dict[str, np.ndarray]:
    goals_axis = np.arange(score_matrix.shape[1], dtype=float)
    expected_goals_a = np.sum(score_matrix * goals_axis[None, :, None], axis=(1, 2))
    expected_goals_b = np.sum(score_matrix * goals_axis[None, None, :], axis=(1, 2))
    draw_probability = np.trace(score_matrix, axis1=1, axis2=2)

    flat_indices = np.argmax(score_matrix.reshape(score_matrix.shape[0], -1), axis=1)
    predicted_score_a = (flat_indices // score_matrix.shape[2]).astype(float)
    predicted_score_b = (flat_indices % score_matrix.shape[2]).astype(float)

    goal_margin_abs = np.abs(np.arange(score_matrix.shape[1])[:, None] - np.arange(score_matrix.shape[2])[None, :])
    blowout_3plus_probability = score_matrix[:, goal_margin_abs >= 3].sum(axis=1)
    blowout_5plus_probability = score_matrix[:, goal_margin_abs >= 5].sum(axis=1)

    return {
        "expected_goals_a": expected_goals_a,
        "expected_goals_b": expected_goals_b,
        "draw_probability": draw_probability,
        "predicted_score_a": predicted_score_a,
        "predicted_score_b": predicted_score_b,
        "blowout_3plus_probability": blowout_3plus_probability,
        "blowout_5plus_probability": blowout_5plus_probability,
    }


def _poisson_draw_gate_mask(
    draw_probability: np.ndarray,
    projected_total_goals: np.ndarray,
    stalemate_signal: np.ndarray,
    expected_goal_gap_abs: np.ndarray,
) -> np.ndarray:
    return (
        (np.asarray(draw_probability, dtype=float) >= POISSON_DRAW_GATE_PROBABILITY_MIN)
        & (np.asarray(projected_total_goals, dtype=float) <= POISSON_DRAW_GATE_TOTAL_GOALS_MAX)
        & (np.asarray(stalemate_signal, dtype=float) >= POISSON_DRAW_GATE_STALEMATE_MIN)
        & (np.asarray(expected_goal_gap_abs, dtype=float) <= POISSON_DRAW_GATE_EXPECTED_GOAL_GAP_MAX)
    )


def _build_common_opponent_feature_summary(
    team_a_id: str,
    team_b_id: str,
    all_games: List[PredictorGame],
    snapshot_index: Dict[str, List[dict]],
    target_date: str,
    team_age_numeric: int,
) -> Dict[str, float]:
    latest_timestamp = _latest_game_timestamp(all_games)
    team_a_opponents: Dict[str, Dict[str, float]] = {}
    team_b_opponents: Dict[str, Dict[str, float]] = {}

    for game in all_games:
        if game.home_score is None or game.away_score is None:
            continue

        involves_team_a = game.home_team_master_id == team_a_id or game.away_team_master_id == team_a_id
        involves_team_b = game.home_team_master_id == team_b_id or game.away_team_master_id == team_b_id
        if (not involves_team_a and not involves_team_b) or (involves_team_a and involves_team_b):
            continue

        subject_team_id = team_a_id if involves_team_a else team_b_id
        is_home = game.home_team_master_id == subject_team_id
        opponent_id = game.away_team_master_id if is_home else game.home_team_master_id
        if opponent_id is None or opponent_id in {team_a_id, team_b_id}:
            continue

        team_score = game.home_score if is_home else game.away_score
        opp_score = game.away_score if is_home else game.home_score
        if team_score is None or opp_score is None:
            continue

        try:
            game_timestamp = float(pd.Timestamp(game.game_date).timestamp())
            days_since = (
                max(0.0, (latest_timestamp - game_timestamp) / 86400.0) if latest_timestamp is not None else 0.0
            )
        except Exception:
            days_since = 0.0

        recency_weight = math.exp(-days_since / COMMON_OPPONENT_RECENCY_DAYS)
        opponent_snapshot = _snapshot_as_of(snapshot_index, str(opponent_id), target_date)
        opponent_power = _to_float(opponent_snapshot.get("power_score_final")) if opponent_snapshot else 0.5
        opponent_age = _extract_age_numeric(opponent_snapshot.get("age_group")) if opponent_snapshot else 0
        same_age = 1.0 if team_age_numeric > 0 and opponent_age == team_age_numeric else 0.0
        opponent_strength_weight = float(np.clip(0.75 + opponent_power, 0.6, 1.75))
        weighted_sample = recency_weight * opponent_strength_weight * (1.15 if same_age else 1.0)

        points = 3.0 if team_score > opp_score else 1.0 if team_score == opp_score else 0.0
        win_rate = 1.0 if team_score > opp_score else 0.0
        draw_rate = 1.0 if team_score == opp_score else 0.0
        goal_margin = float(team_score - opp_score)
        bucket = team_a_opponents if subject_team_id == team_a_id else team_b_opponents
        current = bucket.setdefault(
            str(opponent_id),
            {
                "weightedPoints": 0.0,
                "weightedMargin": 0.0,
                "weightedGoalsFor": 0.0,
                "weightedGoalsAgainst": 0.0,
                "weightedWins": 0.0,
                "weightedDraws": 0.0,
                "weightedOpponentPower": 0.0,
                "weightedSameAge": 0.0,
                "totalWeight": 0.0,
                "games": 0.0,
            },
        )
        current["weightedPoints"] += points * weighted_sample
        current["weightedMargin"] += goal_margin * weighted_sample
        current["weightedGoalsFor"] += float(team_score) * weighted_sample
        current["weightedGoalsAgainst"] += float(opp_score) * weighted_sample
        current["weightedWins"] += win_rate * weighted_sample
        current["weightedDraws"] += draw_rate * weighted_sample
        current["weightedOpponentPower"] += opponent_power * weighted_sample
        current["weightedSameAge"] += same_age * weighted_sample
        current["totalWeight"] += weighted_sample
        current["games"] += 1.0

    shared_opponents = [opponent_id for opponent_id in team_a_opponents if opponent_id in team_b_opponents]
    if not shared_opponents:
        return {
            "strengthWeightedSharedOpponents": 0.0,
            "sameAgeSharedOpponents": 0.0,
            "sameAgeSharedOpponentRate": 0.0,
            "strengthWeightedReliability": 0.0,
            "strengthWeightedMarginDiff": 0.0,
            "strengthWeightedPointsPerGameDiff": 0.0,
            "strengthWeightedGoalsForDiff": 0.0,
            "strengthWeightedGoalsAgainstAdv": 0.0,
            "strengthWeightedWinRateDiff": 0.0,
            "strengthWeightedDrawRateDiff": 0.0,
            "strengthWeightedGoalBalanceDiff": 0.0,
            "strengthWeightedOpponentPower": 0.0,
            "commonOpponentConsensusSignal": 0.0,
        }

    weight_sum = 0.0
    weighted_shared_count = 0.0
    same_age_shared_count = 0.0
    same_age_rate_weighted = 0.0
    weighted_reliability = 0.0
    weighted_margin_diff = 0.0
    weighted_points_diff = 0.0
    weighted_goals_for_diff = 0.0
    weighted_goals_against_adv = 0.0
    weighted_win_rate_diff = 0.0
    weighted_draw_rate_diff = 0.0
    weighted_goal_balance_diff = 0.0
    weighted_opponent_power = 0.0
    weighted_signal = 0.0

    for opponent_id in shared_opponents:
        team_a_stats = team_a_opponents[opponent_id]
        team_b_stats = team_b_opponents[opponent_id]
        if team_a_stats["totalWeight"] <= 0 or team_b_stats["totalWeight"] <= 0:
            continue

        team_a_points_per_game = team_a_stats["weightedPoints"] / team_a_stats["totalWeight"]
        team_b_points_per_game = team_b_stats["weightedPoints"] / team_b_stats["totalWeight"]
        team_a_avg_margin = team_a_stats["weightedMargin"] / team_a_stats["totalWeight"]
        team_b_avg_margin = team_b_stats["weightedMargin"] / team_b_stats["totalWeight"]
        team_a_goals_for = team_a_stats["weightedGoalsFor"] / team_a_stats["totalWeight"]
        team_b_goals_for = team_b_stats["weightedGoalsFor"] / team_b_stats["totalWeight"]
        team_a_goals_against = team_a_stats["weightedGoalsAgainst"] / team_a_stats["totalWeight"]
        team_b_goals_against = team_b_stats["weightedGoalsAgainst"] / team_b_stats["totalWeight"]
        team_a_win_rate = team_a_stats["weightedWins"] / team_a_stats["totalWeight"]
        team_b_win_rate = team_b_stats["weightedWins"] / team_b_stats["totalWeight"]
        team_a_draw_rate = team_a_stats["weightedDraws"] / team_a_stats["totalWeight"]
        team_b_draw_rate = team_b_stats["weightedDraws"] / team_b_stats["totalWeight"]
        team_a_goal_balance = team_a_goals_for - team_a_goals_against
        team_b_goal_balance = team_b_goals_for - team_b_goals_against

        points_diff = team_a_points_per_game - team_b_points_per_game
        margin_diff = team_a_avg_margin - team_b_avg_margin
        goals_for_diff = team_a_goals_for - team_b_goals_for
        goals_against_adv = team_b_goals_against - team_a_goals_against
        win_rate_diff = team_a_win_rate - team_b_win_rate
        draw_rate_diff = team_a_draw_rate - team_b_draw_rate
        goal_balance_diff = team_a_goal_balance - team_b_goal_balance

        avg_opponent_power = (team_a_stats["weightedOpponentPower"] + team_b_stats["weightedOpponentPower"]) / max(
            team_a_stats["totalWeight"] + team_b_stats["totalWeight"], 1e-9
        )
        same_age_rate = min(
            team_a_stats["weightedSameAge"] / team_a_stats["totalWeight"],
            team_b_stats["weightedSameAge"] / team_b_stats["totalWeight"],
        )
        reliability = math.sqrt(
            max(0.0, min(1.0, (team_a_stats["games"] + team_b_stats["games"]) / 6.0))
            * max(0.0, min(1.0, avg_opponent_power / 0.75))
        )
        opponent_weight = (
            max(0.35, min(1.35, (team_a_stats["games"] + team_b_stats["games"]) / 4.0))
            * (0.75 + avg_opponent_power)
            * (1.0 + 0.15 * same_age_rate)
        )
        opponent_signal = (
            max(-1.0, min(1.0, points_diff / 3.0)) * 0.30
            + max(-1.0, min(1.0, margin_diff / 4.0)) * 0.25
            + max(-1.0, min(1.0, goals_for_diff / 3.0)) * 0.15
            + max(-1.0, min(1.0, goals_against_adv / 3.0)) * 0.15
            + max(-1.0, min(1.0, goal_balance_diff / 4.0)) * 0.15
        )

        weight_sum += opponent_weight
        weighted_shared_count += opponent_weight
        same_age_shared_count += same_age_rate * opponent_weight
        same_age_rate_weighted += same_age_rate * opponent_weight
        weighted_reliability += reliability * opponent_weight
        weighted_margin_diff += margin_diff * opponent_weight
        weighted_points_diff += points_diff * opponent_weight
        weighted_goals_for_diff += goals_for_diff * opponent_weight
        weighted_goals_against_adv += goals_against_adv * opponent_weight
        weighted_win_rate_diff += win_rate_diff * opponent_weight
        weighted_draw_rate_diff += draw_rate_diff * opponent_weight
        weighted_goal_balance_diff += goal_balance_diff * opponent_weight
        weighted_opponent_power += avg_opponent_power * opponent_weight
        weighted_signal += opponent_signal * opponent_weight

    if weight_sum <= 0:
        return {
            "strengthWeightedSharedOpponents": 0.0,
            "sameAgeSharedOpponents": 0.0,
            "sameAgeSharedOpponentRate": 0.0,
            "strengthWeightedReliability": 0.0,
            "strengthWeightedMarginDiff": 0.0,
            "strengthWeightedPointsPerGameDiff": 0.0,
            "strengthWeightedGoalsForDiff": 0.0,
            "strengthWeightedGoalsAgainstAdv": 0.0,
            "strengthWeightedWinRateDiff": 0.0,
            "strengthWeightedDrawRateDiff": 0.0,
            "strengthWeightedGoalBalanceDiff": 0.0,
            "strengthWeightedOpponentPower": 0.0,
            "commonOpponentConsensusSignal": 0.0,
        }

    return {
        "strengthWeightedSharedOpponents": float(weighted_shared_count / max(weight_sum, 1.0)),
        "sameAgeSharedOpponents": float(same_age_shared_count / max(weight_sum, 1.0) * len(shared_opponents)),
        "sameAgeSharedOpponentRate": float(same_age_rate_weighted / weight_sum),
        "strengthWeightedReliability": float(weighted_reliability / weight_sum),
        "strengthWeightedMarginDiff": float(weighted_margin_diff / weight_sum),
        "strengthWeightedPointsPerGameDiff": float(weighted_points_diff / weight_sum),
        "strengthWeightedGoalsForDiff": float(weighted_goals_for_diff / weight_sum),
        "strengthWeightedGoalsAgainstAdv": float(weighted_goals_against_adv / weight_sum),
        "strengthWeightedWinRateDiff": float(weighted_win_rate_diff / weight_sum),
        "strengthWeightedDrawRateDiff": float(weighted_draw_rate_diff / weight_sum),
        "strengthWeightedGoalBalanceDiff": float(weighted_goal_balance_diff / weight_sum),
        "strengthWeightedOpponentPower": float(weighted_opponent_power / weight_sum),
        "commonOpponentConsensusSignal": float(weighted_signal / weight_sum),
    }


def _dedupe_games(games: Iterable[PredictorGame]) -> List[PredictorGame]:
    deduped: Dict[str, PredictorGame] = {}
    for game in games:
        deduped[game.id] = game
    return sorted(deduped.values(), key=lambda item: item.game_date, reverse=True)


def _outcome_label(score_a: int, score_b: int) -> Tuple[int, str]:
    if score_a > score_b:
        return OUTCOME_TEAM_A_WIN, OUTCOME_LABELS[OUTCOME_TEAM_A_WIN]
    if score_b > score_a:
        return OUTCOME_TEAM_B_WIN, OUTCOME_LABELS[OUTCOME_TEAM_B_WIN]
    return OUTCOME_DRAW, OUTCOME_LABELS[OUTCOME_DRAW]


def build_point_in_time_matchup_row(
    team_a_id: str,
    team_b_id: str,
    team_a_snapshot: dict,
    team_b_snapshot: dict,
    all_games: List[PredictorGame],
    game_date: str,
    *,
    snapshot_index: Optional[Dict[str, List[dict]]] = None,
    team_names: Optional[Dict[str, str]] = None,
    game_id: str = "shadow_matchup",
    example_orientation: str = "shadow",
    actual_score_a: Optional[int] = None,
    actual_score_b: Optional[int] = None,
) -> Dict[str, object]:
    """
    Build one offline-model feature row for a matchup using point-in-time snapshot fields.

    This is used both by the training harness and by shadow inference so the offline
    model sees the same feature assembly logic in both paths.
    """
    snapshot_index = snapshot_index or {}
    team_names = team_names or {}
    combined_prior_games = _dedupe_games(all_games)
    team_a_prior_games = [
        game
        for game in combined_prior_games
        if game.home_team_master_id == team_a_id or game.away_team_master_id == team_a_id
    ]
    team_b_prior_games = [
        game
        for game in combined_prior_games
        if game.home_team_master_id == team_b_id or game.away_team_master_id == team_b_id
    ]

    recent_form_a = calculate_recent_form(team_a_id, team_a_prior_games)
    recent_form_b = calculate_recent_form(team_b_id, team_b_prior_games)
    h2h = calculate_head_to_head(team_a_id, team_b_id, combined_prior_games)
    common_opponents = calculate_common_opponent_signal(team_a_id, team_b_id, combined_prior_games)
    common_opponent_details = _build_common_opponent_feature_summary(
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        all_games=combined_prior_games,
        snapshot_index=snapshot_index,
        target_date=game_date,
        team_age_numeric=max(
            _extract_age_numeric(team_a_snapshot.get("age_group")),
            _extract_age_numeric(team_b_snapshot.get("age_group")),
        ),
    )

    enriched_team_a_snapshot = {**team_a_snapshot, "_game_date": game_date}
    enriched_team_b_snapshot = {**team_b_snapshot, "_game_date": game_date}
    features = _paired_snapshot_features(enriched_team_a_snapshot, enriched_team_b_snapshot)

    if actual_score_a is not None and actual_score_b is not None:
        actual_outcome_code, actual_outcome_name = _outcome_label(int(actual_score_a), int(actual_score_b))
        actual_margin = int(actual_score_a - actual_score_b)
        actual_score_a_value = int(actual_score_a)
        actual_score_b_value = int(actual_score_b)
    else:
        actual_outcome_code = OUTCOME_DRAW
        actual_outcome_name = OUTCOME_LABELS[OUTCOME_DRAW]
        actual_margin = float("nan")
        actual_score_a_value = float("nan")
        actual_score_b_value = float("nan")

    features.update(
        {
            "team_a_recent_form": recent_form_a,
            "team_b_recent_form": recent_form_b,
            "recent_form_diff": recent_form_a - recent_form_b,
            "recent_form_gap_abs": abs(recent_form_a - recent_form_b),
            "recent_form_closeness": math.exp(-abs(recent_form_a - recent_form_b) / 0.3),
            "head_to_head_advantage": _to_float(h2h.get("advantage")),
            "head_to_head_games": _to_float(h2h.get("gamesPlayed")),
            "head_to_head_avg_margin": _to_float(h2h.get("avgMargin")),
            "head_to_head_gap_abs": abs(_to_float(h2h.get("advantage"))),
            "head_to_head_closeness": math.exp(-abs(_to_float(h2h.get("advantage"))) / 0.35)
            if _to_float(h2h.get("gamesPlayed")) > 0
            else 0.5,
            "common_opponent_advantage": _to_float(common_opponents.get("advantage")),
            "common_opponent_shared": _to_float(common_opponents.get("sharedOpponents")),
            "common_opponent_compared_games": _to_float(common_opponents.get("comparedGames")),
            "common_opponent_avg_margin_diff": _to_float(common_opponents.get("avgMarginDiff")),
            "common_opponent_points_diff": _to_float(common_opponents.get("pointsPerGameDiff")),
            "common_opponent_reliability": _to_float(common_opponents.get("reliability")),
            "common_opponent_gap_abs": abs(_to_float(common_opponents.get("advantage"))),
            "common_opponent_closeness": math.exp(-abs(_to_float(common_opponents.get("advantage"))) / 0.3)
            if _to_float(common_opponents.get("sharedOpponents")) > 0
            else 0.5,
            "common_opponent_strength_weighted_shared": _to_float(
                common_opponent_details.get("strengthWeightedSharedOpponents")
            ),
            "common_opponent_same_age_shared": _to_float(common_opponent_details.get("sameAgeSharedOpponents")),
            "common_opponent_same_age_rate": _to_float(common_opponent_details.get("sameAgeSharedOpponentRate")),
            "common_opponent_strength_weighted_reliability": _to_float(
                common_opponent_details.get("strengthWeightedReliability")
            ),
            "common_opponent_strength_weighted_margin_diff": _to_float(
                common_opponent_details.get("strengthWeightedMarginDiff")
            ),
            "common_opponent_strength_weighted_points_diff": _to_float(
                common_opponent_details.get("strengthWeightedPointsPerGameDiff")
            ),
            "common_opponent_strength_weighted_goals_for_diff": _to_float(
                common_opponent_details.get("strengthWeightedGoalsForDiff")
            ),
            "common_opponent_strength_weighted_goals_against_adv": _to_float(
                common_opponent_details.get("strengthWeightedGoalsAgainstAdv")
            ),
            "common_opponent_strength_weighted_win_rate_diff": _to_float(
                common_opponent_details.get("strengthWeightedWinRateDiff")
            ),
            "common_opponent_strength_weighted_draw_rate_diff": _to_float(
                common_opponent_details.get("strengthWeightedDrawRateDiff")
            ),
            "common_opponent_strength_weighted_goal_balance_diff": _to_float(
                common_opponent_details.get("strengthWeightedGoalBalanceDiff")
            ),
            "common_opponent_strength_weighted_opponent_power": _to_float(
                common_opponent_details.get("strengthWeightedOpponentPower")
            ),
            "common_opponent_consensus_signal": _to_float(common_opponent_details.get("commonOpponentConsensusSignal")),
            "team_a_prior_game_count": float(len(team_a_prior_games)),
            "team_b_prior_game_count": float(len(team_b_prior_games)),
            "combined_prior_game_count": float(len(combined_prior_games)),
            "game_id": str(game_id),
            "game_date": str(game_date),
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "team_a_name": team_names.get(team_a_id),
            "team_b_name": team_names.get(team_b_id),
            "team_a_snapshot_date": team_a_snapshot.get("snapshot_date"),
            "team_b_snapshot_date": team_b_snapshot.get("snapshot_date"),
            "example_orientation": example_orientation,
            "actual_score_a": actual_score_a_value,
            "actual_score_b": actual_score_b_value,
            "actual_margin": actual_margin,
            "actual_outcome": actual_outcome_name,
            "actual_outcome_label": int(actual_outcome_code),
        }
    )

    stalemate_components = [
        _to_float(features.get("snapshot_strength_closeness")),
        _to_float(features.get("goal_balance_signal")),
        _to_float(features.get("low_total_goal_signal")),
        _to_float(features.get("recent_form_closeness")),
        _to_float(features.get("common_opponent_closeness")),
        _to_float(features.get("head_to_head_closeness")),
    ]
    stalemate_signal = float(np.mean(stalemate_components)) * (
        0.7 + 0.6 * _to_float(features.get("combined_draw_rate"))
    )
    features["stalemate_signal"] = float(np.clip(stalemate_signal, 0.0, 1.0))
    features["expected_draw_environment"] = float(
        np.clip(
            _to_float(features.get("combined_draw_rate")) * _to_float(features.get("low_total_goal_signal")),
            0.0,
            1.0,
        )
    )

    return features


def build_point_in_time_dataset(
    games_df: pd.DataFrame,
    snapshot_index: Dict[str, List[dict]],
    team_names: Optional[Dict[str, str]] = None,
    include_mirrored_examples: bool = True,
    progress_log_every: int = 0,
) -> DatasetBuildResult:
    """
    Build a leakage-safe training frame from point-in-time snapshots.

    Each game is converted into one example from team A's perspective. By default,
    a mirrored example is also added so the model cannot learn an arbitrary input
    order bias from historical home/away labels.
    """
    if games_df.empty:
        return DatasetBuildResult(
            dataset=pd.DataFrame(),
            summary={
                "games_seen": 0,
                "games_used": 0,
                "examples_built": 0,
                "skipped_missing_snapshot": 0,
                "unique_snapshot_dates_used": 0,
            },
        )

    team_names = team_names or {}
    games_df = games_df.sort_values("game_date").reset_index(drop=True)
    per_team_history: Dict[str, List[PredictorGame]] = defaultdict(list)
    rows: List[Dict[str, object]] = []
    snapshot_dates_used: set[str] = set()
    skipped_missing_snapshot = 0
    games_used = 0

    def build_example(
        team_a_id: str,
        team_b_id: str,
        team_a_snapshot: dict,
        team_b_snapshot: dict,
        game_row: pd.Series,
        score_a: int,
        score_b: int,
        orientation: str,
    ) -> Dict[str, object]:
        team_a_prior_games = list(per_team_history.get(team_a_id, []))
        team_b_prior_games = list(per_team_history.get(team_b_id, []))
        combined_prior_games = _dedupe_games(team_a_prior_games + team_b_prior_games)
        return build_point_in_time_matchup_row(
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            team_a_snapshot=team_a_snapshot,
            team_b_snapshot=team_b_snapshot,
            all_games=combined_prior_games,
            game_date=str(game_row["game_date"]),
            snapshot_index=snapshot_index,
            team_names=team_names,
            game_id=str(game_row["id"]),
            example_orientation=orientation,
            actual_score_a=score_a,
            actual_score_b=score_b,
        )

    total_games = len(games_df)

    for index, (_, game_row) in enumerate(games_df.iterrows(), start=1):
        if pd.isna(game_row.get("home_team_master_id")) or pd.isna(game_row.get("away_team_master_id")):
            continue
        if pd.isna(game_row.get("home_score")) or pd.isna(game_row.get("away_score")):
            continue

        home_id = str(game_row["home_team_master_id"])
        away_id = str(game_row["away_team_master_id"])
        game_date = str(game_row["game_date"])
        home_score = int(game_row["home_score"])
        away_score = int(game_row["away_score"])

        home_snapshot = _snapshot_as_of(snapshot_index, home_id, game_date)
        away_snapshot = _snapshot_as_of(snapshot_index, away_id, game_date)

        if home_snapshot is None or away_snapshot is None:
            skipped_missing_snapshot += 1
        else:
            rows.append(
                build_example(
                    team_a_id=home_id,
                    team_b_id=away_id,
                    team_a_snapshot=home_snapshot,
                    team_b_snapshot=away_snapshot,
                    game_row=game_row,
                    score_a=home_score,
                    score_b=away_score,
                    orientation="original",
                )
            )
            if include_mirrored_examples:
                rows.append(
                    build_example(
                        team_a_id=away_id,
                        team_b_id=home_id,
                        team_a_snapshot=away_snapshot,
                        team_b_snapshot=home_snapshot,
                        game_row=game_row,
                        score_a=away_score,
                        score_b=home_score,
                        orientation="mirrored",
                    )
                )

            games_used += 1
            if home_snapshot.get("snapshot_date"):
                snapshot_dates_used.add(str(home_snapshot["snapshot_date"]))
            if away_snapshot.get("snapshot_date"):
                snapshot_dates_used.add(str(away_snapshot["snapshot_date"]))

        predictor_game = PredictorGame(
            id=str(game_row["id"]),
            home_team_master_id=home_id,
            away_team_master_id=away_id,
            home_score=home_score,
            away_score=away_score,
            game_date=game_date,
        )
        per_team_history[home_id].append(predictor_game)
        per_team_history[away_id].append(predictor_game)

        if progress_log_every and index % progress_log_every == 0:
            logger.info(
                "Dataset build progress: processed %s/%s games, used=%s, skipped_missing_snapshot=%s, examples=%s",
                f"{index:,}",
                f"{total_games:,}",
                f"{games_used:,}",
                f"{skipped_missing_snapshot:,}",
                f"{len(rows):,}",
            )

    dataset = pd.DataFrame(rows)
    if not dataset.empty:
        for column_name in dataset.columns:
            if column_name in FEATURE_EXCLUDE_COLUMNS:
                continue
            try:
                dataset[column_name] = pd.to_numeric(dataset[column_name])
            except (TypeError, ValueError):
                continue

    summary = {
        "games_seen": int(len(games_df)),
        "games_used": int(games_used),
        "examples_built": int(len(dataset)),
        "skipped_missing_snapshot": int(skipped_missing_snapshot),
        "unique_snapshot_dates_used": int(len(snapshot_dates_used)),
    }
    if not dataset.empty:
        class_counts = dataset["actual_outcome"].value_counts().sort_index()
        summary["class_counts"] = {str(label): int(count) for label, count in class_counts.items()}
        summary["class_rates"] = {
            str(label): float(count) / float(len(dataset)) for label, count in class_counts.items()
        }
    return DatasetBuildResult(dataset=dataset, summary=summary)


class PointInTimeMatchModel:
    """Train and persist a 3-way point-in-time match model."""

    def __init__(self, model_dir: str = "models/point_in_time_match_predictor"):
        self.model_dir = model_dir
        self.feature_names: List[str] = []
        self.class_labels: List[int] = []
        self.classifier = None
        self.draw_classifier = None
        self.blowout_classifier_3plus = None
        self.blowout_classifier_5plus = None
        self.blowout_calibrator_3plus = None
        self.blowout_calibrator_5plus = None
        self.margin_regressor = None
        self.score_a_regressor = None
        self.score_b_regressor = None
        self.draw_rate_prior = 0.0
        self.requested_probability_strategy = DEFAULT_PROBABILITY_STRATEGY
        self.probability_strategy = DEFAULT_PROBABILITY_STRATEGY
        self.auto_strategy_selection: Dict[str, object] = {}
        self.strategy_constraints = dict(DEFAULT_AUTO_STRATEGY_CONSTRAINTS)
        self.draw_decision_policy: Dict[str, object] = {
            "default": {
                "min_draw_probability": POISSON_DRAW_GATE_PROBABILITY_MIN,
                "max_draw_gap": 0.02,
                "max_total_goals": POISSON_DRAW_GATE_TOTAL_GOALS_MAX,
                "min_stalemate_signal": POISSON_DRAW_GATE_STALEMATE_MIN,
            },
            "by_age": {},
        }
        self.blowout_probability_thresholds: Dict[int, float] = {3: 0.5, 5: 0.5}
        self.blowout_probability_thresholds_by_age: Dict[int, Dict[int, float]] = {3: {}, 5: {}}
        self.training_metadata: Dict[str, object] = {}
        self.last_evaluation_frame = pd.DataFrame()
        os.makedirs(model_dir, exist_ok=True)

    def _feature_columns(self, dataset_df: pd.DataFrame) -> List[str]:
        return [column for column in dataset_df.columns if column not in FEATURE_EXCLUDE_COLUMNS]

    def _build_classifier(self, random_state: int, num_classes: int):
        if HAS_XGBOOST:
            return XGBClassifier(
                objective="multi:softprob",
                num_class=num_classes,
                n_estimators=260,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_alpha=0.1,
                reg_lambda=1.2,
                min_child_weight=2,
                gamma=0.05,
                random_state=random_state,
                n_jobs=-1,
                eval_metric="mlogloss",
            )

        logger.warning("XGBoost is unavailable; falling back to RandomForestClassifier for offline harness")
        return RandomForestClassifier(
            n_estimators=250,
            max_depth=12,
            min_samples_leaf=2,
            random_state=random_state,
            n_jobs=-1,
        )

    def _build_binary_classifier(self, random_state: int):
        if HAS_XGBOOST:
            return XGBClassifier(
                objective="binary:logistic",
                n_estimators=240,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_alpha=0.1,
                reg_lambda=1.2,
                min_child_weight=2,
                gamma=0.05,
                random_state=random_state,
                n_jobs=-1,
                eval_metric="logloss",
            )

        logger.warning("XGBoost is unavailable; falling back to RandomForestClassifier for draw model")
        return RandomForestClassifier(
            n_estimators=250,
            max_depth=12,
            min_samples_leaf=2,
            random_state=random_state,
            n_jobs=-1,
            class_weight="balanced_subsample",
        )

    def _build_regressor(self, random_state: int):
        if HAS_XGBOOST:
            return XGBRegressor(
                n_estimators=240,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_alpha=0.1,
                reg_lambda=1.2,
                min_child_weight=2,
                gamma=0.05,
                random_state=random_state,
                n_jobs=-1,
                eval_metric="rmse",
            )

        logger.warning("XGBoost is unavailable; falling back to RandomForestRegressor for offline harness")
        return RandomForestRegressor(
            n_estimators=250,
            max_depth=12,
            min_samples_leaf=2,
            random_state=random_state,
            n_jobs=-1,
        )

    def _build_goal_regressor(self, random_state: int):
        if HAS_XGBOOST:
            return XGBRegressor(
                objective="count:poisson",
                n_estimators=260,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_alpha=0.05,
                reg_lambda=1.1,
                min_child_weight=2,
                gamma=0.02,
                max_delta_step=1,
                random_state=random_state,
                n_jobs=-1,
                eval_metric="poisson-nloglik",
            )

        logger.warning("XGBoost is unavailable; falling back to RandomForestRegressor for goal model")
        return RandomForestRegressor(
            n_estimators=250,
            max_depth=12,
            min_samples_leaf=2,
            random_state=random_state,
            n_jobs=-1,
        )

    def _chronological_split(
        self,
        dataset_df: pd.DataFrame,
        test_ratio: float,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        ordered_df = dataset_df.sort_values(["game_date", "game_id", "example_orientation"]).reset_index(drop=True)
        if len(ordered_df) < 2:
            raise ValueError("Need at least 2 examples to split train/test chronologically")

        split_index = int(len(ordered_df) * (1.0 - test_ratio))
        split_index = min(max(split_index, 1), len(ordered_df) - 1)
        return ordered_df.iloc[:split_index].copy(), ordered_df.iloc[split_index:].copy()

    def _expand_class_probabilities(self, encoded_probabilities: np.ndarray) -> np.ndarray:
        if encoded_probabilities.ndim == 1:
            encoded_probabilities = np.column_stack([1.0 - encoded_probabilities, encoded_probabilities])

        expanded = np.zeros((encoded_probabilities.shape[0], 3), dtype=float)
        for position, class_value in enumerate(self.class_labels):
            expanded[:, class_value] = encoded_probabilities[:, position]
        return expanded

    def _normalize_probabilities(self, probabilities: np.ndarray) -> np.ndarray:
        clipped = np.clip(probabilities, 1e-9, 1.0)
        row_sums = clipped.sum(axis=1, keepdims=True)
        return np.divide(
            clipped,
            row_sums,
            out=np.full_like(clipped, 1.0 / clipped.shape[1]),
            where=row_sums > 0,
        )

    def _prepare_matrix(self, dataset_df: pd.DataFrame) -> pd.DataFrame:
        feature_frame = dataset_df[self.feature_names].copy()
        return feature_frame.fillna(0.0).astype(float)

    def _class_balance_summary(self, labels: np.ndarray) -> Dict[str, object]:
        unique_labels, counts = np.unique(labels, return_counts=True)
        label_counts = {OUTCOME_LABELS[int(label)]: int(count) for label, count in zip(unique_labels, counts)}
        total = int(np.sum(counts))
        label_rates = {label_name: float(count) / float(total) for label_name, count in label_counts.items()}
        return {
            "counts": label_counts,
            "rates": label_rates,
        }

    def _multiclass_sample_weights(self, labels: np.ndarray) -> Tuple[np.ndarray, Dict[str, float]]:
        unique_labels, counts = np.unique(labels, return_counts=True)
        total = float(np.sum(counts))
        weight_map: Dict[int, float] = {}
        for label, count in zip(unique_labels, counts):
            base_weight = total / max(float(len(unique_labels)) * float(count), 1.0)
            if int(label) == OUTCOME_DRAW:
                base_weight *= DRAW_CLASS_WEIGHT_BOOST
            weight_map[int(label)] = float(base_weight)
        sample_weights = np.array([weight_map[int(label)] for label in labels], dtype=float)
        named_weight_map = {OUTCOME_LABELS[label]: weight for label, weight in weight_map.items()}
        return sample_weights, named_weight_map

    def _draw_sample_weights(self, draw_targets: np.ndarray) -> Tuple[np.ndarray, Dict[str, float]]:
        return self._binary_sample_weights(
            draw_targets,
            positive_label="draw",
            cap=DRAW_BINARY_WEIGHT_CAP,
        )

    def _binary_sample_weights(
        self,
        targets: np.ndarray,
        positive_label: str,
        cap: float,
    ) -> Tuple[np.ndarray, Dict[str, float]]:
        positive_count = int(np.sum(targets == 1))
        negative_count = int(np.sum(targets == 0))
        if positive_count <= 0:
            return np.ones_like(targets, dtype=float), {"non_positive": 1.0, positive_label: 1.0}
        positive_weight = min(
            cap,
            max(1.0, math.sqrt(float(negative_count) / float(positive_count))) * 1.2,
        )
        sample_weights = np.where(targets == 1, positive_weight, 1.0).astype(float)
        return sample_weights, {"non_positive": 1.0, positive_label: float(positive_weight)}

    def _predict_draw_probability(self, matrix: pd.DataFrame) -> np.ndarray:
        if self.draw_classifier is None:
            return np.full(len(matrix), np.nan, dtype=float)
        probabilities = self.draw_classifier.predict_proba(matrix)
        draw_classes = getattr(self.draw_classifier, "classes_", np.array([0, 1]))
        draw_index = (
            int(np.where(np.asarray(draw_classes) == 1)[0][0]) if 1 in draw_classes else probabilities.shape[1] - 1
        )
        return np.asarray(probabilities[:, draw_index], dtype=float)

    def _predict_binary_probability(self, classifier, matrix: pd.DataFrame) -> np.ndarray:
        if classifier is None:
            return np.full(len(matrix), np.nan, dtype=float)
        probabilities = classifier.predict_proba(matrix)
        binary_classes = getattr(classifier, "classes_", np.array([0, 1]))
        positive_index = (
            int(np.where(np.asarray(binary_classes) == 1)[0][0]) if 1 in binary_classes else probabilities.shape[1] - 1
        )
        return np.asarray(probabilities[:, positive_index], dtype=float)

    def _default_draw_decision_policy(self) -> Dict[str, float]:
        return {
            "min_draw_probability": POISSON_DRAW_GATE_PROBABILITY_MIN,
            "max_draw_gap": 0.02,
            "max_total_goals": POISSON_DRAW_GATE_TOTAL_GOALS_MAX,
            "min_stalemate_signal": POISSON_DRAW_GATE_STALEMATE_MIN,
        }

    def _apply_draw_decision_policy(
        self,
        probabilities: np.ndarray,
        dataset_df: pd.DataFrame,
        policy: Dict[str, float],
        base_labels: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        labels = np.asarray(
            base_labels if base_labels is not None else np.argmax(probabilities, axis=1),
            dtype=int,
        ).copy()
        draw_probability = np.asarray(probabilities[:, OUTCOME_DRAW], dtype=float)
        draw_gap = np.max(probabilities[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]], axis=1) - draw_probability
        projected_total_goals = (
            pd.to_numeric(dataset_df.get("projected_total_goals"), errors="coerce").fillna(np.inf).to_numpy(dtype=float)
        )
        stalemate_signal = (
            pd.to_numeric(dataset_df.get("stalemate_signal"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        )
        draw_mask = (
            (draw_probability >= float(policy["min_draw_probability"]))
            & (draw_gap <= float(policy["max_draw_gap"]))
            & (projected_total_goals <= float(policy["max_total_goals"]))
            & (stalemate_signal >= float(policy["min_stalemate_signal"]))
        )
        labels[draw_mask] = OUTCOME_DRAW
        return labels

    def _score_draw_decision_policy(
        self,
        probabilities: np.ndarray,
        dataset_df: pd.DataFrame,
        actual_labels: np.ndarray,
        policy: Dict[str, float],
    ) -> Tuple[float, float, float, float]:
        predicted_labels = self._apply_draw_decision_policy(probabilities, dataset_df, policy)
        actual_draw = np.asarray(actual_labels == OUTCOME_DRAW, dtype=int)
        predicted_draw = np.asarray(predicted_labels == OUTCOME_DRAW, dtype=int)
        tp = float(np.sum((predicted_draw == 1) & (actual_draw == 1)))
        fp = float(np.sum((predicted_draw == 1) & (actual_draw == 0)))
        fn = float(np.sum((predicted_draw == 0) & (actual_draw == 1)))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        beta_squared = DRAW_POLICY_BETA * DRAW_POLICY_BETA
        if precision <= 0.0 and recall <= 0.0:
            f_beta = 0.0
        else:
            f_beta = ((1.0 + beta_squared) * precision * recall) / ((beta_squared * precision) + recall)
        predicted_draw_rate = float(np.mean(predicted_draw))
        accuracy = float(np.mean(predicted_labels == actual_labels))
        actual_draw_rate = float(np.mean(actual_draw))
        rate_gap = abs(predicted_draw_rate - actual_draw_rate)
        overshoot = max(0.0, predicted_draw_rate - actual_draw_rate)
        undershoot = max(0.0, actual_draw_rate - predicted_draw_rate)
        score = (
            (2.0 * accuracy)
            + (2.5 * f_beta)
            - (DRAW_POLICY_OVERSHOOT_PENALTY * overshoot)
            - (DRAW_POLICY_UNDERSHOOT_PENALTY * undershoot)
            - (DRAW_POLICY_RATE_GAP_PENALTY * rate_gap)
        )
        return score, predicted_draw_rate, recall, precision

    def _select_draw_decision_policy(
        self,
        probabilities: np.ndarray,
        dataset_df: pd.DataFrame,
        actual_labels: np.ndarray,
    ) -> Dict[str, float]:
        cleaned_probabilities = np.asarray(probabilities, dtype=float)
        cleaned_labels = np.asarray(actual_labels, dtype=int)
        if cleaned_probabilities.size == 0 or len(np.unique(cleaned_labels)) < 2:
            return self._default_draw_decision_policy()

        actual_draw_rate = float(np.mean(cleaned_labels == OUTCOME_DRAW))
        if actual_draw_rate <= 0.0:
            return self._default_draw_decision_policy()

        default_policy = self._default_draw_decision_policy()
        best_policy = default_policy
        best_score, _, _, _ = self._score_draw_decision_policy(
            cleaned_probabilities,
            dataset_df,
            cleaned_labels,
            default_policy,
        )
        rate_tolerance = max(
            DRAW_POLICY_RATE_TOLERANCE_MIN,
            actual_draw_rate * DRAW_POLICY_RATE_TOLERANCE_SHARE,
        )
        best_band_policy: Optional[Dict[str, float]] = None
        best_band_score = -np.inf

        for min_draw_probability in DRAW_POLICY_MIN_PROBABILITY_GRID:
            for max_draw_gap in DRAW_POLICY_MAX_GAP_GRID:
                for max_total_goals in DRAW_POLICY_MAX_TOTAL_GOALS_GRID:
                    for min_stalemate_signal in DRAW_POLICY_MIN_STALEMATE_GRID:
                        candidate_policy = {
                            "min_draw_probability": float(min_draw_probability),
                            "max_draw_gap": float(max_draw_gap),
                            "max_total_goals": float(max_total_goals),
                            "min_stalemate_signal": float(min_stalemate_signal),
                        }
                        score, predicted_draw_rate, _, _ = self._score_draw_decision_policy(
                            cleaned_probabilities,
                            dataset_df,
                            cleaned_labels,
                            candidate_policy,
                        )
                        rate_gap = abs(predicted_draw_rate - actual_draw_rate)
                        if score > best_score:
                            best_score = score
                            best_policy = candidate_policy
                        if rate_gap <= rate_tolerance and score > best_band_score:
                            best_band_score = score
                            best_band_policy = candidate_policy

        return best_band_policy or best_policy

    def _fit_draw_postprocessing(
        self,
        train_df: pd.DataFrame,
        probabilities: np.ndarray,
    ) -> Dict[str, object]:
        actual_labels = train_df["actual_outcome_label"].astype(int).to_numpy()
        default_policy = self._select_draw_decision_policy(probabilities, train_df, actual_labels)
        age_group_numeric = _age_group_numeric_array(train_df)
        by_age: Dict[int, Dict[str, float]] = {}
        for age_value in sorted({int(value) for value in age_group_numeric if int(value) > 0}):
            cohort_mask = age_group_numeric == age_value
            if int(np.sum(cohort_mask)) < COHORT_POSTPROCESSING_MIN_SAMPLES:
                continue
            cohort_labels = actual_labels[cohort_mask]
            if len(np.unique(cohort_labels)) < 2:
                continue
            by_age[age_value] = self._select_draw_decision_policy(
                probabilities[cohort_mask],
                train_df.loc[cohort_mask],
                cohort_labels,
            )
        return {
            "default": default_policy,
            "by_age": by_age,
        }

    def _draw_prediction_labels(
        self,
        probabilities: np.ndarray,
        dataset_df: pd.DataFrame,
        policy: Optional[Dict[str, object]] = None,
    ) -> np.ndarray:
        policy_source = policy or self.draw_decision_policy
        labels = np.asarray(np.argmax(probabilities, axis=1), dtype=int)
        labels = self._apply_draw_decision_policy(
            probabilities=probabilities,
            dataset_df=dataset_df,
            policy=policy_source.get("default", self._default_draw_decision_policy()),
            base_labels=labels,
        )
        age_group_numeric = _age_group_numeric_array(dataset_df)
        by_age_policy = policy_source.get("by_age", {})
        for age_value, age_policy in by_age_policy.items():
            cohort_mask = age_group_numeric == int(age_value)
            if not np.any(cohort_mask):
                continue
            labels[cohort_mask] = self._apply_draw_decision_policy(
                probabilities=probabilities[cohort_mask],
                dataset_df=dataset_df.loc[cohort_mask],
                policy=age_policy,
                base_labels=labels[cohort_mask],
            )
        return labels

    def _fit_blowout_calibrator(
        self,
        probabilities: np.ndarray,
        targets: np.ndarray,
    ) -> Optional[IsotonicRegression]:
        cleaned_probabilities = np.clip(np.asarray(probabilities, dtype=float), 0.0, 1.0)
        cleaned_targets = np.asarray(targets, dtype=int)
        if cleaned_probabilities.size == 0 or len(np.unique(cleaned_targets)) < 2:
            return None
        calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        calibrator.fit(cleaned_probabilities, cleaned_targets.astype(float))
        return calibrator

    def _apply_blowout_calibrator(
        self,
        calibrator: Optional[IsotonicRegression],
        probabilities: np.ndarray,
    ) -> np.ndarray:
        cleaned_probabilities = np.clip(np.asarray(probabilities, dtype=float), 0.0, 1.0)
        if calibrator is None:
            return cleaned_probabilities
        return np.clip(np.asarray(calibrator.predict(cleaned_probabilities), dtype=float), 0.0, 1.0)

    def _select_blowout_threshold(
        self,
        probabilities: np.ndarray,
        targets: np.ndarray,
        beta: float,
    ) -> float:
        cleaned_probabilities = np.clip(np.asarray(probabilities, dtype=float), 0.0, 1.0)
        cleaned_targets = np.asarray(targets, dtype=int)
        if cleaned_probabilities.size == 0 or len(np.unique(cleaned_targets)) < 2:
            return 0.5

        actual_rate = float(np.mean(cleaned_targets == 1))
        mean_probability = float(np.mean(cleaned_probabilities))
        target_rate = float(np.clip((0.85 * actual_rate) + (0.15 * mean_probability), 0.02, 0.98))
        quantile_levels = np.clip(
            np.array(
                [
                    0.10,
                    0.25,
                    0.50,
                    0.75,
                    0.90,
                    1.0 - actual_rate,
                    1.0 - target_rate,
                    1.0 - mean_probability,
                ]
            ),
            0.0,
            1.0,
        )
        candidate_thresholds = np.unique(
            np.clip(
                np.concatenate(
                    [
                        BLOWOUT_THRESHOLD_GRID,
                        np.quantile(cleaned_probabilities, quantile_levels),
                        np.array([actual_rate, target_rate, mean_probability]),
                    ]
                ),
                0.05,
                0.95,
            )
        )
        beta_squared = beta * beta
        rate_tolerance = max(BLOWOUT_RATE_TOLERANCE_MIN, actual_rate * BLOWOUT_RATE_TOLERANCE_SHARE)
        best_band_threshold = None
        best_band_score = -np.inf
        best_fallback_threshold = 0.5
        best_fallback_score = -np.inf

        for threshold in candidate_thresholds:
            predicted_positive = cleaned_probabilities >= float(threshold)
            tp = float(np.sum((predicted_positive == 1) & (cleaned_targets == 1)))
            fp = float(np.sum((predicted_positive == 1) & (cleaned_targets == 0)))
            fn = float(np.sum((predicted_positive == 0) & (cleaned_targets == 1)))
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            if precision <= 0.0 and recall <= 0.0:
                f_beta = 0.0
            else:
                f_beta = ((1.0 + beta_squared) * precision * recall) / ((beta_squared * precision) + recall)
            predicted_rate = float(np.mean(predicted_positive))
            rate_gap = abs(predicted_rate - target_rate)
            overshoot = max(0.0, predicted_rate - target_rate)
            undershoot = max(0.0, target_rate - predicted_rate)
            fallback_score = (
                f_beta
                - (BLOWOUT_RATE_OVERSHOOT_PENALTY * overshoot)
                - (BLOWOUT_RATE_UNDERSHOOT_PENALTY * undershoot)
                - (BLOWOUT_RATE_GAP_PENALTY * rate_gap)
            )
            if fallback_score > best_fallback_score:
                best_fallback_score = fallback_score
                best_fallback_threshold = float(threshold)

            if rate_gap <= rate_tolerance:
                band_score = f_beta - (0.10 * rate_gap)
                if band_score > best_band_score:
                    best_band_score = band_score
                    best_band_threshold = float(threshold)

        if best_band_threshold is not None:
            return best_band_threshold
        return best_fallback_threshold

    def _select_blowout_thresholds_by_age(
        self,
        probabilities: np.ndarray,
        targets: np.ndarray,
        age_group_numeric: np.ndarray,
        beta: float,
    ) -> Tuple[float, Dict[int, float]]:
        global_threshold = self._select_blowout_threshold(
            probabilities=probabilities,
            targets=targets,
            beta=beta,
        )
        thresholds_by_age: Dict[int, float] = {}
        ages = np.asarray(age_group_numeric, dtype=int)
        for age_value in sorted({int(value) for value in ages if int(value) > 0}):
            cohort_mask = ages == age_value
            if int(np.sum(cohort_mask)) < COHORT_POSTPROCESSING_MIN_SAMPLES:
                continue
            cohort_targets = np.asarray(targets[cohort_mask], dtype=int)
            if len(np.unique(cohort_targets)) < 2:
                continue
            thresholds_by_age[age_value] = self._select_blowout_threshold(
                probabilities=np.asarray(probabilities[cohort_mask], dtype=float),
                targets=cohort_targets,
                beta=beta,
            )
        return global_threshold, thresholds_by_age

    def _blowout_prediction_labels(
        self,
        blowout_3plus_probability: np.ndarray,
        blowout_5plus_probability: np.ndarray,
        thresholds: Optional[Dict[int, float]] = None,
        age_group_numeric: Optional[np.ndarray] = None,
        thresholds_by_age: Optional[Dict[int, Dict[int, float]]] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        threshold_source = thresholds or self.blowout_probability_thresholds
        threshold_source_by_age = thresholds_by_age or self.blowout_probability_thresholds_by_age
        threshold_3plus = np.full(
            len(blowout_3plus_probability),
            float(threshold_source.get(3, 0.5)),
            dtype=float,
        )
        threshold_5plus = np.full(
            len(blowout_5plus_probability),
            float(threshold_source.get(5, 0.5)),
            dtype=float,
        )
        if age_group_numeric is not None:
            ages = np.asarray(age_group_numeric, dtype=int)
            for age_value, threshold in threshold_source_by_age.get(3, {}).items():
                threshold_3plus[ages == int(age_value)] = float(threshold)
            for age_value, threshold in threshold_source_by_age.get(5, {}).items():
                threshold_5plus[ages == int(age_value)] = float(threshold)
        predicted_5plus = np.asarray(blowout_5plus_probability >= threshold_5plus, dtype=int)
        predicted_3plus = np.asarray(blowout_3plus_probability >= threshold_3plus, dtype=int)
        predicted_3plus = np.maximum(predicted_3plus, predicted_5plus)
        return predicted_3plus, predicted_5plus

    def _rank_strategy_metric(
        self,
        strategy_metrics: Dict[str, Dict[str, object]],
        strategy_names: List[str],
        metric_key: str,
        higher_is_better: bool,
    ) -> Dict[str, int]:
        metric_values = {}
        for strategy_name in strategy_names:
            raw_value = strategy_metrics[strategy_name].get(metric_key)
            if raw_value is None or pd.isna(raw_value):
                metric_values[strategy_name] = None
            else:
                metric_values[strategy_name] = float(raw_value)

        valid_items = [(name, value) for name, value in metric_values.items() if value is not None]
        if not valid_items:
            return {strategy_name: len(strategy_names) for strategy_name in strategy_names}

        valid_items.sort(key=lambda item: item[1], reverse=higher_is_better)
        ranked: Dict[str, int] = {}
        current_rank = 1
        previous_value = None
        for index, (strategy_name, value) in enumerate(valid_items):
            if previous_value is not None and not math.isclose(value, previous_value, rel_tol=1e-9, abs_tol=1e-9):
                current_rank = index + 1
            ranked[strategy_name] = current_rank
            previous_value = value

        fallback_rank = len(valid_items) + 1
        for strategy_name in strategy_names:
            ranked.setdefault(strategy_name, fallback_rank)
        return ranked

    def _select_probability_strategy(
        self,
        strategy_metrics: Dict[str, Dict[str, object]],
        actual_draw_rate: float,
        constraints: Optional[Dict[str, float]] = None,
    ) -> Tuple[str, Dict[str, object]]:
        merged_constraints = {
            **DEFAULT_AUTO_STRATEGY_CONSTRAINTS,
            **(constraints or {}),
        }
        viable_strategies: List[str] = []
        rejected_strategies: Dict[str, Dict[str, object]] = {}
        best_winner_accuracy = max(
            _to_float(summary.get("winner_accuracy"), default=float("-inf")) for summary in strategy_metrics.values()
        )
        best_log_loss = min(
            _to_float(summary.get("log_loss"), default=float("inf")) for summary in strategy_metrics.values()
        )

        for strategy_name in strategy_metrics:
            strategy_metrics[strategy_name]["draw_rate_gap"] = abs(
                _to_float(strategy_metrics[strategy_name].get("predicted_draw_rate"), default=0.0) - actual_draw_rate
            )

        for strategy_name, summary in strategy_metrics.items():
            draw_recall = _to_float(summary.get("draw_recall"), default=0.0)
            predicted_draw_rate = _to_float(summary.get("predicted_draw_rate"), default=0.0)
            winner_accuracy = _to_float(summary.get("winner_accuracy"), default=float("-inf"))
            log_loss_value = _to_float(summary.get("log_loss"), default=float("inf"))
            draw_rate_gap = _to_float(summary.get("draw_rate_gap"), default=float("inf"))
            failures: List[str] = []
            if draw_recall < merged_constraints["min_draw_recall"]:
                failures.append(f"draw_recall<{merged_constraints['min_draw_recall']:.3f}")
            if draw_rate_gap > merged_constraints["max_draw_rate_gap"]:
                failures.append(f"draw_rate_gap>{merged_constraints['max_draw_rate_gap']:.3f}")
            if winner_accuracy < best_winner_accuracy - merged_constraints["winner_accuracy_tolerance"]:
                failures.append(
                    f"winner_accuracy<{best_winner_accuracy - merged_constraints['winner_accuracy_tolerance']:.3f}"
                )
            if log_loss_value > best_log_loss + merged_constraints["log_loss_tolerance"]:
                failures.append(f"log_loss>{best_log_loss + merged_constraints['log_loss_tolerance']:.4f}")
            if not failures:
                viable_strategies.append(strategy_name)
            else:
                rejected_strategies[strategy_name] = {
                    "reasons": failures,
                    "draw_recall": draw_recall,
                    "predicted_draw_rate": predicted_draw_rate,
                    "draw_rate_gap": draw_rate_gap,
                    "winner_accuracy": winner_accuracy,
                    "log_loss": log_loss_value,
                }

        candidate_strategies = sorted(viable_strategies or strategy_metrics.keys())

        strategy_scores: Dict[str, float] = {strategy_name: 0.0 for strategy_name in candidate_strategies}
        rank_specs = [
            ("winner_accuracy", True),
            ("log_loss", False),
            ("brier_score", False),
            ("draw_recall", True),
            ("draw_rate_gap", False),
            ("exact_score_accuracy", True),
            ("score_within_one_goal_rate", True),
            ("total_goals_mae", False),
            ("blowout_3plus_brier", False),
            ("blowout_5plus_brier", False),
        ]

        for metric_key, higher_is_better in rank_specs:
            metric_ranks = self._rank_strategy_metric(
                strategy_metrics=strategy_metrics,
                strategy_names=candidate_strategies,
                metric_key=metric_key,
                higher_is_better=higher_is_better,
            )
            weight = AUTO_STRATEGY_RANK_WEIGHTS[metric_key]
            for strategy_name in candidate_strategies:
                strategy_scores[strategy_name] += metric_ranks[strategy_name] * weight

        selected_strategy = min(
            candidate_strategies,
            key=lambda strategy_name: (strategy_scores[strategy_name], strategy_name),
        )
        return selected_strategy, {
            "actual_draw_rate": actual_draw_rate,
            "candidate_strategies": candidate_strategies,
            "viable_strategies": sorted(viable_strategies),
            "rejected_strategies": rejected_strategies,
            "constraints": merged_constraints,
            "strategy_scores": {strategy_name: float(score) for strategy_name, score in strategy_scores.items()},
        }

    def _fit_blowout_postprocessing(
        self,
        train_df: pd.DataFrame,
        calibration_outputs: StrategyOutputs,
    ) -> BlowoutPostprocessing:
        train_blowout_targets_3plus = (train_df["actual_margin"].astype(float).abs() >= 3.0).astype(int).to_numpy()
        train_blowout_targets_5plus = (train_df["actual_margin"].astype(float).abs() >= 5.0).astype(int).to_numpy()
        age_group_numeric = _age_group_numeric_array(train_df)
        calibrator_3plus = self._fit_blowout_calibrator(
            calibration_outputs.blowout_3plus_probability,
            train_blowout_targets_3plus,
        )
        calibrator_5plus = self._fit_blowout_calibrator(
            calibration_outputs.blowout_5plus_probability,
            train_blowout_targets_5plus,
        )
        calibrated_train_blowout_3plus = self._apply_blowout_calibrator(
            calibrator_3plus,
            calibration_outputs.blowout_3plus_probability,
        )
        calibrated_train_blowout_5plus = self._apply_blowout_calibrator(
            calibrator_5plus,
            calibration_outputs.blowout_5plus_probability,
        )
        threshold_3plus, thresholds_3plus_by_age = self._select_blowout_thresholds_by_age(
            calibrated_train_blowout_3plus,
            train_blowout_targets_3plus,
            age_group_numeric=age_group_numeric,
            beta=1.15,
        )
        threshold_5plus, thresholds_5plus_by_age = self._select_blowout_thresholds_by_age(
            calibrated_train_blowout_5plus,
            train_blowout_targets_5plus,
            age_group_numeric=age_group_numeric,
            beta=1.05,
        )
        return BlowoutPostprocessing(
            calibrator_3plus=calibrator_3plus,
            calibrator_5plus=calibrator_5plus,
            thresholds={
                3: threshold_3plus,
                5: threshold_5plus,
            },
            thresholds_by_age={
                3: thresholds_3plus_by_age,
                5: thresholds_5plus_by_age,
            },
        )

    def _expected_goals_from_predictions(
        self,
        dataset_df: pd.DataFrame,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
        score_weight: float = 0.7,
    ) -> Tuple[np.ndarray, np.ndarray]:
        prior_goal_a = (
            pd.to_numeric(dataset_df.get("projected_goals_team_a"), errors="coerce")
            .fillna(pd.Series(predicted_score_a))
            .to_numpy(dtype=float)
        )
        prior_goal_b = (
            pd.to_numeric(dataset_df.get("projected_goals_team_b"), errors="coerce")
            .fillna(pd.Series(predicted_score_b))
            .to_numpy(dtype=float)
        )
        prior_weight = 1.0 - score_weight
        expected_goals_a = np.clip(score_weight * predicted_score_a + prior_weight * prior_goal_a, 0.05, 6.0)
        expected_goals_b = np.clip(score_weight * predicted_score_b + prior_weight * prior_goal_b, 0.05, 6.0)
        return expected_goals_a, expected_goals_b

    def _draw_context(
        self,
        dataset_df: pd.DataFrame,
        matrix: pd.DataFrame,
        fallback_draw_probability: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        raw_draw_model_probability = np.nan_to_num(
            self._predict_draw_probability(matrix),
            nan=fallback_draw_probability,
        )
        draw_model_probability = np.clip(
            self.draw_rate_prior + DRAW_MODEL_SHRINK_FACTOR * (raw_draw_model_probability - self.draw_rate_prior),
            0.01,
            0.75,
        )
        stalemate_signal = (
            pd.to_numeric(dataset_df.get("stalemate_signal"), errors="coerce")
            .fillna(0.0)
            .clip(0.0, 1.0)
            .to_numpy(dtype=float)
        )
        expected_draw_environment = (
            pd.to_numeric(dataset_df.get("expected_draw_environment"), errors="coerce")
            .fillna(self.draw_rate_prior)
            .clip(0.0, 1.0)
            .to_numpy(dtype=float)
        )
        projected_total_goals = (
            pd.to_numeric(dataset_df.get("projected_total_goals"), errors="coerce")
            .fillna(0.0)
            .clip(0.05, 8.0)
            .to_numpy(dtype=float)
        )
        return draw_model_probability, stalemate_signal, expected_draw_environment, projected_total_goals

    def _score_matrix_context(
        self,
        expected_goals_a: np.ndarray,
        expected_goals_b: np.ndarray,
        draw_model_probability: np.ndarray,
        stalemate_signal: np.ndarray,
        projected_total_goals: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
        expected_goal_gap_abs = np.abs(expected_goals_a - expected_goals_b)
        rho = _dixon_coles_rho(
            draw_model_probability=draw_model_probability,
            stalemate_signal=stalemate_signal,
            projected_total_goals=projected_total_goals,
            expected_goal_gap_abs=expected_goal_gap_abs,
        )
        score_matrix = _poisson_score_matrix(expected_goals_a, expected_goals_b, rho=rho)
        return score_matrix, _score_matrix_outcome_probabilities(score_matrix), _score_matrix_summary(score_matrix)

    def _blowout_probabilities(
        self,
        matrix: pd.DataFrame,
        score_matrix_summary: Dict[str, np.ndarray],
    ) -> Tuple[np.ndarray, np.ndarray]:
        model_blowout_3plus = np.nan_to_num(
            self._predict_binary_probability(self.blowout_classifier_3plus, matrix),
            nan=score_matrix_summary["blowout_3plus_probability"],
        )
        model_blowout_5plus = np.nan_to_num(
            self._predict_binary_probability(self.blowout_classifier_5plus, matrix),
            nan=score_matrix_summary["blowout_5plus_probability"],
        )
        blowout_3plus_probability = np.clip(
            0.55 * model_blowout_3plus + 0.45 * score_matrix_summary["blowout_3plus_probability"],
            0.0,
            1.0,
        )
        blowout_5plus_probability = np.clip(
            0.60 * model_blowout_5plus + 0.40 * score_matrix_summary["blowout_5plus_probability"],
            0.0,
            1.0,
        )
        return (
            self._apply_blowout_calibrator(self.blowout_calibrator_3plus, blowout_3plus_probability),
            self._apply_blowout_calibrator(self.blowout_calibrator_5plus, blowout_5plus_probability),
        )

    def _compose_outcome_probabilities(
        self,
        dataset_df: pd.DataFrame,
        matrix: pd.DataFrame,
        base_probabilities: np.ndarray,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
    ) -> StrategyOutputs:
        expected_goals_a, expected_goals_b = self._expected_goals_from_predictions(
            dataset_df,
            predicted_score_a,
            predicted_score_b,
            score_weight=0.65,
        )
        (
            draw_model_probability,
            stalemate_signal,
            expected_draw_environment,
            projected_total_goals,
        ) = self._draw_context(
            dataset_df,
            matrix,
            fallback_draw_probability=base_probabilities[:, OUTCOME_DRAW],
        )
        _, poisson_probabilities, score_matrix_summary = self._score_matrix_context(
            expected_goals_a=expected_goals_a,
            expected_goals_b=expected_goals_b,
            draw_model_probability=draw_model_probability,
            stalemate_signal=stalemate_signal,
            projected_total_goals=projected_total_goals,
        )

        combined_draw_probability = (
            0.2 * base_probabilities[:, OUTCOME_DRAW]
            + 0.45 * poisson_probabilities[:, OUTCOME_DRAW]
            + 0.15 * draw_model_probability
            + 0.2 * np.maximum(expected_draw_environment, self.draw_rate_prior)
        )
        combined_draw_probability *= 0.85 + 0.3 * stalemate_signal
        low_total_mask = projected_total_goals <= 2.25
        combined_draw_probability[low_total_mask] *= 1.08
        high_total_mask = projected_total_goals >= 3.25
        combined_draw_probability[high_total_mask] *= 0.84
        dynamic_draw_cap = np.where(
            projected_total_goals <= 2.25,
            0.42,
            np.where(projected_total_goals <= 2.8, 0.36, 0.28),
        )
        combined_draw_probability = np.clip(combined_draw_probability, 0.01, dynamic_draw_cap)

        win_probabilities = (
            0.72 * base_probabilities[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]]
            + 0.28 * poisson_probabilities[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]]
        )
        win_row_sums = win_probabilities.sum(axis=1, keepdims=True)
        win_probabilities = np.divide(
            win_probabilities,
            win_row_sums,
            out=np.full_like(win_probabilities, 0.5),
            where=win_row_sums > 0,
        )

        combined = np.zeros_like(base_probabilities)
        remaining_mass = 1.0 - combined_draw_probability
        combined[:, OUTCOME_DRAW] = combined_draw_probability
        combined[:, OUTCOME_TEAM_A_WIN] = win_probabilities[:, 0] * remaining_mass
        combined[:, OUTCOME_TEAM_B_WIN] = win_probabilities[:, 1] * remaining_mass
        combined = self._normalize_probabilities(combined)

        draw_edge = np.max(combined[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]], axis=1)
        draw_trigger = (
            (stalemate_signal >= 0.74)
            & (projected_total_goals <= 2.15)
            & (combined[:, OUTCOME_DRAW] + 0.02 >= draw_edge)
        )
        if np.any(draw_trigger):
            combined[draw_trigger, OUTCOME_DRAW] = np.maximum(
                combined[draw_trigger, OUTCOME_DRAW],
                draw_edge[draw_trigger] + 1e-3,
            )
            combined = self._normalize_probabilities(combined)

        blowout_3plus_probability, blowout_5plus_probability = self._blowout_probabilities(
            matrix,
            score_matrix_summary,
        )
        return StrategyOutputs(
            probabilities=combined,
            poisson_probabilities=poisson_probabilities,
            draw_model_probability=draw_model_probability,
            expected_goals_a=expected_goals_a,
            expected_goals_b=expected_goals_b,
            predicted_score_a=score_matrix_summary["predicted_score_a"],
            predicted_score_b=score_matrix_summary["predicted_score_b"],
            blowout_3plus_probability=blowout_3plus_probability,
            blowout_5plus_probability=blowout_5plus_probability,
        )

    def _compose_poisson_primary_probabilities(
        self,
        dataset_df: pd.DataFrame,
        matrix: pd.DataFrame,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
    ) -> StrategyOutputs:
        expected_goals_a, expected_goals_b = self._expected_goals_from_predictions(
            dataset_df,
            predicted_score_a,
            predicted_score_b,
            score_weight=0.72,
        )
        (
            draw_model_probability,
            stalemate_signal,
            expected_draw_environment,
            projected_total_goals,
        ) = self._draw_context(
            dataset_df,
            matrix,
            fallback_draw_probability=np.full(len(matrix), self.draw_rate_prior, dtype=float),
        )
        _, poisson_probabilities, score_matrix_summary = self._score_matrix_context(
            expected_goals_a=expected_goals_a,
            expected_goals_b=expected_goals_b,
            draw_model_probability=draw_model_probability,
            stalemate_signal=stalemate_signal,
            projected_total_goals=projected_total_goals,
        )

        combined_draw_probability = (
            0.74 * poisson_probabilities[:, OUTCOME_DRAW]
            + 0.14 * draw_model_probability
            + 0.12 * np.maximum(expected_draw_environment, self.draw_rate_prior)
        )
        combined_draw_probability *= 0.9 + 0.22 * stalemate_signal

        low_total_mask = projected_total_goals <= 2.3
        combined_draw_probability[low_total_mask] *= 1.08
        high_total_mask = projected_total_goals >= 3.1
        combined_draw_probability[high_total_mask] *= 0.85

        dynamic_draw_cap = np.where(
            projected_total_goals <= 2.1,
            0.46,
            np.where(projected_total_goals <= 2.8, 0.35, 0.24),
        )
        combined_draw_probability = np.clip(combined_draw_probability, 0.01, dynamic_draw_cap)

        win_probabilities = poisson_probabilities[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]]
        win_row_sums = win_probabilities.sum(axis=1, keepdims=True)
        win_probabilities = np.divide(
            win_probabilities,
            win_row_sums,
            out=np.full_like(win_probabilities, 0.5),
            where=win_row_sums > 0,
        )

        combined = np.zeros_like(poisson_probabilities)
        remaining_mass = 1.0 - combined_draw_probability
        combined[:, OUTCOME_DRAW] = combined_draw_probability
        combined[:, OUTCOME_TEAM_A_WIN] = win_probabilities[:, 0] * remaining_mass
        combined[:, OUTCOME_TEAM_B_WIN] = win_probabilities[:, 1] * remaining_mass
        combined = self._normalize_probabilities(combined)

        draw_edge = np.max(combined[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]], axis=1)
        draw_trigger = (
            (stalemate_signal >= 0.68)
            & (projected_total_goals <= 2.2)
            & (combined[:, OUTCOME_DRAW] + 0.015 >= draw_edge)
        )
        if np.any(draw_trigger):
            combined[draw_trigger, OUTCOME_DRAW] = np.maximum(
                combined[draw_trigger, OUTCOME_DRAW],
                draw_edge[draw_trigger] + 1e-3,
            )
            combined = self._normalize_probabilities(combined)

        blowout_3plus_probability, blowout_5plus_probability = self._blowout_probabilities(
            matrix,
            score_matrix_summary,
        )
        return StrategyOutputs(
            probabilities=combined,
            poisson_probabilities=poisson_probabilities,
            draw_model_probability=draw_model_probability,
            expected_goals_a=expected_goals_a,
            expected_goals_b=expected_goals_b,
            predicted_score_a=score_matrix_summary["predicted_score_a"],
            predicted_score_b=score_matrix_summary["predicted_score_b"],
            blowout_3plus_probability=blowout_3plus_probability,
            blowout_5plus_probability=blowout_5plus_probability,
        )

    def _compose_poisson_draw_gate_probabilities(
        self,
        dataset_df: pd.DataFrame,
        matrix: pd.DataFrame,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
    ) -> StrategyOutputs:
        strategy_outputs = self._compose_poisson_primary_probabilities(
            dataset_df,
            matrix,
            predicted_score_a,
            predicted_score_b,
        )
        projected_total_goals = (
            pd.to_numeric(dataset_df.get("projected_total_goals"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        )
        stalemate_signal = (
            pd.to_numeric(dataset_df.get("stalemate_signal"), errors="coerce").fillna(0.0).to_numpy(dtype=float)
        )
        expected_goal_gap_abs = np.abs(strategy_outputs.expected_goals_a - strategy_outputs.expected_goals_b)
        draw_trigger = _poisson_draw_gate_mask(
            draw_probability=strategy_outputs.probabilities[:, OUTCOME_DRAW],
            projected_total_goals=projected_total_goals,
            stalemate_signal=stalemate_signal,
            expected_goal_gap_abs=expected_goal_gap_abs,
        )
        if np.any(draw_trigger):
            probabilities = strategy_outputs.probabilities.copy()
            draw_edge = np.max(probabilities[:, [OUTCOME_TEAM_A_WIN, OUTCOME_TEAM_B_WIN]], axis=1)
            probabilities[draw_trigger, OUTCOME_DRAW] = np.maximum(
                probabilities[draw_trigger, OUTCOME_DRAW],
                draw_edge[draw_trigger] + 1e-3,
            )
            strategy_outputs.probabilities = self._normalize_probabilities(probabilities)

        return strategy_outputs

    def _strategy_outputs(
        self,
        probability_strategy: str,
        dataset_df: pd.DataFrame,
        matrix: pd.DataFrame,
        base_probabilities: np.ndarray,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
    ) -> StrategyOutputs:
        if probability_strategy == "hybrid":
            return self._compose_outcome_probabilities(
                dataset_df,
                matrix,
                base_probabilities,
                predicted_score_a,
                predicted_score_b,
            )
        if probability_strategy == "poisson_primary":
            return self._compose_poisson_primary_probabilities(
                dataset_df,
                matrix,
                predicted_score_a,
                predicted_score_b,
            )
        if probability_strategy == "poisson_draw_gate":
            return self._compose_poisson_draw_gate_probabilities(
                dataset_df,
                matrix,
                predicted_score_a,
                predicted_score_b,
            )
        raise ValueError(f"Unsupported probability strategy: {probability_strategy}")

    def _build_evaluation_frame(
        self,
        test_df: pd.DataFrame,
        probabilities: np.ndarray,
        predicted_labels: np.ndarray,
        predicted_margin: np.ndarray,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
        poisson_probabilities: np.ndarray,
        draw_model_probability: np.ndarray,
        expected_goals_a: np.ndarray,
        expected_goals_b: np.ndarray,
        blowout_3plus_probability: np.ndarray,
        blowout_5plus_probability: np.ndarray,
        predicted_blowout_3plus: np.ndarray,
        predicted_blowout_5plus: np.ndarray,
        probability_strategy: str,
    ) -> pd.DataFrame:
        age_group_numeric = pd.to_numeric(test_df.get("age_group_numeric"), errors="coerce").fillna(0).astype(int)
        age_group = age_group_numeric.apply(lambda value: f"u{value}" if value > 0 else "unknown")
        evaluation_frame = pd.DataFrame(
            {
                "game_id": test_df["game_id"].astype(str).to_numpy(),
                "game_date": test_df["game_date"].astype(str).to_numpy(),
                "age_group": age_group.to_numpy(),
                "feature_source": "point_in_time_snapshot",
                "probability_strategy": probability_strategy,
                "actual_outcome": test_df["actual_outcome"].astype(str).to_numpy(),
                "predicted_outcome": [OUTCOME_LABELS[int(label)].replace("_win", "") for label in predicted_labels],
                "prob_team_a_win": probabilities[:, OUTCOME_TEAM_A_WIN],
                "prob_draw": probabilities[:, OUTCOME_DRAW],
                "prob_team_b_win": probabilities[:, OUTCOME_TEAM_B_WIN],
                "poisson_prob_team_a_win": poisson_probabilities[:, OUTCOME_TEAM_A_WIN],
                "poisson_prob_draw": poisson_probabilities[:, OUTCOME_DRAW],
                "poisson_prob_team_b_win": poisson_probabilities[:, OUTCOME_TEAM_B_WIN],
                "draw_model_probability": draw_model_probability,
                "blowout_3plus_probability": blowout_3plus_probability,
                "blowout_5plus_probability": blowout_5plus_probability,
                "predicted_blowout_3plus": predicted_blowout_3plus,
                "predicted_blowout_5plus": predicted_blowout_5plus,
                "stalemate_signal": (
                    pd.to_numeric(test_df.get("stalemate_signal"), errors="coerce").fillna(0.0).to_numpy()
                ),
                "projected_total_goals": (
                    pd.to_numeric(test_df.get("projected_total_goals"), errors="coerce").fillna(0.0).to_numpy()
                ),
                "predicted_margin": predicted_margin,
                "actual_margin": test_df["actual_margin"].astype(float).to_numpy(),
                "predicted_score_a": predicted_score_a,
                "predicted_score_b": predicted_score_b,
                "expected_goals_a": expected_goals_a,
                "expected_goals_b": expected_goals_b,
                "actual_score_a": test_df["actual_score_a"].astype(float).to_numpy(),
                "actual_score_b": test_df["actual_score_b"].astype(float).to_numpy(),
            }
        )
        return evaluation_frame

    def _brier_score(self, y_true: np.ndarray, probabilities: np.ndarray) -> float:
        one_hot = np.zeros_like(probabilities)
        for row_index, class_index in enumerate(y_true):
            one_hot[row_index, class_index] = 1.0
        return float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1)))

    def train(
        self,
        dataset_df: pd.DataFrame,
        test_ratio: float = 0.2,
        random_state: int = 42,
        min_examples: int = 100,
        probability_strategy: str = DEFAULT_PROBABILITY_STRATEGY,
        strategy_constraints: Optional[Dict[str, float]] = None,
    ) -> Dict[str, object]:
        if dataset_df.empty:
            raise ValueError("Point-in-time dataset is empty")
        if len(dataset_df) < min_examples:
            raise ValueError(
                f"Insufficient examples for training: found {len(dataset_df):,}, need at least {min_examples:,}"
            )
        if probability_strategy not in TRAINING_PROBABILITY_STRATEGIES:
            raise ValueError(
                f"Unsupported probability strategy '{probability_strategy}'. "
                f"Expected one of {sorted(TRAINING_PROBABILITY_STRATEGIES)}"
            )

        train_df, test_df = self._chronological_split(dataset_df, test_ratio=test_ratio)
        self.feature_names = self._feature_columns(train_df)
        requested_probability_strategy = probability_strategy
        self.requested_probability_strategy = requested_probability_strategy
        self.strategy_constraints = {
            **DEFAULT_AUTO_STRATEGY_CONSTRAINTS,
            **(strategy_constraints or {}),
        }
        self.probability_strategy = (
            "hybrid" if requested_probability_strategy == AUTO_PROBABILITY_STRATEGY else requested_probability_strategy
        )

        X_train = train_df[self.feature_names].fillna(0.0).astype(float)
        X_test = test_df[self.feature_names].fillna(0.0).astype(float)

        y_train = train_df["actual_outcome_label"].astype(int).to_numpy()
        y_test = test_df["actual_outcome_label"].astype(int).to_numpy()
        class_balance = self._class_balance_summary(y_train)
        self.draw_rate_prior = float(np.mean(y_train == OUTCOME_DRAW))

        unique_labels = sorted(np.unique(y_train).tolist())
        if len(unique_labels) < 2:
            raise ValueError(
                f"Training data does not contain enough class diversity. Observed only outcome labels: {unique_labels}"
            )

        self.class_labels = unique_labels
        label_to_encoded = {label: index for index, label in enumerate(self.class_labels)}
        y_train_encoded = np.array([label_to_encoded[label] for label in y_train], dtype=int)

        self.classifier = self._build_classifier(
            random_state=random_state,
            num_classes=len(self.class_labels),
        )
        self.draw_classifier = self._build_binary_classifier(random_state=random_state)
        self.margin_regressor = self._build_regressor(random_state=random_state)
        self.score_a_regressor = self._build_goal_regressor(random_state=random_state)
        self.score_b_regressor = self._build_goal_regressor(random_state=random_state)
        class_sample_weights, named_class_weights = self._multiclass_sample_weights(y_train)
        self.classifier.fit(X_train, y_train_encoded, sample_weight=class_sample_weights)

        draw_targets_train = (y_train == OUTCOME_DRAW).astype(int)
        draw_sample_weights, draw_weight_map = self._draw_sample_weights(draw_targets_train)
        if np.any(draw_targets_train == 1) and np.any(draw_targets_train == 0):
            self.draw_classifier.fit(X_train, draw_targets_train, sample_weight=draw_sample_weights)
        else:
            self.draw_classifier = None
        blowout_targets_3plus = (train_df["actual_margin"].astype(float).abs() >= 3.0).astype(int).to_numpy()
        blowout_weights_3plus, blowout_weight_map_3plus = self._binary_sample_weights(
            blowout_targets_3plus,
            positive_label="blowout_3plus",
            cap=BLOWOUT_CLASS_WEIGHT_CAP,
        )
        self.blowout_classifier_3plus = self._build_binary_classifier(random_state=random_state)
        if np.any(blowout_targets_3plus == 1) and np.any(blowout_targets_3plus == 0):
            self.blowout_classifier_3plus.fit(
                X_train,
                blowout_targets_3plus,
                sample_weight=blowout_weights_3plus,
            )
        else:
            self.blowout_classifier_3plus = None
        blowout_targets_5plus = (train_df["actual_margin"].astype(float).abs() >= 5.0).astype(int).to_numpy()
        blowout_weights_5plus, blowout_weight_map_5plus = self._binary_sample_weights(
            blowout_targets_5plus,
            positive_label="blowout_5plus",
            cap=BLOWOUT_CLASS_WEIGHT_CAP,
        )
        self.blowout_classifier_5plus = self._build_binary_classifier(random_state=random_state)
        if np.any(blowout_targets_5plus == 1) and np.any(blowout_targets_5plus == 0):
            self.blowout_classifier_5plus.fit(
                X_train,
                blowout_targets_5plus,
                sample_weight=blowout_weights_5plus,
            )
        else:
            self.blowout_classifier_5plus = None
        self.margin_regressor.fit(X_train, train_df["actual_margin"].astype(float))
        self.score_a_regressor.fit(X_train, train_df["actual_score_a"].astype(float))
        self.score_b_regressor.fit(X_train, train_df["actual_score_b"].astype(float))

        encoded_probabilities = self.classifier.predict_proba(X_test)
        base_probabilities = self._normalize_probabilities(self._expand_class_probabilities(encoded_probabilities))
        predicted_margin = self.margin_regressor.predict(X_test)
        predicted_score_a = self.score_a_regressor.predict(X_test)
        predicted_score_b = self.score_b_regressor.predict(X_test)
        train_base_probabilities = self._normalize_probabilities(
            self._expand_class_probabilities(self.classifier.predict_proba(X_train))
        )
        train_predicted_score_a = self.score_a_regressor.predict(X_train)
        train_predicted_score_b = self.score_b_regressor.predict(X_train)
        strategy_metrics: Dict[str, Dict[str, object]] = {}
        strategy_outputs: Dict[str, StrategyOutputs] = {}
        strategy_draw_postprocessing: Dict[str, Dict[str, object]] = {}
        strategy_blowout_postprocessing: Dict[str, BlowoutPostprocessing] = {}
        test_age_group_numeric = _age_group_numeric_array(test_df)
        for strategy_name in sorted(PROBABILITY_STRATEGIES):
            train_outputs = self._strategy_outputs(
                strategy_name,
                dataset_df=train_df,
                matrix=X_train,
                base_probabilities=train_base_probabilities,
                predicted_score_a=train_predicted_score_a,
                predicted_score_b=train_predicted_score_b,
            )
            draw_policy = self._fit_draw_postprocessing(
                train_df=train_df,
                probabilities=train_outputs.probabilities,
            )
            strategy_draw_postprocessing[strategy_name] = draw_policy
            blowout_postprocessing = self._fit_blowout_postprocessing(
                train_df=train_df,
                calibration_outputs=train_outputs,
            )
            strategy_blowout_postprocessing[strategy_name] = blowout_postprocessing
            self.draw_decision_policy = draw_policy
            self.blowout_calibrator_3plus = blowout_postprocessing.calibrator_3plus
            self.blowout_calibrator_5plus = blowout_postprocessing.calibrator_5plus
            self.blowout_probability_thresholds = blowout_postprocessing.thresholds
            self.blowout_probability_thresholds_by_age = blowout_postprocessing.thresholds_by_age
            outputs = self._strategy_outputs(
                strategy_name,
                dataset_df=test_df,
                matrix=X_test,
                base_probabilities=base_probabilities,
                predicted_score_a=predicted_score_a,
                predicted_score_b=predicted_score_b,
            )
            strategy_outputs[strategy_name] = outputs
            probabilities_for_strategy = outputs.probabilities
            predicted_labels_for_strategy = self._draw_prediction_labels(
                probabilities_for_strategy,
                dataset_df=test_df,
                policy=draw_policy,
            )
            predicted_blowout_3plus, predicted_blowout_5plus = self._blowout_prediction_labels(
                outputs.blowout_3plus_probability,
                outputs.blowout_5plus_probability,
                thresholds=blowout_postprocessing.thresholds,
                age_group_numeric=test_age_group_numeric,
                thresholds_by_age=blowout_postprocessing.thresholds_by_age,
            )
            strategy_evaluation_frame = self._build_evaluation_frame(
                test_df=test_df,
                probabilities=probabilities_for_strategy,
                predicted_labels=predicted_labels_for_strategy,
                predicted_margin=predicted_margin,
                predicted_score_a=outputs.predicted_score_a,
                predicted_score_b=outputs.predicted_score_b,
                poisson_probabilities=outputs.poisson_probabilities,
                draw_model_probability=outputs.draw_model_probability,
                expected_goals_a=outputs.expected_goals_a,
                expected_goals_b=outputs.expected_goals_b,
                blowout_3plus_probability=outputs.blowout_3plus_probability,
                blowout_5plus_probability=outputs.blowout_5plus_probability,
                predicted_blowout_3plus=predicted_blowout_3plus,
                predicted_blowout_5plus=predicted_blowout_5plus,
                probability_strategy=strategy_name,
            )
            strategy_summary = compute_evaluation_summary(strategy_evaluation_frame)
            strategy_summary["predicted_draw_rate"] = float(np.mean(predicted_labels_for_strategy == OUTCOME_DRAW))
            strategy_metrics[strategy_name] = strategy_summary

        auto_strategy_selection = None
        if requested_probability_strategy == AUTO_PROBABILITY_STRATEGY:
            selected_probability_strategy, auto_strategy_selection = self._select_probability_strategy(
                strategy_metrics=strategy_metrics,
                actual_draw_rate=float(np.mean(y_test == OUTCOME_DRAW)),
                constraints=self.strategy_constraints,
            )
            self.probability_strategy = selected_probability_strategy

        self.draw_decision_policy = strategy_draw_postprocessing[self.probability_strategy]
        self.auto_strategy_selection = auto_strategy_selection or {}
        selected_blowout_postprocessing = strategy_blowout_postprocessing[self.probability_strategy]
        self.blowout_calibrator_3plus = selected_blowout_postprocessing.calibrator_3plus
        self.blowout_calibrator_5plus = selected_blowout_postprocessing.calibrator_5plus
        self.blowout_probability_thresholds = selected_blowout_postprocessing.thresholds
        self.blowout_probability_thresholds_by_age = selected_blowout_postprocessing.thresholds_by_age
        selected_outputs = strategy_outputs[self.probability_strategy]
        probabilities = selected_outputs.probabilities
        predicted_labels = self._draw_prediction_labels(
            probabilities,
            dataset_df=test_df,
        )
        predicted_blowout_3plus, predicted_blowout_5plus = self._blowout_prediction_labels(
            selected_outputs.blowout_3plus_probability,
            selected_outputs.blowout_5plus_probability,
            thresholds=self.blowout_probability_thresholds,
            age_group_numeric=test_age_group_numeric,
            thresholds_by_age=self.blowout_probability_thresholds_by_age,
        )
        self.last_evaluation_frame = self._build_evaluation_frame(
            test_df=test_df,
            probabilities=probabilities,
            predicted_labels=predicted_labels,
            predicted_margin=predicted_margin,
            predicted_score_a=selected_outputs.predicted_score_a,
            predicted_score_b=selected_outputs.predicted_score_b,
            poisson_probabilities=selected_outputs.poisson_probabilities,
            draw_model_probability=selected_outputs.draw_model_probability,
            expected_goals_a=selected_outputs.expected_goals_a,
            expected_goals_b=selected_outputs.expected_goals_b,
            blowout_3plus_probability=selected_outputs.blowout_3plus_probability,
            blowout_5plus_probability=selected_outputs.blowout_5plus_probability,
            predicted_blowout_3plus=predicted_blowout_3plus,
            predicted_blowout_5plus=predicted_blowout_5plus,
            probability_strategy=self.probability_strategy,
        )
        summary_metrics = compute_evaluation_summary(self.last_evaluation_frame)
        metrics = {
            **summary_metrics,
            "actual_draw_rate": float(np.mean(y_test == OUTCOME_DRAW)),
            "predicted_draw_rate": float(np.mean(predicted_labels == OUTCOME_DRAW)),
            "train_examples": int(len(train_df)),
            "test_examples": int(len(test_df)),
            "requested_probability_strategy": requested_probability_strategy,
            "probability_strategy": self.probability_strategy,
            "class_labels": [OUTCOME_LABELS[label] for label in self.class_labels],
            "feature_count": int(len(self.feature_names)),
            "training_class_balance": class_balance,
            "multiclass_sample_weights": named_class_weights,
            "draw_binary_sample_weights": draw_weight_map,
            "blowout_3plus_sample_weights": blowout_weight_map_3plus,
            "blowout_5plus_sample_weights": blowout_weight_map_5plus,
            "strategy_constraints": self.strategy_constraints,
            "blowout_probability_thresholds": {
                "3plus": float(self.blowout_probability_thresholds[3]),
                "5plus": float(self.blowout_probability_thresholds[5]),
            },
            "blowout_probability_thresholds_by_age": {
                "3plus": {
                    str(age): float(value)
                    for age, value in self.blowout_probability_thresholds_by_age.get(3, {}).items()
                },
                "5plus": {
                    str(age): float(value)
                    for age, value in self.blowout_probability_thresholds_by_age.get(5, {}).items()
                },
            },
            "draw_decision_policy": {
                "default": {key: float(value) for key, value in self.draw_decision_policy.get("default", {}).items()},
                "by_age": {
                    str(age): {key: float(value) for key, value in policy.items()}
                    for age, policy in self.draw_decision_policy.get("by_age", {}).items()
                },
            },
            "strategy_metrics": strategy_metrics,
        }
        if auto_strategy_selection is not None:
            metrics["auto_strategy_selection"] = auto_strategy_selection

        self.training_metadata = {
            "metrics": metrics,
            "train_examples": int(len(train_df)),
            "test_examples": int(len(test_df)),
            "feature_names": self.feature_names,
            "class_labels": self.class_labels,
            "requested_probability_strategy": self.requested_probability_strategy,
            "probability_strategy": self.probability_strategy,
            "strategy_constraints": self.strategy_constraints,
            "auto_strategy_selection": self.auto_strategy_selection,
        }
        return metrics

    @classmethod
    def load(cls, artifact_path: str) -> "PointInTimeMatchModel":
        with open(artifact_path, "rb") as handle:
            payload = pickle.load(handle)

        model = cls(model_dir=str(Path(artifact_path).resolve().parent))
        model.classifier = payload["classifier"]
        model.draw_classifier = payload.get("draw_classifier")
        model.blowout_classifier_3plus = payload.get("blowout_classifier_3plus")
        model.blowout_classifier_5plus = payload.get("blowout_classifier_5plus")
        model.blowout_calibrator_3plus = payload.get("blowout_calibrator_3plus")
        model.blowout_calibrator_5plus = payload.get("blowout_calibrator_5plus")
        model.margin_regressor = payload["margin_regressor"]
        model.score_a_regressor = payload["score_a_regressor"]
        model.score_b_regressor = payload["score_b_regressor"]
        model.draw_rate_prior = payload.get("draw_rate_prior", 0.0)
        model.requested_probability_strategy = payload.get(
            "requested_probability_strategy",
            DEFAULT_PROBABILITY_STRATEGY,
        )
        model.probability_strategy = payload.get("probability_strategy", DEFAULT_PROBABILITY_STRATEGY)
        model.strategy_constraints = payload.get(
            "strategy_constraints",
            dict(DEFAULT_AUTO_STRATEGY_CONSTRAINTS),
        )
        model.auto_strategy_selection = payload.get("auto_strategy_selection", {})
        model.blowout_probability_thresholds = payload.get("blowout_probability_thresholds", {3: 0.5, 5: 0.5})
        model.blowout_probability_thresholds_by_age = payload.get(
            "blowout_probability_thresholds_by_age",
            {3: {}, 5: {}},
        )
        model.draw_decision_policy = payload.get(
            "draw_decision_policy",
            {
                "default": model._default_draw_decision_policy(),
                "by_age": {},
            },
        )
        model.feature_names = payload["feature_names"]
        model.class_labels = payload["class_labels"]
        model.training_metadata = payload.get("training_metadata", {})
        return model

    def predict_frame(self, dataset_df: pd.DataFrame) -> pd.DataFrame:
        if self.classifier is None:
            raise ValueError("Model has not been trained or loaded")
        matrix = self._prepare_matrix(dataset_df)
        encoded_probabilities = self.classifier.predict_proba(matrix)
        base_probabilities = self._normalize_probabilities(self._expand_class_probabilities(encoded_probabilities))
        predicted_margin = self.margin_regressor.predict(matrix)
        predicted_score_a = self.score_a_regressor.predict(matrix)
        predicted_score_b = self.score_b_regressor.predict(matrix)
        strategy_outputs = self._strategy_outputs(
            self.probability_strategy,
            dataset_df=dataset_df,
            matrix=matrix,
            base_probabilities=base_probabilities,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
        )
        probabilities = strategy_outputs.probabilities
        predicted_labels = self._draw_prediction_labels(
            probabilities,
            dataset_df=dataset_df,
        )
        predicted_blowout_3plus, predicted_blowout_5plus = self._blowout_prediction_labels(
            strategy_outputs.blowout_3plus_probability,
            strategy_outputs.blowout_5plus_probability,
            age_group_numeric=_age_group_numeric_array(dataset_df),
        )
        return self._build_evaluation_frame(
            test_df=dataset_df,
            probabilities=probabilities,
            predicted_labels=predicted_labels,
            predicted_margin=predicted_margin,
            predicted_score_a=strategy_outputs.predicted_score_a,
            predicted_score_b=strategy_outputs.predicted_score_b,
            poisson_probabilities=strategy_outputs.poisson_probabilities,
            draw_model_probability=strategy_outputs.draw_model_probability,
            expected_goals_a=strategy_outputs.expected_goals_a,
            expected_goals_b=strategy_outputs.expected_goals_b,
            blowout_3plus_probability=strategy_outputs.blowout_3plus_probability,
            blowout_5plus_probability=strategy_outputs.blowout_5plus_probability,
            predicted_blowout_3plus=predicted_blowout_3plus,
            predicted_blowout_5plus=predicted_blowout_5plus,
            probability_strategy=self.probability_strategy,
        )

    def relabel_evaluation_frame(self, evaluation_frame: pd.DataFrame) -> pd.DataFrame:
        standardized = build_standardized_evaluation_frame(evaluation_frame)
        if standardized.empty:
            return standardized

        probabilities = standardized[list(PROBABILITY_COLUMNS.values())].to_numpy(dtype=float)
        predicted_labels = self._draw_prediction_labels(
            probabilities,
            dataset_df=standardized,
        )
        standardized["predicted_outcome"] = [OUTCOME_ORDER[label] for label in predicted_labels]

        if {
            "blowout_3plus_probability",
            "blowout_5plus_probability",
        }.issubset(standardized.columns):
            predicted_blowout_3plus, predicted_blowout_5plus = self._blowout_prediction_labels(
                blowout_3plus_probability=standardized["blowout_3plus_probability"].to_numpy(dtype=float),
                blowout_5plus_probability=standardized["blowout_5plus_probability"].to_numpy(dtype=float),
                thresholds=self.blowout_probability_thresholds,
                age_group_numeric=_age_group_numeric_array(standardized),
                thresholds_by_age=self.blowout_probability_thresholds_by_age,
            )
            standardized["predicted_blowout_3plus"] = predicted_blowout_3plus.astype(int)
            standardized["predicted_blowout_5plus"] = predicted_blowout_5plus.astype(int)

        return build_standardized_evaluation_frame(standardized)

    def write_evaluation_report(self, output_dir: str, prefix: str = "point_in_time_model") -> dict[str, object]:
        if self.last_evaluation_frame.empty:
            raise ValueError("No evaluation frame available. Train or predict first.")
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        evaluation_csv_path = output_path / f"{prefix}_evaluation.csv"
        self.last_evaluation_frame.to_csv(evaluation_csv_path, index=False)
        summary = write_evaluation_bundle(self.last_evaluation_frame, output_path, prefix=prefix)
        return {
            "evaluation_csv_path": str(evaluation_csv_path),
            "summary": summary,
        }

    def save(self, artifact_name: str = "point_in_time_match_model") -> Dict[str, str]:
        if self.classifier is None:
            raise ValueError("Model has not been trained")

        artifact_base = Path(self.model_dir) / artifact_name
        pickle_path = artifact_base.with_suffix(".pkl")
        metadata_path = artifact_base.with_name(f"{artifact_base.name}_metadata.json")

        payload = {
            "classifier": self.classifier,
            "draw_classifier": self.draw_classifier,
            "blowout_classifier_3plus": self.blowout_classifier_3plus,
            "blowout_classifier_5plus": self.blowout_classifier_5plus,
            "blowout_calibrator_3plus": self.blowout_calibrator_3plus,
            "blowout_calibrator_5plus": self.blowout_calibrator_5plus,
            "margin_regressor": self.margin_regressor,
            "score_a_regressor": self.score_a_regressor,
            "score_b_regressor": self.score_b_regressor,
            "draw_rate_prior": self.draw_rate_prior,
            "requested_probability_strategy": self.requested_probability_strategy,
            "probability_strategy": self.probability_strategy,
            "strategy_constraints": self.strategy_constraints,
            "auto_strategy_selection": self.auto_strategy_selection,
            "blowout_probability_thresholds": self.blowout_probability_thresholds,
            "blowout_probability_thresholds_by_age": self.blowout_probability_thresholds_by_age,
            "draw_decision_policy": self.draw_decision_policy,
            "feature_names": self.feature_names,
            "class_labels": self.class_labels,
            "training_metadata": self.training_metadata,
        }

        with open(pickle_path, "wb") as handle:
            pickle.dump(payload, handle)

        metadata = {
            **self.training_metadata,
            "feature_count": len(self.feature_names),
            "class_labels": [OUTCOME_LABELS[label] for label in self.class_labels],
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return {
            "pickle_path": str(pickle_path),
            "metadata_path": str(metadata_path),
        }
