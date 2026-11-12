"""Offline Compare research. No database writes or production predictor imports."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import subprocess
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.predictions.compare_benchmark import paired_event_interval
from src.predictions.evaluation_reporting import compute_evaluation_summary
from src.predictions.form_policy import (
    CALIBRATION_ROLES,
    FORM_CANDIDATES,
    FORM_HISTORY_SIZE,
    FORM_OPPONENT_CAP,
    FORM_RESIDUAL_CLIP,
    INPUT_ROLES,
    PINNED_REVISION,
    ResearchPolicy,
)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing availability timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Availability timestamps require timezones")
    return parsed.astimezone(timezone.utc)


def match_start(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), timezone.utc)


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def expectation_payload(expected: dict) -> dict:
    payload = {
        key: expected.get(key)
        for key in (
            "source_game_id",
            "game_date",
            "home_team_master_id",
            "away_team_master_id",
            "expected_home_margin",
            "source",
            "model_signature",
        )
    }
    if expected.get("source") == "reconstructed":
        payload["reconstruction_sha256"] = expected.get("reconstruction_sha256")
    return payload


def valid_expectation(expected: dict, game: dict) -> bool:
    identity = {
        "source_game_id": game.get("source_game_id") or game["id"],
        "game_date": game["game_date"],
        "home_team_master_id": game["home_team_master_id"],
        "away_team_master_id": game["away_team_master_id"],
    }
    return (
        all(expected.get(k) == v for k, v in identity.items())
        and bool(expected.get("model_signature"))
        and expected.get("source") in {"frozen", "reconstructed"}
        and finite(expected.get("expected_home_margin"))
        and (
            reconstruction_error(expected) is None
            if expected.get("source") == "reconstructed"
            else provenance_error(expected.get("provenance", {}), game["game_date"]) is None
        )
        and expected["provenance"].get("sha256") == digest(expectation_payload(expected))
    )


def provenance_error(provenance: dict, game_date: str) -> str | None:
    """Strict research gate; a historical date alone does not prove availability."""
    try:
        cutoff = match_start(game_date)
        if (
            not isinstance(provenance.get("sha256"), str)
            or len(provenance["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in provenance["sha256"])
            or not provenance.get("code_revision")
        ):
            return "missing_input_identity"
        if timestamp(provenance.get("created_at")) >= cutoff:
            return "created_after_cutoff"
        if timestamp(provenance.get("last_calculated")) >= cutoff:
            return "calculated_after_cutoff"
        if match_start(provenance["snapshot_date"]) >= cutoff:
            return "snapshot_not_before_match_day"
        if provenance.get("uses_learned_inputs", True):
            if timestamp(provenance.get("trained_at")) >= cutoff:
                return "trained_after_cutoff"
            if match_start(provenance["training_cutoff"]) >= cutoff:
                return "training_crosses_cutoff"
    except (ValueError, TypeError, KeyError):
        return "missing_or_invalid_provenance"
    return None


def prediction_input_error(case: dict, day: str) -> str | None:
    reference = match_start(day)
    if "reference_time" in case:
        try:
            reference = timestamp(case["reference_time"])
            if reference >= match_start(day):
                return "reference_time_after_cutoff"
        except (TypeError, ValueError):
            return "invalid_reference_time"
    fixture = case.get("fixture", {})
    if (not fixture.get("home_team_master_id") or not fixture.get("away_team_master_id")
            or fixture["home_team_master_id"] == fixture["away_team_master_id"]
            or case.get("teamA", {}).get("team_id_master") != fixture["home_team_master_id"]
            or case.get("teamB", {}).get("team_id_master") != fixture["away_team_master_id"]):
        return "invalid_target_orientation"
    if case.get("predictor_revision") != PINNED_REVISION:
        return "wrong_predictor_revision"
    descriptors = case.get("input_provenance", [])
    if len(descriptors) != len(INPUT_ROLES) or {p.get("role") for p in descriptors} != INPUT_ROLES:
        return "missing_input_provenance"
    payloads = {
        "team_a_snapshot": case.get("teamA"),
        "team_b_snapshot": case.get("teamB"),
        **{role: case.get("calibrations", {}).get(file) for role, file in CALIBRATION_ROLES.items()},
    }
    for provenance in descriptors:
        reason = provenance_error(provenance, day)
        if reason:
            return reason
        fields = ("created_at", "last_calculated", "trained_at") if provenance.get("uses_learned_inputs", True) else (
            "created_at", "last_calculated",
        )
        if any(timestamp(provenance[field]) > reference for field in fields):
            return "input_after_reference_time"
        payload = payloads[provenance["role"]]
        if payload is None or provenance["sha256"] != digest(payload):
            return "input_hash_mismatch"
    for game in case.get("games", []):
        if game["game_date"] >= day:
            return "future_or_same_day_history"
        try:
            if timestamp(game.get("result_available_at")) >= match_start(day):
                return "history_result_unavailable_at_cutoff"
            if timestamp(game["result_available_at"]) > reference:
                return "history_result_after_reference_time"
        except (TypeError, ValueError):
            return "missing_history_result_provenance"
        result_payload = {k: game.get(k) for k in (
            "id", "game_date", "home_team_master_id", "away_team_master_id", "home_score", "away_score",
            "result_available_at",
        )}
        if game.get("result_sha256") != digest(result_payload):
            return "history_result_hash_mismatch"
        if game.get("ml_overperformance") is not None:
            learned = game.get("ml_provenance", {})
            reason = provenance_error(learned, day)
            if reason:
                return reason
            if any(timestamp(learned[field]) > reference for field in ("created_at", "last_calculated", "trained_at")
                   if field != "trained_at" or learned.get("uses_learned_inputs", True)):
                return "history_learned_value_after_reference_time"
            if learned["sha256"] != digest({"id": game["id"], "ml_overperformance": game["ml_overperformance"]}):
                return "history_learned_value_hash_mismatch"
    return None


def replay_reference_time(case: dict) -> str:
    value = (timestamp(case["reference_time"]) if case.get("reference_time") else
             match_start(case["fixture"]["game_date"]) - timedelta(milliseconds=1))
    return value.isoformat(timespec="milliseconds")


def reconstruction_inputs(case: dict) -> dict:
    return deepcopy({
        "reference_time": replay_reference_time(case),
        "fixture": {key: case["fixture"][key] for key in (
            "source_game_id", "game_date", "home_team_master_id", "away_team_master_id",
        )},
        **{key: case[key] for key in (
            "predictor_revision", "teamA", "teamB", "games", "calibrations", "input_provenance",
        )},
    })


@lru_cache(maxsize=1)
def _pinned_source_identity() -> tuple:
    root = Path(__file__).resolve().parents[2]

    def source(name):
        return subprocess.check_output(
            ["git", "show", f"{PINNED_REVISION}:frontend/lib/{name}"], cwd=root, encoding="utf-8", timeout=15
        ).replace("\r\n", "\n")

    declaration = re.search(r"const files = \[(.*?)\];", source("prospectiveCapture.ts"), re.S)
    if declaration is None:
        raise ValueError("Pinned collector module list is unavailable")
    names = re.findall(r"'([A-Za-z0-9]+\.ts)'", declaration[1])
    if not names or len(names) != len(set(names)):
        raise ValueError("Invalid pinned collector module list")
    pairs = [[name, source(name)] for name in names]
    return digest(pairs), tuple((name, hashlib.sha256(contents.encode()).hexdigest()) for name, contents in pairs)


def pinned_source_identity() -> dict:
    algorithm_hash, hashes = _pinned_source_identity()
    return {"algorithm_hash": algorithm_hash, "source_hashes": dict(hashes)}


def reconstruction_error(expected: dict) -> str | None:
    try:
        receipt = expected["reconstruction"]
        inputs, prediction = receipt["inputs"], receipt["prediction"]
        fixture = inputs["fixture"]
        if receipt.get("schema_version") != 1 or receipt.get("predictor_revision") != PINNED_REVISION:
            return "wrong_reconstruction_revision"
        if not receipt.get("aa_parity") or any(receipt.get(k) != v for k, v in pinned_source_identity().items()):
            return "unverified_reconstruction_runner"
        if expected["reconstruction_sha256"] != digest(receipt) or receipt["inputs_sha256"] != digest(inputs):
            return "reconstruction_hash_mismatch"
        if receipt["prediction_sha256"] != digest(prediction):
            return "reconstruction_prediction_hash_mismatch"
        if timestamp(inputs["reference_time"]) >= match_start(fixture["game_date"]):
            return "reconstruction_reference_after_cutoff"
        signature_payload = receipt["model_signature_payload"]
        signature_keys = {
            "ageGroups": "age_group_parameters.json", "probability": "probability_parameters.json",
            "margin": "margin_parameters_v2.json", "outcome": "heuristic_outcome_calibration.json",
            "confidence": "confidence_parameters_v2.json",
        }
        if (json.loads(signature_payload) != {
                "algorithm": receipt["algorithm_hash"],
                "calibration": {key: inputs["calibrations"][file] for key, file in signature_keys.items()},
            } or hashlib.sha256(signature_payload.encode()).hexdigest() != receipt["model_signature"]):
            return "reconstruction_signature_payload_mismatch"
        if any(expected.get(k) != fixture.get(k) for k in (
            "source_game_id", "game_date", "home_team_master_id", "away_team_master_id",
        )):
            return "reconstruction_fixture_mismatch"
        if (inputs["teamA"]["team_id_master"] != fixture["home_team_master_id"]
                or inputs["teamB"]["team_id_master"] != fixture["away_team_master_id"]):
            return "reconstruction_orientation_mismatch"
        provenance = expected["provenance"]
        computed = timestamp(receipt["computed_at"])
        if (provenance.get("code_revision") != PINNED_REVISION
                or timestamp(provenance["created_at"]) != timestamp(receipt["computed_at"])
                or timestamp(provenance["last_calculated"]) != timestamp(receipt["computed_at"])):
            return "invalid_reconstruction_timestamp"
        dependencies = inputs["input_provenance"] + [
            g["ml_provenance"] for g in inputs.get("games", []) if g.get("ml_overperformance") is not None
        ]
        if any(timestamp(p[key]) > computed for p in dependencies for key in (
            ("created_at", "last_calculated", "trained_at") if p.get("uses_learned_inputs", True)
            else ("created_at", "last_calculated")
        )):
            return "reconstruction_precedes_inputs"
        if any(timestamp(g["result_available_at"]) > computed for g in inputs.get("games", [])):
            return "reconstruction_precedes_results"
        if not finite(prediction["expectedMargin"]) or prediction["expectedMargin"] != expected["expected_home_margin"]:
            return "reconstruction_margin_mismatch"
        if not expected.get("model_signature") or expected["model_signature"] != receipt["model_signature"]:
            return "reconstruction_signature_mismatch"
        return prediction_input_error(inputs, fixture["game_date"])
    except (ValueError, TypeError, KeyError, AttributeError, OSError, subprocess.SubprocessError):
        return "missing_or_invalid_reconstruction"


def reconstruct_expectations(cases: list[dict], runner: dict, computed_at: str) -> dict:
    timestamp(computed_at)
    if (runner.get("predictor_revision") != PINNED_REVISION or not runner.get("aa_parity")
            or set(runner.get("outputs", {})) != {"baseline"}
            or any(runner.get(k) != v for k, v in pinned_source_identity().items())):
        raise ValueError("Pinned baseline reconstruction parity not established")
    rows = runner["outputs"]["baseline"]
    by_id = {row["id"]: row for row in rows}
    if (len(by_id) != len(rows) or len(by_id) != len(cases)
            or set(by_id) != {c["fixture"]["source_game_id"] for c in cases}):
        raise ValueError("Reconstruction outputs do not match the input fixtures")
    expectations = {}
    for case in cases:
        inputs = reconstruction_inputs(case)
        fixture = inputs["fixture"]
        row = by_id[fixture["source_game_id"]]
        if timestamp(row.get("reference_time")) != timestamp(inputs["reference_time"]):
            raise ValueError("Reconstruction reference time does not match the replay")
        prediction = deepcopy(row["prediction"])
        receipt = {
            "schema_version": 1, "computed_at": computed_at, "predictor_revision": PINNED_REVISION,
            **{key: deepcopy(runner[key]) for key in (
                "source_hashes", "algorithm_hash", "model_signature", "model_signature_payload", "aa_parity",
            )},
            "inputs": inputs, "inputs_sha256": digest(inputs), "prediction": prediction,
            "prediction_sha256": digest(prediction),
        }
        expected = {
            **fixture, "source": "reconstructed", "expected_home_margin": prediction["expectedMargin"],
            "model_signature": runner["model_signature"], "reconstruction": receipt,
            "reconstruction_sha256": digest(receipt),
            "provenance": {"code_revision": PINNED_REVISION, "created_at": computed_at, "last_calculated": computed_at},
        }
        expected["provenance"]["sha256"] = digest(expectation_payload(expected))
        if reconstruction_error(expected):
            raise ValueError("Reconstruction inputs or output provenance are invalid")
        expectations[fixture["source_game_id"]] = expected
    return expectations


def residual_form(team_id: str, games: list[dict], expectations: dict, as_of: str, candidate: str) -> dict:
    """Replace only the scalar form input; other recent-profile fields stay raw."""
    if candidate not in FORM_CANDIDATES:
        raise ValueError("Unknown form candidate")
    recent = sorted(
        (
            g
            for g in games
            if team_id in (g["home_team_master_id"], g["away_team_master_id"])
            and g["game_date"] < as_of
            and not g.get("is_excluded", False)
            and g.get("home_score") is not None
            and g.get("away_score") is not None
        ),
        key=lambda g: g["game_date"],
        reverse=True,
    )[:FORM_HISTORY_SIZE]
    if candidate == "baseline":
        raise ValueError("Baseline form is computed by the pinned TypeScript predictor")
    if candidate == "form_off":
        return {"value": 0.0, "usable": 0, "missing": 0, "provenance": {}}
    samples = []
    origins = Counter()
    missing = 0
    for position, game in enumerate(recent):
        expected = expectations.get(game.get("source_game_id") or game["id"])
        if expected is None:
            expected = expectations.get(game["id"])
        if not expected or not valid_expectation(expected, game):
            missing += 1
            continue
        home = game["home_team_master_id"] == team_id
        actual = game["home_score"] - game["away_score"]
        residual = max(-FORM_RESIDUAL_CLIP, min(FORM_RESIDUAL_CLIP, actual - expected["expected_home_margin"]))
        residual *= 1 if home else -1
        opponent = game["away_team_master_id"] if home else game["home_team_master_id"]
        if candidate == "residual_sequence":
            weight = math.exp(-0.28 * position)
        else:
            half_life = int(candidate.split("_")[1])
            age = (date.fromisoformat(as_of) - date.fromisoformat(game["game_date"])).days
            weight = 2 ** (-age / half_life)
        samples.append((opponent, residual, weight))
        origins[expected["source"]] += 1
    weights = defaultdict(float)
    for opponent, _, weight in samples:
        weights[opponent] += weight
    capped = candidate.endswith("_capped")
    numerator = denominator = 0.0
    for opponent, residual, weight in samples:
        if capped:
            weight /= max(FORM_OPPONENT_CAP, weights[opponent]) / FORM_OPPONENT_CAP
        numerator += residual * weight
        denominator += weight
    sample_size = len(weights) if capped else len(samples)
    shrinkage = min(1.0, sample_size / FORM_HISTORY_SIZE)
    return {
        "value": numerator / denominator * shrinkage if denominator else 0.0,
        "usable": len(samples),
        "missing": missing,
        "opponents": len(weights),
        "effective_weight": denominator,
        "provenance": dict(origins),
    }


def audit_cases(cases: list[dict], policy: ResearchPolicy) -> tuple[list[dict], dict]:
    """Cases carry frozen TS inputs, actual outcomes, and independently verified provenance."""
    seen = set()
    candidates = []
    exclusions = Counter()
    coverage = defaultdict(Counter)
    for case in cases:
        fixture = case["fixture"]
        day = fixture["game_date"]
        group = fixture.get("event_group")
        label = "|".join(str(fixture.get(key, "unknown")) for key in ("provider", "cohort", "history_band"))
        coverage[label]["seen"] += 1
        identity = fixture.get("source_game_id")
        reason = None
        if not identity or identity in seen:
            reason = "missing_or_duplicate_source_identity"
        elif not group:
            reason = "missing_evaluation_group"
        elif fixture.get("is_excluded", False):
            reason = "excluded_result"
        elif not all(finite(fixture.get(k)) and fixture[k] >= 0 for k in ("home_score", "away_score")):
            reason = "missing_result"
        elif case.get("predictor_revision") != policy.predictor_revision:
            reason = "wrong_predictor_revision"
        else:
            reason = prediction_input_error(case, day)
        if reason:
            exclusions[reason] += 1
            coverage[label][reason] += 1
            continue
        seen.add(identity)
        period = (
            "development"
            if policy.development_start <= day <= policy.development_end
            else "evaluation"
            if policy.evaluation_start <= day <= policy.evaluation_end
            else None
        )
        if period:
            candidates.append({**case, "period": period})
        else:
            exclusions["outside_windows"] += 1
    group_periods = defaultdict(set)
    for case in candidates:
        group_periods[case["fixture"]["event_group"]].add(case["period"])
    crossing = {group for group, periods in group_periods.items() if len(periods) > 1}
    eligible = [case for case in candidates if case["fixture"]["event_group"] not in crossing]
    exclusions["crossing_group"] += len(candidates) - len(eligible)
    periods = {}
    for period in ("development", "evaluation"):
        selected = [case for case in eligible if case["period"] == period]
        periods[period] = {"games": len(selected), "groups": len({c["fixture"]["event_group"] for c in selected})}
    for case in eligible:
        f = case["fixture"]
        label = "|".join(str(f.get(k, "unknown")) for k in ("provider", "cohort", "history_band"))
        coverage[label][case["period"] + "_eligible"] += 1
    enough = all(p["games"] >= policy.minimum_games and p["groups"] >= policy.minimum_groups for p in periods.values())
    return eligible, {
        "status": "eligible" if enough else "insufficient_data",
        "periods": periods,
        "exclusions": dict(exclusions),
        "coverage": {k: dict(v) for k, v in coverage.items()},
        "crossing_groups": sorted(crossing),
    }


def evaluation_frame(cases: list[dict], outputs: list[dict]) -> pd.DataFrame:
    by_id = {output["id"]: output["prediction"] for output in outputs}
    if len(by_id) != len(outputs) or set(by_id) != {c["fixture"]["source_game_id"] for c in cases}:
        raise ValueError("Candidate must cover exactly the paired fixture set")
    rows = []
    for case in cases:
        f = case["fixture"]
        p = by_id[f["source_game_id"]]
        probabilities = [p.get("winProbabilityA"), p.get("drawProbability"), p.get("winProbabilityB")]
        if (
            not all(finite(v) and 0 <= v <= 1 for v in probabilities)
            or abs(sum(probabilities) - 1) > 1e-8
            or not finite(p.get("blowout4PlusProbability"))
        ):
            raise ValueError("Incomplete probability/risk output")
        outcome = (
            "team_a_win"
            if f["home_score"] > f["away_score"]
            else ("team_b_win" if f["away_score"] > f["home_score"] else "draw")
        )
        rows.append(
            {
                "actual_game_id": f["source_game_id"],
                "game_id": f["source_game_id"],
                "game_date": f["game_date"],
                "event_group": f["event_group"],
                "actual_outcome": outcome,
                "actual_margin": f["home_score"] - f["away_score"],
                "actual_score_a": f["home_score"],
                "actual_score_b": f["away_score"],
                "predicted_outcome": p["predictedWinner"],
                "prob_team_a_win": probabilities[0],
                "prob_draw": probabilities[1],
                "prob_team_b_win": probabilities[2],
                "predicted_margin": p["expectedMargin"],
                "predicted_score_a": p["expectedScore"]["teamA"],
                "predicted_score_b": p["expectedScore"]["teamB"],
                "blowout_4plus_probability": p["blowout4PlusProbability"],
                "provider": f.get("provider", "unknown"),
                "cohort": f.get("cohort", "unknown"),
                "history_band": f.get("history_band", "unknown"),
            }
        )
    return pd.DataFrame(rows)


def compare_outputs(cases: list[dict], outputs: dict[str, list[dict]], policy: ResearchPolicy) -> dict:
    """Choose on development only; evaluation is read once for the selected candidate."""
    eligible, audit = audit_cases(cases, policy)
    report = {"policy": asdict(policy), "audit": audit, "status": audit["status"]}
    if audit["status"] != "eligible":
        return report
    development = [case for case in eligible if case["period"] == "development"]
    evaluation = [case for case in eligible if case["period"] == "evaluation"]
    summaries = {}
    for name in FORM_CANDIDATES:
        ids = {case["fixture"]["source_game_id"] for case in development}
        frame = evaluation_frame(development, [x for x in outputs[name] if x["id"] in ids])
        summaries[name] = compute_evaluation_summary(frame)
    ablations = {}
    for name in FORM_CANDIDATES[1:]:
        key = name + "_ml_off"
        ids = {case["fixture"]["source_game_id"] for case in development}
        frame = evaluation_frame(development, [x for x in outputs[key] if x["id"] in ids])
        ablations[key] = compute_evaluation_summary(frame)
    selected = min(
        FORM_CANDIDATES[1:],
        key=lambda name: (summaries[name]["log_loss"], summaries[name]["brier_score"], FORM_CANDIDATES.index(name)),
    )
    ids = {case["fixture"]["source_game_id"] for case in evaluation}
    baseline = evaluation_frame(evaluation, [x for x in outputs["baseline"] if x["id"] in ids])
    candidate = evaluation_frame(evaluation, [x for x in outputs[selected] if x["id"] in ids])
    baseline_metrics, candidate_metrics = compute_evaluation_summary(baseline), compute_evaluation_summary(candidate)
    interval = paired_event_interval(baseline, candidate, samples=policy.bootstrap_samples, seed=policy.seed)
    better = candidate_metrics["brier_score"] < baseline_metrics["brier_score"] and interval[1] < 0
    slices = {}
    for column in ("provider", "cohort", "history_band"):
        slices[column] = {
            str(value): {
                "baseline": compute_evaluation_summary(baseline[baseline[column] == value]),
                "candidate": compute_evaluation_summary(candidate[candidate[column] == value]),
            }
            for value in baseline[column].unique()
        }
    report.update(
        status="qualifies_for_confirmation" if better else "no_advancement",
        selected_candidate=selected,
        development=summaries,
        development_ml_ablations=ablations,
        residual_coverage=[
            {
                "source_game_id": c["fixture"]["source_game_id"],
                "period": c["period"],
                "provider": c["fixture"].get("provider"),
                "cohort": c["fixture"].get("cohort"),
                "history_band": c["fixture"].get("history_band"),
                "diagnostics": c.get("formDiagnostics", {}),
            }
            for c in eligible
        ],
        evaluation={"baseline": baseline_metrics, "candidate": candidate_metrics},
        log_loss_delta_95=interval,
        slices=slices,
        production_promotion=False,
    )
    return report


class AttackDefenseModel:
    """Neutral-venue, L2-regularized Poisson strengths within one cohort."""

    def __init__(self, penalty: float = 10.0):
        if not finite(penalty) or penalty <= 0:
            raise ValueError("Positive regularization required")
        self.penalty = penalty

    def fit(self, games: list[dict], cutoff: str):
        training = [g for g in games if g["game_date"] < cutoff and not g.get("is_excluded", False)]
        if not training:
            raise ValueError("No earlier training games")
        self.teams = sorted({g[k] for g in training for k in ("home_team_master_id", "away_team_master_id")})
        self.index = index = {team: i for i, team in enumerate(self.teams)}
        a = np.array([index[g["home_team_master_id"]] for g in training])
        b = np.array([index[g["away_team_master_id"]] for g in training])
        y_a = np.array([g["home_score"] for g in training], dtype=float)
        y_b = np.array([g["away_score"] for g in training], dtype=float)
        if not np.all(np.isfinite([y_a, y_b])) or np.any(y_a < 0) or np.any(y_b < 0):
            raise ValueError("Invalid training scores")
        n = len(self.teams)

        def objective(params):
            attack, defense = params[1 : 1 + n], params[1 + n :]
            eta_a = params[0] + attack[a] - defense[b]
            eta_b = params[0] + attack[b] - defense[a]
            la, lb = np.exp(eta_a), np.exp(eta_b)
            ra, rb = la - y_a, lb - y_b
            grad_attack = np.bincount(a, weights=ra, minlength=n) + np.bincount(b, weights=rb, minlength=n)
            grad_defense = -np.bincount(b, weights=ra, minlength=n) - np.bincount(a, weights=rb, minlength=n)
            grad = np.concatenate(([np.sum(ra + rb)], grad_attack, grad_defense))
            grad[1:] += self.penalty * params[1:]
            loss = np.sum(la - y_a * eta_a + lb - y_b * eta_b) + self.penalty * np.sum(params[1:] ** 2) / 2
            return loss, grad

        initial = np.zeros(1 + 2 * n)
        initial[0] = math.log(max(0.05, float(np.mean([y_a, y_b]))))
        result = minimize(objective, initial, jac=True, method="L-BFGS-B", bounds=[(-3, 3)] + [(-4, 4)] * (2 * n))
        if not result.success:
            raise ValueError(f"Poisson fit failed: {result.message}")
        self.params = result.x
        self.cutoff = cutoff
        return self

    def expected_goals(self, team_a: str, team_b: str, game_date: str) -> tuple[float, float]:
        if game_date < self.cutoff:
            raise ValueError("Model trained after prediction cutoff")
        n = len(self.teams)

        def strengths(team):
            i = self.index.get(team)
            return (0.0, 0.0) if i is None else (self.params[1 + i], self.params[1 + n + i])

        aa, da = strengths(team_a)
        ab, db = strengths(team_b)
        return math.exp(self.params[0] + aa - db), math.exp(self.params[0] + ab - da)


def write_bundle(output: Path, inputs: dict, report: dict, *, dry_run: bool = True) -> None:
    if dry_run:
        return
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    from src.predictions.form_study import is_research_source
    from src.rankings.input_archive import source_file_names

    research_files = [name for name in source_file_names(root) if is_research_source(name)]
    manifest = {
        "schema_version": 1,
        "input_hash": digest(inputs),
        "policy": asdict(ResearchPolicy()),
        "candidates": list(FORM_CANDIDATES),
        "predictor_revision": PINNED_REVISION,
        "research_source_hashes": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in research_files
        },
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
    }
    for name, value in (("inputs.json", inputs), ("manifest.json", manifest), ("report.json", report)):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
