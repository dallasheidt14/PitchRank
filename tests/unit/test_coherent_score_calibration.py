import numpy as np
import pandas as pd

from src.predictions.coherent_score_calibration import (
    NEUTRAL_PARAMETERS,
    apply_score_distribution_calibration,
    apply_score_distribution_parameters,
    fit_score_distribution_calibration,
    score_distribution_calibration_loss,
)
from src.predictions.point_in_time_match_model import (
    _poisson_score_matrix,
    _score_matrix_summary,
)


def _calibration_frame(
    scores: list[tuple[int, int]],
    *,
    ages: list[int] | None = None,
) -> pd.DataFrame:
    count = len(scores)
    score_a = np.asarray([score[0] for score in scores], dtype=float)
    score_b = np.asarray([score[1] for score in scores], dtype=float)
    ages = ages or [14] * count
    return pd.DataFrame(
        {
            "actual_score_a": score_a,
            "actual_score_b": score_b,
            "actual_margin": score_a - score_b,
            "example_orientation": ["original"] * count,
            "age_group_numeric": ages,
            "team_a_is_female": [0.0] * count,
            "team_b_is_female": [0.0] * count,
            "team_a_games_played": [12.0] * count,
            "team_b_games_played": [12.0] * count,
        }
    )


def test_neutral_score_distribution_parameters_are_exact_identity():
    matrices = _poisson_score_matrix(
        np.array([1.2, 2.4]),
        np.array([1.8, 0.7]),
    )

    calibrated = apply_score_distribution_parameters(matrices, NEUTRAL_PARAMETERS)

    np.testing.assert_array_equal(calibrated, matrices)


def test_score_distribution_tilts_preserve_normalization_and_nested_tails():
    matrices = _poisson_score_matrix(
        np.array([1.2, 2.4]),
        np.array([1.8, 0.7]),
    )

    calibrated = apply_score_distribution_parameters(
        matrices,
        {
            "temperature": 0.85,
            "absolute_margin_tilt": 0.18,
            "total_goals_tilt": 0.08,
        },
    )
    summary = _score_matrix_summary(calibrated)

    np.testing.assert_allclose(calibrated.sum(axis=(1, 2)), np.ones(2))
    assert np.all(summary["blowout_5plus_probability"] <= summary["blowout_4plus_probability"])
    assert np.all(summary["blowout_4plus_probability"] <= summary["blowout_3plus_probability"])


def test_fitted_calibration_improves_synthetic_underdispersed_distribution():
    scores = [(4, 0), (0, 4)] * 100
    frame = _calibration_frame(scores)
    raw = _poisson_score_matrix(
        np.full(len(frame), 1.45),
        np.full(len(frame), 1.45),
    )

    calibration = fit_score_distribution_calibration(
        raw,
        frame,
        minimum_segment_examples=500,
    )
    calibrated = apply_score_distribution_calibration(raw, frame, calibration)

    assert calibration["calibrated_loss"] < calibration["neutral_loss"]
    assert score_distribution_calibration_loss(calibrated, frame) < score_distribution_calibration_loss(raw, frame)


def test_segment_calibration_requires_support_and_is_partially_pooled():
    scores = [(4, 0)] * 160 + [(1, 1)] * 160
    ages = [10] * 160 + [16] * 160
    frame = _calibration_frame(scores, ages=ages)
    raw = _poisson_score_matrix(
        np.full(len(frame), 1.4),
        np.full(len(frame), 1.4),
    )

    calibration = fit_score_distribution_calibration(
        raw,
        frame,
        minimum_segment_examples=150,
        shrinkage_examples=300,
    )

    age_segments = calibration["segments"]["age_gender"]
    assert set(age_segments) == {"u10:boys", "u16:boys"}
    assert all(0.0 < segment["shrinkage_weight"] < 1.0 for segment in age_segments.values())
    assert all(segment["loss"] <= segment["global_loss_on_segment"] for segment in age_segments.values())


def test_segment_calibration_skips_small_segments():
    frame = _calibration_frame([(2, 0)] * 50, ages=[11] * 50)
    raw = _poisson_score_matrix(
        np.full(len(frame), 1.4),
        np.full(len(frame), 1.0),
    )

    calibration = fit_score_distribution_calibration(
        raw,
        frame,
        minimum_segment_examples=100,
    )

    assert calibration["segments"]["age_gender"] == {}
    assert calibration["segments"]["history_coverage"] == {}
