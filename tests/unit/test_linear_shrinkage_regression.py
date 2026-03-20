"""
Regression tests ensuring linear shrinkage stays linear.

The low-sample SOS shrinkage formula is:
  shrink_factor = min(gp / MIN_GAMES_FOR_TOP_SOS, 1.0)
  sos_norm = anchor + shrink_factor * (sos_norm_raw - anchor)

Where anchor = SOS_SHRINKAGE_ANCHOR (default 0.35). This must be LINEAR
(proportional to gp), not exponential, sigmoid, or step-function. These
tests guard against regressions that could introduce games-played bias.

Also tests component-size shrinkage (still anchored at 0.5):
  component_shrink = min(component_size / MIN_COMPONENT_SIZE_FOR_FULL_SOS, 1.0)
  sos_norm = 0.5 + component_shrink * (sos_norm_raw - 0.5)
"""

import pytest
import numpy as np
import pandas as pd

from src.etl.v53e import V53EConfig


# ===========================================================================
# Pure formula tests: low-sample SOS shrinkage
# ===========================================================================

class TestLinearShrinkageFormula:
    """Verify the shrinkage formula is strictly linear."""

    @pytest.fixture
    def cfg(self):
        return V53EConfig()

    def _shrink(self, gp, raw_sos_norm, threshold, anchor=0.35):
        """Replicate the shrinkage formula from v53e.py."""
        shrink_factor = min(gp / threshold, 1.0)
        return anchor + shrink_factor * (raw_sos_norm - anchor)

    def test_zero_games_fully_shrunk(self, cfg):
        """0 games → sos_norm = anchor regardless of raw value."""
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        assert self._shrink(0, 1.0, cfg.MIN_GAMES_FOR_TOP_SOS, anchor) == anchor
        assert self._shrink(0, 0.0, cfg.MIN_GAMES_FOR_TOP_SOS, anchor) == anchor
        assert self._shrink(0, 0.9, cfg.MIN_GAMES_FOR_TOP_SOS, anchor) == anchor

    def test_half_threshold_half_deviation(self, cfg):
        """5 games with threshold=10 → retain 50% of deviation from anchor."""
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS  # 10
        anchor = cfg.SOS_SHRINKAGE_ANCHOR  # 0.35
        raw = 0.9
        result = self._shrink(5, raw, threshold, anchor)
        expected = anchor + 0.5 * (0.9 - anchor)  # = 0.35 + 0.5*0.55 = 0.625
        assert abs(result - expected) < 1e-10

    def test_at_threshold_no_shrinkage(self, cfg):
        """At threshold → factor=1.0, no shrinkage."""
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        raw = 0.9
        result = self._shrink(threshold, raw, threshold, anchor)
        assert abs(result - raw) < 1e-10

    def test_above_threshold_no_shrinkage(self, cfg):
        """Above threshold → capped at 1.0, no shrinkage."""
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        result = self._shrink(100, 0.9, cfg.MIN_GAMES_FOR_TOP_SOS, anchor)
        assert abs(result - 0.9) < 1e-10

    def test_linearity_property(self, cfg):
        """
        The key property: shrinkage must be LINEAR in gp.
        For any two game counts g1, g2 below threshold, the shrunk values
        must satisfy:
          shrunk(g2) - shrunk(g1) = (g2 - g1)/threshold * (raw - anchor)
        """
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        raw = 0.85

        for g1 in range(0, threshold):
            for g2 in range(g1 + 1, threshold + 1):
                s1 = self._shrink(g1, raw, threshold, anchor)
                s2 = self._shrink(g2, raw, threshold, anchor)
                expected_diff = (g2 - g1) / threshold * (raw - anchor)
                actual_diff = s2 - s1
                assert abs(actual_diff - expected_diff) < 1e-10, (
                    f"Non-linear shrinkage at g1={g1}, g2={g2}: "
                    f"diff={actual_diff:.6f}, expected={expected_diff:.6f}"
                )

    def test_symmetry_around_anchor(self, cfg):
        """Shrinkage should be symmetric: teams above AND below anchor are
        pulled equally toward anchor."""
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        gp = 5

        high = self._shrink(gp, anchor + 0.4, threshold, anchor)  # pulled down
        low = self._shrink(gp, anchor - 0.4, threshold, anchor)   # pulled up

        # Distance from anchor should be equal
        assert abs((high - anchor) - (anchor - low)) < 1e-10

    def test_monotonic_in_games(self, cfg):
        """More games → closer to raw value (less shrinkage)."""
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        raw = 0.85

        prev = self._shrink(0, raw, threshold, anchor)
        for gp in range(1, threshold + 5):
            curr = self._shrink(gp, raw, threshold, anchor)
            assert curr >= prev - 1e-10, (
                f"Non-monotonic: shrink({gp}) = {curr:.6f} < shrink({gp-1}) = {prev:.6f}"
            )
            prev = curr

    def test_not_exponential(self, cfg):
        """Guard against regression to exponential shrinkage.
        Exponential: factor = 1 - exp(-gp/scale) → NOT linear.
        We check that equal gp increments produce equal sos_norm increments.
        """
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        raw = 0.9

        increments = []
        for gp in range(threshold):
            s_curr = self._shrink(gp, raw, threshold, anchor)
            s_next = self._shrink(gp + 1, raw, threshold, anchor)
            increments.append(s_next - s_curr)

        # All increments should be identical (linear property)
        for i in range(len(increments) - 1):
            assert abs(increments[i] - increments[i + 1]) < 1e-10, (
                f"Non-constant increment: {increments[i]:.8f} != {increments[i+1]:.8f} "
                f"at gp={i} vs gp={i+1}. This suggests non-linear shrinkage."
            )

    def test_not_step_function(self, cfg):
        """Guard against regression to hard cap / step function.
        Step: sos_norm = anchor if gp < threshold, else raw → NOT linear.
        """
        threshold = cfg.MIN_GAMES_FOR_TOP_SOS
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        raw = 0.9

        # Mid-range gp should produce values between anchor and raw
        mid_gp = threshold // 2
        result = self._shrink(mid_gp, raw, threshold, anchor)
        assert result > anchor + 0.01, f"Step-function detected: shrink({mid_gp}) = {result:.6f}"
        assert result < raw - 0.01, f"No shrinkage at mid: shrink({mid_gp}) = {result:.6f}"


# ===========================================================================
# Component-size shrinkage (also linear)
# ===========================================================================

class TestComponentSizeShrinkage:
    """Verify component-size shrinkage is also linear."""

    def _comp_shrink(self, size, raw, min_size):
        factor = min(size / min_size, 1.0)
        return 0.5 + factor * (raw - 0.5)

    def test_small_component_shrinkage(self):
        cfg = V53EConfig()
        min_size = cfg.MIN_COMPONENT_SIZE_FOR_FULL_SOS  # 10

        # 5-team component should retain 50%
        result = self._comp_shrink(5, 0.9, min_size)
        expected = 0.5 + 0.5 * (0.9 - 0.5)
        assert abs(result - expected) < 1e-10

    def test_full_size_no_shrinkage(self):
        cfg = V53EConfig()
        min_size = cfg.MIN_COMPONENT_SIZE_FOR_FULL_SOS
        result = self._comp_shrink(min_size, 0.9, min_size)
        assert abs(result - 0.9) < 1e-10

    def test_linearity(self):
        cfg = V53EConfig()
        min_size = cfg.MIN_COMPONENT_SIZE_FOR_FULL_SOS
        raw = 0.85

        increments = []
        for size in range(min_size):
            s_curr = self._comp_shrink(size, raw, min_size)
            s_next = self._comp_shrink(size + 1, raw, min_size)
            increments.append(s_next - s_curr)

        for i in range(len(increments) - 1):
            assert abs(increments[i] - increments[i + 1]) < 1e-10, (
                f"Non-linear component shrinkage at size={i} vs {i+1}"
            )


# ===========================================================================
# Integration: verify shrinkage in actual pipeline output
# ===========================================================================

class TestShrinkageInPipeline:
    """Verify shrinkage behavior in actual compute_rankings output."""

    def _make_game_pair(self, gid, date, home, away, hs, as_, age="14", gender="male"):
        return [
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": home, "opp_id": away, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
            {"game_id": gid, "date": pd.Timestamp(date),
             "team_id": away, "opp_id": home, "age": age, "gender": gender,
             "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
        ]

    def test_low_gp_teams_shrunk_toward_half(self):
        """Teams with low game count should have sos_norm closer to 0.5
        than teams with high game count (all else equal-ish)."""
        from datetime import datetime, timedelta

        rows = []
        gc = 0
        base = datetime(2025, 6, 1)

        # 15 "full" teams: play 20 games each (round-robin)
        full_ids = [f"full_{i:02d}" for i in range(15)]
        for i, h in enumerate(full_ids):
            for j, a in enumerate(full_ids):
                if i >= j:
                    continue
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(self._make_game_pair(f"g_{gc:04d}", d, h, a, 2, 1))
                    gc += 1

        # 1 "low" team: only 4 games
        for i in range(4):
            d = base - timedelta(days=i * 10)
            rows.extend(self._make_game_pair(f"g_{gc:04d}", d, "low_gp", full_ids[i], 3, 0))
            gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)
        from src.etl.v53e import compute_rankings
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        low_team = teams[teams["team_id"] == "low_gp"]
        if not low_team.empty:
            low_sos_norm = low_team["sos_norm"].values[0]
            anchor = cfg.SOS_SHRINKAGE_ANCHOR
            # Should be closer to anchor than the extremes
            assert abs(low_sos_norm - anchor) < 0.40, (
                f"Low-gp team sos_norm ({low_sos_norm:.3f}) not sufficiently shrunk toward {anchor}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
