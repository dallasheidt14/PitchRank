import math

import pytest

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
    assert active_power_score_scale_version() == "age-gender-v1-2026-09-25"
    assert published_power_score_cap(17, "Male") == pytest.approx(0.8)
    assert published_power_score_cap(19, "Male") == pytest.approx(0.8)
    assert published_power_score_cap(17, "Female") == pytest.approx(53 * 80 / 59 / 100)
    assert published_power_score_cap(19, "Female") == pytest.approx(52 * 80 / 59 / 100)
    assert published_power_score_cap(19, "Female") < published_power_score_cap(17, "Female")
    assert published_power_score_cap(12, "Male") == pytest.approx(49 * 80 / 59 / 100)
    assert published_power_score_cap(12, "Female") == pytest.approx(45 * 80 / 59 / 100)


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


def test_reference_landmarks_are_exact_and_curve_is_smooth():
    scale = get_power_score_scale()
    for gender in ("Male", "Female"):
        for age in AGES[1:]:
            curve = scale.curve(age, gender)
            assert curve.reference_p is not None
            assert curve.reference_score is not None
            assert published_power_score(curve.reference_p, age, gender) == pytest.approx(curve.reference_score)
            step = 1e-7
            center = published_power_score(curve.reference_p, age, gender)
            left_slope = (center - published_power_score(curve.reference_p - step, age, gender)) / step
            right_slope = (published_power_score(curve.reference_p + step, age, gender) - center) / step
            assert left_slope == pytest.approx(right_slope, abs=1e-5)


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
