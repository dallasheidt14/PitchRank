"""Fair model-to-model comparison for tournament arrangements.

Observed scores describe what happened. They are not the counterfactual for a
different seed. This module evaluates the original and proposed matchup pairs
with one cost model so the reported delta isolates arrangement changes.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from statistics import median, stdev
from typing import Any, Callable, Sequence

from src.tournaments.seeding_optimizer import MatchupCost, SeedableTeam


@dataclass(frozen=True)
class ModelledMatchup:
    team_a_id: str
    team_b_id: str
    cost: MatchupCost


def project_matchup_pairs(
    pairs: Sequence[tuple[SeedableTeam, SeedableTeam]],
    matchup_cost_fn: Callable[[SeedableTeam, SeedableTeam], MatchupCost],
) -> tuple[ModelledMatchup, ...]:
    projected: list[ModelledMatchup] = []
    for team_a, team_b in pairs:
        if team_a.team_id == team_b.team_id:
            raise ValueError(f"A tournament entrant cannot play itself: {team_a.team_id}")
        projected.append(
            ModelledMatchup(
                team_a_id=team_a.team_id,
                team_b_id=team_b.team_id,
                cost=matchup_cost_fn(team_a, team_b),
            )
        )
    return tuple(projected)


def _arrangement_signature(matchups: Sequence[ModelledMatchup]) -> str:
    pair_counts = Counter(tuple(sorted((matchup.team_a_id, matchup.team_b_id))) for matchup in matchups)
    serialized = json.dumps(sorted((left, right, count) for (left, right), count in pair_counts.items()))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normal_interval(
    mean: float,
    standard_error: float,
    *,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
) -> dict[str, float]:
    radius = 1.96 * standard_error
    lower = mean - radius
    upper = mean + radius
    if lower_bound is not None:
        lower = max(lower_bound, lower)
    if upper_bound is not None:
        upper = min(upper_bound, upper)
    return {
        "standard_error": float(standard_error),
        "confidence_95_lower": float(lower),
        "confidence_95_upper": float(upper),
    }


def _mean_probability_uncertainty(probabilities: Sequence[float]) -> dict[str, float]:
    count = len(probabilities)
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in probabilities):
        raise ValueError("Model probabilities must be finite values between 0 and 1")
    mean = sum(probabilities) / count
    variance = sum(probability * (1.0 - probability) for probability in probabilities) / (count * count)
    return _normal_interval(mean, math.sqrt(max(0.0, variance)), lower_bound=0.0, upper_bound=1.0)


def summarize_modelled_matchups(
    matchups: Sequence[ModelledMatchup],
    *,
    projection_basis: str,
) -> dict[str, Any]:
    if not matchups:
        return {
            "projection_basis": projection_basis,
            "projected_matchup_count": 0,
            "arrangement_signature": _arrangement_signature(()),
            "average_goal_differential": None,
            "total_model_cost": 0.0,
            "median_goal_differential": None,
            "close_game_probability": None,
            "blowout_3plus_probability": None,
            "blowout_4plus_probability": None,
            "blowout_5plus_probability": None,
            "uncertainty": None,
        }

    margins = [float(matchup.cost.projected_margin) for matchup in matchups]
    close_probabilities = [float(matchup.cost.competitive_probability) for matchup in matchups]
    blowout_3plus = [float(matchup.cost.blowout_3plus_probability) for matchup in matchups]
    blowout_4plus = [matchup.cost.blowout_4plus_probability for matchup in matchups]
    blowout_5plus = [float(matchup.cost.blowout_5plus_probability) for matchup in matchups]
    complete_4plus = all(value is not None for value in blowout_4plus)
    numeric_4plus = [float(value) for value in blowout_4plus if value is not None]
    count = len(matchups)
    average_margin = sum(margins) / count
    margin_standard_error = stdev(margins) / math.sqrt(count) if count > 1 else 0.0

    return {
        "projection_basis": projection_basis,
        "projected_matchup_count": count,
        "arrangement_signature": _arrangement_signature(matchups),
        "average_goal_differential": float(average_margin),
        "total_model_cost": float(sum(float(matchup.cost.total_cost) for matchup in matchups)),
        "median_goal_differential": float(median(margins)),
        "close_game_probability": float(sum(close_probabilities) / count),
        "blowout_3plus_probability": float(sum(blowout_3plus) / count),
        "blowout_4plus_probability": (
            float(sum(numeric_4plus) / count) if complete_4plus else None
        ),
        "blowout_5plus_probability": float(sum(blowout_5plus) / count),
        "uncertainty": {
            "method": "normal_95",
            "assumptions": [
                "match outcomes are independent conditional on the model",
                "margin interval measures variation across scheduled matchups",
            ],
            "average_goal_differential": _normal_interval(
                average_margin,
                margin_standard_error,
                lower_bound=0.0,
            ),
            "close_game_probability": _mean_probability_uncertainty(close_probabilities),
            "blowout_3plus_probability": _mean_probability_uncertainty(blowout_3plus),
            "blowout_4plus_probability": (
                _mean_probability_uncertainty(numeric_4plus) if complete_4plus else None
            ),
            "blowout_5plus_probability": _mean_probability_uncertainty(blowout_5plus),
        },
    }


def _unavailable(reason: str, original_count: int, proposed_count: int) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "comparison_basis": "same_model_original_vs_proposed_matchups",
        "original_matchup_count": original_count,
        "proposed_matchup_count": proposed_count,
    }


def compare_modelled_arrangements(
    original: dict[str, Any],
    proposed: dict[str, Any],
) -> dict[str, Any]:
    """Compare equally sized arrangements evaluated by the same model."""

    original_count = int(original.get("projected_matchup_count") or 0)
    proposed_count = int(proposed.get("projected_matchup_count") or 0)
    if original_count <= 0 or proposed_count <= 0:
        return _unavailable("Both arrangements need at least one modelled matchup", original_count, proposed_count)
    if original_count != proposed_count:
        return _unavailable(
            "Original and proposed arrangements contain different matchup counts",
            original_count,
            proposed_count,
        )

    identical = original.get("arrangement_signature") == proposed.get("arrangement_signature")
    metric_specs = {
        "average_goal_differential_improvement": ("average_goal_differential", "original_minus_proposed"),
        "median_goal_differential_improvement": ("median_goal_differential", "original_minus_proposed"),
        "close_game_probability_delta": ("close_game_probability", "proposed_minus_original"),
        "blowout_3plus_probability_improvement": ("blowout_3plus_probability", "original_minus_proposed"),
        "blowout_4plus_probability_improvement": ("blowout_4plus_probability", "original_minus_proposed"),
        "blowout_5plus_probability_improvement": ("blowout_5plus_probability", "original_minus_proposed"),
    }
    result: dict[str, Any] = {
        "status": "comparable",
        "comparison_basis": "same_model_original_vs_proposed_matchups",
        "original_matchup_count": original_count,
        "proposed_matchup_count": proposed_count,
        "arrangements_identical": identical,
    }
    uncertainty: dict[str, Any] = {
        "method": "conservative_independent_normal_95",
        "identical_arrangements_have_zero_delta_uncertainty": True,
        "metrics": {},
    }

    for output_name, (source_name, direction) in metric_specs.items():
        if original.get(source_name) is None or proposed.get(source_name) is None:
            result[output_name] = None
            uncertainty["metrics"][output_name] = None
            continue
        original_value = float(original[source_name])
        proposed_value = float(proposed[source_name])
        delta = (
            original_value - proposed_value
            if direction == "original_minus_proposed"
            else proposed_value - original_value
        )
        result[output_name] = 0.0 if identical else float(delta)

        if source_name == "median_goal_differential":
            uncertainty["metrics"][output_name] = None
            continue
        if identical:
            standard_error = 0.0
        else:
            original_se = float(original["uncertainty"][source_name]["standard_error"])
            proposed_se = float(proposed["uncertainty"][source_name]["standard_error"])
            standard_error = math.sqrt(original_se * original_se + proposed_se * proposed_se)
        interval = _normal_interval(result[output_name], standard_error)
        uncertainty["metrics"][output_name] = interval

    result["uncertainty"] = uncertainty
    return result
