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
        }
    )

    return features


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
                "head_to_head_advantage": _to_float(h2h.get("advantage")),
                "head_to_head_games": _to_float(h2h.get("gamesPlayed")),
                "head_to_head_avg_margin": _to_float(h2h.get("avgMargin")),
                "common_opponent_advantage": _to_float(common_opponents.get("advantage")),
                "common_opponent_shared": _to_float(common_opponents.get("sharedOpponents")),
                "common_opponent_compared_games": _to_float(common_opponents.get("comparedGames")),
                "common_opponent_avg_margin_diff": _to_float(common_opponents.get("avgMarginDiff")),
                "common_opponent_points_diff": _to_float(common_opponents.get("pointsPerGameDiff")),
                "common_opponent_reliability": _to_float(common_opponents.get("reliability")),
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
    return DatasetBuildResult(dataset=dataset, summary=summary)


class PointInTimeMatchModel:
    """Train and persist a 3-way point-in-time match model."""

    def __init__(self, model_dir: str = "models/point_in_time_match_predictor"):
        self.model_dir = model_dir
        self.feature_names: List[str] = []
        self.class_labels: List[int] = []
        self.classifier = None
        self.margin_regressor = None
        self.score_a_regressor = None
        self.score_b_regressor = None
        self.training_metadata: Dict[str, object] = {}
        self.last_evaluation_frame = pd.DataFrame()
        os.makedirs(model_dir, exist_ok=True)

    def _feature_columns(self, dataset_df: pd.DataFrame) -> List[str]:
        return [column for column in dataset_df.columns if column not in FEATURE_EXCLUDE_COLUMNS]

    def _build_classifier(self, random_state: int):
        if HAS_XGBOOST:
            return XGBClassifier(
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

    def _build_evaluation_frame(
        self,
        test_df: pd.DataFrame,
        probabilities: np.ndarray,
        predicted_labels: np.ndarray,
        predicted_margin: np.ndarray,
        predicted_score_a: np.ndarray,
        predicted_score_b: np.ndarray,
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

        unique_labels = sorted(np.unique(y_train).tolist())
        if len(unique_labels) < 2:
            raise ValueError(
                "Training data does not contain enough class diversity. "
                f"Observed only outcome labels: {unique_labels}"
            )

        self.class_labels = unique_labels
        label_to_encoded = {label: index for index, label in enumerate(self.class_labels)}
        y_train_encoded = np.array([label_to_encoded[label] for label in y_train], dtype=int)

        self.classifier = self._build_classifier(random_state=random_state)
        self.margin_regressor = self._build_regressor(random_state=random_state)
        self.score_a_regressor = self._build_regressor(random_state=random_state)
        self.score_b_regressor = self._build_regressor(random_state=random_state)

        self.classifier.fit(X_train, y_train_encoded)
        self.margin_regressor.fit(X_train, train_df["actual_margin"].astype(float))
        self.score_a_regressor.fit(X_train, train_df["actual_score_a"].astype(float))
        self.score_b_regressor.fit(X_train, train_df["actual_score_b"].astype(float))

        encoded_probabilities = self.classifier.predict_proba(X_test)
        probabilities = self._normalize_probabilities(self._expand_class_probabilities(encoded_probabilities))
        predicted_labels = np.argmax(probabilities, axis=1)
        predicted_margin = self.margin_regressor.predict(X_test)
        predicted_score_a = self.score_a_regressor.predict(X_test)
        predicted_score_b = self.score_b_regressor.predict(X_test)
        self.last_evaluation_frame = self._build_evaluation_frame(
            test_df=test_df,
            probabilities=probabilities,
            predicted_labels=predicted_labels,
            predicted_margin=predicted_margin,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
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
            "margin_mae": float(mean_absolute_error(test_df["actual_margin"], predicted_margin)),
            "margin_rmse": float(math.sqrt(mean_squared_error(test_df["actual_margin"], predicted_margin))),
            "score_a_mae": float(mean_absolute_error(test_df["actual_score_a"], predicted_score_a)),
            "score_b_mae": float(mean_absolute_error(test_df["actual_score_b"], predicted_score_b)),
            "train_examples": int(len(train_df)),
            "test_examples": int(len(test_df)),
            "class_labels": [OUTCOME_LABELS[label] for label in self.class_labels],
            "feature_count": int(len(self.feature_names)),
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
        model.margin_regressor = payload["margin_regressor"]
        model.score_a_regressor = payload["score_a_regressor"]
        model.score_b_regressor = payload["score_b_regressor"]
        model.feature_names = payload["feature_names"]
        model.class_labels = payload["class_labels"]
        model.training_metadata = payload.get("training_metadata", {})
        return model

    def predict_frame(self, dataset_df: pd.DataFrame) -> pd.DataFrame:
        if self.classifier is None:
            raise ValueError("Model has not been trained or loaded")
        matrix = self._prepare_matrix(dataset_df)
        encoded_probabilities = self.classifier.predict_proba(matrix)
        probabilities = self._normalize_probabilities(self._expand_class_probabilities(encoded_probabilities))
        predicted_labels = np.argmax(probabilities, axis=1)
        predicted_margin = self.margin_regressor.predict(matrix)
        predicted_score_a = self.score_a_regressor.predict(matrix)
        predicted_score_b = self.score_b_regressor.predict(matrix)
        return self._build_evaluation_frame(
            test_df=dataset_df,
            probabilities=probabilities,
            predicted_labels=predicted_labels,
            predicted_margin=predicted_margin,
            predicted_score_a=predicted_score_a,
            predicted_score_b=predicted_score_b,
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
            "margin_regressor": self.margin_regressor,
            "score_a_regressor": self.score_a_regressor,
            "score_b_regressor": self.score_b_regressor,
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
