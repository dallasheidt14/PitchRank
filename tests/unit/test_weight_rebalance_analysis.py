"""
Weight Rebalance Analysis: Finding the optimal OFF/DEF/SOS ratio.

Problem: With 60% SOS weight, top-30 teams per cohort all have similar
sos_norm values (percentile ceiling effect). This means SOS contributes
the same amount to everyone's score — it's a constant, not a differentiator.
Rankings end up driven by the 40% OFF+DEF component despite SOS having
the largest nominal weight.

This test suite evaluates many weight ratios and measures:
1. Top-30 spread (differentiation among the best teams)
2. Tier separation (elite > mid > weak ordering)
3. Bubble leak rate (how many weak-bubble teams sneak into top rankings)
4. Effective variance contribution (does each metric actually differentiate?)
5. Rank-order accuracy (do tiers sort correctly?)

The goal: find a weight ratio where schedule strength still matters but
doesn't become a wasted 60% that provides no differentiation at the top.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from itertools import product

from src.etl.v53e import V53EConfig, compute_rankings


# ---------------------------------------------------------------------------
# League Builders
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


def _build_large_tiered_league(seed=42):
    """
    Build a larger, more realistic league with 4 tiers:
    - Elite (8 teams): top national-level teams, play each other heavily
    - Strong (12 teams): good regional teams, play elite + each other
    - Mid (15 teams): average teams, play strong + each other + some weak
    - Weak (15 teams): bubble league, mostly play each other

    Total: 50 teams — enough for meaningful top-30 analysis.
    """
    rng = np.random.RandomState(seed)
    base = datetime(2025, 6, 1)
    rows = []
    gc = 0

    elite = [f"elite_{i}" for i in range(8)]
    strong = [f"strong_{i}" for i in range(12)]
    mid = [f"mid_{i}" for i in range(15)]
    weak = [f"weak_{i}" for i in range(15)]

    # True skill levels (for measuring rank accuracy)
    true_skill = {}
    for i, t in enumerate(elite):
        true_skill[t] = 90 + (8 - i)  # 91-98
    for i, t in enumerate(strong):
        true_skill[t] = 70 + (12 - i)  # 71-82
    for i, t in enumerate(mid):
        true_skill[t] = 45 + (15 - i)  # 46-60
    for i, t in enumerate(weak):
        true_skill[t] = 15 + (15 - i)  # 16-30

    def _score(skill_h, skill_a, rng):
        """Generate realistic score based on skill difference."""
        diff = (skill_h - skill_a) / 20.0
        hs = max(0, int(rng.poisson(max(0.5, 1.5 + diff))))
        as_ = max(0, int(rng.poisson(max(0.5, 1.5 - diff))))
        return hs, as_

    def _add_games(t1_list, t2_list, games_per_pair, rng):
        nonlocal gc
        for t1 in t1_list:
            opponents = rng.choice(t2_list, size=min(len(t2_list), games_per_pair), replace=False)
            for t2 in opponents:
                if t1 == t2:
                    continue
                gc += 1
                hs, as_ = _score(true_skill[t1], true_skill[t2], rng)
                d = base + timedelta(days=gc % 300)
                rows.extend(_make_game_pair(f"g{gc}", d, t1, t2, hs, as_))

    # Elite vs Elite: round-robin (every pair plays twice)
    for i, t1 in enumerate(elite):
        for t2 in elite[i+1:]:
            for rep in range(2):
                gc += 1
                hs, as_ = _score(true_skill[t1], true_skill[t2], rng)
                d = base + timedelta(days=gc % 300)
                rows.extend(_make_game_pair(f"g{gc}", d, t1, t2, hs, as_))

    # Elite vs Strong: 5 games each
    _add_games(elite, strong, 5, rng)

    # Strong vs Strong: 6 games each
    _add_games(strong, strong, 6, rng)

    # Strong vs Mid: 3 games each
    _add_games(strong, mid, 3, rng)

    # Mid vs Mid: 7 games each
    _add_games(mid, mid, 7, rng)

    # Mid vs Weak: only 2 bridge games (sparse)
    bridge_mids = rng.choice(mid, size=3, replace=False)
    for m in bridge_mids:
        for w in rng.choice(weak, size=2, replace=False):
            gc += 1
            hs, as_ = _score(true_skill[m], true_skill[w], rng)
            d = base + timedelta(days=gc % 300)
            rows.extend(_make_game_pair(f"g{gc}", d, m, w, hs, as_))

    # Weak vs Weak: lots of games (bubble league)
    _add_games(weak, weak, 8, rng)

    return pd.DataFrame(rows), elite, strong, mid, weak, true_skill


def _run_with_weights(games, off_w, def_w, sos_w):
    """Run rankings with specific weight configuration."""
    cfg = V53EConfig(
        OFF_WEIGHT=off_w,
        DEF_WEIGHT=def_w,
        SOS_WEIGHT=sos_w,
        SOS_POWER_ITERATIONS=3,
        COMPONENT_SOS_ENABLED=True,
        OPPONENT_ADJUST_ENABLED=True,
        PERF_BLEND_WEIGHT=0.0,
        SCF_ENABLED=True,
        PAGERANK_DAMPENING_ENABLED=True,
    )
    result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2026-01-01"))
    return result["teams"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _compute_metrics(teams, elite, strong, mid, weak, true_skill):
    """Compute quality metrics for a given weight configuration."""
    active = teams[teams["status"] == "Active"].copy()
    if len(active) < 10:
        return None

    active = active.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
    active["rank"] = range(1, len(active) + 1)

    # 1. Top-30 PowerScore spread
    top30 = active.head(30)
    top30_spread = top30["powerscore_adj"].max() - top30["powerscore_adj"].min()

    # 2. Top-30 metric spreads
    top30_sos_spread = top30["sos_norm"].max() - top30["sos_norm"].min()
    top30_off_spread = top30["off_norm"].max() - top30["off_norm"].min()
    top30_def_spread = top30["def_norm"].max() - top30["def_norm"].min()

    # 3. Tier separation: gap between tier averages
    elite_ps = active[active["team_id"].isin(elite)]["powerscore_adj"].mean()
    strong_ps = active[active["team_id"].isin(strong)]["powerscore_adj"].mean()
    mid_ps = active[active["team_id"].isin(mid)]["powerscore_adj"].mean()
    weak_ps = active[active["team_id"].isin(weak)]["powerscore_adj"].mean()

    tier_gap_elite_strong = elite_ps - strong_ps
    tier_gap_strong_mid = strong_ps - mid_ps
    tier_gap_mid_weak = mid_ps - weak_ps
    total_tier_separation = elite_ps - weak_ps

    # 4. Bubble leak: how many weak teams rank in top 30
    top30_ids = set(top30["team_id"])
    bubble_leak = len(top30_ids & set(weak))

    # 5. Tier ordering accuracy: what fraction of pairwise comparisons are correct?
    correct_pairs = 0
    total_pairs = 0
    for _, r1 in active.iterrows():
        for _, r2 in active.iterrows():
            if r1["team_id"] == r2["team_id"]:
                continue
            t1, t2 = r1["team_id"], r2["team_id"]
            if t1 not in true_skill or t2 not in true_skill:
                continue
            if true_skill[t1] > true_skill[t2]:
                total_pairs += 1
                if r1["powerscore_adj"] > r2["powerscore_adj"]:
                    correct_pairs += 1
    pairwise_accuracy = correct_pairs / total_pairs if total_pairs > 0 else 0

    # 6. Rank correlation with true skill
    skill_series = active["team_id"].map(true_skill).dropna()
    if len(skill_series) >= 5:
        rank_corr = active.loc[skill_series.index, "powerscore_adj"].corr(skill_series)
    else:
        rank_corr = 0

    # 7. Effective variance contribution
    cfg_off = active["off_norm"].var()
    cfg_def = active["def_norm"].var()
    cfg_sos = active["sos_norm"].var()
    ps_var = active["powerscore_core"].var()

    # 8. Elite teams in top 10
    top10_ids = set(active.head(10)["team_id"])
    elite_in_top10 = len(top10_ids & set(elite))

    # 9. Top-30 coefficient of variation (higher = more differentiated)
    top30_cv = top30["powerscore_adj"].std() / top30["powerscore_adj"].mean() if top30["powerscore_adj"].mean() > 0 else 0

    return {
        "top30_spread": top30_spread,
        "top30_cv": top30_cv,
        "top30_sos_spread": top30_sos_spread,
        "top30_off_spread": top30_off_spread,
        "top30_def_spread": top30_def_spread,
        "tier_gap_elite_strong": tier_gap_elite_strong,
        "tier_gap_strong_mid": tier_gap_strong_mid,
        "tier_gap_mid_weak": tier_gap_mid_weak,
        "total_tier_separation": total_tier_separation,
        "bubble_leak": bubble_leak,
        "pairwise_accuracy": pairwise_accuracy,
        "rank_corr": rank_corr,
        "elite_in_top10": elite_in_top10,
        "off_var": cfg_off,
        "def_var": cfg_def,
        "sos_var": cfg_sos,
        "elite_avg_ps": elite_ps,
        "strong_avg_ps": strong_ps,
        "mid_avg_ps": mid_ps,
        "weak_avg_ps": weak_ps,
    }


# ===========================================================================
# Main Analysis
# ===========================================================================

class TestWeightRebalanceAnalysis:
    """Test many weight ratios and find the optimal balance."""

    @pytest.fixture(scope="class")
    def league_data(self):
        return _build_large_tiered_league(seed=42)

    def test_weight_ratio_sweep(self, league_data):
        """
        Sweep across weight ratios and measure all quality metrics.
        Weights must sum to 1.0.
        """
        games, elite, strong, mid, weak, true_skill = league_data

        # Weight configurations to test (OFF, DEF, SOS)
        # Symmetric OFF=DEF for simplicity, varying SOS from 0.20 to 0.70
        configs = [
            # (OFF, DEF, SOS, label)
            (0.15, 0.15, 0.70, "15/15/70 (SOS heavy)"),
            (0.20, 0.20, 0.60, "20/20/60 (current)"),
            (0.25, 0.25, 0.50, "25/25/50 (balanced)"),
            (0.30, 0.30, 0.40, "30/30/40 (OFF+DEF lean)"),
            (0.33, 0.33, 0.34, "33/33/34 (equal)"),
            (0.35, 0.35, 0.30, "35/35/30 (results lean)"),
            (0.40, 0.40, 0.20, "40/40/20 (SOS light)"),
            # Asymmetric: offense-heavy
            (0.30, 0.20, 0.50, "30/20/50 (OFF bias)"),
            (0.20, 0.30, 0.50, "20/30/50 (DEF bias)"),
            # Moderate SOS with slight asymmetry
            (0.25, 0.20, 0.55, "25/20/55 (slight OFF)"),
            (0.20, 0.25, 0.55, "20/25/55 (slight DEF)"),
            (0.30, 0.25, 0.45, "30/25/45 (OFF+mid SOS)"),
            (0.25, 0.30, 0.45, "25/30/45 (DEF+mid SOS)"),
        ]

        results = []
        for off_w, def_w, sos_w, label in configs:
            teams = _run_with_weights(games, off_w, def_w, sos_w)
            metrics = _compute_metrics(teams, elite, strong, mid, weak, true_skill)
            if metrics:
                metrics["config"] = label
                metrics["off_w"] = off_w
                metrics["def_w"] = def_w
                metrics["sos_w"] = sos_w
                results.append(metrics)

        # Print comprehensive results table
        print(f"\n{'='*120}")
        print(f"WEIGHT REBALANCE ANALYSIS — 50-team 4-tier league")
        print(f"{'='*120}")

        # Header
        print(f"\n{'Config':<25} {'Top30':<8} {'Top30':<8} {'Tier':<8} {'Bubble':<8} "
              f"{'Pair':<8} {'Rank':<8} {'Elite':<8} {'T30 SOS':<8} {'T30 OFF':<8} {'T30 DEF':<8}")
        print(f"{'':25} {'Spread':<8} {'CV':<8} {'Sep':<8} {'Leak':<8} "
              f"{'Acc':<8} {'Corr':<8} {'in T10':<8} {'Spread':<8} {'Spread':<8} {'Spread':<8}")
        print(f"{'-'*120}")

        for r in results:
            print(f"{r['config']:<25} "
                  f"{r['top30_spread']:.4f}  "
                  f"{r['top30_cv']:.4f}  "
                  f"{r['total_tier_separation']:.4f}  "
                  f"{r['bubble_leak']:>5d}   "
                  f"{r['pairwise_accuracy']:.4f}  "
                  f"{r['rank_corr']:.4f}  "
                  f"{r['elite_in_top10']:>5d}   "
                  f"{r['top30_sos_spread']:.4f}  "
                  f"{r['top30_off_spread']:.4f}  "
                  f"{r['top30_def_spread']:.4f}  ")

        # Print tier averages for each config
        print(f"\n{'='*120}")
        print(f"TIER AVERAGES BY CONFIG")
        print(f"{'='*120}")
        print(f"\n{'Config':<25} {'Elite':<10} {'Strong':<10} {'Mid':<10} {'Weak':<10} "
              f"{'E-S Gap':<10} {'S-M Gap':<10} {'M-W Gap':<10}")
        print(f"{'-'*120}")
        for r in results:
            print(f"{r['config']:<25} "
                  f"{r['elite_avg_ps']:.4f}    "
                  f"{r['strong_avg_ps']:.4f}    "
                  f"{r['mid_avg_ps']:.4f}    "
                  f"{r['weak_avg_ps']:.4f}    "
                  f"{r['tier_gap_elite_strong']:.4f}    "
                  f"{r['tier_gap_strong_mid']:.4f}    "
                  f"{r['tier_gap_mid_weak']:.4f}    ")

        # Find best config by composite score
        print(f"\n{'='*120}")
        print(f"COMPOSITE SCORING (higher = better)")
        print(f"{'='*120}")
        print(f"\nScoring weights:")
        print(f"  - Top-30 spread (0-1 normalized): 15%  (want MORE differentiation)")
        print(f"  - Pairwise accuracy:              30%  (want correct tier ordering)")
        print(f"  - Rank correlation:               25%  (want correlation with true skill)")
        print(f"  - Bubble leak penalty:            15%  (want ZERO weak teams in top 30)")
        print(f"  - Elite in top 10:                15%  (want all 8 elite in top 10)")

        # Normalize top30_spread to [0,1]
        spreads = [r["top30_spread"] for r in results]
        max_spread = max(spreads) if max(spreads) > 0 else 1

        for r in results:
            spread_score = r["top30_spread"] / max_spread
            accuracy_score = r["pairwise_accuracy"]
            corr_score = max(0, r["rank_corr"])  # clamp negative
            leak_score = 1.0 - (r["bubble_leak"] / 15)  # 0 leaks = 1.0
            elite_score = r["elite_in_top10"] / 8  # all 8 elite = 1.0

            composite = (
                0.15 * spread_score
                + 0.30 * accuracy_score
                + 0.25 * corr_score
                + 0.15 * leak_score
                + 0.15 * elite_score
            )
            r["composite"] = composite

        results.sort(key=lambda r: r["composite"], reverse=True)

        print(f"\n{'Rank':<6} {'Config':<25} {'Composite':<10} {'Spread':<8} {'Accuracy':<10} "
              f"{'Corr':<8} {'Leak':<8} {'Elite/10':<8}")
        print(f"{'-'*90}")
        for i, r in enumerate(results):
            marker = " ← CURRENT" if "current" in r["config"] else ""
            marker = " ★ BEST" if i == 0 else marker
            print(f"  {i+1:<4} {r['config']:<25} {r['composite']:.4f}    "
                  f"{r['top30_spread']:.4f}  {r['pairwise_accuracy']:.4f}    "
                  f"{r['rank_corr']:.4f}  {r['bubble_leak']:>4d}    "
                  f"{r['elite_in_top10']:>4d}    {marker}")

        # Always pass — this is a diagnostic test
        best = results[0]
        print(f"\n{'='*120}")
        print(f"RECOMMENDATION: {best['config']}")
        print(f"  Composite score: {best['composite']:.4f}")
        print(f"  Top-30 spread:   {best['top30_spread']:.4f} (vs current {[r for r in results if 'current' in r['config']][0]['top30_spread']:.4f})")
        print(f"  Pairwise acc:    {best['pairwise_accuracy']:.2%}")
        print(f"  Rank corr:       {best['rank_corr']:.4f}")
        print(f"  Bubble leaks:    {best['bubble_leak']}")
        print(f"  Elite in top 10: {best['elite_in_top10']}/8")
        print(f"{'='*120}")

    def test_sensitivity_around_best(self, league_data):
        """
        Fine-grained sweep around the 25/25/50 and 30/30/40 range
        to find the exact sweet spot.
        """
        games, elite, strong, mid, weak, true_skill = league_data

        # Fine-grained: OFF=DEF, SOS from 0.30 to 0.60 in 0.02 steps
        results = []
        for sos_pct in range(30, 62, 2):
            sos_w = sos_pct / 100
            offdef_w = (1.0 - sos_w) / 2
            label = f"{offdef_w:.2f}/{offdef_w:.2f}/{sos_w:.2f}"

            teams = _run_with_weights(games, offdef_w, offdef_w, sos_w)
            metrics = _compute_metrics(teams, elite, strong, mid, weak, true_skill)
            if metrics:
                metrics["config"] = label
                metrics["sos_w"] = sos_w
                results.append(metrics)

        print(f"\n{'='*100}")
        print(f"FINE-GRAINED SOS SWEEP (OFF=DEF, SOS 30%-60%)")
        print(f"{'='*100}")
        print(f"\n{'SOS%':<8} {'Top30 Spread':<14} {'Pair Acc':<10} {'Rank Corr':<10} "
              f"{'Bubble Leak':<13} {'Elite/10':<10} {'Tier Sep':<10}")
        print(f"{'-'*80}")

        for r in results:
            marker = " ← current" if abs(r["sos_w"] - 0.60) < 0.01 else ""
            print(f"{r['sos_w']:.0%}     "
                  f"{r['top30_spread']:.4f}        "
                  f"{r['pairwise_accuracy']:.4f}    "
                  f"{r['rank_corr']:.4f}    "
                  f"{r['bubble_leak']:>5d}        "
                  f"{r['elite_in_top10']:>5d}     "
                  f"{r['total_tier_separation']:.4f}    {marker}")

    def test_cross_seed_stability(self, league_data):
        """
        Test the top 3 configs across multiple random seeds to ensure
        the winner isn't seed-dependent.
        """
        configs_to_test = [
            (0.20, 0.20, 0.60, "20/20/60"),
            (0.25, 0.25, 0.50, "25/25/50"),
            (0.30, 0.30, 0.40, "30/30/40"),
            (0.33, 0.33, 0.34, "33/33/34"),
            (0.35, 0.35, 0.30, "35/35/30"),
        ]

        seeds = [42, 123, 456, 789, 2025]

        print(f"\n{'='*100}")
        print(f"CROSS-SEED STABILITY (5 seeds × 5 configs)")
        print(f"{'='*100}")

        avg_metrics = {label: {"pair_acc": [], "rank_corr": [], "bubble_leak": [],
                                "top30_spread": [], "elite_in_top10": []}
                       for _, _, _, label in configs_to_test}

        for seed in seeds:
            games, elite, strong, mid, weak, true_skill = _build_large_tiered_league(seed=seed)
            for off_w, def_w, sos_w, label in configs_to_test:
                teams = _run_with_weights(games, off_w, def_w, sos_w)
                metrics = _compute_metrics(teams, elite, strong, mid, weak, true_skill)
                if metrics:
                    avg_metrics[label]["pair_acc"].append(metrics["pairwise_accuracy"])
                    avg_metrics[label]["rank_corr"].append(metrics["rank_corr"])
                    avg_metrics[label]["bubble_leak"].append(metrics["bubble_leak"])
                    avg_metrics[label]["top30_spread"].append(metrics["top30_spread"])
                    avg_metrics[label]["elite_in_top10"].append(metrics["elite_in_top10"])

        print(f"\n{'Config':<15} {'Avg Pair Acc':<14} {'Avg Corr':<10} {'Avg Leak':<10} "
              f"{'Avg Spread':<12} {'Avg Elite/10':<12} {'Consistency':<12}")
        print(f"{'-'*90}")

        for _, _, _, label in configs_to_test:
            m = avg_metrics[label]
            pair_mean = np.mean(m["pair_acc"])
            corr_mean = np.mean(m["rank_corr"])
            leak_mean = np.mean(m["bubble_leak"])
            spread_mean = np.mean(m["top30_spread"])
            elite_mean = np.mean(m["elite_in_top10"])
            # Consistency = inverse of std across seeds (lower variance = more stable)
            consistency = 1.0 - np.std(m["pair_acc"]) if np.std(m["pair_acc"]) < 1 else 0

            print(f"{label:<15} "
                  f"{pair_mean:.4f}        "
                  f"{corr_mean:.4f}    "
                  f"{leak_mean:.1f}       "
                  f"{spread_mean:.4f}      "
                  f"{elite_mean:.1f}         "
                  f"{consistency:.4f}")


class TestVarianceDecomposition:
    """Decompose PowerScore variance by metric at each weight config."""

    def test_variance_breakdown(self):
        """Show how much each metric actually contributes to PS variance."""
        games, elite, strong, mid, weak, true_skill = _build_large_tiered_league(seed=42)

        configs = [
            (0.20, 0.20, 0.60, "20/20/60 (current)"),
            (0.25, 0.25, 0.50, "25/25/50"),
            (0.30, 0.30, 0.40, "30/30/40"),
            (0.33, 0.33, 0.34, "33/33/34"),
            (0.35, 0.35, 0.30, "35/35/30"),
        ]

        print(f"\n{'='*100}")
        print(f"VARIANCE DECOMPOSITION — What actually drives rank ordering?")
        print(f"{'='*100}")
        print(f"\n  'Nominal' = weight in formula")
        print(f"  'Effective' = weight × variance (actual influence on ranking)")
        print(f"  'Share' = fraction of total effective variance")

        for off_w, def_w, sos_w, label in configs:
            teams = _run_with_weights(games, off_w, def_w, sos_w)
            active = teams[teams["status"] == "Active"]

            # Weighted contributions
            off_contrib = off_w * active["off_norm"]
            def_contrib = def_w * active["def_norm"]
            sos_contrib = sos_w * active["sos_norm"]

            off_eff = off_contrib.var()
            def_eff = def_contrib.var()
            sos_eff = sos_contrib.var()
            total_eff = off_eff + def_eff + sos_eff

            if total_eff > 0:
                off_share = off_eff / total_eff
                def_share = def_eff / total_eff
                sos_share = sos_eff / total_eff
            else:
                off_share = def_share = sos_share = 0.33

            print(f"\n  {label}")
            print(f"    {'Metric':<8} {'Nominal':<10} {'Eff Var':<12} {'Share':<10} {'Match?'}")
            print(f"    {'OFF':<8} {off_w:.0%}       {off_eff:.6f}    {off_share:.1%}      {'✓' if abs(off_share - off_w) < 0.15 else '✗ MISMATCH'}")
            print(f"    {'DEF':<8} {def_w:.0%}       {def_eff:.6f}    {def_share:.1%}      {'✓' if abs(def_share - def_w) < 0.15 else '✗ MISMATCH'}")
            print(f"    {'SOS':<8} {sos_w:.0%}       {sos_eff:.6f}    {sos_share:.1%}      {'✓' if abs(sos_share - sos_w) < 0.15 else '✗ MISMATCH'}")

            # Check top-30 specifically
            top30 = active.sort_values("powerscore_adj", ascending=False).head(30)
            off_t30 = (off_w * top30["off_norm"]).var()
            def_t30 = (def_w * top30["def_norm"]).var()
            sos_t30 = (sos_w * top30["sos_norm"]).var()
            total_t30 = off_t30 + def_t30 + sos_t30

            if total_t30 > 0:
                print(f"    TOP-30 ONLY:")
                print(f"    {'OFF':<8} {off_w:.0%}       {off_t30:.6f}    {off_t30/total_t30:.1%}")
                print(f"    {'DEF':<8} {def_w:.0%}       {def_t30:.6f}    {def_t30/total_t30:.1%}")
                print(f"    {'SOS':<8} {sos_w:.0%}       {sos_t30:.6f}    {sos_t30/total_t30:.1%}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
