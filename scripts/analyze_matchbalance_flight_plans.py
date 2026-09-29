"""Evaluate explicit complete MatchBalance flight plans from one frozen pack.

This internal diagnostic partitions a selected saved order into consecutive
flights. It never fetches current ratings, changes order, invents structures,
or writes to the saved source pack.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.analyze_matchbalance_groups import (  # noqa: E402
    _canonical_sha256,
    _git,
    _group_payload,
    _pair_payload,
    _sha256_bytes,
    _team_payload,
    build_team_metadata,
    load_frozen_snapshot,
)
from src.tournaments.seeding_pack import (  # noqa: E402
    ANALYSIS_SCHEMA_VERSION,
    PACK_SCHEMA_VERSION,
    cohort_key,
)
from src.tournaments.seeding_plan_assessment import (  # noqa: E402
    APPROVED_ALTERNATIVES,
    EXACT_ORDERED,
    PERMITTED_SIZE_MULTISET,
    AllOpponentAssessment,
    AlternativeComparison,
    FlightPlanAssessment,
    FlightPlanSetAssessment,
    PlanViolation,
    TeamPlanExposure,
    UnassignedEntrant,
    assess_permitted_plans,
    enumerate_arrangements,
)
from src.tournaments.seeding_tiers import CheatSheetAnalysis, TierPolicy  # noqa: E402

STARTING_COMMIT = "5eb68c1324512d4f4e098f8820519ae31579689b"
EXPECTED_BRANCH = "fix/matchbalance-boundary-analysis"
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class StructureRequest:
    """One explicitly permitted structure scenario from the operator."""

    label: str
    mode: str
    requested_structures: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class SelectedOrder:
    """The saved order used for partitioning and its field reconciliation."""

    source: str
    entrant_ids: tuple[str, ...]
    unassigned_entrants: tuple[UnassignedEntrant, ...]


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise ValueError("A report or scenario label must contain letters or numbers")
    return result


def _parse_sizes(value: str) -> tuple[int, ...]:
    pieces = tuple(item.strip() for item in value.split(","))
    if not pieces or any(not item for item in pieces):
        raise ValueError(f"Invalid flight-size sequence: {value!r}")
    try:
        return tuple(int(item) for item in pieces)
    except ValueError as exc:
        raise ValueError(f"Flight sizes must be integers: {value!r}") from exc


def parse_structure_request(value: str, mode: str) -> StructureRequest:
    """Parse ``label=sizes`` or ``label=alternative;alternative`` input."""
    label, separator, raw_structures = value.partition("=")
    if not separator or not label.strip() or not raw_structures.strip():
        raise ValueError(
            "Structure inputs must use label=comma,separated,sizes syntax"
        )
    if mode == APPROVED_ALTERNATIVES:
        structures = tuple(
            _parse_sizes(item.strip()) for item in raw_structures.split(";")
        )
        if len(structures) < 2:
            raise ValueError(
                "An approved-alternatives request must contain at least two alternatives"
            )
    else:
        if ";" in raw_structures:
            raise ValueError(f"{mode} accepts one size sequence")
        structures = (_parse_sizes(raw_structures),)
    return StructureRequest(label.strip(), mode, structures)


def build_structure_requests(
    exact: Sequence[str],
    permutations: Sequence[str],
    alternatives: Sequence[str],
) -> tuple[StructureRequest, ...]:
    """Build validated, distinctly labeled requests in CLI presentation order."""
    result = tuple(
        [parse_structure_request(item, EXACT_ORDERED) for item in exact]
        + [
            parse_structure_request(item, PERMITTED_SIZE_MULTISET)
            for item in permutations
        ]
        + [
            parse_structure_request(item, APPROVED_ALTERNATIVES)
            for item in alternatives
        ]
    )
    if not result:
        raise ValueError("At least one explicit flight-structure request is required")
    labels = tuple(item.label for item in result)
    if len(labels) != len(set(labels)):
        raise ValueError("Structure request labels must be unique")
    slugs = tuple(_slug(item.label) for item in result)
    if len(slugs) != len(set(slugs)):
        raise ValueError("Structure request labels must have unique report slugs")
    return result


def _accepted_entrant_ids(
    loaded: Mapping[str, Any], cohort: str
) -> tuple[str, ...]:
    accepted = tuple(
        str(row.source_index)
        for row in loaded["rows"]
        if cohort_key(row.section_age_group, row.section_gender) == cohort
    )
    if not accepted:
        raise ValueError(f"No accepted entrants were found for {cohort!r}")
    if len(accepted) != len(set(accepted)):
        raise ValueError("The accepted cohort contains duplicate entrant IDs")
    return accepted


def _unassigned_reason(analysis: CheatSheetAnalysis, entrant_id: str) -> str:
    if entrant_id in set(analysis.manual_holds):
        return "Saved manual hold."
    review_reason = analysis.review.get(entrant_id)
    if review_reason:
        return f"Saved placement review: {review_reason}"
    placement_status = analysis.placement_status.get(entrant_id)
    if placement_status:
        return f"Saved placement status: {placement_status}."
    return "Accepted entrant is not present in the selected saved order."


def select_saved_order(
    analysis: CheatSheetAnalysis,
    accepted_entrant_ids: Sequence[str],
    order_source: str | None,
) -> SelectedOrder:
    """Select suggested/effective order without changing saved manual decisions."""
    if analysis.manual_override and order_source is None:
        raise ValueError(
            "This saved pack has a manual override; choose --order-source suggested "
            "or --order-source effective explicitly."
        )
    source = order_source or "suggested"
    if source == "suggested":
        order = tuple(analysis.suggested_order)
    elif source == "effective":
        order = tuple(analysis.ordered_ids)
    else:
        raise ValueError(f"Unknown order source: {source!r}")
    accepted = tuple(accepted_entrant_ids)
    if not set(order).issubset(accepted):
        raise ValueError("The selected saved order contains a non-accepted entrant")
    unassigned = tuple(
        UnassignedEntrant(entrant_id, _unassigned_reason(analysis, entrant_id))
        for entrant_id in accepted
        if entrant_id not in set(order)
    )
    return SelectedOrder(source, order, unassigned)


def _boundary_snapshot(
    analysis: CheatSheetAnalysis, upgraded_pack: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "supported": [item.after_seed for item in analysis.supported_boundaries],
        "uncertain": [item.after_seed for item in analysis.uncertain_boundaries],
        "non_separating": [
            item.after_seed for item in analysis.non_separating_boundaries
        ],
        "complete_boundary_count": len(analysis.boundary_assessments),
        "persisted_boundary_analysis_sha256": _canonical_sha256(
            upgraded_pack.get("boundary_analysis") or {}
        ),
    }


def _order_snapshot(
    analysis: CheatSheetAnalysis, upgraded_pack: Mapping[str, Any], cohort: str
) -> dict[str, Any]:
    return {
        "baseline_order": list(analysis.baseline_order),
        "suggested_order": list(analysis.suggested_order),
        "effective_order": list(analysis.ordered_ids),
        "manual_override": analysis.manual_override,
        "manual_holds": list(analysis.manual_holds),
        "saved_manual_seed_order": upgraded_pack.get("manual_seed_orders", {}).get(
            cohort
        ),
    }


def _violation_payload(item: PlanViolation) -> dict[str, Any]:
    return {
        "flight_number": item.flight_number,
        "pairing": _pair_payload(item.pairing),
        "expected_goal_difference_excess": item.expected_goal_difference_excess,
        "blowout_probability_excess": item.blowout_probability_excess,
    }


def _team_exposure_payload(item: TeamPlanExposure) -> dict[str, Any]:
    return {
        "team": _team_payload(item.team),
        "selected_order_position": item.selected_order_position,
        "flight_number": item.flight_number,
        "potential_opponent_count": item.potential_opponent_count,
        "available_prediction_count": item.available_prediction_count,
        "missing_prediction_count": item.missing_prediction_count,
        "invalid_prediction_count": item.invalid_prediction_count,
        "over_limit_opponent_count": item.over_limit_opponent_count,
        "limited_or_unknown_evidence_opponent_count": (
            item.limited_or_unknown_evidence_opponent_count
        ),
        "worst_projected_matchup": (
            _pair_payload(item.worst_projected_matchup)
            if item.worst_projected_matchup is not None
            else None
        ),
        "violating_pair_keys": [
            "::".join(violation.pairing.entrant_ids)
            for violation in item.violating_matchups
        ],
    }


def _plan_payload(item: FlightPlanAssessment) -> dict[str, Any]:
    return {
        "plan_id": item.plan_id,
        "flight_sizes": list(item.flight_sizes),
        "selected_order": list(item.selected_order),
        "structural_validity": asdict(item.structural),
        "accepted_field_coverage": asdict(item.accepted_field_coverage),
        "prediction_completeness": {
            "complete": item.prediction_complete,
            "conclusion": item.prediction_conclusion,
            "reason": item.prediction_reason,
            "required_unique_pairing_count": item.required_unique_pairing_count,
            "available_unique_pairing_count": item.available_unique_pairing_count,
            "missing_prediction_count": item.missing_prediction_count,
            "invalid_prediction_count": item.invalid_prediction_count,
        },
        "projected_fit": {
            "all_pair_projected_fit_passed": item.all_pair_projected_fit_passed,
            "violating_pairing_count": item.violating_pairing_count,
            "known_violating_fraction_of_required_lower_bound": (
                item.known_violating_fraction_of_required_lower_bound
            ),
            "violating_fraction_of_available_predictions": (
                item.violating_fraction_of_available_predictions
            ),
            "violation_fraction_note": (
                "The available-prediction denominator is the reported violation "
                "percentage when predictions are incomplete. Missing predictions do "
                "not count as safe and the required-pair fraction is only a lower bound."
            ),
            "pair_weighted_average_expected_absolute_goal_difference": (
                item.pair_weighted_average_expected_absolute_goal_difference
            ),
            "pair_weighted_average_blowout_4plus_probability": (
                item.pair_weighted_average_blowout_probability
            ),
            "pair_weighted_average_matchup_cost": (
                item.pair_weighted_average_matchup_cost
            ),
            "maximum_expected_absolute_goal_difference": (
                item.maximum_expected_absolute_goal_difference
            ),
            "maximum_expected_absolute_goal_difference_matchup": (
                _pair_payload(item.maximum_expected_absolute_goal_difference_matchup)
                if item.maximum_expected_absolute_goal_difference_matchup is not None
                else None
            ),
            "maximum_blowout_4plus_probability": item.maximum_blowout_probability,
            "maximum_blowout_probability_matchup": (
                _pair_payload(item.maximum_blowout_probability_matchup)
                if item.maximum_blowout_probability_matchup is not None
                else None
            ),
            "worst_matchup_cost": item.worst_matchup_cost,
            "worst_matchup": (
                _pair_payload(item.worst_matchup)
                if item.worst_matchup is not None
                else None
            ),
        },
        "evidence": {
            "established_history_pairing_count": (
                item.established_history_pairing_count
            ),
            "limited_history_pairing_count": item.limited_history_pairing_count,
            "unknown_history_pairing_count": item.unknown_history_pairing_count,
            "limitations": list(item.evidence_limitations),
        },
        "flights": [
            {
                "flight_number": flight.flight_number,
                "start_order_position": flight.start_order_position,
                "end_order_position": flight.end_order_position,
                "requested_size": flight.requested_size,
                "entrant_ids": list(flight.entrant_ids),
                "complete_group_assessment": _group_payload(flight.group),
            }
            for flight in item.flights
        ],
        "violations": [_violation_payload(value) for value in item.violations],
        "missing_prediction_pairings": [
            _pair_payload(value) for value in item.missing_prediction_pairings
        ],
        "invalid_prediction_pairings": [
            _pair_payload(value) for value in item.invalid_prediction_pairings
        ],
        "team_exposures": [
            _team_exposure_payload(value) for value in item.team_exposures
        ],
    }


def _comparison_payload(item: AlternativeComparison) -> dict[str, Any]:
    return {
        "flight_size_multiset": list(item.flight_size_multiset),
        "plan_ids": list(item.plan_ids),
        "eligible_plan_ids": list(item.eligible_plan_ids),
        "nondominated_plan_ids": list(item.nondominated_plan_ids),
        "dominance": [asdict(value) for value in item.dominance],
        "only_one_permitted_arrangement": item.only_one_permitted_arrangement,
        "explanation": item.explanation,
    }


def _all_opponent_payload(item: AllOpponentAssessment) -> dict[str, Any]:
    return {
        "team": _team_payload(item.team),
        "possible_opponent_count": item.possible_opponent_count,
        "available_prediction_count": item.available_prediction_count,
        "missing_prediction_count": item.missing_prediction_count,
        "invalid_prediction_count": item.invalid_prediction_count,
        "within_policy_opponents": [
            _team_payload(value) for value in item.within_policy_opponents
        ],
        "established_history_within_policy_opponents": [
            _team_payload(value)
            for value in item.established_history_within_policy_opponents
        ],
        "limited_or_unknown_history_within_policy_opponents": [
            _team_payload(value)
            for value in item.limited_or_unknown_history_within_policy_opponents
        ],
        "complete_prediction_coverage": item.complete_prediction_coverage,
        "complete_predictions_establish_no_within_policy_opponent": (
            item.complete_predictions_establish_no_within_policy_opponent
        ),
        "explanation": item.explanation,
    }


def _scenario_payload(
    scenario_id: str,
    request: StructureRequest,
    assessment: FlightPlanSetAssessment,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "label": request.label,
        "mode": request.mode,
        "requested_structures": [
            list(item) for item in request.requested_structures
        ],
        "enumeration": asdict(assessment.enumeration),
        "conclusion": assessment.conclusion,
        "no_all_pair_within_policy_plan_among_evaluated": (
            assessment.no_all_pair_within_policy_plan_among_evaluated
        ),
        "no_all_pair_within_policy_plan_among_permitted": (
            assessment.no_all_pair_within_policy_plan_among_permitted
        ),
        "plans": [_plan_payload(item) for item in assessment.plans],
        "comparisons": [
            _comparison_payload(item) for item in assessment.comparisons
        ],
        "all_opponent_assessments": [
            _all_opponent_payload(item)
            for item in assessment.all_opponent_assessments
        ],
    }


def _source_policy_provenance(
    original_pack: Mapping[str, Any], upgraded_pack: Mapping[str, Any]
) -> dict[str, Any]:
    saved = original_pack.get("policy") or {}
    effective = upgraded_pack["policy"]
    return {
        "values": effective,
        "field_provenance": {
            key: "saved_snapshot" if key in saved else "schema_default_on_upgrade"
            for key in effective
        },
        "saved_snapshot_values": saved,
        "pair_pass_rule": (
            "expected_absolute_goal_difference <= max_expected_margin AND "
            "blowout_4plus_probability <= max_blowout_probability"
        ),
        "limits_are_inclusive": True,
        "matchup_cost_rule": (
            "expected_absolute_goal_difference + blowout_cost_weight * "
            "blowout_4plus_probability"
        ),
    }


def build_report(
    *,
    snapshot_path: Path,
    cohort: str,
    event_name: str,
    report_slug: str,
    requests: Sequence[StructureRequest],
    order_source: str | None,
    expected_source_sha256: str | None,
    expected_predictor_sha256: str | None,
    max_arrangements: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reanalyze one frozen snapshot and return standalone report records."""
    head = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    if branch != EXPECTED_BRANCH:
        raise ValueError(
            f"Run this diagnostic from {EXPECTED_BRANCH!r}, not {branch!r}"
        )
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_COMMIT, head], check=True
    )
    loaded = load_frozen_snapshot(
        snapshot_path,
        cohort,
        expected_source_sha256=expected_source_sha256,
        expected_predictor_sha256=expected_predictor_sha256,
    )
    analysis = loaded["analysis"]
    original_pack = loaded["original_pack"]
    upgraded_pack = loaded["upgraded_pack"]
    accepted_ids = _accepted_entrant_ids(loaded, cohort)
    selected = select_saved_order(analysis, accepted_ids, order_source)
    metadata = build_team_metadata(loaded, cohort, accepted_ids)
    policy = TierPolicy(**upgraded_pack["policy"])
    before_order = _order_snapshot(analysis, upgraded_pack, cohort)
    before_boundary = _boundary_snapshot(analysis, upgraded_pack)
    before_policy = dict(upgraded_pack["policy"])
    scenarios = []
    for index, request in enumerate(requests, start=1):
        enumeration = enumerate_arrangements(
            request.mode,
            request.requested_structures,
            len(selected.entrant_ids),
            max_arrangements=max_arrangements,
        )
        assessment = assess_permitted_plans(
            enumeration,
            selected.entrant_ids,
            loaded["predictions"],
            policy,
            metadata,
            accepted_entrant_ids=accepted_ids,
            unassigned_entrants=selected.unassigned_entrants,
        )
        scenario_id = f"scenario-{index:02d}-{_slug(request.label)}"
        scenarios.append(_scenario_payload(scenario_id, request, assessment))

    after_source_sha256 = _sha256_bytes(snapshot_path.resolve().read_bytes())
    after_order = _order_snapshot(analysis, upgraded_pack, cohort)
    after_boundary = _boundary_snapshot(analysis, upgraded_pack)
    after_policy = dict(upgraded_pack["policy"])
    if loaded["source_sha256"] != after_source_sha256:
        raise RuntimeError("The frozen source file changed during analysis")
    if before_order != after_order:
        raise RuntimeError("Saved order state changed during plan evaluation")
    if before_boundary != after_boundary:
        raise RuntimeError("Boundary state changed during plan evaluation")
    if before_policy != after_policy:
        raise RuntimeError("Policy changed during plan evaluation")

    frozen_payload = {
        "teams": original_pack["teams"][cohort],
        "predictions": original_pack["predictions"][cohort],
        "ratings": original_pack["ratings"],
        "policy": original_pack["policy"],
        "generated_at": original_pack["generated_at"],
        "ratings_as_of": original_pack["ratings_as_of"],
        "predictor_sha256": original_pack["predictor_sha256"],
    }
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": (
            "Internal complete-flight potential-matchup assessment. Pair counts are "
            "unique possible matchups, not scheduled games. No operational format, "
            "membership swap, threshold change, or customer display decision is implied."
        ),
        "event_name": event_name,
        "report_slug": _slug(report_slug),
        "cohort": cohort,
        "code": {
            "commit": head,
            "starting_commit": STARTING_COMMIT,
            "branch": branch,
            "starting_commit_is_ancestor": True,
            "working_tree_clean_at_export": not bool(_git("status", "--short")),
            "pack_schema_version": PACK_SCHEMA_VERSION,
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        },
        "snapshot_provenance": {
            "source_path": str(snapshot_path.resolve()),
            "source_file_sha256_before": loaded["source_sha256"],
            "source_file_sha256_after": after_source_sha256,
            "source_unchanged_during_analysis": (
                loaded["source_sha256"] == after_source_sha256
            ),
            "embedded_pack_sha256": _canonical_sha256(original_pack),
            "frozen_cohort_payload_sha256": _canonical_sha256(frozen_payload),
            "frozen_prediction_records_sha256": _canonical_sha256(
                original_pack["predictions"][cohort]
            ),
            "source_pack_schema_version": original_pack["schema_version"],
            "source_analysis_schema_version": original_pack[
                "analysis_schema_version"
            ],
            "reanalysis_pack_schema_version": upgraded_pack["schema_version"],
            "reanalysis_analysis_schema_version": upgraded_pack[
                "analysis_schema_version"
            ],
            "snapshot_generated_at": original_pack["generated_at"],
            "ratings_as_of": original_pack["ratings_as_of"],
            "predictor_sha256": original_pack["predictor_sha256"],
            "frozen_team_record_count": len(original_pack["teams"][cohort]),
            "accepted_cohort_team_count": len(accepted_ids),
            "frozen_directional_prediction_record_count": len(
                original_pack["predictions"][cohort]
            ),
            "network_access": "blocked by frozen-snapshot loader",
        },
        "effective_policy": _source_policy_provenance(
            original_pack, upgraded_pack
        ),
        "order_and_boundary_regression": {
            "order_source_selected": selected.source,
            "selected_order": list(selected.entrant_ids),
            "accepted_entrant_ids": list(accepted_ids),
            "unassigned_entrants": [
                asdict(item) for item in selected.unassigned_entrants
            ],
            "before_order_state": before_order,
            "after_order_state": after_order,
            "order_state_unchanged": before_order == after_order,
            "before_boundary_state": before_boundary,
            "after_boundary_state": after_boundary,
            "boundary_state_unchanged": before_boundary == after_boundary,
            "policy_unchanged": before_policy == after_policy,
        },
        "accepted_teams": [
            _team_payload(metadata[entrant_id]) for entrant_id in accepted_ids
        ],
        "requested_scenarios": [
            {
                "label": item.label,
                "mode": item.mode,
                "requested_structures": [
                    list(structure) for structure in item.requested_structures
                ],
            }
            for item in requests
        ],
        "scenarios": scenarios,
    }
    report["content_sha256"] = _canonical_sha256(report)
    return report, _csv_rows(report)


def _pair_csv_fields(pair: Mapping[str, Any] | None) -> dict[str, Any]:
    if pair is None:
        return {}
    first = pair["first_team"]
    second = pair["second_team"]
    return {
        "pair_key": pair["pair_key"],
        "first_suggested_seed": first["seed"],
        "first_entrant_id": first["entrant_id"],
        "first_team_name": first["team_name"],
        "first_team_id_master": first["team_id_master"],
        "first_history_quality": first["history_quality"],
        "second_suggested_seed": second["seed"],
        "second_entrant_id": second["entrant_id"],
        "second_team_name": second["team_name"],
        "second_team_id_master": second["team_id_master"],
        "second_history_quality": second["history_quality"],
        "prediction_status": pair["prediction_status"],
        "prediction_issue": pair["prediction_issue"],
        "expected_signed_margin_toward_first": (
            pair["expected_signed_margin_toward_first"]
        ),
        "expected_absolute_goal_difference": (
            pair["expected_absolute_goal_difference"]
        ),
        "blowout_4plus_probability": pair["blowout_4plus_probability"],
        "matchup_cost": pair["matchup_cost"],
        "within_expected_goal_difference_limit": (
            pair["within_expected_goal_difference_limit"]
        ),
        "within_blowout_probability_limit": (
            pair["within_blowout_probability_limit"]
        ),
        "within_both_limits": pair["within_both_limits"],
        "pair_history_quality": pair["history_quality"],
        "provisional_due_to_history": pair["provisional_due_to_history"],
        "outcome_confidence": pair["outcome_confidence"],
        "outcome_confidence_score": pair["outcome_confidence_score"],
    }


def _plan_csv_common(plan: Mapping[str, Any]) -> dict[str, Any]:
    coverage = plan["accepted_field_coverage"]
    completeness = plan["prediction_completeness"]
    fit = plan["projected_fit"]
    evidence = plan["evidence"]
    return {
        "plan_id": plan["plan_id"],
        "flight_sizes": "|".join(str(value) for value in plan["flight_sizes"]),
        "structural_valid": plan["structural_validity"]["valid"],
        "full_accepted_field_coverage": coverage["full_accepted_field_coverage"],
        "plan_for_assigned_subset": coverage["plan_for_assigned_subset"],
        "field_coverage_reason": coverage["reason"],
        "prediction_complete": completeness["complete"],
        "prediction_conclusion": completeness["conclusion"],
        "prediction_reason": completeness["reason"],
        "required_unique_pairing_count": completeness[
            "required_unique_pairing_count"
        ],
        "available_unique_pairing_count": completeness[
            "available_unique_pairing_count"
        ],
        "missing_prediction_count": completeness["missing_prediction_count"],
        "invalid_prediction_count": completeness["invalid_prediction_count"],
        "all_pair_projected_fit_passed": fit[
            "all_pair_projected_fit_passed"
        ],
        "violating_pairing_count": fit["violating_pairing_count"],
        "known_violating_fraction_of_required_lower_bound": fit[
            "known_violating_fraction_of_required_lower_bound"
        ],
        "violating_fraction_of_available_predictions": fit[
            "violating_fraction_of_available_predictions"
        ],
        "pair_weighted_average_expected_absolute_goal_difference": fit[
            "pair_weighted_average_expected_absolute_goal_difference"
        ],
        "pair_weighted_average_blowout_4plus_probability": fit[
            "pair_weighted_average_blowout_4plus_probability"
        ],
        "pair_weighted_average_matchup_cost": fit[
            "pair_weighted_average_matchup_cost"
        ],
        "maximum_expected_absolute_goal_difference": fit[
            "maximum_expected_absolute_goal_difference"
        ],
        "maximum_expected_absolute_goal_difference_pair_key": (
            (fit["maximum_expected_absolute_goal_difference_matchup"] or {}).get(
                "pair_key"
            )
        ),
        "maximum_blowout_4plus_probability": fit[
            "maximum_blowout_4plus_probability"
        ],
        "maximum_blowout_probability_pair_key": (
            (fit["maximum_blowout_probability_matchup"] or {}).get("pair_key")
        ),
        "worst_matchup_cost": fit["worst_matchup_cost"],
        "worst_matchup_pair_key": (fit["worst_matchup"] or {}).get("pair_key"),
        "established_history_pairing_count": evidence[
            "established_history_pairing_count"
        ],
        "limited_history_pairing_count": evidence[
            "limited_history_pairing_count"
        ],
        "unknown_history_pairing_count": evidence[
            "unknown_history_pairing_count"
        ],
        "evidence_limitations": " | ".join(evidence["limitations"]),
    }


def _csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = report["snapshot_provenance"]
    common = {
        "event": report["event_name"],
        "cohort": report["cohort"],
        "code_commit": report["code"]["commit"],
        "source_file_sha256": provenance["source_file_sha256_before"],
        "predictor_sha256": provenance["predictor_sha256"],
        "order_source": report["order_and_boundary_regression"][
            "order_source_selected"
        ],
    }
    rows: list[dict[str, Any]] = []
    for scenario in report["scenarios"]:
        enumeration = scenario["enumeration"]
        scenario_common = {
            **common,
            "scenario_id": scenario["scenario_id"],
            "scenario_label": scenario["label"],
            "structure_mode": scenario["mode"],
            "requested_structures": json.dumps(
                scenario["requested_structures"], separators=(",", ":")
            ),
            "scenario_conclusion": scenario["conclusion"],
            "search_complete": enumeration["search_complete"],
            "total_distinct_arrangement_count": enumeration[
                "total_distinct_arrangement_count"
            ],
            "evaluated_arrangement_count": enumeration[
                "evaluated_arrangement_count"
            ],
            "search_diagnostic": enumeration["diagnostic"],
        }
        rows.append({**scenario_common, "record_type": "scenario_summary"})
        for plan in scenario["plans"]:
            plan_common = {**scenario_common, **_plan_csv_common(plan)}
            rows.append({**plan_common, "record_type": "plan_summary"})
            for flight in plan["flights"]:
                group = flight["complete_group_assessment"]
                fit = group["projected_competitive_fit"]
                evidence = group["evidence_coverage_and_limitations"]
                flight_common = {
                    **plan_common,
                    "flight_number": flight["flight_number"],
                    "flight_start_order_position": flight[
                        "start_order_position"
                    ],
                    "flight_end_order_position": flight["end_order_position"],
                    "flight_requested_size": flight["requested_size"],
                    "flight_entrant_ids": "|".join(flight["entrant_ids"]),
                    "flight_team_names": "|".join(
                        team["team_name"] for team in group["teams"]
                    ),
                    "flight_fit_conclusion": fit["conclusion"],
                    "flight_fit_reason": fit["reason"],
                    "flight_required_pair_count": fit[
                        "expected_unique_pairing_count"
                    ],
                    "flight_available_pair_count": fit[
                        "available_unique_pairing_count"
                    ],
                    "flight_over_limit_count": fit[
                        "exceeding_either_limit_count"
                    ],
                    "flight_all_pair_fit_passed": fit[
                        "all_pair_projected_fit_passed"
                    ],
                    "flight_evidence_limitations": " | ".join(
                        evidence["limitations"]
                    ),
                }
                rows.append(
                    {**flight_common, "record_type": "flight_summary"}
                )
                for pair in group["pairings"]:
                    rows.append(
                        {
                            **flight_common,
                            "record_type": "flight_pair",
                            **_pair_csv_fields(pair),
                        }
                    )
            for violation in plan["violations"]:
                rows.append(
                    {
                        **plan_common,
                        "record_type": "violation",
                        "flight_number": violation["flight_number"],
                        "expected_goal_difference_excess": violation[
                            "expected_goal_difference_excess"
                        ],
                        "blowout_probability_excess": violation[
                            "blowout_probability_excess"
                        ],
                        **_pair_csv_fields(violation["pairing"]),
                    }
                )
            for exposure in plan["team_exposures"]:
                team = exposure["team"]
                worst = exposure["worst_projected_matchup"]
                rows.append(
                    {
                        **plan_common,
                        "record_type": "team_exposure",
                        "flight_number": exposure["flight_number"],
                        "selected_order_position": exposure[
                            "selected_order_position"
                        ],
                        "team_entrant_id": team["entrant_id"],
                        "team_name": team["team_name"],
                        "team_id_master": team["team_id_master"],
                        "team_suggested_seed": team["seed"],
                        "team_history_quality": team["history_quality"],
                        "potential_opponent_count": exposure[
                            "potential_opponent_count"
                        ],
                        "available_prediction_count": exposure[
                            "available_prediction_count"
                        ],
                        "team_missing_prediction_count": exposure[
                            "missing_prediction_count"
                        ],
                        "team_invalid_prediction_count": exposure[
                            "invalid_prediction_count"
                        ],
                        "over_limit_opponent_count": exposure[
                            "over_limit_opponent_count"
                        ],
                        "limited_or_unknown_evidence_opponent_count": exposure[
                            "limited_or_unknown_evidence_opponent_count"
                        ],
                        "team_worst_matchup_pair_key": (
                            (worst or {}).get("pair_key")
                        ),
                        "team_worst_matchup_cost": (
                            (worst or {}).get("matchup_cost")
                        ),
                        "team_violating_pair_keys": "|".join(
                            exposure["violating_pair_keys"]
                        ),
                    }
                )
            for unassigned in plan["accepted_field_coverage"][
                "unassigned_entrants"
            ]:
                rows.append(
                    {
                        **plan_common,
                        "record_type": "unassigned_entrant",
                        "team_entrant_id": unassigned["entrant_id"],
                        "unassigned_reason": unassigned["reason"],
                    }
                )
        for comparison in scenario["comparisons"]:
            dominance_by_id = {
                item["plan_id"]: item for item in comparison["dominance"]
            }
            for plan_id in comparison["plan_ids"]:
                dominance = dominance_by_id[plan_id]
                rows.append(
                    {
                        **scenario_common,
                        "record_type": "alternative_comparison",
                        "comparison_flight_size_multiset": "|".join(
                            str(value)
                            for value in comparison["flight_size_multiset"]
                        ),
                        "plan_id": plan_id,
                        "comparison_eligible": dominance[
                            "comparison_eligible"
                        ],
                        "comparison_ineligibility_reason": dominance[
                            "comparison_ineligibility_reason"
                        ],
                        "dominated_by_plan_ids": "|".join(
                            dominance["dominated_by_plan_ids"]
                        ),
                        "nondominated": dominance["nondominated"],
                        "comparison_explanation": comparison["explanation"],
                    }
                )
        for assessment in scenario["all_opponent_assessments"]:
            team = assessment["team"]
            rows.append(
                {
                    **scenario_common,
                    "record_type": "all_opponent_assessment",
                    "team_entrant_id": team["entrant_id"],
                    "team_name": team["team_name"],
                    "team_id_master": team["team_id_master"],
                    "team_suggested_seed": team["seed"],
                    "team_history_quality": team["history_quality"],
                    "possible_opponent_count": assessment[
                        "possible_opponent_count"
                    ],
                    "available_prediction_count": assessment[
                        "available_prediction_count"
                    ],
                    "team_missing_prediction_count": assessment[
                        "missing_prediction_count"
                    ],
                    "team_invalid_prediction_count": assessment[
                        "invalid_prediction_count"
                    ],
                    "within_policy_opponent_count": len(
                        assessment["within_policy_opponents"]
                    ),
                    "within_policy_opponent_ids": "|".join(
                        item["entrant_id"]
                        for item in assessment["within_policy_opponents"]
                    ),
                    "complete_all_opponent_prediction_coverage": assessment[
                        "complete_prediction_coverage"
                    ],
                    "no_within_policy_opponent": assessment[
                        "complete_predictions_establish_no_within_policy_opponent"
                    ],
                    "all_opponent_explanation": assessment["explanation"],
                }
            )
    return rows


def _format_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _format_percent(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.1%}"


def _pair_name(pair: Mapping[str, Any] | None) -> str:
    if pair is None:
        return "n/a"
    first = pair["first_team"]
    second = pair["second_team"]
    return (
        f"seed {first['seed']} {first['team_name']} vs "
        f"seed {second['seed']} {second['team_name']}"
    )


def _markdown_report(report: Mapping[str, Any]) -> str:
    provenance = report["snapshot_provenance"]
    regression = report["order_and_boundary_regression"]
    policy = report["effective_policy"]["values"]
    lines = [
        f"# {report['event_name']} complete flight-plan analysis",
        "",
        report["scope"],
        "",
        "## Provenance and frozen inputs",
        "",
        f"- Code commit: `{report['code']['commit']}`",
        f"- Branch: `{report['code']['branch']}`",
        f"- Source snapshot: `{provenance['source_path']}`",
        f"- Source SHA-256: `{provenance['source_file_sha256_before']}`",
        f"- Frozen cohort payload SHA-256: "
        f"`{provenance['frozen_cohort_payload_sha256']}`",
        f"- Frozen prediction records SHA-256: "
        f"`{provenance['frozen_prediction_records_sha256']}`",
        f"- Predictor SHA-256: `{provenance['predictor_sha256']}`",
        f"- Schema versions: source pack {provenance['source_pack_schema_version']}, "
        f"source analysis {provenance['source_analysis_schema_version']}, "
        f"reanalysis pack {provenance['reanalysis_pack_schema_version']}, "
        f"reanalysis analysis {provenance['reanalysis_analysis_schema_version']}",
        f"- Selected order source: `{regression['order_source_selected']}`",
        f"- Frozen source unchanged during analysis: "
        f"{provenance['source_unchanged_during_analysis']}",
        f"- Baseline/suggested/effective state unchanged: "
        f"{regression['order_state_unchanged']}",
        f"- Boundary state unchanged: {regression['boundary_state_unchanged']}",
        f"- Policy unchanged: {regression['policy_unchanged']}",
        "",
        "## Effective matchup policy",
        "",
        "```json",
        json.dumps(policy, indent=2, sort_keys=True),
        "```",
        "",
        "A pairing passes only when expected absolute goal difference and 4+ goal "
        "blowout probability both meet their saved inclusive limits. Matchup cost "
        "uses the existing policy calculation unchanged.",
        "",
        "## Selected order and field coverage",
        "",
        "| Position | Suggested seed | Entrant ID | Team | PowerScore | History |",
        "|---:|---:|---|---|---:|---|",
    ]
    teams = {item["entrant_id"]: item for item in report["accepted_teams"]}
    for position, entrant_id in enumerate(regression["selected_order"], start=1):
        team = teams[entrant_id]
        lines.append(
            f"| {position} | {team['seed'] or 'n/a'} | {entrant_id} | "
            f"{team['team_name']} | {_format_number(team['power_score'], 4)} | "
            f"{team['history_quality']} |"
        )
    if regression["unassigned_entrants"]:
        lines.extend(["", "Unassigned accepted entrants:", ""])
        for item in regression["unassigned_entrants"]:
            lines.append(
                f"- {teams[item['entrant_id']]['team_name']} "
                f"(`{item['entrant_id']}`): {item['reason']}"
            )
    else:
        lines.extend(["", "All accepted entrants are in the selected order."])

    lines.extend(["", "## Scenario results", ""])
    for scenario in report["scenarios"]:
        enumeration = scenario["enumeration"]
        lines.extend(
            [
                f"### {scenario['label']}",
                "",
                f"Mode: `{scenario['mode']}`. Requested structures: "
                f"`{scenario['requested_structures']}`. Evaluated "
                f"{enumeration['evaluated_arrangement_count']} of "
                f"{enumeration['total_distinct_arrangement_count']} distinct "
                f"arrangement(s). Search complete: {enumeration['search_complete']}.",
                "",
                scenario["conclusion"],
                "",
            ]
        )
        if enumeration["diagnostic"]:
            lines.extend([f"Search diagnostic: {enumeration['diagnostic']}", ""])
        lines.extend(
            [
                "| Plan | Flight sizes | Coverage | Predictions | Violations | "
                "Average goal diff | Average blowout | Average cost | Worst cost |",
                "|---|---|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for plan in scenario["plans"]:
            coverage = plan["accepted_field_coverage"]
            completeness = plan["prediction_completeness"]
            fit = plan["projected_fit"]
            lines.append(
                f"| {plan['plan_id']} | {plan['flight_sizes']} | "
                f"{'full field' if coverage['full_accepted_field_coverage'] else 'subset/incomplete'} | "
                f"{'complete' if completeness['complete'] else 'incomplete'} | "
                f"{fit['violating_pairing_count']}/"
                f"{completeness['available_unique_pairing_count']} available | "
                f"{_format_number(fit['pair_weighted_average_expected_absolute_goal_difference'])} | "
                f"{_format_percent(fit['pair_weighted_average_blowout_4plus_probability'])} | "
                f"{_format_number(fit['pair_weighted_average_matchup_cost'])} | "
                f"{_format_number(fit['worst_matchup_cost'])} |"
            )
        for comparison in scenario["comparisons"]:
            lines.extend(
                [
                    "",
                    f"Comparison for multiset `{comparison['flight_size_multiset']}`: "
                    f"nondominated plan(s) "
                    f"`{comparison['nondominated_plan_ids']}`. "
                    f"{comparison['explanation']}",
                ]
            )
        for plan in scenario["plans"]:
            completeness = plan["prediction_completeness"]
            fit = plan["projected_fit"]
            evidence = plan["evidence"]
            coverage = plan["accepted_field_coverage"]
            lines.extend(
                [
                    "",
                    f"#### {plan['plan_id']} — sizes {plan['flight_sizes']}",
                    "",
                    f"Structural validity: {plan['structural_validity']['valid']}. "
                    f"Field coverage: {coverage['reason']}",
                    "",
                    f"Prediction result: {completeness['reason']}",
                    "",
                    f"Worst matchup cost: {_format_number(fit['worst_matchup_cost'])} "
                    f"({_pair_name(fit['worst_matchup'])}). Maximum expected absolute "
                    f"goal difference: "
                    f"{_format_number(fit['maximum_expected_absolute_goal_difference'])} "
                    f"({_pair_name(fit['maximum_expected_absolute_goal_difference_matchup'])}). "
                    f"Maximum blowout probability: "
                    f"{_format_percent(fit['maximum_blowout_4plus_probability'])} "
                    f"({_pair_name(fit['maximum_blowout_probability_matchup'])}).",
                    "",
                    f"Evidence pairings: {evidence['established_history_pairing_count']} "
                    f"established, {evidence['limited_history_pairing_count']} limited, "
                    f"{evidence['unknown_history_pairing_count']} unknown.",
                    "",
                    "| Flight | Positions | Teams | Group result | Pairings | Violations |",
                    "|---:|---:|---|---|---:|---:|",
                ]
            )
            for flight in plan["flights"]:
                group = flight["complete_group_assessment"]
                group_fit = group["projected_competitive_fit"]
                names = ", ".join(
                    f"{team['seed']}. {team['team_name']}" for team in group["teams"]
                )
                lines.append(
                    f"| {flight['flight_number']} | "
                    f"{flight['start_order_position']}-{flight['end_order_position']} | "
                    f"{names} | {group_fit['conclusion']} | "
                    f"{group_fit['available_unique_pairing_count']}/"
                    f"{group_fit['expected_unique_pairing_count']} | "
                    f"{group_fit['exceeding_either_limit_count']} |"
                )
            if plan["violations"]:
                lines.extend(
                    [
                        "",
                        "Violating potential matchups:",
                        "",
                        "| Flight | Matchup | Goal diff | Goal excess | Blowout | "
                        "Blowout excess | Cost | History |",
                        "|---:|---|---:|---:|---:|---:|---:|---|",
                    ]
                )
                for violation in plan["violations"]:
                    pair = violation["pairing"]
                    lines.append(
                        f"| {violation['flight_number']} | {_pair_name(pair)} | "
                        f"{_format_number(pair['expected_absolute_goal_difference'])} | "
                        f"{_format_number(violation['expected_goal_difference_excess'])} | "
                        f"{_format_percent(pair['blowout_4plus_probability'])} | "
                        f"{_format_percent(violation['blowout_probability_excess'])} | "
                        f"{_format_number(pair['matchup_cost'])} | "
                        f"{pair['history_quality']} |"
                    )
            else:
                lines.extend(["", "No known pairing exceeds either saved limit."])
            if evidence["limitations"]:
                lines.extend(["", "Evidence limitations:", ""])
                lines.extend(f"- {item}" for item in evidence["limitations"])

    first_scenario = report["scenarios"][0]
    unresolved = [
        item
        for item in first_scenario["all_opponent_assessments"]
        if item["complete_predictions_establish_no_within_policy_opponent"]
    ]
    lines.extend(["", "## All-opponent diagnostics", ""])
    if unresolved:
        for item in unresolved:
            team = item["team"]
            lines.append(
                f"- Seed {team['seed']} {team['team_name']} (`{team['entrant_id']}`): "
                f"{item['explanation']}"
            )
    else:
        lines.append(
            "No entrant has complete frozen predictions showing zero within-policy "
            "opponents across the accepted field."
        )
    lines.extend(
        [
            "",
            "The JSON contains every complete-group pairing and per-team exposure. The "
            "CSV repeats provenance on flattened scenario, plan, flight, pairing, "
            "violation, exposure, comparison, and all-opponent records.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    preferred = (
        "record_type",
        "event",
        "cohort",
        "code_commit",
        "source_file_sha256",
        "predictor_sha256",
        "order_source",
        "scenario_id",
        "scenario_label",
        "structure_mode",
        "requested_structures",
        "search_complete",
        "plan_id",
        "flight_sizes",
        "flight_number",
        "flight_start_order_position",
        "flight_end_order_position",
        "flight_team_names",
        "team_suggested_seed",
        "team_entrant_id",
        "team_name",
        "pair_key",
        "first_suggested_seed",
        "first_team_name",
        "second_suggested_seed",
        "second_team_name",
        "expected_absolute_goal_difference",
        "expected_goal_difference_excess",
        "blowout_4plus_probability",
        "blowout_probability_excess",
        "matchup_cost",
        "within_both_limits",
        "pair_history_quality",
        "prediction_complete",
        "all_pair_projected_fit_passed",
        "violating_pairing_count",
    )
    all_fields = {key for row in rows for key in row}
    fieldnames = [key for key in preferred if key in all_fields]
    fieldnames.extend(sorted(all_fields - set(fieldnames)))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--report-slug", required=True)
    parser.add_argument(
        "--order-source", choices=("suggested", "effective"), default=None
    )
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-predictor-sha256")
    parser.add_argument(
        "--exact",
        action="append",
        default=[],
        help="Labeled exact ordered sizes, e.g. four-by-four=4,4,4,4",
    )
    parser.add_argument(
        "--permutations",
        action="append",
        default=[],
        help="Labeled permitted multiset, e.g. six-five-five=6,5,5",
    )
    parser.add_argument(
        "--alternatives",
        action="append",
        default=[],
        help="Labeled approved alternatives, e.g. options=8,8;4,4,4,4",
    )
    parser.add_argument("--max-arrangements", type=int, default=10_000)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    requests = build_structure_requests(
        args.exact, args.permutations, args.alternatives
    )
    report, rows = build_report(
        snapshot_path=args.snapshot,
        cohort=args.cohort,
        event_name=args.event_name,
        report_slug=args.report_slug,
        requests=requests,
        order_source=args.order_source,
        expected_source_sha256=args.expected_source_sha256,
        expected_predictor_sha256=args.expected_predictor_sha256,
        max_arrangements=args.max_arrangements,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['report_slug']}-flight-plan-analysis"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, rows)
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    print(f"JSON={json_path}")
    print(f"CSV={csv_path}")
    print(f"MARKDOWN={markdown_path}")
    print(f"CONTENT_SHA256={report['content_sha256']}")
    print(f"CSV_ROW_COUNT={len(rows)}")


if __name__ == "__main__":
    main()
