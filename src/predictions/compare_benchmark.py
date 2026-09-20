"""Offline calibration experiments on frozen, demonstrably pre-game forecasts."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.evaluate_prospective_match_predictions import _extract_prediction_payload, _safe_json
from src.predictions.evaluation_reporting import (
    OUTCOME_ORDER,
    PROBABILITY_COLUMNS,
    build_group_metrics,
    compute_evaluation_summary,
    outcome_log_losses,
    write_evaluation_bundle,
)


@dataclass(frozen=True)
class BenchmarkConfig:
    model_version: str
    train_end: str
    test_start: str
    test_end: str
    temperatures: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
    minimum_games: int = 200
    minimum_events: int = 3
    bootstrap_samples: int = 1000
    seed: int = 20260920

    def validate(self) -> None:
        if not self.model_version.strip():
            raise ValueError("Specify one source model version; versions cannot be pooled.")
        train_end, test_start, test_end = (
            _calendar_date(value) for value in (self.train_end, self.test_start, self.test_end)
        )
        if not train_end < test_start <= test_end:
            raise ValueError("Training must end before the test window starts.")
        if not self.temperatures or any(not _finite(t) or t <= 0 for t in self.temperatures):
            raise ValueError("Temperatures must be finite and positive.")
        if self.minimum_games < 1 or self.minimum_events < 2 or self.bootstrap_samples < 100:
            raise ValueError("Require positive game coverage, at least two events, and at least 100 resamples.")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _calendar_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("Game and split dates must use YYYY-MM-DD.")
    return parsed


def _gender(value: Any) -> str:
    return {"m": "Male", "male": "Male", "b": "Male", "boys": "Male",
            "f": "Female", "female": "Female", "g": "Female", "girls": "Female"}.get(str(value).lower(), "unknown")


def _metadata(row: dict, payload: dict) -> dict:
    context = _safe_json(payload.get("shadowContext"))
    teams = [_safe_json(context.get(key)) for key in ("teamAInput", "teamBInput")]
    ages = [team.get("age") for team in teams]
    games = [team.get("games_played") for team in teams]
    scores = [team.get("power_score_final") for team in teams]
    fixture = _safe_json(row.get("fixture_payload"))
    home = _safe_json(fixture.get("home_row"))
    gender = _gender(home.get("gender"))
    gap = abs(scores[0] - scores[1]) if all(_finite(score) for score in scores) else None
    history = "unknown" if not all(_finite(count) and count >= 0 for count in games) else (
        "under_12_games" if min(games) < 12 else "12_plus_games"
    )
    return {
        "gender": gender,
        "cohort": f"{str(home.get('age_group') or 'unknown').lower()}|{gender}",
        "history_band": history,
        "age_pair": "unknown" if not all(_finite(age) and age > 0 for age in ages) else (
            "same_age" if ages[0] == ages[1] else "cross_age"
        ),
        "power_gap_band": "unknown" if gap is None else (
            "under_0.05" if gap < 0.05 else "0.05_to_0.15" if gap < 0.15 else "0.15_plus"
        ),
    }


def _frozen_teams_match(row: dict, payload: dict) -> bool:
    response = _safe_json(payload.get("response"))
    context = _safe_json(payload.get("shadowContext"))
    identities = []
    for team_key, aliases_key, fixture_key in (
        ("teamA", "resolvedTeamAIds", "home_team_master_id"),
        ("teamB", "resolvedTeamBIds", "away_team_master_id"),
    ):
        primary = _safe_json(response.get(team_key)).get("team_id_master")
        aliases = context.get(aliases_key, [])
        if not isinstance(primary, str) or not primary or not isinstance(aliases, list):
            return False
        if not all(isinstance(alias, str) and alias for alias in aliases):
            return False
        known_ids = {primary, *aliases}
        if row.get(fixture_key) not in known_ids:
            return False
        identities.append(known_ids)
    return identities[0].isdisjoint(identities[1])


def prepare_forecasts(rows: list[dict], model_version: str) -> tuple[pd.DataFrame, dict]:
    """Reject unverifiable records instead of filling missing predictions with guesses."""
    rejected: Counter = Counter()
    eligible = []
    versions = Counter(str(row.get("heuristic_model_version") or "missing") for row in rows)
    for row in rows:
        reason = None
        payload = _safe_json(row.get("heuristic_prediction"))
        prediction = _safe_json(_safe_json(payload.get("response")).get("prediction"))
        version = row.get("heuristic_model_version")
        if version != model_version:
            reason = "other_model_version"
        elif row.get("evaluation_status") != "settled" or row.get("heuristic_prediction_status") != "completed":
            reason = "not_completed_and_settled"
        elif payload.get("modelVersion") != version:
            reason = "conflicting_or_missing_payload_version"
        elif _safe_json(payload.get("shadowContext")).get("predictorVersion") != version:
            reason = "conflicting_or_missing_predictor_version"
        elif not row.get("actual_game_id") or not row.get("fixture_key") or not row.get("source_event_id"):
            reason = "missing_game_fixture_or_event_identity"
        elif not _frozen_teams_match(row, payload):
            reason = "conflicting_or_missing_prediction_team_identity"
        if reason:
            rejected[reason] += 1
            continue
        try:
            played = _calendar_date(row["game_date"])
            predicted_at = datetime.fromisoformat(row["heuristic_predicted_at"].replace("Z", "+00:00"))
            if predicted_at.tzinfo is None or predicted_at.utcoffset() is None:
                raise ValueError("Missing timezone")
            if predicted_at.astimezone(timezone.utc).date() >= played:
                rejected["not_proven_before_game_day"] += 1
                continue
        except (KeyError, ValueError, TypeError, AttributeError):
            rejected["invalid_prediction_or_game_timestamp"] += 1
            continue
        scores = [row.get(key) for key in ("actual_home_score", "actual_away_score")]
        probabilities = [prediction.get(key) for key in ("winProbabilityA", "drawProbability", "winProbabilityB")]
        risk = prediction.get("blowout4PlusProbability", prediction.get("blowoutProbability4Plus"))
        if not all(_finite(score) and score >= 0 and int(score) == score for score in scores):
            reason = "invalid_actual_scores"
        elif not all(_finite(p) and 0 <= p <= 1 for p in probabilities) or abs(sum(probabilities) - 1) > 1e-6:
            reason = "invalid_outcome_probabilities"
        elif prediction.get("predictedWinner") not in OUTCOME_ORDER or not _finite(prediction.get("expectedMargin")):
            reason = "missing_outcome_or_margin"
        elif risk is not None and (not _finite(risk) or not 0 <= risk <= 1):
            reason = "invalid_four_goal_probability"
        if reason:
            rejected[reason] += 1
            continue
        extracted = _extract_prediction_payload(row, "heuristic")
        # Remove harmless serialization rounding once, so every metric and
        # paired comparison consumes the same normalized probability vector.
        for column, probability in zip(PROBABILITY_COLUMNS.values(), probabilities):
            extracted[column] = probability / sum(probabilities)
        if row.get("actual_outcome") not in (None, extracted["actual_outcome"]):
            rejected["conflicting_actual_outcome"] += 1
            continue
        extracted.update(_metadata(row, payload))
        extracted["event_group"] = f"{row.get('provider_code') or 'unknown'}:{row['source_event_id']}"
        extracted["predicted_at"] = predicted_at.astimezone(timezone.utc).isoformat()
        eligible.append(extracted)
    # A game's earliest eligible frozen forecast is one observation, even if the
    # same result was captured through several provider fixture keys.
    frame = pd.DataFrame(eligible)
    if not frame.empty:
        frame = frame.sort_values(["predicted_at", "fixture_key"], kind="stable")
        before = len(frame)
        frame = frame.drop_duplicates("actual_game_id", keep="first").reset_index(drop=True)
        rejected["duplicate_actual_game"] += before - len(frame)
    return frame, {"input_rows": len(rows), "source_versions": dict(sorted(versions.items())),
                   "eligible_rows": len(frame), "excluded": dict(sorted(rejected.items()))}


def split_events(frame: pd.DataFrame, config: BenchmarkConfig) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    if frame.empty:
        return frame.copy(), frame.copy(), []
    train = frame[frame["game_date"] <= config.train_end].copy()
    test = frame[frame["game_date"].between(config.test_start, config.test_end)].copy()
    # Never train on an early round of an event and test on that event's later rounds.
    overlap = sorted(set(train["event_group"]) & set(test["event_group"]))
    return (train[~train["event_group"].isin(overlap)].copy(),
            test[~test["event_group"].isin(overlap)].copy(), overlap)


def apply_temperature(frame: pd.DataFrame, temperature: float) -> pd.DataFrame:
    if not _finite(temperature) or temperature <= 0:
        raise ValueError("Temperature must be finite and positive.")
    result = frame.copy(deep=True)
    if frame.empty or temperature == 1:
        return result
    probabilities = frame[list(PROBABILITY_COLUMNS.values())].to_numpy(dtype=float)
    # One scalar treats A/B identically. Outcome policy, goal margins and blowout
    # probabilities stay frozen; this tests probability calibration alone.
    logits = np.log(np.clip(probabilities, 1e-15, 1)) / temperature
    weights = np.exp(logits - logits.max(axis=1, keepdims=True))
    result[list(PROBABILITY_COLUMNS.values())] = weights / weights.sum(axis=1, keepdims=True)
    return result


def select_temperature(train: pd.DataFrame, temperatures: tuple[float, ...]) -> tuple[float, list[dict]]:
    if train.empty:
        raise ValueError("No development forecasts available.")
    candidates = []
    for temperature in sorted(set(temperatures) | {1.0}):
        summary = compute_evaluation_summary(apply_temperature(train, temperature))
        candidates.append({"temperature": temperature, "development_log_loss": summary["log_loss"]})
    selected = min(candidates, key=lambda item: (
        item["development_log_loss"], abs(math.log(item["temperature"])), item["temperature"]
    ))
    return selected["temperature"], candidates


def paired_event_interval(baseline: pd.DataFrame, candidate: pd.DataFrame, *, samples: int, seed: int) -> list[float]:
    if not baseline["actual_game_id"].equals(candidate["actual_game_id"]):
        raise ValueError("Paired comparisons require identical games in identical order.")
    differences = pd.DataFrame({"event": baseline["event_group"].to_numpy(),
                                "delta": outcome_log_losses(candidate) - outcome_log_losses(baseline)})
    groups = differences.groupby("event")["delta"].agg(["sum", "count"])
    if len(groups) < 2:
        raise ValueError("At least two independent events are required.")
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(groups), size=(samples, len(groups)))
    means = groups["sum"].to_numpy()[draws].sum(axis=1) / groups["count"].to_numpy()[draws].sum(axis=1)
    return [float(value) for value in np.quantile(means, [0.025, 0.975])]


def _coverage(frame: pd.DataFrame) -> dict:
    return {"games": len(frame), "events": int(frame["event_group"].nunique()) if not frame.empty else 0,
            "first_game": frame["game_date"].min() if not frame.empty else None,
            "last_game": frame["game_date"].max() if not frame.empty else None,
            "four_goal_probability_games": (
                int(frame["blowout_4plus_probability"].notna().sum()) if not frame.empty else 0
            )}


def run_benchmark(rows: list[dict], config: BenchmarkConfig, output_dir: Path, *, current_model_version: str) -> dict:
    config.validate()
    # Never overwrite a completed experiment after its holdout has been inspected.
    output_dir.mkdir(parents=True, exist_ok=False)
    frame, inventory = prepare_forecasts(rows, config.model_version)
    train, test, overlap = split_events(frame, config)
    report = {
        "schema_version": 1, "config": asdict(config), "current_model_version": current_model_version,
        "input_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True, allow_nan=False).encode()).hexdigest(),
        "inventory": inventory, "development": _coverage(train), "holdout": _coverage(test),
        "excluded_overlapping_events": overlap, "production_changed": False,
        "experiment": "Frozen-output temperature calibration; outcome decisions, margins and risk unchanged.",
        "limitations": ["Same-day forecasts are excluded because kickoff times are not stored.",
                        "Missing four-goal probabilities are unavailable evidence, not zero risk.",
                        "This is not a replay of the current predictor on historical inputs.",
                        "Repeated experiments on this holdout require a new untouched test set before release."],
    }
    if not frame.empty:
        write_evaluation_bundle(frame, output_dir, prefix="source")
    blockers = []
    for label, part in (("development", train), ("holdout", test)):
        coverage = _coverage(part)
        if coverage["games"] < config.minimum_games or coverage["events"] < config.minimum_events:
            blockers.append(f"Insufficient {label} coverage: {coverage['games']} games / {coverage['events']} events.")
    if blockers:
        report.update(status="insufficient_data", blockers=blockers)
    else:
        temperature, candidates = select_temperature(train, config.temperatures)
        candidate = apply_temperature(test, temperature)
        baseline_summary = write_evaluation_bundle(test, output_dir, prefix="holdout_baseline")
        candidate_summary = write_evaluation_bundle(candidate, output_dir, prefix="holdout_candidate")
        interval = paired_event_interval(test, candidate, samples=config.bootstrap_samples, seed=config.seed)
        improved = interval[1] < 0 and candidate_summary["brier_score"] < baseline_summary["brier_score"]
        report.update(selected_temperature=temperature, development_candidates=candidates,
                      baseline=baseline_summary, candidate=candidate_summary,
                      log_loss_delta_interval_95=interval, candidate_improves_holdout=bool(improved))
        for group in ("cohort", "gender", "age_pair", "history_band", "power_gap_band", "event_group"):
            for name, part in (("baseline", test), ("candidate", candidate)):
                build_group_metrics(part, group).to_csv(output_dir / f"holdout_{name}_by_{group}.csv", index=False)
        if config.model_version != current_model_version:
            blockers.append("Historical source version differs from the current Compare predictor.")
        if _coverage(test)["four_goal_probability_games"] < len(test):
            blockers.append("Holdout does not contain complete four-goal risk forecasts.")
        if not improved:
            blockers.append("No supported improvement in holdout probability scores.")
        report.update(status="candidate_for_shadow_validation" if not blockers else "research_only", blockers=blockers)
    (output_dir / "benchmark.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    text = ["# Compare calibration benchmark", "", f"Status: {report['status']}",
            f"Source model: {config.model_version}. Current model: {current_model_version}.",
            f"Development: {len(train)} games. Holdout: {len(test)} games.",
            f"Four-goal risk coverage in holdout: {report['holdout']['four_goal_probability_games']}/{len(test)}.",
            "Production predictions were not changed.", ""]
    if "selected_temperature" in report:
        text.extend([f"Selected temperature (development only): {report['selected_temperature']}",
                     f"Holdout log loss: {report['baseline']['log_loss']:.6f} -> {report['candidate']['log_loss']:.6f}",
                     f"Holdout Brier score: {report['baseline']['brier_score']:.6f} -> "
                     f"{report['candidate']['brier_score']:.6f}",
                     f"95% event-resampled log-loss delta interval: {report['log_loss_delta_interval_95']}", ""])
    text.extend(f"- {item}" for item in blockers + report["limitations"])
    (output_dir / "benchmark.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return report
