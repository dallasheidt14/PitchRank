"""Turn complete, fixed-order division assessments into practical sheet breaks."""

from __future__ import annotations

import json
from dataclasses import asdict
from functools import lru_cache
from typing import Any, Mapping, Sequence

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_flight_suggestions import suggest_automatic_flights
from src.tournaments.seeding_format_library import FormatLibrary, parse_format_library, resolve_format_profile
from src.tournaments.seeding_group_assessment import GroupTeam
from src.tournaments.seeding_plan_assessment import UnassignedEntrant
from src.tournaments.seeding_tiers import CheatSheetAnalysis, TierEntrant, TierPolicy


def build_tier_guidance(
    analysis: CheatSheetAnalysis, entrants: Sequence[TierEntrant], predictions: Mapping,
    policy: TierPolicy, library: FormatLibrary, *, profile_id: str | None = None,
    tier_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Never change order, relax limits, or infer strength for unplaced entrants."""
    inputs = {
        "order": analysis.ordered_ids, "natural": [item.after_seed for item in analysis.breaks],
        "review": analysis.review, "entrants": [asdict(item) for item in entrants],
        "predictions": [[list(pair), asdict(value)] for pair, value in sorted(predictions.items())],
        "policy": asdict(policy), "library": asdict(library), "profile": profile_id, "names": tier_names,
    }
    # Cache only immutable serialized inputs/results; callers receive their own copy.
    return json.loads(_cached_guidance(json.dumps(inputs, sort_keys=True, default=str, allow_nan=False)))


@lru_cache(maxsize=32)
def _cached_guidance(serialized: str) -> str:
    inputs = json.loads(serialized)
    result = _calculate_guidance(
        inputs["order"], set(inputs["natural"]), inputs["review"],
        [TierEntrant(**item) for item in inputs["entrants"]],
        {tuple(pair): ComparePrediction(**value) for pair, value in inputs["predictions"]},
        TierPolicy(**inputs["policy"]), parse_format_library(inputs["library"]),
        profile_id=inputs["profile"], tier_names=inputs["names"],
    )
    return json.dumps(result, allow_nan=False)


def _calculate_guidance(order, natural, review, entrants, predictions, policy, library, *, profile_id, tier_names):
    accepted = tuple(item.entrant_id for item in entrants)
    positions = {key: seed for seed, key in enumerate(order, 1)}
    metadata = {
        item.entrant_id: GroupTeam(
            entrant_id=item.entrant_id, team_name=item.team_name,
            seed=positions.get(item.entrant_id), power_score=item.power_score,
            limited_history=item.limited_history, evidence_game_count=item.evidence_game_count,
        ) for item in entrants
    }
    unassigned = tuple(
        UnassignedEntrant(item.entrant_id, review.get(item.entrant_id) or "Held for manual placement")
        for item in entrants if item.entrant_id not in positions
    )
    profile = resolve_format_profile(library, profile_id)
    result = suggest_automatic_flights(
        order, predictions, policy, metadata, library, profile,
        accepted_entrant_ids=accepted, unassigned_entrants=unassigned,
    )
    plans = result.assessment.plans if result.assessment else ()
    by_id = {item.plan_id: item for item in plans}

    def normalized_risk(plan):
        return max((max(
            pair.expected_absolute_goal_difference / policy.max_expected_margin,
            pair.blowout_probability / policy.max_blowout_probability,
        ) for flight in plan.flights for pair in flight.group.pairings
            if pair.expected_absolute_goal_difference is not None
            and pair.blowout_probability is not None), default=0.0)

    chosen = by_id.get(result.primary_plan_id)
    compromise = False
    if chosen is None and result.generation.search_complete:
        complete = [item for item in plans if item.structural.valid and item.prediction_complete
                    and item.accepted_field_coverage.every_accepted_entrant_accounted_for]
        if complete:
            chosen = min(complete, key=lambda item: (
                normalized_risk(item), item.violating_pairing_count,
                item.pair_weighted_average_matchup_cost, len(item.flights), item.flight_sizes,
            ))
            compromise = True
    alternatives = [by_id[item.plan_id] for item in result.useful_alternatives]
    alternative = min(alternatives, key=lambda item: (
        item.worst_matchup_cost, item.pair_weighted_average_matchup_cost, item.flight_sizes,
    ), default=None)
    alternative_detail = next((asdict(item) for item in result.useful_alternatives
                               if alternative and item.plan_id == alternative.plan_id), None)
    divisions = []
    if chosen is not None:
        start = 1
        for index, flight in enumerate(chosen.flights):
            size = len(flight.entrant_ids)
            options = next(item for item in result.generation.size_template_options if item.team_count == size)
            template = library.templates_by_id[options.preferred_template_id]
            end = start + size - 1
            divisions.append({
                "label": tier_names[index].strip() if index < len(tier_names) and tier_names[index].strip()
                else f"Tier {index + 1}",
                "start_seed": start, "end_seed": end, "size": size,
                "entrant_ids": list(flight.entrant_ids), "pool_sizes": list(template.pool_sizes),
                "template_id": template.template_id, "natural_break_after": end in natural,
                "minimum_games": template.minimum_guaranteed_games_per_team,
                "compatible_formats": [{
                    "template_id": template_id,
                    "pool_sizes": list(library.templates_by_id[template_id].pool_sizes),
                    "minimum_games": library.templates_by_id[template_id].minimum_guaranteed_games_per_team,
                } for template_id in options.compatible_template_ids],
            })
            start = end + 1
    warnings = []
    if unassigned:
        warnings.append(f"{len(positions)} of {len(accepted)} teams assessed in the tier order; "
                        f"{len(unassigned)} still need placement. These breaks cover the assessed subset.")
    if compromise:
        warnings.append("Review-required compromise: every evaluated arrangement retains projected mismatches.")
    if not result.generation.search_complete:
        warnings.append("Search incomplete; no primary tier split is recommended.")
    if chosen is None:
        warnings.append(result.selection_reason)
    risks = []
    if chosen is not None:
        for flight in chosen.flights:
            evidence = flight.group.evidence_coverage
            if evidence.limited_history_teams or evidence.unknown_history_teams:
                warnings.append("Limited or unknown playing history makes the tier guidance provisional.")
        risks = [pair for flight in chosen.flights
                 for pair in flight.group.projected_fit.over_limit_matchups]
        if risks:
            worst = max(risks, key=lambda pair: max(
                pair.expected_absolute_goal_difference / policy.max_expected_margin,
                pair.blowout_probability / policy.max_blowout_probability,
            ))
            first, second = worst.entrant_ids
            warnings.append(
                f"Worst remaining mismatch: {metadata[first].team_name} vs {metadata[second].team_name}; "
                f"expected absolute goal difference {worst.expected_absolute_goal_difference:.2f}, "
                f"four-goal margin probability {worst.blowout_probability:.0%}."
            )
    return {
        "version": 1, "status": "review_required_compromise" if compromise else result.status,
        "review_required": compromise or chosen is None or bool(unassigned)
        or result.primary_evidence_status == "provisional_due_to_history",
        "accepted_count": len(accepted), "assessed_count": len(positions),
        "divisions": divisions, "cuts": [item["end_seed"] for item in divisions[:-1]],
        "alternative_sizes": list(alternative.flight_sizes) if alternative else [],
        "alternative": alternative_detail,
        "warnings": list(dict.fromkeys(warnings)),
        "profile_id": profile.profile_id, "profile_version": profile.version,
        "format_assumptions": [profile.source_note, *profile.unresolved_assumptions],
        "search_complete": result.generation.search_complete,
        "candidate_count": result.generation.generated_structure_count,
        "risky_pairings": [{"entrant_ids": list(pair.entrant_ids),
                            "expected_absolute_goal_difference": pair.expected_absolute_goal_difference,
                            "blowout_4plus_probability": pair.blowout_probability} for pair in risks],
        "alternatives": [asdict(item) for item in result.useful_alternatives],
    }
