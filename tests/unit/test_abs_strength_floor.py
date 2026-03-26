"""
Test that abs_strength is floored at UNRANKED_SOS_BASE (0.35).

Regression test for the bug where ranked teams with low power_presos * anchor
would get abs_strength < 0.35, contributing LESS to SOS than the default
for unranked opponents (UNRANKED_SOS_BASE = 0.35). This penalizes teams
whose opponents are ranked but weak, making their SOS artificially low.

Fix: clip(cfg.UNRANKED_SOS_BASE, 1.0) instead of clip(0.0, 1.0)
"""

import numpy as np
import pandas as pd
import pytest


class TestAbsStrengthFloor:
    """abs_strength must never fall below UNRANKED_SOS_BASE for ranked teams."""

    UNRANKED_SOS_BASE = 0.35

    def _compute_abs_strength(self, power_presos: float, anchor: float) -> float:
        """Replicate the fixed abs_strength formula from v53e.py."""
        return np.clip(power_presos * anchor, self.UNRANKED_SOS_BASE, 1.0)

    def test_strong_team_high_age_unchanged(self):
        """A strong U19 team should keep its high abs_strength."""
        result = self._compute_abs_strength(0.85, 1.0)
        assert result == 0.85

    def test_weak_team_low_age_floored(self):
        """A weak U10 team (anchor=0.40) with low power should be floored."""
        # power_presos=0.30, anchor=0.40 → raw = 0.12 → floored to 0.35
        result = self._compute_abs_strength(0.30, 0.40)
        assert result == self.UNRANKED_SOS_BASE

    def test_moderate_team_u12_floored(self):
        """U12 team with moderate power: 0.50 * 0.55 = 0.275 → floored."""
        result = self._compute_abs_strength(0.50, 0.55)
        assert result == self.UNRANKED_SOS_BASE

    def test_strong_team_u12_above_floor(self):
        """Strong U12 team: 0.80 * 0.55 = 0.44 → above floor, unchanged."""
        result = self._compute_abs_strength(0.80, 0.55)
        assert abs(result - 0.44) < 1e-9

    def test_ceiling_at_1(self):
        """abs_strength is capped at 1.0."""
        result = self._compute_abs_strength(1.2, 1.0)
        assert result == 1.0

    def test_floor_equals_unranked_default(self):
        """The floor ensures ranked teams are never worth less than unranked ones."""
        # Any ranked team's abs_strength should be >= UNRANKED_SOS_BASE
        for power in np.arange(0.0, 1.01, 0.1):
            for anchor in [0.40, 0.475, 0.55, 0.625, 0.70, 0.775, 0.85, 0.925, 1.0]:
                result = self._compute_abs_strength(power, anchor)
                assert result >= self.UNRANKED_SOS_BASE, (
                    f"abs_strength={result:.3f} < UNRANKED_SOS_BASE={self.UNRANKED_SOS_BASE} "
                    f"for power_presos={power:.2f}, anchor={anchor:.3f}"
                )

    def test_vectorized_clip(self):
        """Simulate the actual pandas vectorized operation from v53e.py."""
        df = pd.DataFrame({
            "power_presos": [0.10, 0.30, 0.50, 0.70, 0.90],
            "anchor": [0.40, 0.55, 0.70, 0.85, 1.00],
        })
        df["abs_strength"] = (df["power_presos"] * df["anchor"]).clip(
            self.UNRANKED_SOS_BASE, 1.0
        )
        # All values should be >= floor
        assert (df["abs_strength"] >= self.UNRANKED_SOS_BASE).all()
        # Raw values: 0.04, 0.165, 0.35, 0.595, 0.90
        expected = [0.35, 0.35, 0.35, 0.595, 0.90]
        np.testing.assert_allclose(df["abs_strength"].values, expected, atol=1e-9)

    def test_old_clip_would_allow_below_floor(self):
        """Prove the OLD clip(0.0, 1.0) allows values below UNRANKED_SOS_BASE."""
        raw = 0.30 * 0.40  # = 0.12
        old_result = np.clip(raw, 0.0, 1.0)
        new_result = np.clip(raw, self.UNRANKED_SOS_BASE, 1.0)
        assert old_result < self.UNRANKED_SOS_BASE  # Old bug
        assert new_result == self.UNRANKED_SOS_BASE  # Fixed
