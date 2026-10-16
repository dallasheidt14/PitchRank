"""Offline scorecard for genuinely pre-event MatchBalance predictions.

This evaluates observed matches, never synthetic matchups from proposed tiers.
It does not approve a candidate for release or fit model constants.
"""
from __future__ import annotations

import math
import random
from datetime import date
from statistics import mean

from src.tournaments.seeding_validation_inputs import frozen_validation_inputs, validate_frozen_row

__all__ = ["frozen_validation_inputs", "scorecard"]


def scorecard(records: list[dict], *, baseline: str, confirmation: bool = False) -> dict:
    if not records:
        return {"status": "insufficient_evidence", "games": 0,
                "reason": "No eligible frozen pre-event comparisons were supplied."}
    models = set(records[0]["predictions"])
    if baseline not in models:
        raise ValueError("Baseline predictions are required")
    seen = set()
    cohort_freezes = {}
    for row in records:
        if row["game_id"] in seen:
            raise ValueError("Duplicate observed game")
        seen.add(row["game_id"])
        if set(row["predictions"]) != models:
            raise ValueError("Models must be compared on exactly the same observed games")
        cutoff = date.fromisoformat(row["cutoff"])
        if cutoff >= date.fromisoformat(row["game_date"]):
            raise ValueError("Outcome must occur after the frozen input cutoff")
        manifest = row["input_manifest"]
        for field in ("ratings_available_date", "history_max_date", "calibration_available_date"):
            if date.fromisoformat(manifest[field]) > cutoff:
                raise ValueError(f"Post-cutoff input: {field}")
        for model, (cohort, digest) in validate_frozen_row(row, models, cutoff).items():
            key = (row["event_id"], cohort, model)
            if cohort_freezes.setdefault(key, digest) != digest:
                raise ValueError("One event cohort must use a consistent frozen candidate across observed games")
        if not row.get("event_id") or not row.get("team_a") or not row.get("team_b"):
            raise ValueError("Team and event cluster identities are required")
        if row["team_a"] == row["team_b"]:
            raise ValueError("An observed game needs two distinct teams")
        for prediction in row["predictions"].values():
            if any(isinstance(prediction.get(key), bool) or not isinstance(prediction.get(key), int)
                   or prediction[key] < 1 for key in ("seed_a", "seed_b")):
                raise ValueError("Each candidate needs the actual frozen cohort seeds for both teams")
            probs = prediction["probabilities"]
            if (len(probs) != 3 or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs)
                    or abs(sum(probs) - 1) > 1e-6):
                raise ValueError("Invalid three-way probabilities")
            if not math.isfinite(prediction["margin"]) or not 0 <= prediction["blowout_probability"] <= 1:
                raise ValueError("Invalid matchup risk")
        if not math.isfinite(row["actual_margin"]) or int(row["actual_margin"]) != row["actual_margin"]:
            raise ValueError("Invalid observed margin")
        if confirmation and row.get("previously_examined", True):
            raise ValueError("Confirmation must use previously untouched events")
    metrics = {model: [_metrics(row, model) for row in records] for model in sorted(models)}
    summaries = {model: {key: mean(item[key] for item in rows) for key in rows[0]}
                 for model, rows in metrics.items()}
    for model in summaries:
        severe = [row for row in records if abs(row["actual_margin"]) >= 4]
        summaries[model]["severe_mismatch_recall_at_30_percent"] = (
            mean(row["predictions"][model]["blowout_probability"] >= 0.30 for row in severe) if severe else None
        )
        summaries[model]["risk_calibration"] = [
            {"risk_band": [low, high], "games": len(group),
             "predicted": mean(item["predicted_severe_rate"] for item in group),
             "observed": mean(item["observed_severe_rate"] for item in group)}
            for low, high in ((0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 1.000001))
            if (group := [item for item in metrics[model] if low <= item["predicted_severe_rate"] < high])
        ]
    subgroups = {}
    for label in ("limited_history", "playing_up", "age_group", "gender"):
        known = [row for row in records if row.get(label) is not None]
        groups = {str(row[label]) for row in known}
        subgroups[label] = {"classified_games": len(known), "unclassified_games": len(records)-len(known),
                           "groups": {value: {model: {
                               metric: mean(metrics[model][i][metric] for i, row in enumerate(records)
                                            if row.get(label) is not None and str(row[label]) == value)
                               for metric in ("seed_order_agreement_half_credit_ties", "brier", "margin_mae",
                                              "severe_mismatch_brier")
                           } for model in sorted(models)} for value in sorted(groups)}}
    comparison_metrics = ("brier", "seed_order_agreement_half_credit_ties", "direction_agreement_half_credit_ties",
                          "margin_mae", "severe_mismatch_brier")
    differences = {(model, metric): [candidate[metric] - control[metric]
                                    for candidate, control in zip(metrics[model], metrics[baseline])]
                   for model in sorted(models - {baseline}) for metric in comparison_metrics}
    intervals = _cluster_intervals(records, differences, comparisons=len(models)-1)
    comparisons = {}
    for model in sorted(models - {baseline}):
        comparisons[model] = {"brier_delta": mean(differences[model, "brier"]),
                              "cluster_interval": intervals[model, "brier"]}
        for metric in comparison_metrics[1:]:
            comparisons[model][metric] = {"delta": mean(differences[model, metric]),
                                          "cluster_interval": intervals[model, metric]}
    return {"status": "measured_confirmation" if confirmation else "measured_screening",
            "games": len(records), "events": len({row["event_id"] for row in records}),
            "models": summaries, "comparisons": comparisons, "subgroups": subgroups,
            "limitation": "Observed prediction accuracy only; alternative tier benefits remain projected. "
                          "A screening result does not authorize changing the default model."}


def _metrics(row, model):
    prediction = row["predictions"][model]
    probabilities = prediction["probabilities"]  # A win, draw, B win
    actual = row["actual_margin"]
    outcome = 0 if actual > 0 else 2 if actual < 0 else 1
    direction = prediction["margin"]
    credit = 0.5 if direction == 0 or actual == 0 else float(direction * actual > 0)
    seed_direction = prediction["seed_b"] - prediction["seed_a"]
    seed_credit = 0.5 if seed_direction == 0 or actual == 0 else float(seed_direction * actual > 0)
    risk = prediction["blowout_probability"]
    return {"direction_agreement_half_credit_ties": credit, "seed_order_agreement_half_credit_ties": seed_credit,
            "brier": sum((p - int(index == outcome)) ** 2 for index, p in enumerate(probabilities)),
            "log_loss": -math.log(max(probabilities[outcome], 1e-15)),
            "margin_mae": abs(direction - actual),
            "severe_mismatch_brier": (risk - int(abs(actual) >= 4)) ** 2,
            "predicted_severe_rate": risk, "observed_severe_rate": float(abs(actual) >= 4)}


def _cluster_intervals(records, differences, *, comparisons=1):
    if not differences:
        return {}
    events = sorted({row["event_id"] for row in records})
    teams = sorted({row[key] for row in records for key in ("team_a", "team_b")})
    if len(events) < 5 or len(teams) < 20:
        return {key: {"status": "insufficient_clusters", "interval_95": None} for key in differences}
    # Pigeonhole bootstrap: shared teams and events share weights. This avoids
    # pretending every game is an independent observation. It is approximate.
    rng = random.Random(20261016)
    estimates = {key: [] for key in differences}
    for _ in range(2000):
        ew = {event: 0 for event in events}
        tw = {team: 0 for team in teams}
        for event in rng.choices(events, k=len(events)):
            ew[event] += 1
        for team in rng.choices(teams, k=len(teams)):
            tw[team] += 1
        weights = [ew[row["event_id"]] * tw[row["team_a"]] * tw[row["team_b"]] for row in records]
        total = sum(weights)
        if total:
            for key, values in differences.items():
                estimates[key].append(sum(w * d for w, d in zip(weights, values)) / total)
    return {key: _interval_summary(values, comparisons) for key, values in estimates.items()}


def _interval_summary(estimates, comparisons):
    if len(estimates) < 1000:
        return {"status": "insufficient_resamples", "interval_95": None}
    estimates.sort()
    alpha = 0.05 / max(1, comparisons)
    return {"status": "approximate_team_event_bootstrap", "resamples": len(estimates),
            "interval_95": [estimates[int(len(estimates) * 0.025)], estimates[int(len(estimates) * 0.975)]],
            "family_adjusted_interval": [estimates[int(len(estimates) * alpha / 2)],
                                         estimates[min(len(estimates)-1, int(len(estimates) * (1-alpha/2)))]],
            "adjustment": "Bonferroni across candidate models", "candidate_comparisons": comparisons}
