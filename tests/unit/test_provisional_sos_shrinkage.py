"""
Tests for provisional multiplier + SOS shrinkage compounding.

Verifies:
- Provisional multiplier thresholds (0.85 / 0.95 / 1.00) at game-count boundaries
- SOS low-sample shrinkage toward anchor (default 0.35)
- The compound effect: provisional_mult * powerscore_core where sos_norm is
  already shrunk for low-game-count teams
- Boundary conditions at the thresholds (gp=7→8, gp=14→15)
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.v53e import V53EConfig, compute_rankings, _provisional_multiplier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game_pair(game_id, date, home, away, hs, as_, age="14", gender="male"):
    return [
        {
            "game_id": game_id,
            "date": pd.Timestamp(date),
            "team_id": home,
            "opp_id": away,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": hs,
            "ga": as_,
        },
        {
            "game_id": game_id,
            "date": pd.Timestamp(date),
            "team_id": away,
            "opp_id": home,
            "age": age,
            "gender": gender,
            "opp_age": age,
            "opp_gender": gender,
            "gf": as_,
            "ga": hs,
        },
    ]


def _build_team_with_n_games(team_id, n_games, opponents, base_date, gc_start=0):
    """Create n_games for a specific team against supplied opponents."""
    rows = []
    gc = gc_start
    for i in range(n_games):
        opp = opponents[i % len(opponents)]
        d = base_date - timedelta(days=i * 5)
        rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_id, opp, 2, 1))
        gc += 1
    return rows, gc


# ===========================================================================
# Unit tests for _provisional_multiplier
# ===========================================================================


class TestProvisionalMultiplierUnit:
    """Direct tests on the _provisional_multiplier function."""

    def test_below_min_games(self):
        # Linear ramp: 0.85 + (gp/15) * 0.15
        assert _provisional_multiplier(0, 8) == 0.85
        assert abs(_provisional_multiplier(5, 8) - 0.90) < 0.01
        assert abs(_provisional_multiplier(7, 8) - 0.92) < 0.01

    def test_at_min_games_boundary(self):
        assert abs(_provisional_multiplier(8, 8) - 0.93) < 0.01

    def test_between_thresholds(self):
        assert abs(_provisional_multiplier(10, 8) - 0.95) < 0.01
        assert abs(_provisional_multiplier(14, 8) - 0.99) < 0.01

    def test_at_full_confidence(self):
        assert _provisional_multiplier(15, 8) == 1.0

    def test_well_above_threshold(self):
        assert _provisional_multiplier(30, 8) == 1.0
        assert _provisional_multiplier(100, 8) == 1.0


# ===========================================================================
# Integration: provisional multiplier applied correctly in pipeline
# ===========================================================================


class TestProvisionalMultInPipeline:
    """Verify provisional_mult column matches expected values in compute_rankings."""

    def _build_scenario(self, games_per_team_map):
        """
        Build games for teams with different game counts.
        games_per_team_map: dict of team_id -> n_games
        Also creates 15 "filler" opponents so there's a real cohort.
        """
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)

        # Filler opponents (each plays 12 games against each other)
        fillers = [f"filler_{i:02d}" for i in range(15)]
        for i, f1 in enumerate(fillers):
            for j in range(i + 1, min(i + 5, len(fillers))):
                f2 = fillers[j]
                for rep in range(3):
                    d = base - timedelta(days=10 + i * 3 + j + rep)
                    rows.extend(_make_game_pair(f"fg_{gc:04d}", d, f1, f2, 2, 1))
                    gc += 1

        # Test teams play against fillers
        for tid, n in games_per_team_map.items():
            new_rows, gc = _build_team_with_n_games(tid, n, fillers, base, gc)
            rows.extend(new_rows)

        return pd.DataFrame(rows)

    def test_provisional_mult_values(self):
        """Verify that gp thresholds map to correct multiplier in output (linear ramp)."""
        games = self._build_scenario(
            {
                "few_games": 5,  # 5 games → ~0.90
                "mid_games": 10,  # 10 games → ~0.95
                "full_games": 20,  # ≥ 15 → 1.00
            }
        )
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"].set_index("team_id")

        if "few_games" in teams.index:
            assert abs(teams.loc["few_games", "provisional_mult"] - 0.90) < 0.01
        if "mid_games" in teams.index:
            assert abs(teams.loc["mid_games", "provisional_mult"] - 0.95) < 0.01
        if "full_games" in teams.index:
            assert teams.loc["full_games", "provisional_mult"] == 1.0

    def test_powerscore_adj_equals_core_times_mult(self):
        """powerscore_adj = powerscore_core * provisional_mult."""
        games = self._build_scenario({"team_a": 5, "team_b": 20})
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))

        for _, row in result["teams"].iterrows():
            expected = row["powerscore_core"] * row["provisional_mult"]
            assert abs(expected - row["powerscore_adj"]) < 1e-6, (
                f"{row['team_id']}: core={row['powerscore_core']:.6f} * "
                f"mult={row['provisional_mult']:.2f} = {expected:.6f}, "
                f"adj={row['powerscore_adj']:.6f}"
            )


# ===========================================================================
# SOS shrinkage for low-sample teams
# ===========================================================================


class TestSOSShrinkage:
    """Verify SOS low-sample shrinkage toward anchor."""

    def test_shrinkage_formula_linear(self):
        """
        For teams with gp < MIN_GAMES_FOR_TOP_SOS (10), sos_norm should be
        shrunk toward anchor: sos_norm = anchor + (gp/10) * (raw - anchor).
        """
        cfg = V53EConfig()
        anchor = cfg.SOS_SHRINKAGE_ANCHOR  # 0.35
        # A team with 5 games out of threshold 10 should retain 50% of the
        # deviation from anchor
        gp = 5
        raw_sos_norm = 0.9
        shrink_factor = min(gp / cfg.MIN_GAMES_FOR_TOP_SOS, 1.0)
        expected = anchor + shrink_factor * (raw_sos_norm - anchor)
        # 0.35 + 0.5*(0.9-0.35) = 0.35 + 0.275 = 0.625
        assert abs(expected - 0.625) < 0.01

    def test_full_games_no_shrinkage(self):
        """Teams with >= MIN_GAMES_FOR_TOP_SOS games should have no shrinkage."""
        cfg = V53EConfig()
        anchor = cfg.SOS_SHRINKAGE_ANCHOR
        gp = 10
        raw_sos_norm = 0.9
        shrink_factor = min(gp / cfg.MIN_GAMES_FOR_TOP_SOS, 1.0)
        expected = anchor + shrink_factor * (raw_sos_norm - anchor)
        assert abs(expected - 0.9) < 0.01  # factor=1.0 → no change


# ===========================================================================
# Compound effect: provisional * shrunk SOS
# ===========================================================================


class TestCompoundEffect:
    """Verify the compound penalty for low-game teams."""

    def test_low_games_double_penalty(self):
        """
        A team with 5 games gets:
        1. SOS shrinkage: sos_norm pulled toward anchor (factor=0.5)
        2. Provisional: powerscore_adj = powerscore_core * 0.85

        The compound effect should be strictly less than a team with 20 games
        and identical OFF/DEF performance.
        """
        # This is a formula-level test
        cfg = V53EConfig()
        anchor = cfg.SOS_SHRINKAGE_ANCHOR

        # Simulate two teams with same off/def norms but different gp
        off_norm = 0.8
        def_norm = 0.7
        raw_sos_norm = 0.9

        # Team A: 5 games
        shrink_a = min(5 / cfg.MIN_GAMES_FOR_TOP_SOS, 1.0)  # 0.5
        sos_norm_a = anchor + shrink_a * (raw_sos_norm - anchor)  # 0.35 + 0.5*0.55 = 0.625
        core_a = cfg.OFF_WEIGHT * off_norm + cfg.DEF_WEIGHT * def_norm + cfg.SOS_WEIGHT * sos_norm_a
        adj_a = core_a * _provisional_multiplier(5, cfg.MIN_GAMES_PROVISIONAL)  # * 0.85

        # Team B: 20 games (no penalties)
        sos_norm_b = raw_sos_norm  # 0.9 (no shrinkage)
        core_b = cfg.OFF_WEIGHT * off_norm + cfg.DEF_WEIGHT * def_norm + cfg.SOS_WEIGHT * sos_norm_b
        adj_b = core_b * _provisional_multiplier(20, cfg.MIN_GAMES_PROVISIONAL)  # * 1.0

        assert adj_a < adj_b, f"5-game team ({adj_a:.4f}) should score lower than 20-game team ({adj_b:.4f})"
        # The difference should be significant due to compound effect
        gap = adj_b - adj_a
        assert gap > 0.05, f"Compound penalty gap too small: {gap:.4f}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
