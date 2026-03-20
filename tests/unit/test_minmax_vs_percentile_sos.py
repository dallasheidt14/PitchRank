"""
Ripple-effect tests: min-max vs percentile SOS normalization.

Runs the same data through both normalization approaches and compares
every downstream metric to identify what breaks, what improves, and
what needs threshold adjustment.

Key areas tested:
1. Distribution shape and clustering
2. Rank ordering changes
3. Outlier sensitivity (min-max Achilles heel)
4. Power-SOS iteration convergence
5. Low-sample + component shrinkage interaction
6. GP-SOS correlation (games-played bias)
7. ML SOS-conditioned scaling threshold behavior
8. Identical-result teams (the noise amplification case)
9. Isolated bubble / unranked opponent effects
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from copy import deepcopy

from src.etl.v53e import V53EConfig, compute_rankings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_pair(gid, date, home, away, hs, as_, age="14", gender="male"):
    return [
        {"game_id": gid, "date": pd.Timestamp(date),
         "team_id": home, "opp_id": away, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": hs, "ga": as_},
        {"game_id": gid, "date": pd.Timestamp(date),
         "team_id": away, "opp_id": home, "age": age, "gender": gender,
         "opp_age": age, "opp_gender": gender, "gf": as_, "ga": hs},
    ]


def _build_cohort(num_teams=30, games_per_team=14, seed=42, age="14"):
    rng = np.random.RandomState(seed)
    ids = [f"team_{i:03d}" for i in range(num_teams)]
    rows = []
    gc = 0
    base = datetime(2025, 6, 1)
    needed = (num_teams * games_per_team) // 2 + num_teams
    for _ in range(needed):
        h, a = rng.choice(num_teams, size=2, replace=False)
        hs, as_ = int(rng.poisson(1.5)), int(rng.poisson(1.5))
        d = base - timedelta(days=int(rng.randint(1, 300)))
        rows.extend(_make_game_pair(f"g_{gc:04d}", d, ids[h], ids[a], hs, as_, age=age))
        gc += 1
    return pd.DataFrame(rows), ids


def _minmax_within_group(x):
    """Min-max scaling: maps to [0, 1] using actual value range."""
    if len(x) <= 1:
        return pd.Series([0.5] * len(x), index=x.index)
    x_rounded = x.round(10)
    mn, mx = x_rounded.min(), x_rounded.max()
    if mx - mn < 1e-10:
        return pd.Series([0.5] * len(x), index=x.index)
    return (x_rounded - mn) / (mx - mn)


def _run_with_normalization(games, cfg, norm_fn, today="2025-07-01"):
    """
    Run compute_rankings but monkey-patch the SOS normalization function.

    This is fragile but lets us compare approaches without forking v53e.py.
    We run the standard percentile version, then re-normalize sos_norm
    using the alternative function and recompute PowerScore.
    """
    result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp(today))
    teams = result["teams"].copy()

    if teams.empty:
        return teams

    # Determine groupby cols (match v53e logic)
    sos_group_cols = ['age', 'gender']
    if cfg.COMPONENT_SOS_ENABLED and 'component_id' in teams.columns:
        sos_group_cols = ['age', 'gender', 'component_id']

    # Re-normalize raw SOS using the alternative function
    teams['sos_norm'] = teams.groupby(sos_group_cols)['sos'].transform(norm_fn)
    teams['sos_norm'] = teams['sos_norm'].fillna(0.5).clip(0.0, 1.0)

    # Re-apply component-size shrinkage
    if cfg.COMPONENT_SOS_ENABLED and 'component_size' in teams.columns:
        min_size = cfg.MIN_COMPONENT_SIZE_FOR_FULL_SOS
        comp_shrink = (teams["component_size"] / min_size).clip(0.0, 1.0)
        teams["sos_norm"] = 0.5 + comp_shrink * (teams["sos_norm"] - 0.5)

    # Re-apply low-sample shrinkage
    low_mask = teams["gp"] < cfg.MIN_GAMES_FOR_TOP_SOS
    shrink = (teams["gp"] / cfg.MIN_GAMES_FOR_TOP_SOS).clip(0.0, 1.0)
    anchor = cfg.SOS_SHRINKAGE_ANCHOR
    teams.loc[low_mask, "sos_norm"] = (
        anchor + shrink[low_mask] * (teams.loc[low_mask, "sos_norm"] - anchor)
    )

    # Recompute PowerScore
    MAX_PS = 1.0 + cfg.PERF_CAP * cfg.PERF_BLEND_WEIGHT
    teams["powerscore_core"] = (
        cfg.OFF_WEIGHT * teams["off_norm"]
        + cfg.DEF_WEIGHT * teams["def_norm"]
        + cfg.SOS_WEIGHT * teams["sos_norm"]
        + teams["perf_centered"] * cfg.PERF_BLEND_WEIGHT
    ) / MAX_PS
    teams["powerscore_adj"] = teams["powerscore_core"] * teams["provisional_mult"]

    return teams


def _percentile_within_group(x):
    """Current behavior: percentile ranking."""
    if len(x) <= 1:
        return pd.Series([0.5] * len(x), index=x.index)
    x_rounded = x.round(10)
    ranks = x_rounded.rank(method='average')
    return (ranks - 1) / (len(x) - 1)


# ===========================================================================
# 1. Distribution shape and spread
# ===========================================================================

class TestDistributionShape:
    """Compare how percentile vs min-max distribute sos_norm values."""

    @pytest.fixture
    def both_results(self):
        games, ids = _build_cohort(num_teams=35, games_per_team=14)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)
        return t_pct, t_mm, cfg

    def test_minmax_compresses_sos_norm(self, both_results):
        """Min-max should produce a LESS uniform distribution than percentile.

        Percentile forces uniform distribution (by definition).
        Min-max preserves the natural clustering — most teams will be
        bunched in the middle with few at the extremes.
        """
        t_pct, t_mm, _ = both_results

        # Percentile: std should be close to 1/sqrt(12) ≈ 0.289 (uniform)
        pct_std = t_pct["sos_norm"].std()
        mm_std = t_mm["sos_norm"].std()

        # Min-max std should be SMALLER (more clustered)
        assert mm_std < pct_std, (
            f"Min-max should compress SOS distribution: "
            f"mm_std={mm_std:.4f}, pct_std={pct_std:.4f}"
        )

    def test_minmax_still_uses_full_range(self, both_results):
        """Min-max should still span [0, 1] (by definition of min-max)."""
        _, t_mm, _ = both_results
        assert t_mm["sos_norm"].min() < 0.05, f"Min-max min too high: {t_mm['sos_norm'].min():.3f}"
        assert t_mm["sos_norm"].max() > 0.95, f"Min-max max too low: {t_mm['sos_norm'].max():.3f}"

    def test_minmax_reduces_powerscore_spread(self, both_results):
        """With SOS compressed, PowerScore spread should decrease."""
        t_pct, t_mm, _ = both_results

        ps_spread_pct = t_pct["powerscore_adj"].std()
        ps_spread_mm = t_mm["powerscore_adj"].std()

        assert ps_spread_mm < ps_spread_pct, (
            f"Min-max should reduce PowerScore spread: "
            f"mm={ps_spread_mm:.4f}, pct={ps_spread_pct:.4f}"
        )

    def test_minmax_offdef_contribution_increases(self, both_results):
        """With SOS compressed, OFF/DEF should matter more (higher % of variance)."""
        t_pct, t_mm, cfg = both_results

        def variance_fractions(t):
            ps_var = t["powerscore_core"].var()
            if ps_var < 1e-10:
                return 0, 0, 0
            off_frac = (cfg.OFF_WEIGHT * t["off_norm"]).var() / ps_var
            def_frac = (cfg.DEF_WEIGHT * t["def_norm"]).var() / ps_var
            sos_frac = (cfg.SOS_WEIGHT * t["sos_norm"]).var() / ps_var
            return off_frac, def_frac, sos_frac

        off_pct, def_pct, sos_pct = variance_fractions(t_pct)
        off_mm, def_mm, sos_mm = variance_fractions(t_mm)

        # SOS fraction should decrease with min-max
        assert sos_mm < sos_pct, (
            f"SOS variance fraction should decrease: "
            f"pct={sos_pct:.1%}, mm={sos_mm:.1%}"
        )

        # OFF+DEF fraction should increase
        offdef_pct = off_pct + def_pct
        offdef_mm = off_mm + def_mm
        assert offdef_mm > offdef_pct, (
            f"OFF+DEF variance fraction should increase: "
            f"pct={offdef_pct:.1%}, mm={offdef_mm:.1%}"
        )


# ===========================================================================
# 2. Rank ordering changes
# ===========================================================================

class TestRankOrdering:
    """How much do rankings change between approaches?"""

    @pytest.fixture
    def both_ranked(self):
        games, ids = _build_cohort(num_teams=35, games_per_team=14)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        # Rank by powerscore_adj
        for t in [t_pct, t_mm]:
            active = t[t["status"] == "Active"].copy()
            active = active.sort_values("powerscore_adj", ascending=False)
            active["rank"] = range(1, len(active) + 1)
            t.loc[active.index, "rank"] = active["rank"]

        return t_pct, t_mm

    def test_top_5_overlap(self, both_ranked):
        """Most top-5 teams should remain in top-5 with either approach."""
        t_pct, t_mm = both_ranked
        pct_active = t_pct[t_pct["status"] == "Active"].sort_values("powerscore_adj", ascending=False)
        mm_active = t_mm[t_mm["status"] == "Active"].sort_values("powerscore_adj", ascending=False)

        if len(pct_active) >= 5 and len(mm_active) >= 5:
            top5_pct = set(pct_active.head(5)["team_id"])
            top5_mm = set(mm_active.head(5)["team_id"])
            overlap = len(top5_pct & top5_mm)
            assert overlap >= 3, (
                f"Top-5 overlap too low: {overlap}/5. "
                f"pct={top5_pct}, mm={top5_mm}"
            )

    def test_rank_correlation(self, both_ranked):
        """Spearman rank correlation should be high (>0.80) — same general order."""
        t_pct, t_mm = both_ranked
        pct_active = t_pct[t_pct["status"] == "Active"].set_index("team_id")
        mm_active = t_mm[t_mm["status"] == "Active"].set_index("team_id")
        common = pct_active.index.intersection(mm_active.index)

        if len(common) >= 10:
            from scipy.stats import spearmanr
            corr, _ = spearmanr(
                pct_active.loc[common, "powerscore_adj"],
                mm_active.loc[common, "powerscore_adj"]
            )
            assert corr > 0.80, (
                f"Rank correlation too low: {corr:.3f}. "
                f"Min-max would drastically reorder rankings."
            )

    def test_average_rank_change(self, both_ranked):
        """Average rank change should be modest (< 5 positions)."""
        t_pct, t_mm = both_ranked
        pct_active = t_pct[t_pct["status"] == "Active"].set_index("team_id")
        mm_active = t_mm[t_mm["status"] == "Active"].set_index("team_id")
        common = pct_active.index.intersection(mm_active.index)

        if len(common) >= 10:
            # Compute rank in each
            pct_ranks = pct_active.loc[common, "powerscore_adj"].rank(ascending=False)
            mm_ranks = mm_active.loc[common, "powerscore_adj"].rank(ascending=False)
            avg_change = (pct_ranks - mm_ranks).abs().mean()

            # Report but don't fail — this is informational
            print(f"\nAverage rank change: {avg_change:.1f} positions")
            print(f"Max rank change: {(pct_ranks - mm_ranks).abs().max():.0f} positions")


# ===========================================================================
# 3. Outlier sensitivity (min-max vulnerability)
# ===========================================================================

class TestOutlierSensitivity:
    """Min-max is vulnerable to outliers: one extreme SOS value can
    compress all other teams into a narrow band."""

    def test_single_outlier_compresses_minmax(self):
        """One team with extreme SOS should not compress others to a narrow range."""
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)
        team_ids = [f"t{i}" for i in range(20)]

        # 19 teams play each other in round-robin (similar SOS)
        for i in range(19):
            for j in range(i + 1, min(i + 6, 19)):
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[i], team_ids[j], 2, 1))
                    gc += 1

        # t19 plays only against unranked/unknown teams (very low SOS)
        for i in range(12):
            d = base - timedelta(days=gc)
            rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[19], f"unknown_{i}", 5, 0))
            gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        # Check: do the 19 "normal" teams still have reasonable spread?
        normal = t_mm[t_mm["team_id"] != "t19"]
        if len(normal) >= 10:
            sos_range = normal["sos_norm"].max() - normal["sos_norm"].min()
            assert sos_range > 0.30, (
                f"OUTLIER RISK: Single extreme team compressed normal teams' "
                f"sos_norm range to {sos_range:.3f} (expected > 0.30). "
                f"Min-max is vulnerable to outliers."
            )

    def test_outlier_impact_on_powerscore(self):
        """With an outlier present, compare PowerScore spread between approaches."""
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)
        team_ids = [f"t{i}" for i in range(20)]

        for i in range(19):
            for j in range(i + 1, min(i + 6, 19)):
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[i], team_ids[j], 2, 1))
                    gc += 1

        for i in range(12):
            d = base - timedelta(days=gc)
            rows.extend(_make_game_pair(f"g_{gc:04d}", d, team_ids[19], f"unknown_{i}", 5, 0))
            gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)

        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        # Normal teams should still be differentiated under min-max
        normal_pct = t_pct[~t_pct["team_id"].isin(["t19"])]["powerscore_adj"]
        normal_mm = t_mm[~t_mm["team_id"].isin(["t19"])]["powerscore_adj"]

        if len(normal_pct) >= 10 and len(normal_mm) >= 10:
            pct_std = normal_pct.std()
            mm_std = normal_mm.std()
            # Min-max may compress, but not to zero
            assert mm_std > 0.01, (
                f"OUTLIER RISK: Min-max compressed normal teams' PowerScore "
                f"std to {mm_std:.4f} (percentile: {pct_std:.4f})"
            )


# ===========================================================================
# 4. ML SOS-conditioned scaling thresholds
# ===========================================================================

class TestMLThresholdBehavior:
    """The ML scaling uses sos_norm thresholds (0.45, 0.60).
    Min-max changes what these thresholds mean."""

    @pytest.fixture
    def both_results(self):
        games, ids = _build_cohort(num_teams=35, games_per_team=14)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)
        return t_pct, t_mm

    def test_ml_authority_fraction_changes(self, both_results):
        """The fraction of teams with ML authority (sos_norm > 0.45) will differ."""
        t_pct, t_mm = both_results

        SOS_ML_THRESHOLD_LOW = 0.45

        pct_above = (t_pct["sos_norm"] > SOS_ML_THRESHOLD_LOW).mean()
        mm_above = (t_mm["sos_norm"] > SOS_ML_THRESHOLD_LOW).mean()

        print(f"\nTeams with ML authority (sos_norm > {SOS_ML_THRESHOLD_LOW}):")
        print(f"  Percentile: {pct_above:.1%}")
        print(f"  Min-max:    {mm_above:.1%}")

        # With min-max compression, FEWER teams may exceed the threshold
        # This is a key ripple effect: ML becomes less influential
        # Document the difference but don't fail — this is expected
        diff = abs(pct_above - mm_above)
        if diff > 0.20:
            print(f"  WARNING: {diff:.0%} of teams change ML authority status")

    def test_ml_full_authority_fraction(self, both_results):
        """Fraction with full ML authority (sos_norm >= 0.60) will also change."""
        t_pct, t_mm = both_results

        SOS_ML_THRESHOLD_HIGH = 0.60

        pct_full = (t_pct["sos_norm"] >= SOS_ML_THRESHOLD_HIGH).mean()
        mm_full = (t_mm["sos_norm"] >= SOS_ML_THRESHOLD_HIGH).mean()

        print(f"\nTeams with FULL ML authority (sos_norm >= {SOS_ML_THRESHOLD_HIGH}):")
        print(f"  Percentile: {pct_full:.1%}")
        print(f"  Min-max:    {mm_full:.1%}")

    def test_median_sos_norm_shift(self, both_results):
        """Min-max will shift the median sos_norm — critical for threshold behavior."""
        t_pct, t_mm = both_results

        pct_median = t_pct["sos_norm"].median()
        mm_median = t_mm["sos_norm"].median()

        print(f"\nMedian sos_norm:")
        print(f"  Percentile: {pct_median:.4f}")
        print(f"  Min-max:    {mm_median:.4f}")

        # Percentile median is always ~0.5 by construction
        assert abs(pct_median - 0.5) < 0.1
        # Min-max median reflects actual SOS distribution (likely > 0.5
        # because PageRank dampening anchors values around 0.5)


# ===========================================================================
# 5. GP-SOS correlation (games-played bias)
# ===========================================================================

class TestGPSOSBias:
    """Does min-max improve or worsen the GP-SOS correlation?"""

    def test_gp_sos_correlation_comparison(self):
        """Compare GP-SOS correlation between approaches."""
        games, _ = _build_cohort(num_teams=35, games_per_team=14)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)

        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        corr_pct = t_pct[["gp", "sos_norm"]].corr().iloc[0, 1]
        corr_mm = t_mm[["gp", "sos_norm"]].corr().iloc[0, 1]

        print(f"\nGP-SOS correlation:")
        print(f"  Percentile: {corr_pct:.4f}")
        print(f"  Min-max:    {corr_mm:.4f}")

        # Both should be within acceptable range
        assert abs(corr_mm) < 0.30, (
            f"Min-max GP-SOS correlation too high: {corr_mm:.4f}"
        )


# ===========================================================================
# 6. Identical results (the noise test)
# ===========================================================================

class TestIdenticalResults:
    """The original noise problem: do identical teams get identical scores?"""

    def test_minmax_handles_identical_sos(self):
        """With identical raw SOS, min-max should assign 0.5 to all (tied)."""
        team_ids = [f"t{i}" for i in range(10)]
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)
        for rnd in range(3):
            for i, h in enumerate(team_ids):
                for j, a in enumerate(team_ids):
                    if i >= j:
                        continue
                    d = base - timedelta(days=gc * 3 + rnd)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, h, a, 1, 1))
                    gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        # All teams should get sos_norm = 0.5 (range is 0, so all tied)
        sos_spread = t_mm["sos_norm"].max() - t_mm["sos_norm"].min()
        assert sos_spread < 0.01, (
            f"Min-max should assign 0.5 to identical SOS teams, "
            f"got spread={sos_spread:.4f}"
        )

        # PowerScore spread should be near-zero
        ps_spread = t_mm["powerscore_adj"].max() - t_mm["powerscore_adj"].min()
        assert ps_spread < 0.05, (
            f"Identical teams should have near-identical PowerScore, "
            f"got spread={ps_spread:.4f}"
        )


# ===========================================================================
# 7. Isolated bubble / unranked opponents
# ===========================================================================

class TestBubbleEffects:
    """How does min-max handle teams in isolated bubbles or with unranked opponents?"""

    def test_unranked_opponent_team_sos(self):
        """A team playing only unranked opponents should have low sos_norm
        in both approaches."""
        rows = []
        gc = 0
        base = datetime(2025, 6, 1)

        # 15 normal teams
        normals = [f"normal_{i}" for i in range(15)]
        for i in range(15):
            for j in range(i + 1, min(i + 5, 15)):
                for rep in range(2):
                    d = base - timedelta(days=gc)
                    rows.extend(_make_game_pair(f"g_{gc:04d}", d, normals[i], normals[j], 2, 1))
                    gc += 1

        # 1 team playing ONLY unknowns
        for i in range(12):
            d = base - timedelta(days=gc)
            rows.extend(_make_game_pair(f"g_{gc:04d}", d, "loner", f"ghost_{i}", 5, 0))
            gc += 1

        games = pd.DataFrame(rows)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False, PAGERANK_DAMPENING_ENABLED=False)

        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        for label, t in [("pct", t_pct), ("mm", t_mm)]:
            loner = t[t["team_id"] == "loner"]
            if not loner.empty:
                sos_norm = loner["sos_norm"].values[0]
                assert sos_norm < 0.3, (
                    f"[{label}] Loner with unranked opponents should have "
                    f"low sos_norm, got {sos_norm:.4f}"
                )


# ===========================================================================
# 8. Power-SOS iteration interaction
# ===========================================================================

class TestPowerSOSInteraction:
    """Does min-max interact differently with Power-SOS iterations?"""

    def test_iterations_converge_with_minmax(self):
        """Power-SOS iterations should still converge under min-max."""
        games, _ = _build_cohort(num_teams=25, games_per_team=14)

        # Can't easily monkey-patch iterations, so just verify current
        # behavior with iterations ON stays bounded
        cfg = V53EConfig(SOS_POWER_ITERATIONS=3, SCF_ENABLED=False)
        result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2025-07-01"))
        teams = result["teams"]

        # Re-normalize with min-max
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        assert (t_mm["powerscore_adj"] >= 0.0).all()
        assert (t_mm["powerscore_adj"] <= 1.0).all()
        assert (t_mm["sos_norm"] >= 0.0).all()
        assert (t_mm["sos_norm"] <= 1.0).all()


# ===========================================================================
# 9. Summary comparison (not a test — diagnostic output)
# ===========================================================================

class TestSummaryComparison:
    """Print a comprehensive comparison table."""

    def test_print_comparison(self):
        """Side-by-side metrics for both approaches."""
        games, _ = _build_cohort(num_teams=35, games_per_team=14)
        cfg = V53EConfig(SOS_POWER_ITERATIONS=0, SCF_ENABLED=False)

        t_pct = _run_with_normalization(games, cfg, _percentile_within_group)
        t_mm = _run_with_normalization(games, cfg, _minmax_within_group)

        def stats(t, label):
            ps = t["powerscore_adj"]
            sn = t["sos_norm"]
            gp_corr = t[["gp", "sos_norm"]].corr().iloc[0, 1]
            sos_var_frac = (cfg.SOS_WEIGHT * sn).var() / ps.var() if ps.var() > 0 else 0
            offdef_var_frac = ((cfg.OFF_WEIGHT * t["off_norm"]).var() + (cfg.DEF_WEIGHT * t["def_norm"]).var()) / ps.var() if ps.var() > 0 else 0
            ml_above_45 = (sn > 0.45).mean()
            ml_above_60 = (sn >= 0.60).mean()

            return {
                "label": label,
                "ps_mean": ps.mean(),
                "ps_std": ps.std(),
                "ps_range": ps.max() - ps.min(),
                "sos_norm_mean": sn.mean(),
                "sos_norm_std": sn.std(),
                "sos_norm_median": sn.median(),
                "gp_sos_corr": gp_corr,
                "sos_var_%": sos_var_frac * 100,
                "offdef_var_%": offdef_var_frac * 100,
                "ml_authority_%": ml_above_45 * 100,
                "ml_full_%": ml_above_60 * 100,
            }

        s_pct = stats(t_pct, "Percentile")
        s_mm = stats(t_mm, "Min-Max")

        print("\n" + "=" * 70)
        print("PERCENTILE vs MIN-MAX SOS NORMALIZATION — COMPARISON")
        print("=" * 70)
        print(f"{'Metric':<30} {'Percentile':>15} {'Min-Max':>15}")
        print("-" * 60)
        for key in s_pct:
            if key == "label":
                continue
            pv = s_pct[key]
            mv = s_mm[key]
            print(f"{key:<30} {pv:>15.4f} {mv:>15.4f}")
        print("=" * 70)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
