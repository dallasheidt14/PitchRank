"""Generate automatic MatchBalance flight suggestions from one frozen saved pack.

The command defaults to every cohort selected in the saved pack. It never fetches
current ratings or predictions, mutates the source pack, changes seed order, or
claims schedule feasibility.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.analyze_matchbalance_flight_plans import (  # noqa: E402
    _accepted_entrant_ids,
    _all_opponent_payload,
    _boundary_snapshot,
    _comparison_payload,
    _order_snapshot,
    _plan_payload,
    _slug,
    _source_policy_provenance,
    select_saved_order,
)
from scripts.analyze_matchbalance_groups import (  # noqa: E402
    _canonical_sha256,
    _git,
    _sha256_bytes,
    _team_payload,
    build_team_metadata,
    load_frozen_snapshot,
)
from src.tournaments.seeding_flight_suggestions import (  # noqa: E402
    AutomaticFlightSuggestion,
    suggest_automatic_flights,
)
from src.tournaments.seeding_format_library import (  # noqa: E402
    FormatLibrary,
    FormatLibraryValidation,
    format_library_payload,
    load_format_library,
    resolve_format_profile,
    validate_format_library,
)
from src.tournaments.seeding_pack import (  # noqa: E402
    ANALYSIS_SCHEMA_VERSION,
    PACK_SCHEMA_VERSION,
)
from src.tournaments.seeding_tiers import TierPolicy  # noqa: E402

STARTING_COMMIT = "bbf26fed2bfe319bb5be6cd1fe1759c752205b95"
EXPECTED_BRANCH = "fix/matchbalance-boundary-analysis"
REPORT_SCHEMA_VERSION = 1


def _saved_selected_cohorts(snapshot_path: Path) -> tuple[str, ...]:
    payload = json.loads(snapshot_path.resolve().read_text(encoding="utf-8"))
    selected = tuple(str(item) for item in payload["pack"]["selected_cohorts"])
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("The frozen pack needs distinct selected cohorts")
    return selected


def _plan_by_id(
    suggestion: AutomaticFlightSuggestion, plan_id: str | None
) -> Mapping[str, Any] | None:
    if plan_id is None or suggestion.assessment is None:
        return None
    plan = next(
        (item for item in suggestion.assessment.plans if item.plan_id == plan_id),
        None,
    )
    return _plan_payload(plan) if plan is not None else None


def _suggestion_payload(
    suggestion: AutomaticFlightSuggestion,
) -> dict[str, Any]:
    assessment = suggestion.assessment
    return {
        "status": suggestion.status,
        "primary_plan_id": suggestion.primary_plan_id,
        "best_evaluated_plan_id": suggestion.best_evaluated_plan_id,
        "primary_evidence_status": suggestion.primary_evidence_status,
        "selection_reason": suggestion.selection_reason,
        "operational_feasibility_note": suggestion.operational_feasibility_note,
        "candidate_generation": asdict(suggestion.generation),
        "primary_plan": _plan_by_id(suggestion, suggestion.primary_plan_id),
        "best_evaluated_plan": _plan_by_id(
            suggestion, suggestion.best_evaluated_plan_id
        ),
        "useful_alternatives": [
            asdict(item) for item in suggestion.useful_alternatives
        ],
        "nondominated_compromise_plan_ids": list(
            suggestion.compromise_plan_ids
        ),
        "nondominated_compromise_basis": (
            "Complete structurally valid plans are compared without a composite "
            "weight across flight count, violation count, worst matchup cost, and "
            "pair-weighted average matchup cost. Cross-flight-count comparisons "
            "are conditional on the effective profile and potential-matchup model."
        ),
        "incomplete_prediction_plan_ids": list(
            suggestion.incomplete_prediction_plan_ids
        ),
        "format_options_by_plan": [
            asdict(item) for item in suggestion.format_options
        ],
        "assessment": (
            {
                "conclusion": assessment.conclusion,
                "no_all_pair_within_policy_plan_among_evaluated": (
                    assessment.no_all_pair_within_policy_plan_among_evaluated
                ),
                "no_all_pair_within_policy_plan_among_generated": (
                    assessment.no_all_pair_within_policy_plan_among_permitted
                    if suggestion.generation.search_complete
                    else None
                ),
                "plans": [_plan_payload(item) for item in assessment.plans],
                "same_size_multiset_comparisons": [
                    _comparison_payload(item) for item in assessment.comparisons
                ],
                "all_opponent_assessments": [
                    _all_opponent_payload(item)
                    for item in assessment.all_opponent_assessments
                ],
            }
            if assessment is not None
            else None
        ),
    }


def _cohort_report(
    *,
    loaded: Mapping[str, Any],
    cohort: str,
    library: FormatLibrary,
    profile_id: str | None,
    order_source: str | None,
    max_candidate_structures: int | None,
) -> dict[str, Any]:
    analysis = loaded["analysis"]
    original_pack = loaded["original_pack"]
    upgraded_pack = loaded["upgraded_pack"]
    accepted_ids = _accepted_entrant_ids(loaded, cohort)
    selected = select_saved_order(analysis, accepted_ids, order_source)
    metadata = build_team_metadata(loaded, cohort, accepted_ids)
    competitive_policy = TierPolicy(**upgraded_pack["policy"])
    profile = resolve_format_profile(library, profile_id)

    before_order = _order_snapshot(analysis, upgraded_pack, cohort)
    before_boundary = _boundary_snapshot(analysis, upgraded_pack)
    before_policy = dict(upgraded_pack["policy"])
    suggestion = suggest_automatic_flights(
        selected.entrant_ids,
        loaded["predictions"],
        competitive_policy,
        metadata,
        library,
        profile,
        accepted_entrant_ids=accepted_ids,
        unassigned_entrants=selected.unassigned_entrants,
        max_candidate_structures=max_candidate_structures,
    )
    after_order = _order_snapshot(analysis, upgraded_pack, cohort)
    after_boundary = _boundary_snapshot(analysis, upgraded_pack)
    after_policy = dict(upgraded_pack["policy"])
    if before_order != after_order:
        raise RuntimeError("Saved order state changed during automatic evaluation")
    if before_boundary != after_boundary:
        raise RuntimeError("Boundary state changed during automatic evaluation")
    if before_policy != after_policy:
        raise RuntimeError("Competitive policy changed during automatic evaluation")

    return {
        "cohort": cohort,
        "accepted_team_count": len(accepted_ids),
        "assigned_team_count": len(selected.entrant_ids),
        "accepted_teams": [
            _team_payload(metadata[entrant_id]) for entrant_id in accepted_ids
        ],
        "effective_competitive_policy": _source_policy_provenance(
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
            "competitive_policy_unchanged": before_policy == after_policy,
        },
        "natural_separation_findings": {
            "meaning": (
                "Contextual findings from the existing boundary-analysis engine; "
                "they are not required cuts or certificates of within-flight fit."
            ),
            **before_boundary,
        },
        "automatic_flight_suggestion": _suggestion_payload(suggestion),
    }


def build_automatic_report(
    *,
    snapshot_path: Path,
    event_name: str,
    report_slug: str,
    cohorts: Sequence[str] | None,
    profile_id: str | None,
    order_source: str | None,
    expected_source_sha256: str | None,
    expected_predictor_sha256: str | None,
    max_candidate_structures: int | None,
    library_path: Path | None = None,
) -> dict[str, Any]:
    """Build a complete internal automatic-suggestion report."""
    head = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_COMMIT, head], check=True
    )

    snapshot_path = snapshot_path.resolve()
    source_bytes = snapshot_path.read_bytes()
    source_sha256 = _sha256_bytes(source_bytes)
    if (
        expected_source_sha256 is not None
        and source_sha256 != expected_source_sha256
    ):
        raise ValueError(
            f"Frozen source hash changed for {snapshot_path}: {source_sha256}"
        )
    selected_cohorts = _saved_selected_cohorts(snapshot_path)
    requested_cohorts = tuple(cohorts) if cohorts else selected_cohorts
    if not requested_cohorts or len(requested_cohorts) != len(
        set(requested_cohorts)
    ):
        raise ValueError("Requested cohorts must be a distinct non-empty sequence")
    unknown = tuple(item for item in requested_cohorts if item not in selected_cohorts)
    if unknown:
        raise ValueError(
            "Requested cohort(s) are not selected in the frozen pack: "
            + ", ".join(unknown)
        )

    library = load_format_library(library_path)
    validation = validate_format_library(library)
    profile = resolve_format_profile(library, profile_id)
    recommendation_policy = library.policies_by_id[
        profile.recommendation_policy_id
    ]

    cohort_reports = []
    loaded_by_cohort = {}
    for cohort in requested_cohorts:
        loaded = load_frozen_snapshot(
            snapshot_path,
            cohort,
            expected_source_sha256=source_sha256,
            expected_predictor_sha256=expected_predictor_sha256,
        )
        loaded_by_cohort[cohort] = loaded
        cohort_reports.append(
            _cohort_report(
                loaded=loaded,
                cohort=cohort,
                library=library,
                profile_id=profile.profile_id,
                order_source=order_source,
                max_candidate_structures=max_candidate_structures,
            )
        )

    source_sha256_after = _sha256_bytes(snapshot_path.read_bytes())
    if source_sha256 != source_sha256_after:
        raise RuntimeError("The frozen source file changed during analysis")
    first_loaded = loaded_by_cohort[requested_cohorts[0]]
    original_pack = first_loaded["original_pack"]
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": (
            "Internal automatic MatchBalance flight suggestions. Flights are "
            "contiguous partitions of the unchanged saved order. Pair counts are "
            "unique potential matchups, not scheduled games. Format compatibility "
            "does not establish operational schedule feasibility."
        ),
        "event_name": event_name,
        "report_slug": _slug(report_slug),
        "code": {
            "commit": head,
            "starting_commit": STARTING_COMMIT,
            "branch": branch,
            "implementation_branch": EXPECTED_BRANCH,
            "on_implementation_branch": branch == EXPECTED_BRANCH,
            "starting_commit_is_ancestor": True,
            "working_tree_clean_at_export": not bool(_git("status", "--short")),
            "pack_schema_version": PACK_SCHEMA_VERSION,
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        },
        "snapshot_provenance": {
            "source_path": str(snapshot_path),
            "source_file_sha256_before": source_sha256,
            "source_file_sha256_after": source_sha256_after,
            "source_unchanged_during_analysis": (
                source_sha256 == source_sha256_after
            ),
            "embedded_pack_sha256": _canonical_sha256(original_pack),
            "source_pack_schema_version": original_pack["schema_version"],
            "source_analysis_schema_version": original_pack[
                "analysis_schema_version"
            ],
            "reanalysis_pack_schema_version": first_loaded["upgraded_pack"][
                "schema_version"
            ],
            "reanalysis_analysis_schema_version": first_loaded["upgraded_pack"][
                "analysis_schema_version"
            ],
            "snapshot_generated_at": original_pack["generated_at"],
            "ratings_as_of": original_pack["ratings_as_of"],
            "predictor_sha256": original_pack["predictor_sha256"],
            "saved_selected_cohorts": list(selected_cohorts),
            "reanalyzed_cohorts": list(requested_cohorts),
            "network_access": "blocked by frozen-snapshot loader",
        },
        "format_library": format_library_payload(library, validation),
        "effective_profile": asdict(profile),
        "recommendation_policy": asdict(recommendation_policy),
        "profile_resolution": (
            "Explicit versioned event profile."
            if profile_id is not None
            else "Versioned MatchBalance default profile; no explicit event profile supplied."
        ),
        "cohorts": cohort_reports,
    }
    report["content_sha256"] = _canonical_sha256(report)
    return report


def _csv_common(report: Mapping[str, Any], cohort: Mapping[str, Any]) -> dict[str, Any]:
    suggestion = cohort["automatic_flight_suggestion"]
    provenance = report["snapshot_provenance"]
    return {
        "event": report["event_name"],
        "cohort": cohort["cohort"],
        "code_commit": report["code"]["commit"],
        "source_file_sha256": provenance["source_file_sha256_before"],
        "predictor_sha256": provenance["predictor_sha256"],
        "profile_id": report["effective_profile"]["profile_id"],
        "profile_version": report["effective_profile"]["version"],
        "recommendation_policy_id": report["recommendation_policy"]["policy_id"],
        "recommendation_policy_version": report["recommendation_policy"]["version"],
        "recommendation_status": suggestion["status"],
        "primary_plan_id": suggestion["primary_plan_id"],
        "search_complete": suggestion["candidate_generation"]["search_complete"],
    }


def _csv_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cohort in report["cohorts"]:
        common = _csv_common(report, cohort)
        suggestion = cohort["automatic_flight_suggestion"]
        generation = suggestion["candidate_generation"]
        rows.append(
            {
                **common,
                "record_type": "cohort_summary",
                "accepted_team_count": cohort["accepted_team_count"],
                "assigned_team_count": cohort["assigned_team_count"],
                "supported_flight_sizes": ",".join(
                    str(item) for item in generation["supported_flight_sizes"]
                ),
                "total_candidate_count": generation[
                    "total_distinct_structure_count"
                ],
                "evaluated_candidate_count": generation[
                    "generated_structure_count"
                ],
                "excluded_template_ids": ",".join(
                    item["template_id"]
                    for item in generation["excluded_templates"]
                ),
                "excluded_template_reasons": " | ".join(
                    f"{item['template_id']}: {item['reason']}"
                    for item in generation["excluded_templates"]
                ),
                "selection_reason": suggestion["selection_reason"],
            }
        )
        assessment = suggestion["assessment"]
        if assessment is None:
            continue
        format_by_plan = {
            item["plan_id"]: item for item in suggestion["format_options_by_plan"]
        }
        alternatives = {
            item["plan_id"]: item for item in suggestion["useful_alternatives"]
        }
        compromise_ids = set(suggestion["nondominated_compromise_plan_ids"])
        for plan in assessment["plans"]:
            fit = plan["projected_fit"]
            prediction = plan["prediction_completeness"]
            role = (
                "primary"
                if plan["plan_id"] == suggestion["primary_plan_id"]
                else "useful_alternative"
                if plan["plan_id"] in alternatives
                else "nondominated_compromise"
                if plan["plan_id"] in compromise_ids
                else "evaluated"
            )
            plan_common = {
                **common,
                "plan_id": plan["plan_id"],
                "plan_role": role,
                "flight_sizes": ",".join(str(item) for item in plan["flight_sizes"]),
                "flight_count": len(plan["flight_sizes"]),
                "prediction_complete": prediction["complete"],
                "all_pair_projected_fit_passed": fit[
                    "all_pair_projected_fit_passed"
                ],
                "required_unique_pairing_count": prediction[
                    "required_unique_pairing_count"
                ],
                "available_unique_pairing_count": prediction[
                    "available_unique_pairing_count"
                ],
                "missing_prediction_count": prediction["missing_prediction_count"],
                "invalid_prediction_count": prediction["invalid_prediction_count"],
                "violating_pairing_count": fit["violating_pairing_count"],
                "worst_matchup_cost": fit["worst_matchup_cost"],
                "pair_weighted_average_matchup_cost": fit[
                    "pair_weighted_average_matchup_cost"
                ],
                "maximum_expected_absolute_goal_difference": fit[
                    "maximum_expected_absolute_goal_difference"
                ],
                "maximum_blowout_4plus_probability": fit[
                    "maximum_blowout_4plus_probability"
                ],
            }
            rows.append({**plan_common, "record_type": "plan_summary"})
            plan_formats = format_by_plan[plan["plan_id"]]["flights"]
            for flight, formats in zip(
                plan["flights"], plan_formats, strict=True
            ):
                group = flight["complete_group_assessment"]
                group_fit = group["projected_competitive_fit"]
                flight_common = {
                    **plan_common,
                    "flight_number": flight["flight_number"],
                    "flight_start_order_position": flight[
                        "start_order_position"
                    ],
                    "flight_end_order_position": flight["end_order_position"],
                    "flight_team_count": flight["requested_size"],
                    "flight_entrant_ids": ",".join(flight["entrant_ids"]),
                    "flight_team_names": " | ".join(
                        item["team_name"] for item in group["teams"]
                    ),
                    "preferred_template_id": formats["preferred_template_id"],
                    "compatible_template_ids": ",".join(
                        formats["compatible_template_ids"]
                    ),
                    "flight_conclusion": group_fit["conclusion"],
                }
                rows.append({**flight_common, "record_type": "flight_summary"})
                for pairing in group["pairings"]:
                    rows.append(
                        {
                            **flight_common,
                            "record_type": "potential_matchup",
                            "pair_key": pairing["pair_key"],
                            "first_team_id": pairing["first_team"][
                                "team_id_master"
                            ],
                            "first_team_name": pairing["first_team"]["team_name"],
                            "first_seed": pairing["first_team"]["seed"],
                            "second_team_id": pairing["second_team"][
                                "team_id_master"
                            ],
                            "second_team_name": pairing["second_team"][
                                "team_name"
                            ],
                            "second_seed": pairing["second_team"]["seed"],
                            "expected_absolute_goal_difference": pairing[
                                "expected_absolute_goal_difference"
                            ],
                            "blowout_4plus_probability": pairing[
                                "blowout_4plus_probability"
                            ],
                            "matchup_cost": pairing["matchup_cost"],
                            "within_both_limits": pairing["within_both_limits"],
                            "history_quality": pairing["history_quality"],
                            "provisional_due_to_history": pairing[
                                "provisional_due_to_history"
                            ],
                        }
                    )
        for item in assessment["all_opponent_assessments"]:
            team = item["team"]
            rows.append(
                {
                    **common,
                    "record_type": "all_opponent_assessment",
                    "team_entrant_id": team["entrant_id"],
                    "team_id": team["team_id_master"],
                    "team_name": team["team_name"],
                    "team_seed": team["seed"],
                    "possible_opponent_count": item["possible_opponent_count"],
                    "available_prediction_count": item[
                        "available_prediction_count"
                    ],
                    "missing_prediction_count": item["missing_prediction_count"],
                    "invalid_prediction_count": item["invalid_prediction_count"],
                    "within_policy_opponent_count": len(
                        item["within_policy_opponents"]
                    ),
                    "no_within_policy_opponent": item[
                        "complete_predictions_establish_no_within_policy_opponent"
                    ],
                    "explanation": item["explanation"],
                }
            )

    validation = report["format_library"]["validation"]
    common_library = {
        "event": report["event_name"],
        "code_commit": report["code"]["commit"],
        "profile_id": report["effective_profile"]["profile_id"],
        "recommendation_policy_id": report["recommendation_policy"]["policy_id"],
    }
    for item in validation["template_results"]:
        rows.append(
            {
                **common_library,
                "record_type": "template_validation",
                "template_id": item["template_id"],
                "template_status": item["availability_status"],
                "template_usable": item["usable_in_profiles"],
                "validation_errors": " | ".join(item["errors"]),
                "validation_warnings": " | ".join(item["warnings"]),
            }
        )
    for item in validation["source_issues"]:
        rows.append(
            {
                **common_library,
                "record_type": "source_issue",
                "source_issue_id": item["issue_id"],
                "source_entry": item["source_entry"],
                "source_issue_status": item["status"],
                "source_issue_reason": item["reason"],
            }
        )
    return rows


def _format_number(value: Any, digits: int = 3) -> str:
    return "-" if value is None else f"{float(value):.{digits}f}"


def _markdown_report(report: Mapping[str, Any]) -> str:
    profile = report["effective_profile"]
    library = report["format_library"]
    lines = [
        f"# {report['event_name']} - automatic MatchBalance flight suggestions",
        "",
        f"- Code commit: `{report['code']['commit']}`",
        f"- Frozen source SHA-256: `{report['snapshot_provenance']['source_file_sha256_before']}`",
        f"- Predictor SHA-256: `{report['snapshot_provenance']['predictor_sha256']}`",
        f"- Format library: `{library['library_id']}` `{library['library_version']}` (`{library['source_sha256']}`)",
        f"- Effective profile: `{profile['profile_id']}` v{profile['version']}",
        "- Recommendation policy: "
        f"`{report['recommendation_policy']['policy_id']}` "
        f"v{report['recommendation_policy']['version']}",
        f"- Profile resolution: {report['profile_resolution']}",
        f"- Profile provenance: {profile['source_note']}",
        "",
        "The format profile is a MatchBalance product default based on the supplied "
        "reference. It is not labeled as an official/current event or governing-body "
        "rule set.",
        "",
        "Unresolved profile assumptions:",
        "",
        *(
            f"- {item}" for item in profile["unresolved_assumptions"]
        ),
        "",
        "## Format-library validation",
        "",
        "| Template | Teams | Pools | Status | Usable |",
        "|---|---:|---|---|---|",
    ]
    templates = {item["template_id"]: item for item in library["templates"]}
    for result in library["validation"]["template_results"]:
        template = templates[result["template_id"]]
        lines.append(
            f"| {result['template_id']} | {template['team_count']} | "
            f"{'/'.join(str(item) for item in template['pool_sizes'])} | "
            f"{result['availability_status']} | {result['usable_in_profiles']} |"
        )
    lines.extend(["", "Blocked or reference-only source issues:", ""])
    for issue in library["validation"]["source_issues"]:
        lines.append(
            f"- `{issue['issue_id']}` ({issue['status']}): {issue['reason']}"
        )

    for cohort in report["cohorts"]:
        suggestion = cohort["automatic_flight_suggestion"]
        generation = suggestion["candidate_generation"]
        assessment = suggestion["assessment"]
        regression = cohort["order_and_boundary_regression"]
        lines.extend(
            [
                "",
                f"## {cohort['cohort']}",
                "",
                f"- Status: **{suggestion['status']}**",
                f"- Accepted / assigned teams: {cohort['accepted_team_count']} / {cohort['assigned_team_count']}",
                f"- Order source: `{regression['order_source_selected']}`",
                f"- Order unchanged: {regression['order_state_unchanged']}",
                f"- Boundary analysis unchanged: {regression['boundary_state_unchanged']}",
                f"- Competitive policy unchanged: {regression['competitive_policy_unchanged']}",
                f"- Supported flight sizes: {', '.join(str(item) for item in generation['supported_flight_sizes'])}",
                "- Generated / total structures: "
                f"{generation['generated_structure_count']} / "
                f"{generation['total_distinct_structure_count']}",
                f"- Search complete: {generation['search_complete']}",
                "- Excluded template variants: "
                + (
                    "; ".join(
                        f"`{item['template_id']}` ({item['reason']})"
                        for item in generation["excluded_templates"]
                    )
                    or "none"
                ),
                f"- Selection: {suggestion['selection_reason']}",
                f"- Operational limitation: {suggestion['operational_feasibility_note']}",
                "",
                "Natural competitive separation remains separate: "
                f"supported={cohort['natural_separation_findings']['supported']}, "
                f"uncertain={cohort['natural_separation_findings']['uncertain']}, "
                f"non-separating={cohort['natural_separation_findings']['non_separating']}.",
            ]
        )
        primary = suggestion["primary_plan"]
        if primary is not None:
            fit = primary["projected_fit"]
            lines.extend(
                [
                    "",
                    "### Primary suggestion",
                    "",
                    f"- Plan: `{primary['plan_id']}`",
                    f"- Flight sizes: `{'/'.join(str(item) for item in primary['flight_sizes'])}`",
                    f"- Evidence status: `{suggestion['primary_evidence_status']}`",
                    "- Required potential matchups: "
                    f"{primary['prediction_completeness']['required_unique_pairing_count']}",
                    f"- Violations: {fit['violating_pairing_count']}",
                    f"- Worst matchup cost: {_format_number(fit['worst_matchup_cost'])}",
                    f"- Pair-weighted average cost: {_format_number(fit['pair_weighted_average_matchup_cost'])}",
                    "",
                    "| Flight | Seeds | Count | Membership | Preferred format | Other compatible formats |",
                    "|---:|---|---:|---|---|---|",
                ]
            )
            primary_formats = next(
                item
                for item in suggestion["format_options_by_plan"]
                if item["plan_id"] == primary["plan_id"]
            )
            for flight, item in zip(
                primary["flights"], primary_formats["flights"], strict=True
            ):
                others = [
                    value
                    for value in item["compatible_template_ids"]
                    if value != item["preferred_template_id"]
                ]
                membership = "; ".join(
                    f"{team['seed']}. {team['team_name']}"
                    for team in flight["complete_group_assessment"]["teams"]
                )
                lines.append(
                    f"| {item['flight_number']} | {item['start_order_position']}-{item['end_order_position']} | "
                    f"{item['team_count']} | {membership} | "
                    f"{item['preferred_template_id']} | "
                    f"{', '.join(others) or '-'} |"
                )
        else:
            lines.extend(
                [
                    "",
                    "No primary suggestion was issued.",
                    "",
                    "Nondominated compromise plans: "
                    + (
                        ", ".join(
                            f"`{item}`"
                            for item in suggestion[
                                "nondominated_compromise_plan_ids"
                            ]
                        )
                        or "none"
                    ),
                ]
            )
        if assessment is not None:
            alternatives = {
                item["plan_id"] for item in suggestion["useful_alternatives"]
            }
            compromise = set(suggestion["nondominated_compromise_plan_ids"])
            lines.extend(
                [
                    "",
                    "### Complete candidate summary",
                    "",
                    "| Plan | Flight sizes | Complete | Pass | Violations | Worst cost | Average cost | Role |",
                    "|---|---|---|---|---:|---:|---:|---|",
                ]
            )
            for plan in assessment["plans"]:
                fit = plan["projected_fit"]
                role = (
                    "primary"
                    if plan["plan_id"] == suggestion["primary_plan_id"]
                    else "alternative"
                    if plan["plan_id"] in alternatives
                    else "compromise"
                    if plan["plan_id"] in compromise
                    else "evaluated"
                )
                lines.append(
                    f"| {plan['plan_id']} | {'/'.join(str(item) for item in plan['flight_sizes'])} | "
                    f"{plan['prediction_completeness']['complete']} | "
                    f"{fit['all_pair_projected_fit_passed']} | "
                    f"{fit['violating_pairing_count']} | "
                    f"{_format_number(fit['worst_matchup_cost'])} | "
                    f"{_format_number(fit['pair_weighted_average_matchup_cost'])} | {role} |"
                )
            no_opponents = [
                item
                for item in assessment["all_opponent_assessments"]
                if item[
                    "complete_predictions_establish_no_within_policy_opponent"
                ]
            ]
            lines.extend(["", "Teams with no within-policy opponent:", ""])
            if no_opponents:
                for item in no_opponents:
                    team = item["team"]
                    lines.append(
                        f"- Seed {team['seed']} {team['team_name']}: {item['explanation']}"
                    )
            else:
                lines.append("- None established by complete frozen predictions.")
    return "\n".join(lines) + "\n"


def _validation_markdown(
    library: FormatLibrary, validation: FormatLibraryValidation
) -> str:
    templates = library.templates_by_id
    lines = [
        "# MatchBalance format-library validation",
        "",
        f"- Library: `{library.library_id}` `{library.library_version}`",
        f"- Schema: {library.schema_version}",
        f"- File SHA-256: `{library.source_sha256}`",
        f"- Overall valid: {validation.valid}",
        "",
        "| Template | Teams | Pools | Status | Usable | Errors / warnings |",
        "|---|---:|---|---|---|---|",
    ]
    for result in validation.template_results:
        template = templates[result.template_id]
        diagnostics = (*result.errors, *result.warnings)
        lines.append(
            f"| {result.template_id} | {template.team_count} | "
            f"{'/'.join(str(item) for item in template.pool_sizes)} | "
            f"{result.availability_status} | {result.usable_in_profiles} | "
            f"{' / '.join(diagnostics) or '-'} |"
        )
    lines.extend(["", "## Source issues", ""])
    for issue in validation.source_issues:
        lines.append(f"- `{issue.issue_id}` ({issue.status}): {issue.reason}")
    return "\n".join(lines) + "\n"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = sorted({key for row in rows for key in row})
    preferred = [
        "record_type",
        "event",
        "cohort",
        "code_commit",
        "source_file_sha256",
        "predictor_sha256",
        "profile_id",
        "recommendation_policy_id",
        "recommendation_status",
        "primary_plan_id",
        "plan_id",
        "plan_role",
        "flight_sizes",
        "flight_number",
        "pair_key",
    ]
    fieldnames = [item for item in preferred if item in fields]
    fieldnames.extend(item for item in fields if item not in fieldnames)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--report-slug", required=True)
    parser.add_argument(
        "--cohort",
        action="append",
        default=None,
        help="Saved cohort key; omit to evaluate every selected cohort.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="Versioned event profile ID; omit for the MatchBalance default.",
    )
    parser.add_argument(
        "--order-source", choices=("suggested", "effective"), default=None
    )
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-predictor-sha256")
    parser.add_argument("--max-candidate-structures", type=int, default=None)
    parser.add_argument("--format-library", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    report = build_automatic_report(
        snapshot_path=args.snapshot,
        event_name=args.event_name,
        report_slug=args.report_slug,
        cohorts=args.cohort,
        profile_id=args.profile,
        order_source=args.order_source,
        expected_source_sha256=args.expected_source_sha256,
        expected_predictor_sha256=args.expected_predictor_sha256,
        max_candidate_structures=args.max_candidate_structures,
        library_path=args.format_library,
    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['report_slug']}-automatic-flight-suggestions"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"
    validation_json_path = output_dir / "matchbalance-format-library-validation.json"
    validation_markdown_path = output_dir / "matchbalance-format-library-validation.md"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows = _csv_rows(report)
    _write_csv(csv_path, rows)
    markdown_path.write_text(_markdown_report(report), encoding="utf-8")
    library = load_format_library(args.format_library)
    validation = validate_format_library(library)
    validation_json_path.write_text(
        json.dumps(
            format_library_payload(library, validation),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    validation_markdown_path.write_text(
        _validation_markdown(library, validation), encoding="utf-8"
    )
    print(f"JSON={json_path}")
    print(f"CSV={csv_path}")
    print(f"MARKDOWN={markdown_path}")
    print(f"TEMPLATE_VALIDATION_JSON={validation_json_path}")
    print(f"TEMPLATE_VALIDATION_MARKDOWN={validation_markdown_path}")
    print(f"CONTENT_SHA256={report['content_sha256']}")
    print(f"CSV_ROW_COUNT={len(rows)}")


if __name__ == "__main__":
    main()
