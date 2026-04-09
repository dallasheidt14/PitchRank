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
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error, mean_squared_error

try:
    from xgboost import XGBClassifier, XGBRegressor

    HAS_XGBOOST = True
except ImportError:  # pragma: no cover - exercised only when xgboost is missing
    HAS_XGBOOST = False

from scripts.predictor_python import (
    Game as PredictorGame,
)
from scripts.predictor_python import calculate_common_opponent_signal, calculate_head_to_head, calculate_recent_form
from src.predictions.evaluation_reporting import write_evaluation_bundle

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


@dataclass
class DatasetBuildResult:
    dataset: pd.DataFrame
    summary: Dict[str, object]


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
            -abs(
                _to_float(team_a_snapshot.get("glicko_rating"))
                - _to_float(team_b_snapshot.get("glicko_rating"))
            )
            / 140.0
        ),
        math.exp(
            -abs(
                _to_float(team_a_snapshot.get("exp_margin"))
                - _to_float(team_b_snapshot.get("exp_margin"))
            )
            / 1.25
        ),
        math.exp(
            -6.0
            * abs(
                _to_float(team_a_snapshot.get("exp_win_rate"))
                - _to_float(team_b_snapshot.get("exp_win_rate"))
            )
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
            - (
                _to_float(team_b_snapshot.get("power_score_final")) * _to_float(team_b_snapshot.get("sos_norm"))
            ),
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


def build_point_in_time_dataset(
    games_df: pd.DataFrame,
    snapshot_index: Dict[str, List[dict]],
    team_names: Optional[Dict[str, str]] = None,
    include_mirrored_examples: bool = True,
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

        recent_form_a = calculate_recent_form(team_a_id, team_a_prior_games)
        recent_form_b = calculate_recent_form(team_b_id, team_b_prior_games)
        h2h = calculate_head_to_head(team_a_id, team_b_id, combined_prior_games)
        common_opponents = calculate_common_opponent_signal(team_a_id, team_b_id, combined_prior_games)
        actual_outcome_code, actual_outcome_name = _outcome_label(score_a, score_b)

        enriched_team_a_snapshot = {**team_a_snapshot, "_game_date": game_row["game_date"]}
        enriched_team_b_snapshot = {**team_b_snapshot, "_game_date": game_row["game_date"]}
        features = _paired_snapshot_features(enriched_team_a_snapshot, enriched_team_b_snapshot)

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
                "team_a_prior_game_count": float(len(team_a_prior_games)),
                "team_b_prior_game_count": float(len(team_b_prior_games)),
                "combined_prior_game_count": float(len(combined_prior_games)),
                "game_id": str(game_row["id"]),
                "game_date": str(game_row["game_date"]),
                "team_a_id": team_a_id,
                "team_b_id": team_b_id,
                "team_a_name": team_names.get(team_a_id),
                "team_b_name": team_names.get(team_b_id),
                "team_a_snapshot_date": team_a_snapshot.get("snapshot_date"),
                "team_b_snapshot_date": team_b_snapshot.get("snapshot_date"),
                "example_orientation": orientation,
                "actual_score_a": int(score_a),
                "actual_score_b": int(score_b),
                "actual_margin": int(score_a - score_b),
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

    for _, game_row in games_df.iterrows():
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
            str(label): float(count) / float(len(dataset))
            for label, count in class_counts.items()
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
        self.margin_regressor = None
        self.score_a_regressor = None
        self.score_b_regressor = None
        self.draw_rate_prior = 0.0
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
        draw_count = int(np.sum(draw_targets == 1))
        non_draw_count = int(np.sum(draw_targets == 0))
        if draw_count <= 0:
            return np.ones_like(draw_targets, dtype=float), {"non_draw": 1.0, "draw": 1.0}
        positive_weight = min(
            DRAW_BINARY_WEIGHT_CAP,
            max(1.0, math.sqrt(float(non_draw_count) / float(draw_count))) * 1.2,
        )
        sample_weights = np.where(draw_targets == 1, positive_weight, 1.0).astype(float)
        return sample_weights, {"non_draw": 1.0, "draw": float(positive_weight)}

    def _predict_draw_probability(self, matrix: pd.DataFrame) -> np.ndarray:
        if self.draw_classifier is None:
            return np.full(len(matrix), np.nan, dtype=float)
        probabilities = self.draw_classifier.predict_proba(matrix)
        draw_classes = getattr(self.draw_classifier, "classes_", np.array([0, 1]))
        draw_index = (
            int(np.where(np.asarray(draw_classes) == 1)[0][0])
            if 1 in draw_classes
            else probabilities.shape[1] - 1
        )
        return np.asarray(probabilities[:, draw_index], dtype=float)

    def _compose_outcome_probabilities(
        self,
        dataset_df: pd.DataFrame,
        matrix: pd.DataFrame,
        base_probabilities: np.ndarray,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
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
        expected_goals_a = np.clip(0.65 * predicted_score_a + 0.35 * prior_goal_a, 0.05, 6.0)
        expected_goals_b = np.clip(0.65 * predicted_score_b + 0.35 * prior_goal_b, 0.05, 6.0)

        poisson_probabilities = _poisson_outcome_probabilities(expected_goals_a, expected_goals_b)
        raw_draw_model_probability = np.nan_to_num(
            self._predict_draw_probability(matrix),
            nan=base_probabilities[:, OUTCOME_DRAW],
        )
        draw_model_probability = np.clip(
            self.draw_rate_prior
            + DRAW_MODEL_SHRINK_FACTOR * (raw_draw_model_probability - self.draw_rate_prior),
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
            .fillna(pd.Series(expected_goals_a + expected_goals_b))
            .clip(0.05, 8.0)
            .to_numpy(dtype=float)
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

        return combined, poisson_probabilities, draw_model_probability

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
    ) -> pd.DataFrame:
        age_group_numeric = pd.to_numeric(test_df.get("age_group_numeric"), errors="coerce").fillna(0).astype(int)
        age_group = age_group_numeric.apply(lambda value: f"u{value}" if value > 0 else "unknown")
        evaluation_frame = pd.DataFrame(
            {
                "game_id": test_df["game_id"].astype(str).to_numpy(),
                "game_date": test_df["game_date"].astype(str).to_numpy(),
                "age_group": age_group.to_numpy(),
                "feature_source": "point_in_time_snapshot",
                "actual_outcome": test_df["actual_outcome"].astype(str).to_numpy(),
                "predicted_outcome": [OUTCOME_LABELS[int(label)].replace("_win", "") for label in predicted_labels],
                "prob_team_a_win": probabilities[:, OUTCOME_TEAM_A_WIN],
                "prob_draw": probabilities[:, OUTCOME_DRAW],
                "prob_team_b_win": probabilities[:, OUTCOME_TEAM_B_WIN],
                "poisson_prob_team_a_win": poisson_probabilities[:, OUTCOME_TEAM_A_WIN],
                "poisson_prob_draw": poisson_probabilities[:, OUTCOME_DRAW],
                "poisson_prob_team_b_win": poisson_probabilities[:, OUTCOME_TEAM_B_WIN],
                "draw_model_probability": draw_model_probability,
                "stalemate_signal": (
                    pd.to_numeric(test_df.get("stalemate_signal"), errors="coerce")
                    .fillna(0.0)
                    .to_numpy()
                ),
                "projected_total_goals": (
                    pd.to_numeric(test_df.get("projected_total_goals"), errors="coerce")
                    .fillna(0.0)
                    .to_numpy()
                ),
                "predicted_margin": predicted_margin,
                "actual_margin": test_df["actual_margin"].astype(float).to_numpy(),
                "predicted_score_a": predicted_score_a,
                "predicted_score_b": predicted_score_b,
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
    ) -> Dict[str, object]:
        if dataset_df.empty:
            raise ValueError("Point-in-time dataset is empty")
        if len(dataset_df) < min_examples:
            raise ValueError(
                f"Insufficient examples for training: found {len(dataset_df):,}, need at least {min_examples:,}"
            )

        train_df, test_df = self._chronological_split(dataset_df, test_ratio=test_ratio)
        self.feature_names = self._feature_columns(train_df)

        X_train = train_df[self.feature_names].fillna(0.0).astype(float)
        X_test = test_df[self.feature_names].fillna(0.0).astype(float)

        y_train = train_df["actual_outcome_label"].astype(int).to_numpy()
        y_test = test_df["actual_outcome_label"].astype(int).to_numpy()
        class_balance = self._class_balance_summary(y_train)
        self.draw_rate_prior = float(np.mean(y_train == OUTCOME_DRAW))

        unique_labels = sorted(np.unique(y_train).tolist())
        if len(unique_labels) < 2:
            raise ValueError(
                "Training data does not contain enough class diversity. "
                f"Observed only outcome labels: {unique_labels}"
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
        self.score_a_regressor = self._build_regressor(random_state=random_state)
        self.score_b_regressor = self._build_regressor(random_state=random_state)
        class_sample_weights, named_class_weights = self._multiclass_sample_weights(y_train)
        self.classifier.fit(X_train, y_train_encoded, sample_weight=class_sample_weights)

        draw_targets_train = (y_train == OUTCOME_DRAW).astype(int)
        draw_sample_weights, draw_weight_map = self._draw_sample_weights(draw_targets_train)
        if np.any(draw_targets_train == 1) and np.any(draw_targets_train == 0):
            self.draw_classifier.fit(X_train, draw_targets_train, sample_weight=draw_sample_weights)
        else:
            self.draw_classifier = None
        self.margin_regressor.fit(X_train, train_df["actual_margin"].astype(float))
        self.score_a_regressor.fit(X_train, train_df["actual_score_a"].astype(float))
        self.score_b_regressor.fit(X_train, train_df["actual_score_b"].astype(float))

        encoded_probabilities = self.classifier.predict_proba(X_test)
        base_probabilities = self._normalize_probabilities(self._expand_class_probabilities(encoded_probabilities))
        predicted_margin = self.margin_regressor.predict(X_test)
        predicted_score_a = self.score_a_regressor.predict(X_test)
        predicted_score_b = self.score_b_regressor.predict(X_test)
        probabilities, poisson_probabilities, draw_model_probability = self._compose_outcome_probabilities(
            dataset_df=test_df,
            matrix=X_test,
            base_probabilities=base_probabilities,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
        )
        predicted_labels = np.argmax(probabilities, axis=1)
        self.last_evaluation_frame = self._build_evaluation_frame(
            test_df=test_df,
            probabilities=probabilities,
            predicted_labels=predicted_labels,
            predicted_margin=predicted_margin,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
            poisson_probabilities=poisson_probabilities,
            draw_model_probability=draw_model_probability,
        )

        metrics = {
            "winner_accuracy": float(accuracy_score(y_test, predicted_labels)),
            "log_loss": float(log_loss(y_test, probabilities, labels=[0, 1, 2])),
            "brier_score": self._brier_score(y_test, probabilities),
            "draw_recall": float(np.mean(predicted_labels[y_test == OUTCOME_DRAW] == OUTCOME_DRAW))
            if np.any(y_test == OUTCOME_DRAW)
            else None,
            "draw_precision": float(np.mean(y_test[predicted_labels == OUTCOME_DRAW] == OUTCOME_DRAW))
            if np.any(predicted_labels == OUTCOME_DRAW)
            else None,
            "actual_draw_rate": float(np.mean(y_test == OUTCOME_DRAW)),
            "predicted_draw_rate": float(np.mean(predicted_labels == OUTCOME_DRAW)),
            "margin_mae": float(mean_absolute_error(test_df["actual_margin"], predicted_margin)),
            "margin_rmse": float(math.sqrt(mean_squared_error(test_df["actual_margin"], predicted_margin))),
            "score_a_mae": float(mean_absolute_error(test_df["actual_score_a"], predicted_score_a)),
            "score_b_mae": float(mean_absolute_error(test_df["actual_score_b"], predicted_score_b)),
            "train_examples": int(len(train_df)),
            "test_examples": int(len(test_df)),
            "class_labels": [OUTCOME_LABELS[label] for label in self.class_labels],
            "feature_count": int(len(self.feature_names)),
            "training_class_balance": class_balance,
            "multiclass_sample_weights": named_class_weights,
            "draw_binary_sample_weights": draw_weight_map,
        }

        self.training_metadata = {
            "metrics": metrics,
            "train_examples": int(len(train_df)),
            "test_examples": int(len(test_df)),
            "feature_names": self.feature_names,
            "class_labels": self.class_labels,
        }
        return metrics

    @classmethod
    def load(cls, artifact_path: str) -> "PointInTimeMatchModel":
        with open(artifact_path, "rb") as handle:
            payload = pickle.load(handle)

        model = cls(model_dir=str(Path(artifact_path).resolve().parent))
        model.classifier = payload["classifier"]
        model.draw_classifier = payload.get("draw_classifier")
        model.margin_regressor = payload["margin_regressor"]
        model.score_a_regressor = payload["score_a_regressor"]
        model.score_b_regressor = payload["score_b_regressor"]
        model.draw_rate_prior = payload.get("draw_rate_prior", 0.0)
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
        probabilities, poisson_probabilities, draw_model_probability = self._compose_outcome_probabilities(
            dataset_df=dataset_df,
            matrix=matrix,
            base_probabilities=base_probabilities,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
        )
        predicted_labels = np.argmax(probabilities, axis=1)
        return self._build_evaluation_frame(
            test_df=dataset_df,
            probabilities=probabilities,
            predicted_labels=predicted_labels,
            predicted_margin=predicted_margin,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
            poisson_probabilities=poisson_probabilities,
            draw_model_probability=draw_model_probability,
        )

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
            "margin_regressor": self.margin_regressor,
            "score_a_regressor": self.score_a_regressor,
            "score_b_regressor": self.score_b_regressor,
            "draw_rate_prior": self.draw_rate_prior,
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
