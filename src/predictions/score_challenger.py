"""Offline score candidates; baseline outcome probabilities and decisions are immutable."""

from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.special import gammaln

OUTCOME_FIELDS = ("winProbabilityA", "drawProbability", "winProbabilityB", "predictedWinner")
MAX_GOALS = 40
CANDIDATES = ("baseline", "blend_25", "tail_guard_full")


@dataclass(frozen=True)
class ScoreResult:
    prediction: dict
    matrix: np.ndarray
    status: str


def candidate_definition(candidate: str) -> dict:
    if candidate not in CANDIDATES:
        raise ValueError("Unknown score candidate")
    return {
        "schema_version": 1,
        "candidate": candidate,
        "challenger_weight": {"baseline": 0.0, "blend_25": 0.25, "tail_guard_full": 1.0}[candidate],
        "preserve_four_goal_risk": candidate == "tail_guard_full",
        "max_goals": MAX_GOALS,
        "family": "outcome_conditioned_independent_poisson",
        "score_rule": "modal_score_within_baseline_decision; ties_lowest_total_then_margin",
        "outcome_fields_preserved": list(OUTCOME_FIELDS),
        "live_enabled": False,
    }


def _probability(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def _validate_baseline(baseline: dict) -> None:
    probabilities = [baseline.get(field) for field in OUTCOME_FIELDS[:3]]
    if not all(_probability(value) for value in probabilities) or abs(sum(probabilities) - 1) > 1e-12:
        raise ValueError("Complete normalized baseline outcome probabilities are required")
    winner = baseline.get("predictedWinner")
    if winner not in ("team_a", "draw", "team_b"):
        raise ValueError("A baseline outcome decision is required")
    if probabilities[("team_a", "draw", "team_b").index(winner)] == 0:
        raise ValueError("The selected baseline outcome has no probability mass")
    if not _probability(baseline.get("blowout4PlusProbability")):
        raise ValueError("A complete baseline four-goal-risk probability is required")
    score = baseline.get("expectedScore", {})
    if any(type(score.get(team)) is not int or score[team] < 0 for team in ("teamA", "teamB")):
        raise ValueError("Nonnegative integer baseline scores are required")


def conditioned_score_matrix(rates, baseline: dict) -> np.ndarray:
    """A 0..40 goal grid, conditioned on the supplied three outcome masses."""
    values = np.asarray(rates, dtype=float)
    if values.shape != (2,) or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Two finite positive expected goal rates are required")
    axis = np.arange(MAX_GOALS + 1)
    marginals = np.exp(-values[:, None] + axis * np.log(values[:, None]) - gammaln(axis + 1))
    matrix = np.outer(*marginals)
    if not math.isclose(float(matrix.sum()), 1.0, abs_tol=1e-10, rel_tol=0):
        raise ValueError("Goal rates exceed the declared score grid's tail tolerance")
    margin = axis[:, None] - axis[None, :]
    for mask, field in zip((margin > 0, margin == 0, margin < 0), OUTCOME_FIELDS[:3], strict=True):
        mass = matrix[mask].sum()
        if mass <= 0:
            raise ValueError("Score grid has no support for an outcome")
        matrix[mask] *= baseline[field] / mass
    return matrix / matrix.sum()


def _preserve_tail(matrix: np.ndarray, original: np.ndarray, baseline: dict) -> np.ndarray:
    axis = np.arange(MAX_GOALS + 1)
    margin = axis[:, None] - axis[None, :]
    a, d, b = (baseline[field] for field in OUTCOME_FIELDS[:3])
    risk = baseline["blowout4PlusProbability"]
    if risk > a + b:
        raise ValueError("Baseline four-goal risk exceeds the total win probability")
    a_tail = float(original[margin >= 4].sum())
    b_tail = float(original[margin <= -4].sum())
    a_target = risk * a_tail / (a_tail + b_tail) if a_tail + b_tail else risk * a / max(a + b, 1e-15)
    a_target = min(min(risk, a), max(max(0, risk - b), a_target))
    b_target = risk - a_target
    result = matrix.copy()
    regions = (
        (margin >= 4, a_target), ((margin > 0) & (margin < 4), a - a_target),
        (margin == 0, d), ((margin < 0) & (margin > -4), b - b_target), (margin <= -4, b_target),
    )
    for mask, target in regions:
        mass = float(result[mask].sum())
        if mass == 0 and target > 1e-14:
            raise ValueError("Score grid cannot support the protected baseline tail")
        result[mask] = result[mask] * max(0, target) / mass if mass else 0
    return result / result.sum()


def _prediction(matrix: np.ndarray, baseline: dict) -> dict:
    axis = np.arange(MAX_GOALS + 1)
    margin = axis[:, None] - axis[None, :]
    mask = {"team_a": margin > 0, "draw": margin == 0, "team_b": margin < 0}[baseline["predictedWinner"]]
    highest = float(matrix[mask].max())
    # This tie rule is unchanged by swapping teams.
    scores = np.argwhere(mask & (matrix == highest))
    a, b = min(scores.tolist(), key=lambda pair: (sum(pair), abs(pair[0] - pair[1])))
    result = {field: baseline[field] for field in OUTCOME_FIELDS}
    result.update({
        "expectedScore": {"teamA": a, "teamB": b},
        "expectedGoals": {"teamA": float(matrix.sum(axis=1) @ axis), "teamB": float(matrix.sum(axis=0) @ axis)},
        "expectedMargin": float((matrix * margin).sum()),
        "blowout4PlusProbability": float(matrix[abs(margin) >= 4].sum()),
    })
    return result


def score_candidate(baseline: dict, learned_rates=None, *, candidate="blend_25", eligibility="eligible") -> ScoreResult:
    definition = candidate_definition(candidate)
    _validate_baseline(baseline)
    if not isinstance(eligibility, str) or not eligibility:
        raise ValueError("An explicit eligibility status is required")
    goals = baseline.get("expectedGoals", {})
    original = conditioned_score_matrix([goals.get("teamA"), goals.get("teamB")], baseline)
    if candidate == "baseline" or eligibility != "eligible" or learned_rates is None:
        status = "baseline_control" if candidate == "baseline" else (
            eligibility if eligibility != "eligible" else "missing_learned_rates"
        )
        return ScoreResult(deepcopy(baseline), original, status)
    donor = conditioned_score_matrix(learned_rates, baseline)
    weight = definition["challenger_weight"]
    matrix = (1 - weight) * original + weight * donor
    if definition["preserve_four_goal_risk"]:
        matrix = _preserve_tail(matrix, original, baseline)
    result = _prediction(matrix, baseline)
    return ScoreResult(result, matrix, "applied")


def build_score_batch(batch: dict, fit: dict, *, candidate="blend_25") -> dict:
    """Transform a frozen rate batch without fitting, reading outcomes, or claiming prospective registration."""
    definition = candidate_definition(candidate)
    receipt = fit["receipt"]
    cutoff = date.fromisoformat(receipt["cutoff"])
    latest = date.fromisoformat(receipt["latest_training_game"])
    if latest >= cutoff or receipt.get("optimizer_success") is not True:
        raise ValueError("A successful fit with a strictly earlier training cutoff is required")
    rows, counts, seen_ids, seen_sources = [], Counter(), set(), set()
    for row in batch["rows"]:
        fixture_id, source_id = row["id"], row["source_game_id"]
        if not fixture_id or not source_id or fixture_id in seen_ids or source_id in seen_sources:
            raise ValueError("Every baseline and exact-source fixture must be unique")
        seen_ids.add(fixture_id)
        seen_sources.add(source_id)
        game_date = date.fromisoformat(row["game_date"])
        if cutoff > game_date or latest >= game_date:
            raise ValueError("Fitted goal rates must use results strictly before the target day")
        baseline = row["variants"]["baseline"]
        result = score_candidate(
            baseline, row.get("learned_rates"), candidate=candidate, eligibility=row["eligibility"]
        )
        counts[result.status] += 1
        metadata = {key: deepcopy(value) for key, value in row.items() if key not in ("variants", "learned_rates")}
        rows.append(metadata | {"prediction": result.prediction, "candidate_status": result.status})
    if not rows:
        raise ValueError("A nonempty frozen forecast batch is required")
    return {
        "definition": definition,
        "scope": "Offline replay only; provided frozen rates, not independently reconstructed from model parameters",
        "fit_receipt": deepcopy(receipt),
        "coverage": dict(counts),
        "rows": rows,
        "winner_probabilities_preserved": True,
        "production_promotion": False,
        "formal_confirmation_registered": False,
    }
