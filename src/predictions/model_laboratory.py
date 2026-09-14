"""Offline tournament-blocked model comparison and promotion evidence."""

from __future__ import annotations

import hashlib
import json
import math
import random
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.predictions.evaluation_reporting import (
    build_group_metrics,
    build_standardized_evaluation_frame,
)
from src.predictions.match_model_benchmarks import (
    BENCHMARK_METRICS,
    _canonical_games,
    build_frozen_holdout_benchmark,
    build_historical_count_benchmark,
)
from src.predictions.temporal_partitioning import event_aware_partition_groups

DEFAULT_COUNT_CANDIDATES: Mapping[str, tuple[str, bool]] = {
    "cohort_average_poisson": ("poisson", False),
    "historical_hierarchical_poisson": ("poisson", True),
    "historical_hierarchical_negative_binomial": ("negative_binomial", True),
    "historical_hierarchical_bivariate_poisson": ("bivariate_poisson", True),
}

MODEL_FEATURE_GROUPS: Mapping[str, tuple[str, ...]] = {
    "pre_event_strength": (
        "team_a_power_score_final",
        "team_b_power_score_final",
        "team_a_glicko_rd",
        "team_b_glicko_rd",
    ),
    "attack_defence": (
        "team_a_offense_norm",
        "team_b_offense_norm",
        "team_a_defense_norm",
        "team_b_defense_norm",
    ),
    "recent_schedule_load": (
        "team_a_days_since_last_game",
        "team_b_days_since_last_game",
        "team_a_games_last_7_days",
        "team_b_games_last_7_days",
    ),
    "match_duration": ("match_duration_minutes",),
    "playing_format": ("players_per_side",),
    "roster_continuity": (
        "team_a_roster_continuity",
        "team_b_roster_continuity",
    ),
    "event_strength": ("event_strength",),
    "tournament_rest": (
        "team_a_rest_minutes",
        "team_b_rest_minutes",
    ),
}

PROMOTION_PRIMARY_METRICS: tuple[str, ...] = (
    "log_loss",
    "margin_mae",
    "blowout_4plus_brier",
)
DEFAULT_PROMOTION_BASELINE = "historical_hierarchical_poisson"

DEFAULT_NONINFERIORITY_TOLERANCES: Mapping[str, float] = {
    "log_loss": 0.01,
    "brier_score": 0.01,
    "margin_mae": 0.05,
    "blowout_4plus_brier": 0.01,
    "competitive_game_recall": 0.02,
    "competitive_game_precision": 0.02,
}


@dataclass(frozen=True)
class TournamentEvaluationFold:
    fold_id: str
    train_groups: tuple[str, ...]
    test_groups: tuple[str, ...]
    train_start_date: str
    train_end_date: str
    test_start_date: str
    test_end_date: str
    train_games: int
    test_games: int


@dataclass
class ModelLaboratoryResult:
    folds: tuple[TournamentEvaluationFold, ...]
    fold_metrics: pd.DataFrame
    aggregate_metrics: pd.DataFrame
    segment_metrics: pd.DataFrame
    predictions: pd.DataFrame
    failures: tuple[dict[str, Any], ...]


def _validate_dataset(dataset_df: pd.DataFrame) -> pd.DataFrame:
    required = {
        "game_id",
        "game_date",
        "team_a_id",
        "team_b_id",
        "actual_score_a",
        "actual_score_b",
        "actual_margin",
        "actual_outcome",
    }
    missing = sorted(required - set(dataset_df.columns))
    if missing:
        raise ValueError(f"Model laboratory dataset is missing columns: {missing}")
    result = dataset_df.copy()
    result["game_date"] = pd.to_datetime(result["game_date"], errors="raise").dt.normalize()
    return result


def build_feature_coverage_report(dataset_df: pd.DataFrame) -> dict[str, Any]:
    """Expose which current and proposed accuracy features are actually usable."""

    total_rows = int(len(dataset_df))
    groups = []
    for group_name, required_columns in MODEL_FEATURE_GROUPS.items():
        available = [column for column in required_columns if column in dataset_df.columns]
        missing = [column for column in required_columns if column not in dataset_df.columns]
        if available and total_rows:
            coverage_by_column = {
                column: float(dataset_df[column].notna().mean())
                for column in available
            }
            row_coverage = float(
                dataset_df[available].notna().all(axis=1).mean()
            )
        else:
            coverage_by_column = {}
            row_coverage = 0.0
        groups.append(
            {
                "feature_group": group_name,
                "required_columns": list(required_columns),
                "available_columns": available,
                "missing_columns": missing,
                "coverage_by_column": coverage_by_column,
                "complete_row_coverage": row_coverage,
                "ready_for_experiment": not missing and row_coverage >= 0.80,
            }
        )
    return {
        "rows": total_rows,
        "groups": groups,
        "ready_groups": [
            row["feature_group"] for row in groups if row["ready_for_experiment"]
        ],
        "collection_backlog": [
            row["feature_group"] for row in groups if not row["ready_for_experiment"]
        ],
    }


def build_rolling_tournament_folds(
    dataset_df: pd.DataFrame,
    *,
    min_train_groups: int = 8,
    test_group_count: int = 1,
    step_groups: int | None = None,
    min_train_games: int = 100,
    max_folds: int | None = None,
) -> tuple[TournamentEvaluationFold, ...]:
    """Build expanding-window folds while keeping event/date blocks indivisible."""

    if min_train_groups < 1:
        raise ValueError("min_train_groups must be positive")
    if test_group_count < 1:
        raise ValueError("test_group_count must be positive")
    if min_train_games < 1:
        raise ValueError("min_train_games must be positive")
    if max_folds is not None and max_folds < 1:
        raise ValueError("max_folds must be positive when supplied")
    step = test_group_count if step_groups is None else step_groups
    if step < 1:
        raise ValueError("step_groups must be positive")

    frame = _validate_dataset(dataset_df)
    frame["_time_group"] = event_aware_partition_groups(frame)
    group_rows: list[dict[str, Any]] = []
    for group_name, group in frame.groupby("_time_group", sort=False):
        canonical = _canonical_games(group)
        group_rows.append(
            {
                "group": str(group_name),
                "start": pd.Timestamp(group["game_date"].min()),
                "end": pd.Timestamp(group["game_date"].max()),
                "games": int(canonical["game_id"].nunique()),
            }
        )
    ordered = sorted(group_rows, key=lambda row: (row["start"], row["end"], row["group"]))
    folds: list[TournamentEvaluationFold] = []
    for test_start in range(min_train_groups, len(ordered) - test_group_count + 1, step):
        train_rows = ordered[:test_start]
        test_rows = ordered[test_start : test_start + test_group_count]
        train_games = sum(int(row["games"]) for row in train_rows)
        if train_games < min_train_games:
            continue
        train_end = max(row["end"] for row in train_rows)
        test_begin = min(row["start"] for row in test_rows)
        if train_end >= test_begin:
            raise ValueError(
                "Tournament fold is not chronological: "
                f"training ends {train_end.date()} and test begins {test_begin.date()}"
            )
        fold_index = len(folds) + 1
        folds.append(
            TournamentEvaluationFold(
                fold_id=f"fold-{fold_index:03d}",
                train_groups=tuple(str(row["group"]) for row in train_rows),
                test_groups=tuple(str(row["group"]) for row in test_rows),
                train_start_date=min(row["start"] for row in train_rows).date().isoformat(),
                train_end_date=train_end.date().isoformat(),
                test_start_date=test_begin.date().isoformat(),
                test_end_date=max(row["end"] for row in test_rows).date().isoformat(),
                train_games=train_games,
                test_games=sum(int(row["games"]) for row in test_rows),
            )
        )
    if max_folds is not None:
        folds = folds[-max_folds:]
        folds = [
            TournamentEvaluationFold(
                **{**asdict(fold), "fold_id": f"fold-{index:03d}"}
            )
            for index, fold in enumerate(folds, start=1)
        ]
    return tuple(folds)


def _fold_frames(
    dataset_df: pd.DataFrame,
    fold: TournamentEvaluationFold,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = _validate_dataset(dataset_df)
    groups = event_aware_partition_groups(frame)
    train = frame[groups.isin(fold.train_groups)].copy()
    test = _canonical_games(frame[groups.isin(fold.test_groups)].copy())
    if train.empty or test.empty:
        raise ValueError(f"{fold.fold_id} produced an empty training or test frame")
    if pd.Timestamp(train["game_date"].max()) >= pd.Timestamp(test["game_date"].min()):
        raise ValueError(f"{fold.fold_id} violates the exclusive chronological boundary")
    return train, test


def run_count_model_laboratory(
    dataset_df: pd.DataFrame,
    *,
    folds: Sequence[TournamentEvaluationFold] | None = None,
    candidates: Mapping[str, tuple[str, bool]] = DEFAULT_COUNT_CANDIDATES,
    half_life_days: float = 120.0,
    prior_games: float = 6.0,
    min_train_groups: int = 8,
    test_group_count: int = 1,
    min_train_games: int = 100,
    max_folds: int | None = None,
    include_matchbalance_learned: bool = False,
    learned_min_examples: int = 100,
    random_seed: int = 42,
) -> ModelLaboratoryResult:
    """Evaluate count-model challengers on the same untouched tournament folds."""

    frame = _validate_dataset(dataset_df)
    resolved_folds = tuple(folds) if folds is not None else build_rolling_tournament_folds(
        frame,
        min_train_groups=min_train_groups,
        test_group_count=test_group_count,
        min_train_games=min_train_games,
        max_folds=max_folds,
    )
    if not resolved_folds:
        raise ValueError("No eligible rolling tournament folds were available")
    fold_metric_frames: list[pd.DataFrame] = []
    prediction_frames: list[pd.DataFrame] = []
    failures: list[dict[str, Any]] = []
    for fold in resolved_folds:
        train, test = _fold_frames(frame, fold)
        fold_candidates: dict[str, pd.DataFrame] = {}
        for candidate_name, (family, hierarchical) in candidates.items():
            try:
                prediction = build_historical_count_benchmark(
                    train,
                    test,
                    family=family,
                    hierarchical=hierarchical,
                    half_life_days=half_life_days,
                    prior_games=prior_games,
                )
            except Exception as exc:  # keep the entire lab report reviewable
                failures.append(
                    {
                        "fold_id": fold.fold_id,
                        "candidate": candidate_name,
                        "error": str(exc),
                    }
                )
                continue
            prediction = prediction.copy()
            prediction["candidate"] = candidate_name
            prediction["fold_id"] = fold.fold_id
            prediction["test_group"] = ",".join(fold.test_groups)
            fold_candidates[candidate_name] = prediction
            prediction_frames.append(prediction)
        if include_matchbalance_learned:
            try:
                from src.predictions.point_in_time_match_model import (
                    COHERENT_SCORE_DISTRIBUTION_STRATEGY,
                    COMPETITIVE_MATCH_SELECTION_OBJECTIVE,
                    PointInTimeMatchModel,
                )

                with tempfile.TemporaryDirectory(prefix="matchbalance-model-lab-") as model_dir:
                    model = PointInTimeMatchModel(model_dir=model_dir)
                    model.train(
                        train,
                        min_examples=learned_min_examples,
                        probability_strategy=COHERENT_SCORE_DISTRIBUTION_STRATEGY,
                        selection_objective=COMPETITIVE_MATCH_SELECTION_OBJECTIVE,
                        random_state=random_seed + len(fold_metric_frames),
                    )
                    prediction = model.predict_frame(test)
                prediction["candidate"] = "matchbalance_learned"
                prediction["fold_id"] = fold.fold_id
                prediction["test_group"] = ",".join(fold.test_groups)
                fold_candidates["matchbalance_learned"] = prediction
                prediction_frames.append(prediction)
            except Exception as exc:  # an incomplete learned fold must stay visible
                failures.append(
                    {
                        "fold_id": fold.fold_id,
                        "candidate": "matchbalance_learned",
                        "error": str(exc),
                    }
                )
        if fold_candidates:
            metrics = build_frozen_holdout_benchmark(fold_candidates)
            metrics["fold_id"] = fold.fold_id
            metrics["train_end_date"] = fold.train_end_date
            metrics["test_start_date"] = fold.test_start_date
            metrics["test_end_date"] = fold.test_end_date
            fold_metric_frames.append(metrics)

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame()
    )
    fold_metrics = (
        pd.concat(
            [item.dropna(axis=1, how="all") for item in fold_metric_frames],
            ignore_index=True,
        )
        if fold_metric_frames
        else pd.DataFrame()
    )
    aggregate_candidates = {
        candidate: group.copy()
        for candidate, group in predictions.groupby("candidate", sort=True)
    }
    aggregate_metrics = build_frozen_holdout_benchmark(aggregate_candidates)
    segment_metrics = build_candidate_segment_metrics(predictions)
    return ModelLaboratoryResult(
        folds=resolved_folds,
        fold_metrics=fold_metrics,
        aggregate_metrics=aggregate_metrics,
        segment_metrics=segment_metrics,
        predictions=predictions,
        failures=tuple(failures),
    )


def build_candidate_segment_metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    """Score age, gender, and evidence-coverage slices for every candidate."""

    if predictions.empty or "candidate" not in predictions.columns:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    for candidate, candidate_frame in predictions.groupby("candidate", sort=True):
        standardized = build_standardized_evaluation_frame(candidate_frame)
        segment_columns = (
            "age_group",
            "matchup_gender",
            "history_coverage_band",
        )
        for segment_column in segment_columns:
            metrics = build_group_metrics(standardized, segment_column)
            if metrics.empty:
                continue
            metrics = metrics.rename(columns={segment_column: "segment_value"})
            metrics.insert(0, "segment_type", segment_column)
            metrics.insert(0, "candidate", candidate)
            rows.append(metrics)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _bootstrap_mean_interval(
    values: Sequence[float],
    *,
    random_seed: int,
    samples: int = 2000,
) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(random_seed)
    bootstrap_means = [
        float(np.mean([values[rng.randrange(len(values))] for _ in values]))
        for _ in range(samples)
    ]
    return (
        float(np.quantile(bootstrap_means, 0.025)),
        float(np.quantile(bootstrap_means, 0.975)),
    )


def evaluate_candidate_promotion(
    fold_metrics: pd.DataFrame,
    *,
    champion: str,
    challenger: str,
    minimum_folds: int = 3,
    minimum_shared_games: int = 250,
    required_fold_win_rate: float = 0.60,
    required_primary_improvements: int = 2,
    noninferiority_tolerances: Mapping[str, float] = DEFAULT_NONINFERIORITY_TOLERANCES,
    random_seed: int = 42,
    segment_metrics: pd.DataFrame | None = None,
    minimum_segment_games: int = 50,
) -> dict[str, Any]:
    """Return a reviewable gate; this function never changes the active model."""

    required_columns = {"candidate", "fold_id", "shared_examples"}
    missing = sorted(required_columns - set(fold_metrics.columns))
    if missing:
        raise ValueError(f"Fold metrics are missing columns: {missing}")
    champion_rows = fold_metrics[fold_metrics["candidate"] == champion].set_index("fold_id")
    challenger_rows = fold_metrics[fold_metrics["candidate"] == challenger].set_index("fold_id")
    common_folds = sorted(set(champion_rows.index) & set(challenger_rows.index))
    details: dict[str, Any] = {}
    primary_improvements = 0
    noninferior = True
    consistent_primary_wins = 0
    for metric, higher_is_better in BENCHMARK_METRICS:
        if metric not in champion_rows.columns or metric not in challenger_rows.columns:
            continue
        deltas: list[float] = []
        weights: list[float] = []
        for fold_id in common_folds:
            champion_value = pd.to_numeric(champion_rows.loc[fold_id, metric], errors="coerce")
            challenger_value = pd.to_numeric(challenger_rows.loc[fold_id, metric], errors="coerce")
            if pd.isna(champion_value) or pd.isna(challenger_value):
                continue
            improvement = (
                float(challenger_value - champion_value)
                if higher_is_better
                else float(champion_value - challenger_value)
            )
            deltas.append(improvement)
            weights.append(
                float(
                    min(
                        champion_rows.loc[fold_id, "shared_examples"],
                        challenger_rows.loc[fold_id, "shared_examples"],
                    )
                )
            )
        if not deltas:
            continue
        weighted_improvement = float(np.average(deltas, weights=weights))
        fold_win_rate = float(np.mean(np.asarray(deltas) > 0.0))
        lower, upper = _bootstrap_mean_interval(
            deltas,
            random_seed=random_seed + len(details),
        )
        tolerance = float(noninferiority_tolerances.get(metric, 0.0))
        metric_noninferior = weighted_improvement >= -tolerance
        if metric in PROMOTION_PRIMARY_METRICS:
            noninferior = noninferior and metric_noninferior
            if weighted_improvement > 0.0:
                primary_improvements += 1
            if fold_win_rate >= required_fold_win_rate:
                consistent_primary_wins += 1
        details[metric] = {
            "folds": len(deltas),
            "weighted_improvement": weighted_improvement,
            "fold_win_rate": fold_win_rate,
            "bootstrap_95_interval": [lower, upper],
            "noninferiority_tolerance": tolerance,
            "noninferior": metric_noninferior,
        }

    shared_games = int(
        sum(
            min(
                int(champion_rows.loc[fold_id, "shared_examples"]),
                int(challenger_rows.loc[fold_id, "shared_examples"]),
            )
            for fold_id in common_folds
        )
    )
    coverage_complete = (
        set(champion_rows.index) == set(challenger_rows.index)
        and len(common_folds) >= minimum_folds
        and shared_games >= minimum_shared_games
    )
    promote = (
        coverage_complete
        and noninferior
        and primary_improvements >= required_primary_improvements
        and consistent_primary_wins >= required_primary_improvements
    )
    segment_regressions: list[dict[str, Any]] = []
    if segment_metrics is not None and not segment_metrics.empty:
        required_segment_columns = {
            "candidate",
            "segment_type",
            "segment_value",
            "games",
        }
        missing_segment_columns = sorted(
            required_segment_columns - set(segment_metrics.columns)
        )
        if missing_segment_columns:
            raise ValueError(
                f"Segment metrics are missing columns: {missing_segment_columns}"
            )
        segment_keys = ["segment_type", "segment_value"]
        champion_segments = segment_metrics[
            segment_metrics["candidate"] == champion
        ].set_index(segment_keys)
        challenger_segments = segment_metrics[
            segment_metrics["candidate"] == challenger
        ].set_index(segment_keys)
        for segment_key in sorted(
            set(champion_segments.index) & set(challenger_segments.index)
        ):
            champion_segment = champion_segments.loc[segment_key]
            challenger_segment = challenger_segments.loc[segment_key]
            games = min(
                int(champion_segment["games"]),
                int(challenger_segment["games"]),
            )
            if games < minimum_segment_games:
                continue
            for metric in PROMOTION_PRIMARY_METRICS:
                if metric not in champion_segments.columns:
                    continue
                champion_value = pd.to_numeric(champion_segment[metric], errors="coerce")
                challenger_value = pd.to_numeric(challenger_segment[metric], errors="coerce")
                if pd.isna(champion_value) or pd.isna(challenger_value):
                    continue
                regression = float(challenger_value - champion_value)
                tolerance = float(noninferiority_tolerances.get(metric, 0.0))
                if regression > tolerance:
                    segment_regressions.append(
                        {
                            "segment_type": segment_key[0],
                            "segment_value": segment_key[1],
                            "games": games,
                            "metric": metric,
                            "regression": regression,
                            "tolerance": tolerance,
                        }
                    )
        promote = promote and not segment_regressions
    reasons: list[str] = []
    if not coverage_complete:
        reasons.append(
            "Candidate coverage is incomplete or below the required fold/game count."
        )
    if not noninferior:
        reasons.append("At least one primary metric regressed beyond tolerance.")
    if primary_improvements < required_primary_improvements:
        reasons.append("Too few primary metrics improved overall.")
    if consistent_primary_wins < required_primary_improvements:
        reasons.append("Improvements did not repeat across enough tournament folds.")
    if segment_regressions:
        reasons.append("At least one adequately sized age, gender, or history segment regressed.")
    return {
        "decision": "promote" if promote else "hold",
        "champion": champion,
        "challenger": challenger,
        "common_folds": common_folds,
        "shared_games": shared_games,
        "requirements": {
            "minimum_folds": minimum_folds,
            "minimum_shared_games": minimum_shared_games,
            "required_fold_win_rate": required_fold_win_rate,
            "required_primary_improvements": required_primary_improvements,
        },
        "primary_metrics_improved": primary_improvements,
        "primary_metrics_with_consistent_wins": consistent_primary_wins,
        "metrics": details,
        "segment_regressions": segment_regressions,
        "reasons": reasons,
        "automatic_activation": False,
    }


def build_promotion_decisions(
    fold_metrics: pd.DataFrame,
    *,
    promotion_baseline: str = DEFAULT_PROMOTION_BASELINE,
    minimum_folds: int = 3,
    minimum_shared_games: int = 500,
    segment_metrics: pd.DataFrame | None = None,
) -> dict[str, dict[str, Any]]:
    """Evaluate every registrable candidate against one declared baseline."""

    candidates = sorted(fold_metrics.get("candidate", pd.Series(dtype=str)).unique())
    if promotion_baseline not in candidates:
        return {}
    return {
        candidate: evaluate_candidate_promotion(
            fold_metrics,
            champion=promotion_baseline,
            challenger=candidate,
            minimum_folds=minimum_folds,
            minimum_shared_games=minimum_shared_games,
            segment_metrics=segment_metrics,
        )
        for candidate in candidates
        if candidate != promotion_baseline
    }


def dataset_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def report_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def finite_json_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Return records safe for strict JSON manifests."""

    records = frame.replace({np.nan: None, np.inf: None, -np.inf: None}).to_dict(
        orient="records"
    )
    for row in records:
        for key, value in tuple(row.items()):
            if isinstance(value, np.generic):
                row[key] = value.item()
            elif isinstance(value, pd.Timestamp):
                row[key] = value.isoformat()
            elif isinstance(value, float) and not math.isfinite(value):
                row[key] = None
    return records
