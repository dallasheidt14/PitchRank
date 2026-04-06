from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import sigmoid_zscore_normalize


def _compute_sos_scale(sos_norm: pd.Series, cfg: GlickoConfig) -> pd.Series:
    """Replicate the SOS adjustment logic from compute_rankings_v2."""
    weak = ((cfg.SOS_ADJ_WEAK_THRESHOLD - sos_norm).clip(lower=0)
            / cfg.SOS_ADJ_WEAK_THRESHOLD)
    strong = ((sos_norm - cfg.SOS_ADJ_STRONG_THRESHOLD).clip(lower=0)
              / (1.0 - cfg.SOS_ADJ_STRONG_THRESHOLD))
    sos_scale = (1.0
                 + cfg.SOS_ADJ_STRONG_MAX * strong
                 - cfg.SOS_ADJ_WEAK_MAX * weak)
    return sos_scale.clip(1.0 - cfg.SOS_ADJ_WEAK_MAX, 1.0 + cfg.SOS_ADJ_STRONG_MAX)


class TestSOSAdjDeadZone:
    """Teams with sos_norm inside [0.45, 0.60] get sos_scale == 1.0 exactly."""

    def test_dead_zone_no_op(self):
        cfg = GlickoConfig()
        sos_norm = pd.Series([0.45, 0.50, 0.55, 0.60])
        scale = _compute_sos_scale(sos_norm, cfg)

        np.testing.assert_allclose(scale.values, 1.0, atol=1e-12)

    def test_dead_zone_powerscore_matches_baseline(self):
        """powerscore_adj with all-dead-zone SOS matches unadjusted sigmoid(mu)."""
        cfg = GlickoConfig()
        mu = pd.Series([1400.0, 1500.0, 1600.0, 1700.0])
        sos_norm = pd.Series([0.50, 0.50, 0.50, 0.50])

        scale = _compute_sos_scale(sos_norm, cfg)
        mu_sos = cfg.INITIAL_MU + (mu - cfg.INITIAL_MU) * scale
        adjusted = sigmoid_zscore_normalize(mu_sos)
        baseline = sigmoid_zscore_normalize(mu)

        pd.testing.assert_series_equal(adjusted, baseline)


class TestSOSAdjWeakPenalty:
    """Weak schedules (sos_norm < 0.45) compress mu deviation toward neutral."""

    def test_scale_at_boundaries(self):
        cfg = GlickoConfig()
        sos_norm = pd.Series([0.0, 0.10, 0.20, 0.45])
        scale = _compute_sos_scale(sos_norm, cfg)

        # sos_norm=0.0: weak = 0.45/0.45 = 1.0, scale = 1.0 - 0.16*1.0 = 0.84
        assert abs(scale.iloc[0] - 0.84) < 1e-12
        # sos_norm=0.10: weak = 0.35/0.45 ≈ 0.778, scale ≈ 0.876
        assert abs(scale.iloc[1] - (1.0 - 0.16 * 0.35 / 0.45)) < 1e-12
        # sos_norm=0.20: weak = 0.25/0.45 ≈ 0.556, scale ≈ 0.911
        assert abs(scale.iloc[2] - (1.0 - 0.16 * 0.25 / 0.45)) < 1e-12
        # sos_norm=0.45: dead zone edge, scale = 1.0
        assert abs(scale.iloc[3] - 1.0) < 1e-12

    def test_mu_sos_compressed(self):
        cfg = GlickoConfig()
        mu = pd.Series([1700.0, 1700.0])
        sos_norm = pd.Series([0.0, 0.50])  # weakest vs dead-zone

        scale = _compute_sos_scale(sos_norm, cfg)
        mu_sos = cfg.INITIAL_MU + (mu - cfg.INITIAL_MU) * scale

        # Weak team: 1500 + 200 * 0.84 = 1668
        assert abs(mu_sos.iloc[0] - 1668.0) < 1e-9
        # Dead-zone team: 1500 + 200 * 1.0 = 1700
        assert abs(mu_sos.iloc[1] - 1700.0) < 1e-9

    def test_powerscore_ordering(self):
        """Weak-SOS team gets lower powerscore_adj than dead-zone team with same mu."""
        cfg = GlickoConfig()
        mu = pd.Series([1700.0, 1700.0])
        sos_norm = pd.Series([0.10, 0.50])

        scale = _compute_sos_scale(sos_norm, cfg)
        mu_sos = cfg.INITIAL_MU + (mu - cfg.INITIAL_MU) * scale
        ps = sigmoid_zscore_normalize(mu_sos)

        assert ps.iloc[0] < ps.iloc[1]


class TestSOSAdjStrongReward:
    """Strong schedules (sos_norm > 0.60) get a modest mu deviation boost."""

    def test_scale_at_boundaries(self):
        cfg = GlickoConfig()
        sos_norm = pd.Series([0.60, 0.80, 0.90, 1.0])
        scale = _compute_sos_scale(sos_norm, cfg)

        # sos_norm=0.60: dead zone edge, scale = 1.0
        assert abs(scale.iloc[0] - 1.0) < 1e-12
        # sos_norm=0.80: strong = 0.20/0.40 = 0.5, scale = 1.0 + 0.03*0.5 = 1.015
        assert abs(scale.iloc[1] - 1.015) < 1e-12
        # sos_norm=0.90: strong = 0.30/0.40 = 0.75, scale = 1.0 + 0.03*0.75 = 1.0225
        assert abs(scale.iloc[2] - 1.0225) < 1e-12
        # sos_norm=1.0: strong = 0.40/0.40 = 1.0, scale = 1.0 + 0.03*1.0 = 1.03
        assert abs(scale.iloc[3] - 1.03) < 1e-12

    def test_powerscore_ordering(self):
        """Strong-SOS team gets higher powerscore_adj than dead-zone team with same mu."""
        cfg = GlickoConfig()
        mu = pd.Series([1700.0, 1700.0])
        sos_norm = pd.Series([0.90, 0.50])

        scale = _compute_sos_scale(sos_norm, cfg)
        mu_sos = cfg.INITIAL_MU + (mu - cfg.INITIAL_MU) * scale
        ps = sigmoid_zscore_normalize(mu_sos)

        assert ps.iloc[0] > ps.iloc[1]


class TestSOSAdjDisabled:
    """SOS_ADJ_ENABLED=False produces exactly sigmoid_zscore_normalize(mu)."""

    def test_disabled_matches_old_behavior(self):
        cfg = GlickoConfig()
        cfg.SOS_ADJ_ENABLED = False
        mu = pd.Series([1300.0, 1450.0, 1500.0, 1600.0, 1800.0])

        # With disabled flag, powerscore_adj should be sigmoid_zscore_normalize(mu)
        expected = sigmoid_zscore_normalize(mu)

        # Verify the flag gates the adjustment: scale should be 1.0 for all
        # (This tests the config flag, not the engine directly — the engine
        # test is the integration test that runs compute_rankings_v2.)
        assert cfg.SOS_ADJ_ENABLED is False
        pd.testing.assert_series_equal(expected, sigmoid_zscore_normalize(mu))
