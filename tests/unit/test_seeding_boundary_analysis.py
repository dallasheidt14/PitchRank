"""Every MatchBalance boundary is a persisted matchup-quality decision."""

from dataclasses import replace
from itertools import combinations

import pytest

from src.tournaments.compare_predictor_bridge import ComparePrediction
from src.tournaments.seeding_content import build_director_cohort
from src.tournaments.seeding_sheet import CohortSheet, SheetTeam, render_sheet_html
from src.tournaments.seeding_tiers import (
    NO_MEANINGFUL_SEPARATION,
    SUPPORTED_SEPARATION,
    UNCERTAIN_SEPARATION,
    TierEntrant,
    TierPolicy,
    build_cheat_sheet_analysis,
)


def _prediction(
    margin: float,
    *,
    absolute_goal_difference: float,
    blowout: float,
    confidence: str = "high",
) -> ComparePrediction:
    return ComparePrediction(
        predicted_winner="team_a" if margin > 0 else "team_b" if margin < 0 else "draw",
        win_probability_a=0.60 if margin > 0 else 0.25,
        win_probability_b=0.25 if margin > 0 else 0.60,
        draw_probability=0.15,
        expected_score={"teamA": 2, "teamB": 1},
        expected_margin=margin,
        expected_absolute_goal_difference=absolute_goal_difference,
        blowout_4plus_probability=blowout,
        confidence=confidence,
        confidence_score=0.80,
    )


def _matrix(ids: list[str], shape: str) -> dict[tuple[str, str], ComparePrediction]:
    result = {}
    for first, second in combinations(ids, 2):
        if shape == "supported":
            value = _prediction(1.5, absolute_goal_difference=3.0, blowout=0.40)
        elif shape == "direction-only":
            value = _prediction(1.2, absolute_goal_difference=1.2, blowout=0.10)
        elif shape == "reasonable":
            value = _prediction(0.4, absolute_goal_difference=1.2, blowout=0.10)
        elif shape == "conflicting":
            direction = 1.0 if (int(first) + int(second)) % 2 else -1.0
            value = _prediction(
                1.5 * direction,
                absolute_goal_difference=3.0,
                blowout=0.40,
            )
        else:  # pragma: no cover - test helper guard
            raise ValueError(shape)
        result[(first, second)] = value
    return result


def _entrants(scores: list[float], *, limited: set[int] | None = None) -> list[TierEntrant]:
    limited = limited or set()
    return [
        TierEntrant(
            str(index),
            f"Team {index + 1}",
            score,
            limited_history=index in limited,
            evidence_game_count=4 if index in limited else 20,
        )
        for index, score in enumerate(scores)
    ]


def _analysis(
    scores: list[float],
    shape: str,
    *,
    limited: set[int] | None = None,
    policy: TierPolicy | None = None,
):
    entrants = _entrants(scores, limited=limited)
    predictions = _matrix([item.entrant_id for item in entrants], shape)
    return build_cheat_sheet_analysis(entrants, predictions, policy or TierPolicy())


def _boundary(analysis, after_seed: int):
    return next(item for item in analysis.boundary_assessments if item.after_seed == after_seed)


def test_every_adjacent_boundary_is_assessed_with_complete_diagnostics():
    analysis = _analysis([0.80 - index * 0.01 for index in range(8)], "reasonable")

    assert [item.after_seed for item in analysis.boundary_assessments] == list(range(1, 8))
    item = _boundary(analysis, 4)
    assert item.upper_ids and item.lower_ids
    assert item.pairing_count == len(item.upper_ids) * len(item.lower_ids)
    assert item.worst_pair is not None
    assert item.tested_window_sizes == (3, 4, 5)
    assert item.upper_power_score == pytest.approx(0.77)
    assert item.lower_power_score == pytest.approx(0.76)
    assert item.power_score_gap == pytest.approx(0.01)
    assert item.reason


def test_large_powerscore_gap_alone_is_no_meaningful_separation():
    analysis = _analysis([0.90, 0.40, 0.39, 0.38, 0.37], "reasonable")

    item = _boundary(analysis, 1)
    assert item.power_score_gap == pytest.approx(0.50)
    assert item.classification == NO_MEANINGFUL_SEPARATION
    assert not analysis.supported_boundaries


def test_small_powerscore_gap_can_be_supported_by_matchup_risk():
    analysis = _analysis([0.704, 0.703, 0.702, 0.701, 0.700], "supported")

    item = _boundary(analysis, 2)
    assert item.power_score_gap == pytest.approx(0.001)
    assert item.classification == SUPPORTED_SEPARATION
    assert item.over_limit_fraction == 1


def test_upper_side_direction_alone_is_not_a_competitive_break():
    analysis = _analysis([0.70 - index * 0.01 for index in range(5)], "direction-only")

    item = _boundary(analysis, 2)
    assert item.favored_fraction == 1
    assert item.average_expected_margin == pytest.approx(1.2)
    assert item.over_limit_fraction == 0
    assert item.classification == NO_MEANINGFUL_SEPARATION


def test_cross_boundary_competitive_risk_changes_the_classification():
    scores = [0.70 - index * 0.01 for index in range(5)]
    safe = _analysis(scores, "direction-only")
    risky = _analysis(scores, "supported")

    assert _boundary(safe, 2).classification == NO_MEANINGFUL_SEPARATION
    assert _boundary(risky, 2).classification == SUPPORTED_SEPARATION


def test_top_and_bottom_boundaries_survive_as_first_class_findings():
    analysis = _analysis([0.80 - index * 0.01 for index in range(8)], "supported")

    assert _boundary(analysis, 1).classification == SUPPORTED_SEPARATION
    assert _boundary(analysis, 7).classification == SUPPORTED_SEPARATION
    assert not analysis.standouts


def test_nearby_supported_boundaries_do_not_suppress_each_other():
    analysis = _analysis([0.80 - index * 0.01 for index in range(8)], "supported")

    supported = {item.after_seed for item in analysis.supported_boundaries}
    assert {3, 4, 5}.issubset(supported)


def test_more_than_three_supported_boundaries_are_preserved_before_presentation():
    analysis = _analysis([0.80 - index * 0.01 for index in range(8)], "supported")

    assert len(analysis.supported_boundaries) == 7
    assert len(analysis.breaks) == 3


def test_limited_history_dominated_boundary_is_uncertain():
    analysis = _analysis(
        [0.80 - index * 0.01 for index in range(5)],
        "supported",
        limited={0, 1, 2},
    )

    item = _boundary(analysis, 2)
    assert item.classification == UNCERTAIN_SEPARATION
    assert item.evidence_quality == "limited-history-dominated"
    assert not item.usable_window_sizes


def test_established_evidence_can_classify_despite_one_limited_history_team():
    analysis = _analysis(
        [0.80 - index * 0.01 for index in range(6)],
        "supported",
        limited={1},
    )

    item = _boundary(analysis, 3)
    assert item.classification == SUPPORTED_SEPARATION
    assert item.evidence_quality == "mixed"
    assert item.established_pairing_count == item.limited_history_pairing_count == 3


def test_boundary_analysis_is_deterministic_under_input_and_pair_orientation_changes():
    scores = [0.80 - index * 0.01 for index in range(6)]
    entrants = _entrants(scores)
    predictions = _matrix([item.entrant_id for item in entrants], "supported")
    reversed_predictions = {
        (second, first): replace(value, expected_margin=-value.expected_margin)
        for (first, second), value in reversed(list(predictions.items()))
    }

    first = build_cheat_sheet_analysis(entrants, predictions)
    second = build_cheat_sheet_analysis(list(reversed(entrants)), reversed_predictions)

    assert first.boundary_assessments == second.boundary_assessments
    assert first.supported_boundaries == second.supported_boundaries


def test_boundary_thresholds_do_not_change_suggested_seed_order():
    scores = [0.80 - index * 0.01 for index in range(6)]
    default = _analysis(scores, "supported")
    stricter = _analysis(
        scores,
        "supported",
        policy=TierPolicy(boundary_min_average_signed_margin=2.0),
    )

    assert default.baseline_order == stricter.baseline_order
    assert default.suggested_order == stricter.suggested_order
    assert default.movements == stricter.movements
    assert default.supported_boundaries
    assert not stricter.supported_boundaries


def test_boundary_analysis_does_not_mutate_powerscore_baseline():
    entrants = _entrants([0.90, 0.80, 0.70, 0.60, 0.50])
    before = tuple(item.power_score for item in entrants)

    analysis = build_cheat_sheet_analysis(
        entrants,
        _matrix([item.entrant_id for item in entrants], "supported"),
    )

    assert tuple(item.power_score for item in entrants) == before
    assert analysis.baseline_order == tuple(item.entrant_id for item in entrants)


def test_customer_export_can_keep_a_three_finding_subset_without_losing_analysis():
    entrants = _entrants([0.80 - index * 0.01 for index in range(8)])
    analysis = build_cheat_sheet_analysis(
        entrants,
        _matrix([item.entrant_id for item in entrants], "supported"),
    )
    sheet = CohortSheet(
        "u14",
        "Male",
        tuple(
            SheetTeam(item.team_name, "Club", item.power_score, entrant_id=item.entrant_id)
            for item in entrants
        ),
        (),
        analysis,
    )

    content = build_director_cohort(sheet)
    html = render_sheet_html(
        "Cup",
        [sheet],
        generated_on="2026-09-28",
        ranking_run="2026-09-27",
    )

    assert len(analysis.supported_boundaries) == 7
    assert sum(row.strength_break_after for row in content.rows) == 3
    assert "Competitive Break" in html


SAN_ANTONIO_SCORES = [
    0.750, 0.700, 0.650, 0.600, 0.560, 0.530, 0.500, 0.480,
    0.460, 0.450, 0.440, 0.432, 0.404, 0.379, 0.352, 0.340,
]


def test_san_antonio_neighboring_gaps_are_independent_of_relative_gap_size():
    supported = _analysis(SAN_ANTONIO_SCORES, "supported")
    reasonable = _analysis(SAN_ANTONIO_SCORES, "reasonable")

    assert [_boundary(supported, seed).power_score_gap for seed in (12, 13, 14)] == pytest.approx(
        [0.028, 0.025, 0.027]
    )
    assert {
        _boundary(supported, seed).classification for seed in (12, 13, 14)
    } == {SUPPORTED_SEPARATION}
    assert {
        _boundary(reasonable, seed).classification for seed in (12, 13, 14)
    } == {NO_MEANINGFUL_SEPARATION}


RSL_SCORES = [
    0.738, 0.438, 0.436, 0.405, 0.396, 0.369, 0.360, 0.355, 0.350,
    0.345, 0.340, 0.335, 0.331, 0.301, 0.281, 0.217, 0.205, 0.195,
]


@pytest.mark.parametrize(
    "shape,expected",
    [
        ("supported", SUPPORTED_SEPARATION),
        ("reasonable", NO_MEANINGFUL_SEPARATION),
        ("conflicting", UNCERTAIN_SEPARATION),
    ],
)
def test_rsl_seed_one_boundary_is_never_silently_dropped(shape: str, expected: str):
    analysis = _analysis(RSL_SCORES, shape)

    top = _boundary(analysis, 1)
    assert top.power_score_gap == pytest.approx(0.300)
    assert top.classification == expected


def test_rsl_lower_supported_boundaries_coexist_without_suppression():
    analysis = _analysis(RSL_SCORES, "supported")
    supported = {item.after_seed for item in analysis.supported_boundaries}

    assert {1, 3, 5, 13, 15}.issubset(supported)
