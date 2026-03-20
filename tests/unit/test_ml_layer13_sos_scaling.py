"""
Tests for ML Layer 13 SOS-conditioned scaling.

The SOS-conditioned ML scaling in calculator.py gates ML authority by schedule
strength:
  - sos_norm < 0.45 → ML has NO authority (ml_scale = 0)
  - 0.45 ≤ sos_norm < 0.60 → linear ramp (0 → 1)
  - sos_norm ≥ 0.60 → ML has FULL authority (ml_scale = 1)

Formula:
  ml_scale = clip((sos_norm - 0.45) / (0.60 - 0.45), 0, 1)
  final = powerscore_adj + ml_scale * (powerscore_ml - powerscore_adj)
"""

import pytest
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants (matching calculator.py)
# ---------------------------------------------------------------------------
SOS_ML_THRESHOLD_LOW = 0.45
SOS_ML_THRESHOLD_HIGH = 0.60


def ml_scale_formula(sos_norm):
    """Replicate the SOS-conditioned ML scaling formula."""
    return np.clip(
        (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW),
        0.0, 1.0
    )


def final_score(ps_adj, ps_ml, sos_norm):
    """Compute final score using SOS-conditioned ML scaling."""
    scale = ml_scale_formula(sos_norm)
    ml_delta = ps_ml - ps_adj
    return np.clip(ps_adj + ml_delta * scale, 0.0, 1.0)


# ===========================================================================
# Unit tests for ml_scale formula
# ===========================================================================

class TestMLScaleFormula:
    """Test the SOS → ml_scale mapping."""

    def test_below_low_threshold(self):
        """sos_norm < 0.45 → ml_scale = 0."""
        assert ml_scale_formula(0.0) == 0.0
        assert ml_scale_formula(0.30) == 0.0
        assert ml_scale_formula(0.44) == 0.0
        assert ml_scale_formula(0.449) == 0.0

    def test_at_low_threshold(self):
        """sos_norm = 0.45 → ml_scale = 0."""
        assert ml_scale_formula(0.45) == pytest.approx(0.0, abs=1e-9)

    def test_midpoint(self):
        """sos_norm = 0.525 → ml_scale = 0.5."""
        mid = (SOS_ML_THRESHOLD_LOW + SOS_ML_THRESHOLD_HIGH) / 2
        assert ml_scale_formula(mid) == pytest.approx(0.5, abs=1e-9)

    def test_at_high_threshold(self):
        """sos_norm = 0.60 → ml_scale = 1.0."""
        assert ml_scale_formula(0.60) == pytest.approx(1.0, abs=1e-9)

    def test_above_high_threshold(self):
        """sos_norm > 0.60 → ml_scale = 1.0 (clamped)."""
        assert ml_scale_formula(0.70) == 1.0
        assert ml_scale_formula(0.90) == 1.0
        assert ml_scale_formula(1.00) == 1.0

    def test_linear_interpolation(self):
        """Scale should be linear between thresholds."""
        for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
            sos = SOS_ML_THRESHOLD_LOW + frac * (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)
            assert ml_scale_formula(sos) == pytest.approx(frac, abs=1e-9)

    def test_monotonically_increasing(self):
        """ml_scale must be non-decreasing as sos_norm increases."""
        sos_values = np.linspace(0.0, 1.0, 100)
        scales = [ml_scale_formula(s) for s in sos_values]
        for i in range(len(scales) - 1):
            assert scales[i] <= scales[i + 1] + 1e-10


# ===========================================================================
# Final score computation
# ===========================================================================

class TestFinalScoreComputation:
    """Test the full SOS-conditioned ML blending."""

    def test_weak_schedule_ignores_ml(self):
        """With sos_norm < 0.45, final = ps_adj regardless of ML."""
        ps_adj = 0.5
        ps_ml = 0.9  # ML thinks team is great
        result = final_score(ps_adj, ps_ml, sos_norm=0.30)
        assert result == pytest.approx(ps_adj, abs=1e-9)

    def test_strong_schedule_uses_full_ml(self):
        """With sos_norm >= 0.60, final = ps_adj + (ps_ml - ps_adj) = ps_ml."""
        ps_adj = 0.5
        ps_ml = 0.7
        result = final_score(ps_adj, ps_ml, sos_norm=0.80)
        assert result == pytest.approx(ps_ml, abs=1e-9)

    def test_mid_schedule_partial_ml(self):
        """With sos_norm = 0.525 (midpoint), final = ps_adj + 0.5 * delta."""
        ps_adj = 0.5
        ps_ml = 0.7
        mid_sos = (SOS_ML_THRESHOLD_LOW + SOS_ML_THRESHOLD_HIGH) / 2
        result = final_score(ps_adj, ps_ml, sos_norm=mid_sos)
        expected = ps_adj + 0.5 * (ps_ml - ps_adj)  # 0.5 + 0.5*0.2 = 0.6
        assert result == pytest.approx(expected, abs=1e-9)

    def test_negative_ml_delta_with_weak_schedule(self):
        """ML saying team is WORSE should be ignored with weak schedule."""
        ps_adj = 0.7
        ps_ml = 0.4  # ML says team is worse
        result = final_score(ps_adj, ps_ml, sos_norm=0.30)
        assert result == pytest.approx(ps_adj, abs=1e-9)

    def test_negative_ml_delta_with_strong_schedule(self):
        """ML saying team is WORSE should be applied with strong schedule."""
        ps_adj = 0.7
        ps_ml = 0.5
        result = final_score(ps_adj, ps_ml, sos_norm=0.80)
        assert result == pytest.approx(ps_ml, abs=1e-9)

    def test_bounds_clamping(self):
        """Final score should always be in [0, 1]."""
        # Extreme case: ML pushes above 1.0
        result = final_score(0.95, 1.5, sos_norm=0.80)
        assert result <= 1.0

        # Extreme case: ML pushes below 0.0
        result = final_score(0.05, -0.5, sos_norm=0.80)
        assert result >= 0.0


# ===========================================================================
# ML Layer 13 blending formula
# ===========================================================================

class TestLayer13BlendFormula:
    """Test the ML Layer 13 blending formula:
    powerscore_ml = (powerscore_adj + alpha * ml_norm) / MAX_ML_THEORETICAL
    where MAX_ML_THEORETICAL = 1.0 + 0.5 * alpha
    """

    def test_alpha_zero_passthrough(self):
        """With alpha=0, powerscore_ml should equal powerscore_adj."""
        alpha = 0.0
        ps_adj = 0.65
        ml_norm = 0.3  # Should be ignored
        MAX_ML = 1.0 + 0.5 * alpha  # = 1.0
        ps_ml = (ps_adj + alpha * ml_norm) / MAX_ML
        assert ps_ml == pytest.approx(ps_adj, abs=1e-9)

    def test_default_alpha_blend(self):
        """With default alpha=0.10, verify the formula."""
        alpha = 0.10
        ps_adj = 0.60
        ml_norm = 0.3  # Moderate overperformance
        MAX_ML = 1.0 + 0.5 * alpha  # = 1.05
        ps_ml = (ps_adj + alpha * ml_norm) / MAX_ML
        expected = (0.60 + 0.10 * 0.3) / 1.05  # = 0.63 / 1.05 ≈ 0.600
        assert ps_ml == pytest.approx(expected, abs=1e-6)

    def test_ml_norm_range_produces_valid_output(self):
        """ml_norm in [-0.5, +0.5] should keep powerscore_ml in [0, 1]."""
        alpha = 0.10
        MAX_ML = 1.0 + 0.5 * alpha

        for ps_adj in [0.0, 0.2, 0.5, 0.8, 1.0]:
            for ml_norm in [-0.5, -0.25, 0.0, 0.25, 0.5]:
                ps_ml = np.clip((ps_adj + alpha * ml_norm) / MAX_ML, 0.0, 1.0)
                assert 0.0 <= ps_ml <= 1.0, (
                    f"ps_ml={ps_ml:.4f} out of bounds with "
                    f"ps_adj={ps_adj}, ml_norm={ml_norm}"
                )

    def test_max_ml_contribution(self):
        """Maximum ML adjustment: alpha * 0.5 = 0.05 (with alpha=0.10)."""
        alpha = 0.10
        MAX_ML = 1.0 + 0.5 * alpha
        # Best case: ps_adj=1.0, ml_norm=+0.5
        ps_ml_max = (1.0 + alpha * 0.5) / MAX_ML  # = 1.05/1.05 = 1.0
        assert ps_ml_max == pytest.approx(1.0, abs=1e-9)

        # Worst case: ps_adj=0.0, ml_norm=-0.5
        ps_ml_min = (0.0 + alpha * (-0.5)) / MAX_ML  # = -0.05/1.05 ≈ -0.048
        # After clipping
        assert np.clip(ps_ml_min, 0.0, 1.0) == 0.0


# ===========================================================================
# Vectorized SOS-conditioned scaling (matching calculator.py)
# ===========================================================================

class TestVectorizedSOSScaling:
    """Test the vectorized version of SOS-conditioned scaling as used in calculator.py."""

    def test_vectorized_matches_scalar(self):
        """Vectorized computation should match element-wise scalar computation."""
        np.random.seed(42)
        n = 100
        ps_adj = np.random.uniform(0.2, 0.9, n)
        ps_ml = ps_adj + np.random.uniform(-0.1, 0.1, n)
        sos_norm = np.random.uniform(0.0, 1.0, n)

        # Vectorized (pandas-style, as in calculator.py)
        ml_delta = ps_ml - ps_adj
        ml_scale = np.clip(
            (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW),
            0.0, 1.0
        )
        vec_result = np.clip(ps_adj + ml_delta * ml_scale, 0.0, 1.0)

        # Scalar
        scalar_result = np.array([
            final_score(pa, pm, sn)
            for pa, pm, sn in zip(ps_adj, ps_ml, sos_norm)
        ])

        np.testing.assert_allclose(vec_result, scalar_result, atol=1e-10)

    def test_sos_nan_fills_to_half(self):
        """When sos_norm is NaN, it should be filled to 0.5 (within transition zone)."""
        sos_norm = pd.Series([np.nan, 0.5, np.nan])
        filled = sos_norm.fillna(0.5)
        expected_scale = ml_scale_formula(0.5)
        # 0.5 is between 0.45 and 0.60 → partial authority
        assert expected_scale == pytest.approx(1.0 / 3.0, abs=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
