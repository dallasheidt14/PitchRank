"""Export complete-pair MatchBalance diagnostics from frozen saved packs.

This is an internal validation tool. It never fetches ratings or predictions,
never changes the saved pack, and never assigns flights. Candidate sizes are
explicit inputs and every contiguous candidate is evaluated independently.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import socket
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from src.tournaments.roster_paste import ParsedRoster, RosterRow  # noqa: E402
from src.tournaments.roster_resolver import ResolvedTeam  # noqa: E402
from src.tournaments.seeding_assessment import (  # noqa: E402
    effective_roster,
    package_roster,
)
from src.tournaments.seeding_group_assessment import (  # noqa: E402
    GroupAdditionAssessment,
    GroupAssessment,
    GroupPairAssessment,
    GroupTeam,
    assess_contiguous_groups,
    assess_group,
)
from src.tournaments.seeding_pack import (  # noqa: E402
    ANALYSIS_SCHEMA_VERSION,
    PACK_SCHEMA_VERSION,
    _snapshot_predictions,
    analyze_pack,
    prediction_request,
    upgrade_pack_analysis,
)
from src.tournaments.seeding_tiers import TierPolicy  # noqa: E402

STARTING_COMMIT = "c7125bf72c438d4518971393217fb8535b8cb7ef"
EXPECTED_PREDICTOR = "98b059f074e32584e973ca679c09985581b0867fe4175002a02cec0ada73cb5d"
REPORT_SCHEMA_VERSION = 1
DEFAULT_GROUP_SIZES = (4, 5, 6, 8)

CASES = (
    {
        "slug": "san-antonio-labor-cup-u14-boys",
        "event": "SAN ANTONIO LABOR CUP 26",
        "cohort": "u14|Male",
        "source_path": Path(
            r"C:\PitchRank\reports\seeding\san-antonio-labor-cup-26\seeding_run.json"
        ),
        "source_sha256": "a3ca6f1c7c2a03eb55d11d94bc0e60013cbcfeb1d8d1b5c560cdac6082e1a012",
        "expected_team_count": 16,
        "expected_order": (
            "6", "4", "12", "9", "0", "7", "10", "5",
            "14", "1", "3", "15", "13", "11", "2", "8",
        ),
        "expected_boundaries": {
            "supported": (),
            "uncertain": (14, 15),
            "non_separating": tuple(range(1, 14)),
        },
        "highlight_start": 13,
        "highlight_size": 4,
        "highlight_label": "San Antonio seeds 13-16",
        "source_selection_note": (
            "The current saved run is the 16-team U14 Boys snapshot matching the "
            "validated sample. The older 15-team history file was not substituted."
        ),
    },
    {
        "slug": "rsl-cactus-kickoff-u13-boys",
        "event": "RSL Cactus Kickoff",
        "cohort": "u13|Male",
        "source_path": Path(
            r"C:\PitchRank\reports\seeding\rsl-cactus-kickoff\history\20260928T184704914765.json"
        ),
        "source_sha256": "e53f5d626520976c269d51067142150391746d1a7da3b9a7e0d5ead50cb0a05c",
        "expected_team_count": 18,
        "expected_order": (
            "77", "92", "89", "88", "84", "85", "79", "87", "76",
            "78", "81", "75", "91", "86", "83", "90", "82", "80",
        ),
        "expected_boundaries": {
            "supported": (1,),
            "uncertain": (2, 9, 10, 11, 12, 13, 14, 15, 16, 17),
            "non_separating": (3, 4, 5, 6, 7, 8),
        },
        "highlight_start": 2,
        "highlight_size": 6,
        "highlight_label": "RSL seeds 2-7",
        "source_selection_note": (
            "This archived schema-3 run is the exact 18-team snapshot validated for "
            "the original score shape. A later pack was not substituted."
        ),
    },
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--group-size",
        type=int,
        action="append",
        dest="group_sizes",
        help="Contiguous candidate size; repeat for multiple explicit sizes.",
    )
    return parser.parse_args()


@contextmanager
def _network_blocked() -> Iterator[None]:
    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("Network access is forbidden during frozen-pack analysis.")

    with patch.object(socket.socket, "connect", blocked), patch.object(
        socket, "create_connection", blocked
    ):
        yield


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _team_payload(team: GroupTeam) -> dict[str, Any]:
    return {**asdict(team), "history_quality": team.history_quality}


def _pair_key(pair: GroupPairAssessment | None) -> str | None:
    return None if pair is None else "::".join(pair.entrant_ids)


def _pair_payload(pair: GroupPairAssessment) -> dict[str, Any]:
    return {
        "pair_key": _pair_key(pair),
        "first_team": _team_payload(pair.first),
        "second_team": _team_payload(pair.second),
        "prediction_status": pair.prediction_status,
        "prediction_issue": pair.prediction_issue,
        "expected_signed_margin_toward_first": pair.expected_signed_margin_toward_first,
        "expected_absolute_goal_difference": pair.expected_absolute_goal_difference,
        "blowout_4plus_probability": pair.blowout_probability,
        "matchup_cost": pair.matchup_cost,
        "within_expected_goal_difference_limit": (
            pair.within_expected_goal_difference_limit
        ),
        "within_blowout_probability_limit": pair.within_blowout_probability_limit,
        "within_both_limits": pair.within_both_limits,
        "exceeds_expected_goal_difference_limit": (
            pair.exceeds_expected_goal_difference_limit
        ),
        "exceeds_blowout_probability_limit": (
            pair.exceeds_blowout_probability_limit
        ),
        "history_quality": pair.history_quality,
        "provisional_due_to_history": pair.provisional_due_to_history,
        "outcome_confidence": pair.outcome_confidence,
        "outcome_confidence_score": pair.outcome_confidence_score,
        "low_outcome_confidence": pair.low_outcome_confidence,
    }


def _fit_summary(assessment: GroupAssessment) -> dict[str, Any]:
    fit = assessment.projected_fit
    return {
        "conclusion": fit.conclusion,
        "reason": fit.reason,
        "expected_unique_pairing_count": fit.expected_unique_pairing_count,
        "available_unique_pairing_count": fit.available_unique_pairing_count,
        "missing_prediction_count": fit.missing_prediction_count,
        "invalid_prediction_count": fit.invalid_prediction_count,
        "complete_prediction_coverage": fit.complete_prediction_coverage,
        "within_both_limits_count": fit.within_both_limits_count,
        "within_both_limits_fraction_of_available": (
            fit.within_both_limits_fraction_of_available
        ),
        "within_both_limits_fraction_of_expected": (
            fit.within_both_limits_fraction_of_expected
        ),
        "exceeding_either_limit_count": fit.exceeding_either_limit_count,
        "exceeding_either_limit_fraction_of_available": (
            fit.exceeding_either_limit_fraction_of_available
        ),
        "exceeding_either_limit_fraction_of_expected": (
            fit.exceeding_either_limit_fraction_of_expected
        ),
        "all_available_matchups_within_limits": (
            fit.all_available_matchups_within_limits
        ),
        "all_pair_projected_fit_passed": fit.all_pair_projected_fit_passed,
        "average_expected_absolute_goal_difference": (
            fit.average_expected_absolute_goal_difference
        ),
        "maximum_expected_absolute_goal_difference": (
            fit.maximum_expected_absolute_goal_difference
        ),
        "average_blowout_4plus_probability": fit.average_blowout_probability,
        "maximum_blowout_4plus_probability": fit.maximum_blowout_probability,
        "average_matchup_cost": fit.average_matchup_cost,
        "maximum_matchup_cost": fit.maximum_matchup_cost,
        "worst_matchup": (
            _pair_payload(fit.worst_matchup) if fit.worst_matchup is not None else None
        ),
        "maximum_expected_absolute_goal_difference_matchup": (
            _pair_payload(fit.maximum_expected_absolute_goal_difference_matchup)
            if fit.maximum_expected_absolute_goal_difference_matchup is not None
            else None
        ),
        "maximum_blowout_probability_matchup": (
            _pair_payload(fit.maximum_blowout_probability_matchup)
            if fit.maximum_blowout_probability_matchup is not None
            else None
        ),
        "over_limit_pair_keys": [
            _pair_key(item) for item in fit.over_limit_matchups
        ],
    }


def _evidence_summary(assessment: GroupAssessment) -> dict[str, Any]:
    evidence = assessment.evidence_coverage
    return {
        "established_history_teams": [
            _team_payload(item) for item in evidence.established_history_teams
        ],
        "limited_history_teams": [
            _team_payload(item) for item in evidence.limited_history_teams
        ],
        "unknown_history_teams": [
            _team_payload(item) for item in evidence.unknown_history_teams
        ],
        "all_team_history_metadata_available": (
            evidence.all_team_history_metadata_available
        ),
        "pairings_involving_limited_or_unknown_history": [
            _pair_key(item)
            for item in evidence.pairings_involving_limited_or_unknown_history
        ],
        "provisional_within_limit_pairings": [
            _pair_key(item) for item in evidence.provisional_within_limit_pairings
        ],
        "missing_prediction_pairings": [
            _pair_key(item) for item in evidence.missing_prediction_pairings
        ],
        "invalid_prediction_pairings": [
            _pair_key(item) for item in evidence.invalid_prediction_pairings
        ],
        "limitations": list(evidence.limitations),
    }


def _group_payload(assessment: GroupAssessment) -> dict[str, Any]:
    return {
        "entrant_ids": list(assessment.entrant_ids),
        "teams": [_team_payload(item) for item in assessment.teams],
        "projected_competitive_fit": _fit_summary(assessment),
        "evidence_coverage_and_limitations": _evidence_summary(assessment),
        "pairings": [_pair_payload(item) for item in assessment.pairings],
    }


def _addition_payload(addition: GroupAdditionAssessment | None) -> dict[str, Any] | None:
    if addition is None:
        return None
    return {
        "direction": addition.direction,
        "added_team": _team_payload(addition.added_team),
        "original_group_conclusion": addition.original_group.projected_fit.conclusion,
        "expanded_group_conclusion": addition.expanded_group.projected_fit.conclusion,
        "newly_introduced_matchups": [
            _pair_payload(item) for item in addition.newly_introduced_matchups
        ],
        "newly_over_limit_pair_keys": [
            _pair_key(item) for item in addition.newly_over_limit_matchups
        ],
        "newly_missing_or_invalid_pair_keys": [
            _pair_key(item) for item in addition.newly_missing_or_invalid_matchups
        ],
        "original_over_limit_pair_keys": [
            _pair_key(item) for item in addition.original_over_limit_matchups
        ],
        "original_missing_or_invalid_pair_keys": [
            _pair_key(item)
            for item in addition.original_missing_or_invalid_matchups
        ],
        "original_group_had_projected_failures": (
            addition.original_group_had_projected_failures
        ),
        "original_group_had_incomplete_predictions": (
            addition.original_group_had_incomplete_predictions
        ),
        "average_expected_absolute_goal_difference_change": (
            addition.average_expected_absolute_goal_difference_change
        ),
        "maximum_expected_absolute_goal_difference_change": (
            addition.maximum_expected_absolute_goal_difference_change
        ),
        "average_blowout_probability_change": (
            addition.average_blowout_probability_change
        ),
        "maximum_blowout_probability_change": (
            addition.maximum_blowout_probability_change
        ),
        "average_matchup_cost_change": addition.average_matchup_cost_change,
        "maximum_matchup_cost_change": addition.maximum_matchup_cost_change,
        "added_evidence_limitations": list(addition.added_evidence_limitations),
    }


def load_frozen_snapshot(
    source_path: Path,
    cohort: str,
    *,
    expected_source_sha256: str | None = None,
    expected_predictor_sha256: str | None = None,
) -> dict[str, Any]:
    """Load and upgrade one saved pack without network access or source writes."""
    source_path = source_path.resolve()
    source_bytes = source_path.read_bytes()
    actual_sha = _sha256_bytes(source_bytes)
    if expected_source_sha256 is not None and actual_sha != expected_source_sha256:
        raise ValueError(
            f"Frozen source hash changed for {source_path}: {actual_sha}"
        )
    payload = json.loads(source_bytes.decode("utf-8"))
    parsed = ParsedRoster(
        rows=tuple(RosterRow(**item) for item in payload.get("rows", ())),
        warnings=tuple(payload.get("warnings") or ()),
    )
    decisions = {
        int(index): value
        for index, value in (payload.get("cohort_decisions") or {}).items()
    }
    rows = package_roster(effective_roster(parsed, decisions)).rows
    resolved = tuple(
        ResolvedTeam(**{**item, "candidates": tuple(item.get("candidates") or ())})
        for item in payload.get("resolved", ())
    )
    overrides = {
        int(index): value for index, value in (payload.get("overrides") or {}).items()
    }
    original_pack = payload["pack"]
    predictor_sha256 = str(original_pack.get("predictor_sha256") or "")
    if (
        expected_predictor_sha256 is not None
        and predictor_sha256 != expected_predictor_sha256
    ):
        raise ValueError(f"Unexpected predictor for {source_path}")
    selected = list(original_pack["selected_cohorts"])
    if cohort not in selected:
        raise ValueError(f"Frozen snapshot does not include cohort {cohort!r}")
    with _network_blocked():
        if (
            original_pack.get("schema_version") == PACK_SCHEMA_VERSION
            and original_pack.get("analysis_schema_version")
            == ANALYSIS_SCHEMA_VERSION
        ):
            upgraded_pack = json.loads(
                json.dumps(original_pack, ensure_ascii=False, allow_nan=False)
            )
        else:
            upgraded_pack = upgrade_pack_analysis(
                original_pack,
                rows,
                resolved,
                overrides,
                selected,
                predictor_sha256=predictor_sha256,
            )
        analyses = analyze_pack(upgraded_pack, rows, resolved, overrides)
        request = prediction_request(rows, resolved, overrides, selected)
        predictions = _snapshot_predictions(upgraded_pack, request)
    age, gender = cohort.split("|", 1)
    analysis = analyses[(age, gender)]
    return {
        "source_path": source_path,
        "source_sha256": actual_sha,
        "payload": payload,
        "source_bytes": source_bytes,
        "rows": rows,
        "resolved": resolved,
        "overrides": overrides,
        "original_pack": original_pack,
        "upgraded_pack": upgraded_pack,
        "analysis": analysis,
        "predictions": predictions[cohort],
    }


def _load_case(case: Mapping[str, Any]) -> dict[str, Any]:
    loaded = load_frozen_snapshot(
        Path(case["source_path"]),
        str(case["cohort"]),
        expected_source_sha256=str(case["source_sha256"]),
        expected_predictor_sha256=EXPECTED_PREDICTOR,
    )
    analysis = loaded["analysis"]
    if len(analysis.suggested_order) != case["expected_team_count"]:
        raise ValueError(f"Unexpected seeded-team count for {case['slug']}")
    if tuple(analysis.baseline_order) != tuple(case["expected_order"]):
        raise ValueError(f"Baseline order regressed for {case['slug']}")
    if tuple(analysis.suggested_order) != tuple(case["expected_order"]):
        raise ValueError(f"Suggested order regressed for {case['slug']}")
    actual_boundaries = {
        "supported": tuple(item.after_seed for item in analysis.supported_boundaries),
        "uncertain": tuple(item.after_seed for item in analysis.uncertain_boundaries),
        "non_separating": tuple(
            item.after_seed for item in analysis.non_separating_boundaries
        ),
    }
    if actual_boundaries != case["expected_boundaries"]:
        raise ValueError(f"Boundary classifications regressed for {case['slug']}")
    return {**loaded, "actual_boundaries": actual_boundaries}


def build_team_metadata(
    loaded: Mapping[str, Any],
    cohort: str,
    entrant_ids: Sequence[str],
) -> dict[str, GroupTeam]:
    """Build frozen reporting metadata, retaining suggested seed references."""
    analysis = loaded["analysis"]
    rows = {str(row.source_index): row for row in loaded["rows"]}
    frozen_teams = loaded["upgraded_pack"]["teams"][cohort]
    ratings = loaded["upgraded_pack"]["ratings"]
    suggested_seed = {
        entrant_id: seed
        for seed, entrant_id in enumerate(analysis.suggested_order, start=1)
    }
    metadata: dict[str, GroupTeam] = {}
    for entrant_id in entrant_ids:
        row = rows[entrant_id]
        frozen = frozen_teams.get(entrant_id, {})
        team_id = frozen.get("team_id_master")
        evidence = {**ratings.get(str(team_id), {}), **frozen}
        rating_status = evidence.get("status")
        if rating_status is None:
            limited_history = None
        else:
            limited_history = rating_status == "Not Enough Ranked Games"
        flags = []
        if rating_status:
            flags.append(f"rating_status={rating_status}")
        placement_status = analysis.placement_status.get(entrant_id)
        if placement_status:
            flags.append(f"placement_status={placement_status}")
        review_reason = analysis.review.get(entrant_id)
        if review_reason:
            flags.append(f"placement_review={review_reason}")
        metadata[entrant_id] = GroupTeam(
            entrant_id=entrant_id,
            team_name=row.registered_name,
            team_id_master=team_id,
            seed=suggested_seed.get(entrant_id),
            power_score=evidence.get("power_score_final"),
            limited_history=limited_history,
            evidence_game_count=evidence.get("prediction_game_count"),
            evidence_flags=tuple(flags),
        )
    return metadata


def _team_metadata(loaded: Mapping[str, Any], cohort: str) -> dict[str, GroupTeam]:
    return build_team_metadata(
        loaded,
        cohort,
        loaded["analysis"].suggested_order,
    )


def _boundary_snapshot(loaded: Mapping[str, Any]) -> dict[str, Any]:
    analysis = loaded["analysis"]
    return {
        "supported": list(loaded["actual_boundaries"]["supported"]),
        "uncertain": list(loaded["actual_boundaries"]["uncertain"]),
        "non_separating": list(loaded["actual_boundaries"]["non_separating"]),
        "assessment_sha256": _canonical_sha256(
            loaded["upgraded_pack"]["boundary_analysis"]
        ),
        "complete_boundary_count": len(analysis.boundary_assessments),
    }


def _candidate_csv_common(
    event_report: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    group = candidate["assessment"]
    fit = group["projected_competitive_fit"]
    evidence = group["evidence_coverage_and_limitations"]
    return {
        "event": event_report["event_name"],
        "cohort": event_report["cohort"],
        "source_file_sha256": event_report["snapshot_provenance"]["source_file_sha256"],
        "predictor_sha256": event_report["snapshot_provenance"]["predictor_sha256"],
        "candidate_id": candidate["candidate_id"],
        "requested_size": candidate["requested_size"],
        "start_seed": candidate["start_seed"],
        "end_seed": candidate["end_seed"],
        "highlight": candidate.get("highlight"),
        "group_entrant_ids": "|".join(group["entrant_ids"]),
        "group_team_names": "|".join(item["team_name"] for item in group["teams"]),
        "fit_conclusion": fit["conclusion"],
        "fit_reason": fit["reason"],
        "expected_pair_count": fit["expected_unique_pairing_count"],
        "available_pair_count": fit["available_unique_pairing_count"],
        "within_both_count": fit["within_both_limits_count"],
        "within_both_fraction_expected": fit["within_both_limits_fraction_of_expected"],
        "over_limit_count": fit["exceeding_either_limit_count"],
        "over_limit_fraction_expected": fit["exceeding_either_limit_fraction_of_expected"],
        "missing_prediction_count": fit["missing_prediction_count"],
        "invalid_prediction_count": fit["invalid_prediction_count"],
        "all_pair_projected_fit_passed": fit["all_pair_projected_fit_passed"],
        "average_expected_absolute_goal_difference": (
            fit["average_expected_absolute_goal_difference"]
        ),
        "maximum_expected_absolute_goal_difference": (
            fit["maximum_expected_absolute_goal_difference"]
        ),
        "average_blowout_4plus_probability": (
            fit["average_blowout_4plus_probability"]
        ),
        "maximum_blowout_4plus_probability": (
            fit["maximum_blowout_4plus_probability"]
        ),
        "average_matchup_cost": fit["average_matchup_cost"],
        "maximum_matchup_cost": fit["maximum_matchup_cost"],
        "established_team_count": len(evidence["established_history_teams"]),
        "limited_team_count": len(evidence["limited_history_teams"]),
        "unknown_history_team_count": len(evidence["unknown_history_teams"]),
        "evidence_limitations": " | ".join(evidence["limitations"]),
    }


def _pair_csv_fields(pair: Mapping[str, Any]) -> dict[str, Any]:
    first = pair["first_team"]
    second = pair["second_team"]
    return {
        "pair_key": pair["pair_key"],
        "first_seed": first["seed"],
        "first_entrant_id": first["entrant_id"],
        "first_team_name": first["team_name"],
        "first_team_id_master": first["team_id_master"],
        "first_power_score": first["power_score"],
        "first_history_quality": first["history_quality"],
        "first_evidence_game_count": first["evidence_game_count"],
        "first_evidence_flags": " | ".join(first["evidence_flags"]),
        "second_seed": second["seed"],
        "second_entrant_id": second["entrant_id"],
        "second_team_name": second["team_name"],
        "second_team_id_master": second["team_id_master"],
        "second_power_score": second["power_score"],
        "second_history_quality": second["history_quality"],
        "second_evidence_game_count": second["evidence_game_count"],
        "second_evidence_flags": " | ".join(second["evidence_flags"]),
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
        "exceeds_expected_goal_difference_limit": (
            pair["exceeds_expected_goal_difference_limit"]
        ),
        "exceeds_blowout_probability_limit": (
            pair["exceeds_blowout_probability_limit"]
        ),
        "pair_history_quality": pair["history_quality"],
        "provisional_due_to_history": pair["provisional_due_to_history"],
        "outcome_confidence": pair["outcome_confidence"],
        "outcome_confidence_score": pair["outcome_confidence_score"],
    }


def _case_report(
    case: Mapping[str, Any], group_sizes: Sequence[int]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    loaded = _load_case(case)
    pack = loaded["upgraded_pack"]
    original_pack = loaded["original_pack"]
    analysis = loaded["analysis"]
    cohort = str(case["cohort"])
    policy = TierPolicy(**pack["policy"])
    metadata = _team_metadata(loaded, cohort)
    order = tuple(analysis.suggested_order)
    scan = assess_contiguous_groups(
        order, group_sizes, loaded["predictions"], policy, metadata
    )
    highlight_key = (
        int(case["highlight_size"]),
        int(case["highlight_start"]),
    )
    candidates = []
    highlighted_group: dict[str, Any] | None = None
    csv_rows: list[dict[str, Any]] = []
    for candidate in scan.candidates:
        candidate_id = (
            f"size-{candidate.requested_size}-seeds-"
            f"{candidate.start_order_position}-{candidate.end_order_position}"
        )
        highlight = (
            str(case["highlight_label"])
            if (candidate.requested_size, candidate.start_order_position) == highlight_key
            else None
        )
        item = {
            "candidate_id": candidate_id,
            "requested_size": candidate.requested_size,
            "start_seed": candidate.start_order_position,
            "end_seed": candidate.end_order_position,
            "highlight": highlight,
            "assessment": _group_payload(candidate.assessment),
            "add_next_above": _addition_payload(candidate.add_above),
            "add_next_below": _addition_payload(candidate.add_below),
        }
        candidates.append(item)
        if highlight:
            highlighted_group = item

    source_policy = original_pack.get("policy") or {}
    policy_sources = {
        key: "saved_snapshot" if key in source_policy else "schema_default_on_upgrade"
        for key in pack["policy"]
    }
    report = {
        "event_name": case["event"],
        "cohort": cohort,
        "snapshot_provenance": {
            "source_path": str(case["source_path"]),
            "source_file_sha256": _sha256_bytes(loaded["source_bytes"]),
            "embedded_pack_sha256": _canonical_sha256(original_pack),
            "frozen_cohort_payload_sha256": _canonical_sha256(
                {
                    "teams": original_pack["teams"][cohort],
                    "predictions": original_pack["predictions"][cohort],
                    "ratings": original_pack["ratings"],
                    "policy": original_pack["policy"],
                    "generated_at": original_pack["generated_at"],
                    "ratings_as_of": original_pack["ratings_as_of"],
                    "predictor_sha256": original_pack["predictor_sha256"],
                }
            ),
            "frozen_prediction_records_sha256": _canonical_sha256(
                original_pack["predictions"][cohort]
            ),
            "source_pack_schema_version": original_pack["schema_version"],
            "source_analysis_schema_version": original_pack["analysis_schema_version"],
            "reanalysis_pack_schema_version": pack["schema_version"],
            "reanalysis_analysis_schema_version": pack["analysis_schema_version"],
            "snapshot_generated_at": original_pack["generated_at"],
            "ratings_as_of": original_pack["ratings_as_of"],
            "predictor_sha256": original_pack["predictor_sha256"],
            "frozen_team_count": len(order),
            "frozen_directional_prediction_record_count": len(
                original_pack["predictions"][cohort]
            ),
            "source_selection_note": case["source_selection_note"],
            "network_access": "blocked",
        },
        "effective_policy": {
            "values": pack["policy"],
            "field_provenance": policy_sources,
            "saved_snapshot_values": source_policy,
            "pair_pass_rule": (
                "expected_absolute_goal_difference <= max_expected_margin AND "
                "blowout_4plus_probability <= max_blowout_probability"
            ),
            "limits_are_inclusive": True,
        },
        "order_and_boundary_regression": {
            "baseline_order": list(analysis.baseline_order),
            "suggested_order": list(analysis.suggested_order),
            "baseline_equals_validated_order": True,
            "suggested_equals_validated_order": True,
            "manual_seed_order": pack.get("manual_seed_orders", {}).get(cohort),
            "boundary_classifications": _boundary_snapshot(loaded),
        },
        "candidate_scan": {
            "ordered_ids": list(scan.ordered_ids),
            "requested_sizes": list(scan.requested_sizes),
            "available_sizes": list(scan.available_sizes),
            "unavailable_sizes": list(scan.unavailable_sizes),
            "candidate_count": len(scan.candidates),
            "interpretation": (
                "Candidates are overlapping alternatives, not a partition or flight assignment."
            ),
            "candidates": candidates,
        },
        "highlighted_group": highlighted_group,
    }
    if highlighted_group is None:
        raise ValueError(f"Requested highlighted group was not assessed for {case['slug']}")

    if case["slug"] == "rsl-cactus-kickoff-u13-boys":
        first_id = order[0]
        seed_one_pairs = []
        for opponent_id in order[1:]:
            assessment = assess_group(
                (first_id, opponent_id), loaded["predictions"], policy, metadata
            )
            pair = assessment.pairings[0]
            seed_one_pairs.append(_pair_payload(pair))
        report["seed_1_against_every_other_team"] = {
            "seed_1_team": _team_payload(metadata[first_id]),
            "comparison_count": len(seed_one_pairs),
            "within_limits_pair_keys": [
                item["pair_key"] for item in seed_one_pairs if item["within_both_limits"]
            ],
            "established_history_within_limits_pair_keys": [
                item["pair_key"]
                for item in seed_one_pairs
                if item["within_both_limits"] and item["history_quality"] == "established"
            ],
            "limited_or_unknown_history_within_limits_pair_keys": [
                item["pair_key"]
                for item in seed_one_pairs
                if item["within_both_limits"] and item["history_quality"] != "established"
            ],
            "comparisons": seed_one_pairs,
        }

    for candidate in candidates:
        common = _candidate_csv_common(report, candidate)
        csv_rows.append({**common, "record_type": "candidate_summary"})
        for pair in candidate["assessment"]["pairings"]:
            csv_rows.append(
                {
                    **common,
                    "record_type": "candidate_pair",
                    **_pair_csv_fields(pair),
                }
            )
        for direction_key in ("add_next_above", "add_next_below"):
            addition = candidate[direction_key]
            if addition is None:
                continue
            addition_common = {
                **common,
                "addition_direction": addition["direction"],
                "added_seed": addition["added_team"]["seed"],
                "added_entrant_id": addition["added_team"]["entrant_id"],
                "added_team_name": addition["added_team"]["team_name"],
                "original_group_had_projected_failures": (
                    addition["original_group_had_projected_failures"]
                ),
                "original_group_had_incomplete_predictions": (
                    addition["original_group_had_incomplete_predictions"]
                ),
                "newly_over_limit_pair_keys": "|".join(
                    addition["newly_over_limit_pair_keys"]
                ),
                "newly_missing_or_invalid_pair_keys": "|".join(
                    addition["newly_missing_or_invalid_pair_keys"]
                ),
                "average_expected_absolute_goal_difference_change": (
                    addition["average_expected_absolute_goal_difference_change"]
                ),
                "maximum_expected_absolute_goal_difference_change": (
                    addition["maximum_expected_absolute_goal_difference_change"]
                ),
                "average_blowout_probability_change": (
                    addition["average_blowout_probability_change"]
                ),
                "maximum_blowout_probability_change": (
                    addition["maximum_blowout_probability_change"]
                ),
                "average_matchup_cost_change": addition["average_matchup_cost_change"],
                "maximum_matchup_cost_change": addition["maximum_matchup_cost_change"],
                "added_evidence_limitations": " | ".join(
                    addition["added_evidence_limitations"]
                ),
            }
            csv_rows.append({**addition_common, "record_type": "addition_summary"})
            for pair in addition["newly_introduced_matchups"]:
                csv_rows.append(
                    {
                        **addition_common,
                        "record_type": "addition_pair",
                        "new_pair_exceeds_limits": (
                            pair["pair_key"] in addition["newly_over_limit_pair_keys"]
                        ),
                        "new_pair_missing_or_invalid": (
                            pair["pair_key"]
                            in addition["newly_missing_or_invalid_pair_keys"]
                        ),
                        **_pair_csv_fields(pair),
                    }
                )
    for pair in report.get("seed_1_against_every_other_team", {}).get(
        "comparisons", []
    ):
        csv_rows.append(
            {
                "event": report["event_name"],
                "cohort": cohort,
                "source_file_sha256": report["snapshot_provenance"]["source_file_sha256"],
                "predictor_sha256": report["snapshot_provenance"]["predictor_sha256"],
                "record_type": "seed_1_comparison",
                "highlight": "RSL seed 1 against every other team",
                **_pair_csv_fields(pair),
            }
        )
    return report, csv_rows


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    preferred = (
        "record_type", "event", "cohort", "source_file_sha256", "predictor_sha256",
        "candidate_id", "requested_size", "start_seed", "end_seed", "highlight",
        "addition_direction", "added_seed", "added_entrant_id", "added_team_name",
        "pair_key", "first_seed", "first_entrant_id", "first_team_name",
        "second_seed", "second_entrant_id", "second_team_name",
        "expected_absolute_goal_difference", "blowout_4plus_probability", "matchup_cost",
        "within_both_limits", "pair_history_quality", "provisional_due_to_history",
    )
    all_fields = {key for row in rows for key in row}
    fieldnames = [key for key in preferred if key in all_fields]
    fieldnames.extend(sorted(all_fields - set(fieldnames)))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = _parse_args()
    group_sizes = tuple(args.group_sizes or DEFAULT_GROUP_SIZES)
    if len(group_sizes) != len(set(group_sizes)) or any(size < 1 for size in group_sizes):
        raise ValueError("Group sizes must be unique positive integers")
    head = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    if branch != "fix/matchbalance-boundary-analysis":
        raise ValueError(f"Run this diagnostic from the isolated fix branch, not {branch!r}")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", STARTING_COMMIT, head], check=True
    )
    reports = []
    csv_rows: list[dict[str, Any]] = []
    for case in CASES:
        report, case_rows = _case_report(case, group_sizes)
        reports.append(report)
        csv_rows.extend(case_rows)
    result = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": (
            "Internal all-pair projected-fit and evidence diagnostics. No flight assignment, "
            "customer-export decision, or demonstrated match outcome is implied."
        ),
        "code": {
            "commit": head,
            "starting_commit": STARTING_COMMIT,
            "branch": branch,
            "starting_commit_is_ancestor": True,
            "working_tree_clean_at_export": not bool(_git("status", "--short")),
            "pack_schema_version": PACK_SCHEMA_VERSION,
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        },
        "requested_group_sizes": list(group_sizes),
        "tournaments": reports,
    }
    result["content_sha256"] = _canonical_sha256(result)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "matchbalance-complete-group-analysis.json"
    csv_path = output_dir / "matchbalance-complete-group-analysis.csv"
    json_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_csv(csv_path, csv_rows)
    print(f"JSON={json_path}")
    print(f"CSV={csv_path}")
    print(f"CONTENT_SHA256={result['content_sha256']}")
    print(f"CSV_ROW_COUNT={len(csv_rows)}")


if __name__ == "__main__":
    main()
