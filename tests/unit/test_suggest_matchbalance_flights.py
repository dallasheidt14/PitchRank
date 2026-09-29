"""Frozen-pack regressions for automatic MatchBalance flight suggestions."""

from pathlib import Path

import pytest

from scripts.suggest_matchbalance_flights import (
    STARTING_COMMIT,
    _csv_rows,
    _markdown_report,
    build_automatic_report,
)

PREDICTOR_SHA256 = (
    "98b059f074e32584e973ca679c09985581b0867fe4175002a02cec0ada73cb5d"
)
SAN_SNAPSHOT = Path(
    r"C:\PitchRank\reports\seeding\san-antonio-labor-cup-26\seeding_run.json"
)
SAN_SHA256 = "a3ca6f1c7c2a03eb55d11d94bc0e60013cbcfeb1d8d1b5c560cdac6082e1a012"
SAN_ORDER = (
    "6",
    "4",
    "12",
    "9",
    "0",
    "7",
    "10",
    "5",
    "14",
    "1",
    "3",
    "15",
    "13",
    "11",
    "2",
    "8",
)
RSL_SNAPSHOT = Path(
    r"C:\PitchRank\reports\seeding\rsl-cactus-kickoff\history\20260928T184704914765.json"
)
RSL_SHA256 = "e53f5d626520976c269d51067142150391746d1a7da3b9a7e0d5ead50cb0a05c"
RSL_ORDER = (
    "77",
    "92",
    "89",
    "88",
    "84",
    "85",
    "79",
    "87",
    "76",
    "78",
    "81",
    "75",
    "91",
    "86",
    "83",
    "90",
    "82",
    "80",
)


def _report(snapshot: Path, sha256: str, event: str, slug: str):
    return build_automatic_report(
        snapshot_path=snapshot,
        event_name=event,
        report_slug=slug,
        cohorts=None,
        profile_id=None,
        order_source=None,
        expected_source_sha256=sha256,
        expected_predictor_sha256=PREDICTOR_SHA256,
        max_candidate_structures=None,
    )


def _plan(suggestion, sizes: tuple[int, ...]):
    return next(
        item
        for item in suggestion["assessment"]["plans"]
        if tuple(item["flight_sizes"]) == sizes
    )


@pytest.mark.skipif(not SAN_SNAPSHOT.exists(), reason="Frozen San snapshot unavailable")
def test_real_san_automatic_default_is_complete_and_preserves_regressions():
    report = _report(
        SAN_SNAPSHOT,
        SAN_SHA256,
        "SAN ANTONIO LABOR CUP 26",
        "san-antonio-labor-cup-u14-boys",
    )
    cohort = report["cohorts"][0]
    regression = cohort["order_and_boundary_regression"]
    suggestion = cohort["automatic_flight_suggestion"]

    assert report["code"]["starting_commit"] == STARTING_COMMIT
    assert report["code"]["starting_commit_is_ancestor"] is True
    assert report["snapshot_provenance"]["source_file_sha256_before"] == SAN_SHA256
    assert report["snapshot_provenance"]["source_unchanged_during_analysis"] is True
    assert tuple(regression["before_order_state"]["baseline_order"]) == SAN_ORDER
    assert tuple(regression["before_order_state"]["suggested_order"]) == SAN_ORDER
    assert regression["order_state_unchanged"] is True
    assert regression["boundary_state_unchanged"] is True
    assert regression["competitive_policy_unchanged"] is True
    assert cohort["natural_separation_findings"]["supported"] == []
    assert cohort["natural_separation_findings"]["uncertain"] == [14, 15]

    generation = suggestion["candidate_generation"]
    assert generation["supported_flight_sizes"] == (
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        12,
        13,
        14,
        15,
        16,
    )
    assert generation["generated_structure_count"] == 86
    assert generation["total_distinct_structure_count"] == 86
    assert generation["search_complete"] is True
    assert suggestion["status"] == "primary_suggestion_selected"
    assert suggestion["primary_plan"]["flight_sizes"] == [10, 6]
    assert suggestion["primary_evidence_status"] == "provisional_due_to_history"

    four = _plan(suggestion, (4, 4, 4, 4))
    assert four["projected_fit"]["all_pair_projected_fit_passed"] is True
    assert all(
        flight["complete_group_assessment"]["projected_competitive_fit"][
            "all_pair_projected_fit_passed"
        ]
        for flight in four["flights"]
    )
    eight = _plan(suggestion, (8, 8))
    assert eight["projected_fit"]["violating_pairing_count"] == 1
    assert {
        eight["violations"][0]["pairing"]["first_team"]["seed"],
        eight["violations"][0]["pairing"]["second_team"]["seed"],
    } == {10, 15}
    assert eight["violations"][0]["pairing"][
        "expected_absolute_goal_difference"
    ] == pytest.approx(2.1683822511264665)
    assert all(
        _plan(suggestion, sizes)["projected_fit"][
            "all_pair_projected_fit_passed"
        ]
        for sizes in ((5, 5, 6), (5, 6, 5), (6, 5, 5))
    )

    rows = _csv_rows(report)
    assert any(item["record_type"] == "potential_matchup" for item in rows)
    assert any(item["record_type"] == "template_validation" for item in rows)
    markdown = _markdown_report(report)
    assert "Natural competitive separation remains separate" in markdown
    assert "10/6" in markdown


@pytest.mark.skipif(not RSL_SNAPSHOT.exists(), reason="Frozen RSL snapshot unavailable")
def test_real_rsl_default_requires_review_and_keeps_outlier_visible():
    report = _report(
        RSL_SNAPSHOT,
        RSL_SHA256,
        "RSL Cactus Kickoff",
        "rsl-cactus-kickoff-u13-boys",
    )
    cohort = report["cohorts"][0]
    regression = cohort["order_and_boundary_regression"]
    suggestion = cohort["automatic_flight_suggestion"]

    assert report["snapshot_provenance"]["source_file_sha256_before"] == RSL_SHA256
    assert tuple(regression["before_order_state"]["baseline_order"]) == RSL_ORDER
    assert tuple(regression["before_order_state"]["suggested_order"]) == RSL_ORDER
    assert regression["order_state_unchanged"] is True
    assert regression["boundary_state_unchanged"] is True
    assert regression["competitive_policy_unchanged"] is True
    assert cohort["natural_separation_findings"]["supported"] == [1]

    generation = suggestion["candidate_generation"]
    assert generation["generated_structure_count"] == 180
    assert generation["total_distinct_structure_count"] == 180
    assert generation["search_complete"] is True
    assert suggestion["status"] == "no_complete_within_policy_arrangement"
    assert suggestion["primary_plan_id"] is None
    compromises = suggestion["nondominated_compromise_plan_ids"]
    plans_by_id = {
        item["plan_id"]: item for item in suggestion["assessment"]["plans"]
    }
    assert "plan-018-3-10-5" in compromises
    assert any(
        len(plans_by_id[plan_id]["flight_sizes"]) == 2
        for plan_id in compromises
    )
    assert "flight count" in suggestion["nondominated_compromise_basis"]

    six = _plan(suggestion, (6, 6, 6))
    assert six["projected_fit"]["violating_pairing_count"] == 6
    assert any(
        {
            item["pairing"]["first_team"]["seed"],
            item["pairing"]["second_team"]["seed"],
        }
        == {13, 16}
        for item in six["violations"]
    )
    assert _plan(suggestion, (4, 4, 5, 5))["projected_fit"][
        "all_pair_projected_fit_passed"
    ] is False

    seed_one = next(
        item
        for item in suggestion["assessment"]["all_opponent_assessments"]
        if item["team"]["seed"] == 1
    )
    assert seed_one["available_prediction_count"] == 17
    assert seed_one["missing_prediction_count"] == 0
    assert seed_one["invalid_prediction_count"] == 0
    assert seed_one["within_policy_opponents"] == []
    assert seed_one[
        "complete_predictions_establish_no_within_policy_opponent"
    ] is True


@pytest.mark.skipif(not SAN_SNAPSHOT.exists(), reason="Frozen San snapshot unavailable")
def test_real_snapshot_automatic_report_is_reproducible():
    first = _report(
        SAN_SNAPSHOT,
        SAN_SHA256,
        "SAN ANTONIO LABOR CUP 26",
        "san-antonio-labor-cup-u14-boys",
    )
    second = _report(
        SAN_SNAPSHOT,
        SAN_SHA256,
        "SAN ANTONIO LABOR CUP 26",
        "san-antonio-labor-cup-u14-boys",
    )

    assert first["content_sha256"] == second["content_sha256"]
    assert first["cohorts"] == second["cohorts"]
