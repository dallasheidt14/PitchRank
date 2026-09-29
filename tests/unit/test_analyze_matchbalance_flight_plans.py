"""Standalone complete flight-plan diagnostic and frozen-data regressions."""

from pathlib import Path

import pytest

from scripts.analyze_matchbalance_flight_plans import (
    EXPECTED_BRANCH,
    STARTING_COMMIT,
    build_report,
    build_structure_requests,
    select_saved_order,
)
from src.tournaments.seeding_plan_assessment import (
    APPROVED_ALTERNATIVES,
    EXACT_ORDERED,
    PERMITTED_SIZE_MULTISET,
)
from src.tournaments.seeding_tiers import CheatSheetAnalysis

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


def _scenario(report, label: str):
    return next(item for item in report["scenarios"] if item["label"] == label)


def test_cli_structure_modes_are_explicit_and_labeled():
    requests = build_structure_requests(
        ["ordered=6,6,6"],
        ["permuted=6,5,5"],
        ["approved=8,8;4,4,4,4"],
    )

    assert [item.mode for item in requests] == [
        EXACT_ORDERED,
        PERMITTED_SIZE_MULTISET,
        APPROVED_ALTERNATIVES,
    ]
    assert requests[2].requested_structures == ((8, 8), (4, 4, 4, 4))


@pytest.mark.parametrize(
    "inputs",
    [
        (["same=2,2"], ["same=2,2"], []),
        (["same-label=2,2"], ["same label=2,2"], []),
    ],
)
def test_cli_structure_labels_must_be_distinct(inputs):
    with pytest.raises(ValueError, match="unique"):
        build_structure_requests(*inputs)


def test_manual_override_requires_explicit_order_choice_without_mutation():
    analysis = CheatSheetAnalysis(
        ordered_ids=("b", "a"),
        review={"c": "Placement review"},
        placement_status={"a": "Seeded", "b": "Seeded", "c": "Data review"},
        breaks=(),
        close_ranges=(),
        notes=(),
        diagnostics=(),
        baseline_order=("a", "b"),
        suggested_order=("a", "b"),
        manual_override=True,
        manual_holds=(),
    )
    before = analysis

    with pytest.raises(ValueError, match="manual override"):
        select_saved_order(analysis, ("a", "b", "c"), None)

    suggested = select_saved_order(
        analysis, ("a", "b", "c"), "suggested"
    )
    effective = select_saved_order(
        analysis, ("a", "b", "c"), "effective"
    )

    assert suggested.entrant_ids == ("a", "b")
    assert effective.entrant_ids == ("b", "a")
    assert suggested.unassigned_entrants[0].entrant_id == "c"
    assert analysis == before


@pytest.mark.skipif(not SAN_SNAPSHOT.exists(), reason="Frozen San snapshot unavailable")
def test_real_san_complete_plan_regression():
    requests = build_structure_requests(
        ["four-by-four=4,4,4,4", "eight-by-eight=8,8"],
        ["six-five-five=6,5,5"],
        [],
    )
    report, rows = build_report(
        snapshot_path=SAN_SNAPSHOT,
        cohort="u14|Male",
        event_name="SAN ANTONIO LABOR CUP 26",
        report_slug="san-antonio-labor-cup-u14-boys",
        requests=requests,
        order_source=None,
        expected_source_sha256=SAN_SHA256,
        expected_predictor_sha256=PREDICTOR_SHA256,
        max_arrangements=10_000,
    )

    regression = report["order_and_boundary_regression"]
    assert report["code"]["implementation_branch"] == EXPECTED_BRANCH
    assert report["code"]["starting_commit_ancestry_required"] is False
    assert report["code"]["starting_commit"] == STARTING_COMMIT
    assert tuple(regression["before_order_state"]["baseline_order"]) == SAN_ORDER
    assert tuple(regression["before_order_state"]["suggested_order"]) == SAN_ORDER
    assert regression["order_state_unchanged"] is True
    assert regression["boundary_state_unchanged"] is True
    assert regression["policy_unchanged"] is True
    assert report["snapshot_provenance"]["source_unchanged_during_analysis"] is True

    four = _scenario(report, "four-by-four")
    assert len(four["plans"]) == 1
    assert four["plans"][0]["projected_fit"][
        "all_pair_projected_fit_passed"
    ] is True
    assert [
        flight["complete_group_assessment"]["projected_competitive_fit"][
            "all_pair_projected_fit_passed"
        ]
        for flight in four["plans"][0]["flights"]
    ] == [True, True, True, True]
    assert four["plans"][0]["evidence"]["limited_history_pairing_count"] > 0

    eight = _scenario(report, "eight-by-eight")
    eight_plan = eight["plans"][0]
    assert eight["conclusion"] == (
        "No all-pair within-policy plan among the permitted arrangements."
    )
    assert eight_plan["projected_fit"]["violating_pairing_count"] == 1
    violation = eight_plan["violations"][0]
    assert {
        violation["pairing"]["first_team"]["seed"],
        violation["pairing"]["second_team"]["seed"],
    } == {10, 15}
    assert violation["pairing"]["expected_absolute_goal_difference"] == pytest.approx(
        2.1683822511264665
    )
    assert violation["expected_goal_difference_excess"] == pytest.approx(
        0.16838225112646654
    )
    assert violation["pairing"]["within_blowout_probability_limit"] is True

    permuted = _scenario(report, "six-five-five")
    assert [plan["flight_sizes"] for plan in permuted["plans"]] == [
        [5, 5, 6],
        [5, 6, 5],
        [6, 5, 5],
    ]
    assert all(
        plan["projected_fit"]["all_pair_projected_fit_passed"]
        for plan in permuted["plans"]
    )
    assert any(row["record_type"] == "flight_pair" for row in rows)


@pytest.mark.skipif(not RSL_SNAPSHOT.exists(), reason="Frozen RSL snapshot unavailable")
def test_real_rsl_complete_plan_and_all_opponent_regression():
    requests = build_structure_requests(
        ["six-by-six=6,6,6"],
        ["five-five-four-four=5,5,4,4"],
        [],
    )
    report, _ = build_report(
        snapshot_path=RSL_SNAPSHOT,
        cohort="u13|Male",
        event_name="RSL Cactus Kickoff",
        report_slug="rsl-cactus-kickoff-u13-boys",
        requests=requests,
        order_source=None,
        expected_source_sha256=RSL_SHA256,
        expected_predictor_sha256=PREDICTOR_SHA256,
        max_arrangements=10_000,
    )

    regression = report["order_and_boundary_regression"]
    assert tuple(regression["before_order_state"]["baseline_order"]) == RSL_ORDER
    assert tuple(regression["before_order_state"]["suggested_order"]) == RSL_ORDER
    assert regression["order_state_unchanged"] is True
    assert regression["boundary_state_unchanged"] is True
    assert regression["policy_unchanged"] is True

    six = _scenario(report, "six-by-six")
    assert six["conclusion"] == (
        "No all-pair within-policy plan among the permitted arrangements."
    )
    six_plan = six["plans"][0]
    assert six_plan["projected_fit"]["violating_pairing_count"] == 6
    assert any(
        {
            item["pairing"]["first_team"]["seed"],
            item["pairing"]["second_team"]["seed"],
        }
        == {13, 16}
        for item in six_plan["violations"]
    )

    permuted = _scenario(report, "five-five-four-four")
    assert len(permuted["plans"]) == 6
    assert not any(
        plan["projected_fit"]["all_pair_projected_fit_passed"]
        for plan in permuted["plans"]
    )
    assert permuted["comparisons"][0]["nondominated_plan_ids"] == [
        "plan-001-4-4-5-5"
    ]
    assert all(
        plan["selected_order"][0] == RSL_ORDER[0] for plan in permuted["plans"]
    )

    seed_one = next(
        item
        for item in six["all_opponent_assessments"]
        if item["team"]["seed"] == 1
    )
    assert seed_one["team"]["history_quality"] == "established"
    assert seed_one["available_prediction_count"] == 17
    assert seed_one["missing_prediction_count"] == 0
    assert seed_one["invalid_prediction_count"] == 0
    assert seed_one["within_policy_opponents"] == []
    assert seed_one[
        "complete_predictions_establish_no_within_policy_opponent"
    ] is True
