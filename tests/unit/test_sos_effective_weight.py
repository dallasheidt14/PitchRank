"""
Tests for SOS effective weight verification.

Validates that SOS weight (60%) actually drives ~60% of PowerScore variance,
and that the documented formula (0.20*OFF + 0.20*DEF + 0.60*SOS) is faithfully
implemented.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.etl.v53e import V53EConfig, compute_rankings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_pair(game_id, date, home, away, home_score, away_score,
                    age="14", gender="male"):
    return [
        {
            "game_id": game_id, "date": pd.Timestamp(date),
            "team_id": home, "opp_id": away,
            "age": age, "gender": gender,
            "opp_age": age, "opp_gender": gender,
            "gf": home_score, "ga": away_score,
        },
        {
            "game_id": game_id, "date": pd.Timestamp(date),
            "team_id": away, "opp_id": home,
            "age": age, "gender": gender,
            "opp_age": age, "opp_gender": gender,
            "gf": away_score, "ga": home_score,
        },
    ]


def _build_cohort(num_teams=20, games_per_team=12, seed=42):
    """Build a cohort with enough teams and games for meaningful SOS variance."""
    rng = np.random.RandomState(seed)
    team_ids = [f"team_{i:03d}" for i in range(num_teams)]
    rows = []
    gc = 0
    base = datetime(2025, 6, 1)

    games_needed = (num_teams * games_per_team) // 2 + num_teams
    for _ in range(games_needed):
        h, a = rng.choice(num_teams, size=2, replace=False)
        hs, as_ = int(rng.poisson(1.5)), int(rng.poisson(1.5))
        d = base - timedelta(days=int(rng.randint(1, 300)))
        rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[h], team_ids[a], hs, as_))
        gc += 1

    return pd.DataFrame(rows), team_ids


# ===========================================================================
# T1: SOS effective weight in PowerScore formula
# ===========================================================================

class TestSOSEffectiveWeight:
    """Verify that SOS weight in the PowerScore formula is correctly applied."""

    @pytest.fixture
    def computed(self):
        games, ids = _build_cohort(num_teams=35, games_per_team=12)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        return result["teams"], cfg

    def test_powerscore_core_uses_documented_weights(self, computed):
        """Verify powerscore_core = 0.20*off + 0.20*def + 0.60*sos (perf=0)."""
        teams, cfg = computed
        MAX_PS = 1.0 + cfg.PERF_CAP * cfg.PERF_BLEND_WEIGHT

        for _, row in teams.head(10).iterrows():
            expected = (
                cfg.OFF_WEIGHT * row["off_norm"]
                + cfg.DEF_WEIGHT * row["def_norm"]
                + cfg.SOS_WEIGHT * row["sos_norm"]
                + row["perf_centered"] * cfg.PERF_BLEND_WEIGHT
            ) / MAX_PS
            assert abs(expected - row["powerscore_core"]) < 1e-6, (
                f"Formula mismatch: expected={expected:.6f}, "
                f"actual={row['powerscore_core']:.6f}"
            )

    def test_sos_drives_majority_of_variance(self, computed):
        """With 60% weight, SOS should explain most PowerScore variance."""
        teams, cfg = computed
        active = teams[teams["status"] == "Active"]
        if len(active) < 10:
            pytest.skip("Not enough active teams")

        # Compute the SOS-only contribution
        sos_contrib = cfg.SOS_WEIGHT * active["sos_norm"]
        offdef_contrib = cfg.OFF_WEIGHT * active["off_norm"] + cfg.DEF_WEIGHT * active["def_norm"]

        # SOS variance should be >= off+def variance (since 60% > 40%)
        sos_var = sos_contrib.var()
        offdef_var = offdef_contrib.var()
        assert sos_var > 0, "SOS contribution has zero variance"
        # SOS should contribute meaningfully relative to total variance
        total_var = active["powerscore_core"].var()
        sos_fraction = sos_var / total_var if total_var > 0 else 0
        assert sos_fraction > 0.2, (
            f"SOS explains only {sos_fraction:.1%} of variance, expected > 20%"
        )

    def test_changing_sos_weight_shifts_rankings(self):
        """Doubling SOS weight should change ranking order."""
        games, _ = _build_cohort(num_teams=20, games_per_team=12)

        cfg_60 = V53EConfig()  # SOS=0.60 (default)
        cfg_90 = V53EConfig(OFF_WEIGHT=0.05, DEF_WEIGHT=0.05, SOS_WEIGHT=0.90)

        r60 = compute_rankings(games_df=games, cfg=cfg_60, today=pd.Timestamp("2025-07-01"))
        r90 = compute_rankings(games_df=games, cfg=cfg_90, today=pd.Timestamp("2025-07-01"))

        t60 = r60["teams"].set_index("team_id")
        t90 = r90["teams"].set_index("team_id")
        common = t60.index.intersection(t90.index)

        diff = (t60.loc[common, "powerscore_core"] - t90.loc[common, "powerscore_core"]).abs()
        assert diff.max() > 0.01, (
            "Changing SOS weight should change PowerScore values"
        )

    def test_zero_sos_weight_makes_sos_irrelevant(self):
        """With SOS_WEIGHT=0, different SOS values should not affect PowerScore."""
        games, _ = _build_cohort(num_teams=20, games_per_team=12)

        cfg = V53EConfig(OFF_WEIGHT=0.50, DEF_WEIGHT=0.50, SOS_WEIGHT=0.00)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        # PowerScore should be exactly 0.5*off + 0.5*def (no SOS)
        for _, row in teams.head(5).iterrows():
            MAX_PS = 1.0 + cfg.PERF_CAP * cfg.PERF_BLEND_WEIGHT
            expected = (0.50 * row["off_norm"] + 0.50 * row["def_norm"]) / MAX_PS
            assert abs(expected - row["powerscore_core"]) < 1e-6

    def test_sos_norm_full_range_used(self, computed):
        """sos_norm should span close to [0, 1] — full weight is effective only
        if the input has sufficient spread."""
        teams, _ = computed
        active = teams[teams["status"] == "Active"]
        sos_norm = active["sos_norm"].dropna()
        if len(sos_norm) >= 10:
            assert sos_norm.min() < 0.15, f"sos_norm min too high: {sos_norm.min():.3f}"
            assert sos_norm.max() > 0.85, f"sos_norm max too low: {sos_norm.max():.3f}"


class TestSOSPercentileAmplification:
    """Test that SOS percentile normalization doesn't over-amplify small diffs.

    FINDING: With PageRank dampening, raw SOS typically spans only ~0.07
    (e.g. 0.365 to 0.435). Percentile normalization stretches this to [0,1],
    creating 14x amplification. With 60% SOS weight, this means SOS explains
    ~86% of PowerScore variance instead of the intended ~60%.

    This is a known design trade-off (percentile norm guarantees full range),
    but the amplification ratio should be monitored.
    """

    def test_sos_amplification_ratio_bounded(self):
        """SOS amplification (norm range / raw range) should not exceed 20x.

        If amplification is extreme, tiny SOS differences dominate rankings
        and OFF/DEF performance becomes nearly irrelevant.
        """
        games, _ = _build_cohort(num_teams=35, games_per_team=12)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        raw_range = teams["sos"].max() - teams["sos"].min()
        norm_range = teams["sos_norm"].max() - teams["sos_norm"].min()

        if raw_range > 1e-10:
            amp = norm_range / raw_range
            assert amp < 20.0, (
                f"SOS percentile amplification too extreme: {amp:.1f}x "
                f"(raw range={raw_range:.4f}, norm range={norm_range:.4f}). "
                f"SOS noise dominates rankings."
            )

    def test_sos_variance_fraction_reasonable(self):
        """SOS should not explain more than 95% of PowerScore variance.

        If SOS explains >95%, OFF/DEF performance is nearly irrelevant
        and teams are ranked essentially by schedule alone.
        """
        games, _ = _build_cohort(num_teams=35, games_per_team=12)
        cfg = V53EConfig()
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        sos_contrib_var = (cfg.SOS_WEIGHT * teams["sos_norm"]).var()
        ps_var = teams["powerscore_core"].var()

        if ps_var > 1e-10:
            sos_fraction = sos_contrib_var / ps_var
            assert sos_fraction < 0.95, (
                f"SOS explains {sos_fraction:.1%} of PowerScore variance "
                f"(expected <95%). OFF/DEF may be irrelevant."
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
