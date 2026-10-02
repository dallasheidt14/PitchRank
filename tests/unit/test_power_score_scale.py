import math

import pandas as pd
import pytest

from src.rankings.calculator import _power_score_scale_alignment_report
from src.rankings.constants import AGE_TO_ANCHOR
from src.rankings.power_score_scale import (
    active_power_score_scale_version,
    get_power_score_scale,
    prediction_power_score,
    published_power_score,
    published_power_score_cap,
)

AGES = (10, 11, 12, 13, 14, 15, 16, 17, 19)


def test_active_scale_preserves_the_separate_boys_and_girls_shape():
    assert active_power_score_scale_version() == "age-gender-v2-2026-09-25"
    assert published_power_score_cap(17, "Male") == pytest.approx(0.646259980431884)
    assert published_power_score_cap(19, "Male") == pytest.approx(0.8)
    assert published_power_score_cap(17, "Female") == pytest.approx(0.605779518153415)
    assert published_power_score_cap(19, "Female") == pytest.approx(0.705084745762712)
    assert published_power_score_cap(19, "Female") > published_power_score_cap(17, "Female")
    assert published_power_score_cap(12, "Male") == pytest.approx(0.451016136022036)
    assert published_power_score_cap(12, "Female") == pytest.approx(0.448130475383406)


@pytest.mark.parametrize("gender", ["Male", "Female", "Boys", "Girls", "M", "F"])
@pytest.mark.parametrize("age", AGES)
def test_every_curve_is_bounded_and_strictly_increasing(age, gender):
    normalized_gender = "Female" if gender in {"Female", "Girls", "F"} else "Male"
    values = [published_power_score(index / 1000, age, gender) for index in range(1001)]
    cap = published_power_score_cap(age, normalized_gender)
    assert values[0] == 0
    assert values[-1] == pytest.approx(cap)
    assert all(math.isfinite(value) and 0 <= value <= cap for value in values)
    assert all(left < right for left, right in zip(values, values[1:]))


def test_tail_landmarks_are_exact_and_preserve_the_legacy_mapping_below_the_tail():
    scale = get_power_score_scale()
    for gender in ("Male", "Female"):
        for age in AGES:
            curve = scale.curve(age, gender)
            assert published_power_score(curve.tail_start_p, age, gender) == pytest.approx(curve.tail_start_score)
            assert published_power_score(curve.observed_max_p, age, gender) == pytest.approx(
                curve.observed_top_score
            )
            assert published_power_score(curve.tail_start_p / 2, age, gender) == pytest.approx(
                curve.tail_start_p / 2 * AGE_TO_ANCHOR[age]
            )


def test_observed_younger_number_one_matches_the_frozen_next_age_number_25():
    scale = get_power_score_scale()
    next_age_by_age = dict(zip(AGES[:-1], AGES[1:]))
    rank_25 = scale.reference_snapshot["next_age_rank_25_power_score_true"]

    for gender in ("Male", "Female"):
        for younger_age, older_age in next_age_by_age.items():
            younger_curve = scale.curve(younger_age, gender)
            older_rank_25_score = published_power_score(
                rank_25[gender][str(older_age)], older_age, gender
            )
            assert younger_curve.observed_top_score == pytest.approx(older_rank_25_score)


def test_alignment_monitor_reports_rank_25_and_detects_reference_max_drift():
    scale = get_power_score_scale()
    younger = scale.curve(12, "Male")
    target = younger.observed_top_score
    rows = [
        {
            "age_num": 12,
            "gender": "Male",
            "power_score_true": younger.observed_max_p + 0.001,
            "power_score_final": target,
            "status": "Active",
        }
    ]
    rows.extend(
        {
            "age_num": 13,
            "gender": "Male",
            "power_score_true": 0.9 - index / 1000,
            "power_score_final": target + (25 - index) / 1000,
            "status": "Active",
        }
        for index in range(1, 26)
    )
    rows.append(
        {
            "age_num": 13,
            "gender": "Male",
            "power_score_true": 0.4,
            "power_score_final": target - 0.001,
            "status": "Active",
        }
    )

    report = _power_score_scale_alignment_report(pd.DataFrame(rows), scale.version)
    u12 = next(item for item in report if item["gender"] == "Male" and item["age"] == 12)

    assert u12["equivalent_rank"] == 25
    assert u12["max_drifted"] is True


def test_u18_uses_the_combined_u19_scale_without_creating_a_new_board():
    for gender in ("Male", "Female"):
        assert published_power_score(0.7, 18, gender) == pytest.approx(published_power_score(0.7, 19, gender))


def test_prediction_score_preserves_the_legacy_anchor_mapping():
    for age, anchor in AGE_TO_ANCHOR.items():
        assert prediction_power_score(0.731, age) == pytest.approx(0.731 * anchor)


@pytest.mark.parametrize("score", [-0.01, 1.01, math.nan, math.inf])
def test_invalid_scores_fail_closed(score):
    with pytest.raises(ValueError):
        published_power_score(score, 12, "Male")


@pytest.mark.parametrize(
    "age,gender,error",
    [
        (9, "Male", "Unsupported PowerScore scale cohort"),
        (20, "Female", "Unsupported PowerScore scale cohort"),
        (12, "Unknown", "Unsupported PowerScore scale gender"),
    ],
)
def test_unknown_cohorts_fail_closed(age, gender, error):
    with pytest.raises(ValueError, match=error):
        published_power_score(0.5, age, gender)
