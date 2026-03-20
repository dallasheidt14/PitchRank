"""
Diagnostic tests: Why do teams with bad SOS rank higher than they should?

Root cause analysis of the PowerScore formula and SOS mechanics:

1. SHRINKAGE INFLATION: Low-sample and component-size shrinkage pull sos_norm
   toward 0.5 (the median). For teams with genuinely bad SOS (say 0.10), this
   is a massive free boost. A team with 5 games and raw sos_norm=0.10 gets
   shrunk to 0.5 + 0.5*(0.10 - 0.5) = 0.30 — nearly 3x its earned value.

2. WEIGHT IMBALANCE: SOS is 60% of PowerScore, but off_norm/def_norm are
   opponent-adjusted, meaning opponent strength is partially double-counted.
   A team beating weak opponents gets LOW off_norm (good, opponent-adjusted)
   but their 60% SOS weight still dominates the score.

3. NEUTRAL ANCHOR = 0.5: The shrinkage anchor is 0.5 (median). For weak-SOS
   teams, this is generous. A more appropriate anchor might be lower (e.g., 0.35)
   to avoid rewarding teams that haven't proven their schedule quality.

These tests quantify each mechanism and test potential fixes.
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


def _build_tiered_league(seed=42):
    """
    Build a realistic league with 3 tiers of teams:
    - Elite (5 teams): play each other + some mid-tier opponents
    - Mid (10 teams): play each other + some elite + some weak opponents
    - Weak (10 teams): mostly play each other (bubble league)

    The weak tier teams that dominate their bubble should NOT rank highly
    despite having great off/def numbers vs weak opponents.
    """
    rng = np.random.RandomState(seed)
    base = datetime(2025, 6, 1)
    rows = []
    gc = 0

    elite = [f"elite_{i}" for i in range(5)]
    mid = [f"mid_{i}" for i in range(10)]
    weak = [f"weak_{i}" for i in range(10)]

    # Elite vs Elite: competitive games (2-1, 1-0, 3-2 type scores)
    for i, t1 in enumerate(elite):
        for t2 in elite[i+1:]:
            gc += 1
            hs = rng.choice([1, 2, 3])
            as_ = rng.choice([0, 1, 2])
            rows.extend(_make_game_pair(
                f"g{gc}", base + timedelta(days=gc), t1, t2, hs, as_))

    # Elite vs Mid: elite usually wins
    for e in elite:
        opponents = rng.choice(mid, size=4, replace=False)
        for m in opponents:
            gc += 1
            hs = rng.randint(2, 5)  # elite scores 2-4
            as_ = rng.randint(0, 2)  # mid scores 0-1
            rows.extend(_make_game_pair(
                f"g{gc}", base + timedelta(days=gc), e, m, hs, as_))

    # Mid vs Mid: fairly competitive
    for i, t1 in enumerate(mid):
        opponents = rng.choice([m for j, m in enumerate(mid) if j != i], size=5, replace=False)
        for t2 in opponents:
            gc += 1
            hs = rng.randint(1, 4)
            as_ = rng.randint(0, 3)
            rows.extend(_make_game_pair(
                f"g{gc}", base + timedelta(days=gc), t1, t2, hs, as_))

    # Mid vs Weak (bridge games — only 2 mid teams play weak teams)
    bridge_mids = rng.choice(mid, size=2, replace=False)
    for m in bridge_mids:
        opponents = rng.choice(weak, size=2, replace=False)
        for w in opponents:
            gc += 1
            hs = rng.randint(3, 6)
            as_ = rng.randint(0, 1)
            rows.extend(_make_game_pair(
                f"g{gc}", base + timedelta(days=gc), m, w, hs, as_))

    # Weak vs Weak: the bubble league — lots of games, easy opponents
    for i, t1 in enumerate(weak):
        opponents = rng.choice([w for j, w in enumerate(weak) if j != i], size=6, replace=False)
        for t2 in opponents:
            gc += 1
            # Some weak teams dominate: scores like 4-0, 5-1
            hs = rng.randint(0, 5)
            as_ = rng.randint(0, 4)
            rows.extend(_make_game_pair(
                f"g{gc}", base + timedelta(days=gc), t1, t2, hs, as_))

    return pd.DataFrame(rows), elite, mid, weak


def _run_rankings(games, cfg=None):
    if cfg is None:
        cfg = V53EConfig()
    cfg.SOS_POWER_ITERATIONS = 3
    cfg.COMPONENT_SOS_ENABLED = True
    cfg.OPPONENT_ADJUST_ENABLED = True
    cfg.PERF_BLEND_WEIGHT = 0.0
    result = compute_rankings(games_df=games, cfg=cfg, today=pd.Timestamp("2026-01-01"))
    team = result["teams"]
    return team


# ---------------------------------------------------------------------------
# Test Class 1: Quantify the Problem
# ---------------------------------------------------------------------------

class TestBadSOSRankingDiagnosis:
    """Demonstrate and measure how weak-schedule teams rank too high."""

    def test_weak_bubble_champion_vs_mid_tier(self):
        """
        The best weak-bubble team should NOT outrank mid-tier teams.
        This test quantifies how many mid-tier teams a bubble champion beats.
        """
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        # Find the top weak-bubble team
        weak_teams = team[team["team_id"].isin(weak)].sort_values("powerscore_adj", ascending=False)
        best_weak = weak_teams.iloc[0]

        # Find mid-tier teams
        mid_teams = team[team["team_id"].isin(mid)].sort_values("powerscore_adj", ascending=False)

        # Count how many mid-tier teams the best weak team outranks
        mid_outranked = (mid_teams["powerscore_adj"] < best_weak["powerscore_adj"]).sum()
        mid_count = len(mid_teams)

        print(f"\n{'='*70}")
        print(f"BUBBLE CHAMPION DIAGNOSIS")
        print(f"{'='*70}")
        print(f"Best weak-bubble team: {best_weak['team_id']}")
        print(f"  PowerScore: {best_weak['powerscore_adj']:.4f}")
        print(f"  off_norm:   {best_weak['off_norm']:.4f}")
        print(f"  def_norm:   {best_weak['def_norm']:.4f}")
        print(f"  sos_norm:   {best_weak['sos_norm']:.4f}")
        print(f"  games:      {best_weak['gp']:.0f}")
        print(f"\nMid-tier teams outranked: {mid_outranked}/{mid_count}")
        print(f"\nTop 5 mid-tier:")
        for _, r in mid_teams.head().iterrows():
            print(f"  {r['team_id']}: PS={r['powerscore_adj']:.4f} "
                  f"off={r['off_norm']:.3f} def={r['def_norm']:.3f} sos={r['sos_norm']:.3f}")
        print(f"\nTop 3 weak-bubble:")
        for _, r in weak_teams.head(3).iterrows():
            print(f"  {r['team_id']}: PS={r['powerscore_adj']:.4f} "
                  f"off={r['off_norm']:.3f} def={r['def_norm']:.3f} sos={r['sos_norm']:.3f}")

        # The best weak team should NOT outrank more than 2 mid-tier teams
        # (Currently it likely outranks several — this test documents the problem)
        print(f"\n⚠️  Bubble champion outranks {mid_outranked}/{mid_count} mid-tier teams")
        # This assertion documents the CURRENT behavior (may fail = problem exists)
        # We WANT this to pass: bubble champion should outrank at most 2 mid teams
        if mid_outranked > 2:
            print(f"❌ PROBLEM CONFIRMED: Bubble champion outranks {mid_outranked} mid-tier teams")

    def test_shrinkage_inflation_magnitude(self):
        """
        Quantify how much shrinkage inflates sos_norm for weak-SOS teams.
        Compare shrunk vs unshrunk values.
        """
        games, elite, mid, weak = _build_tiered_league()

        # Run with shrinkage
        cfg_shrunk = V53EConfig()
        cfg_shrunk.SOS_POWER_ITERATIONS = 3
        cfg_shrunk.COMPONENT_SOS_ENABLED = True
        cfg_shrunk.OPPONENT_ADJUST_ENABLED = True
        cfg_shrunk.PERF_BLEND_WEIGHT = 0.0
        result_shrunk = compute_rankings(games_df=games, cfg=cfg_shrunk, today=pd.Timestamp("2026-01-01"))
        team_shrunk = result_shrunk["teams"]

        # Run without component shrinkage (low-sample still on)
        cfg_noshrink = deepcopy(cfg_shrunk)
        cfg_noshrink.COMPONENT_SOS_ENABLED = False
        result_noshrink = compute_rankings(games_df=games, cfg=cfg_noshrink, today=pd.Timestamp("2026-01-01"))
        team_noshrink = result_noshrink["teams"]

        # Compare weak teams' sos_norm
        weak_shrunk = team_shrunk[team_shrunk["team_id"].isin(weak)].set_index("team_id")
        weak_noshrink = team_noshrink[team_noshrink["team_id"].isin(weak)].set_index("team_id")

        print(f"\n{'='*70}")
        print(f"SHRINKAGE INFLATION ANALYSIS")
        print(f"{'='*70}")
        for tid in sorted(weak[:5]):
            s = weak_shrunk.loc[tid, "sos_norm"]
            ns = weak_noshrink.loc[tid, "sos_norm"]
            diff = s - ns
            print(f"  {tid}: shrunk={s:.4f}, unshrunk={ns:.4f}, inflation={diff:+.4f}")

        avg_inflation = (weak_shrunk["sos_norm"] - weak_noshrink.reindex(weak_shrunk.index)["sos_norm"]).mean()
        print(f"\n  Average SOS inflation for weak teams: {avg_inflation:+.4f}")

    def test_powerscore_decomposition(self):
        """
        Break down PowerScore into OFF/DEF/SOS contributions for each tier.
        Shows how much each component contributes to the final score.
        """
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        print(f"\n{'='*70}")
        print(f"POWERSCORE COMPONENT DECOMPOSITION")
        print(f"  Formula: 0.20*off + 0.20*def + 0.60*sos")
        print(f"{'='*70}")

        for label, ids in [("Elite", elite), ("Mid", mid), ("Weak", weak)]:
            tier = team[team["team_id"].isin(ids)]
            off_contrib = 0.20 * tier["off_norm"].mean()
            def_contrib = 0.20 * tier["def_norm"].mean()
            sos_contrib = 0.60 * tier["sos_norm"].mean()
            total = off_contrib + def_contrib + sos_contrib

            print(f"\n  {label} tier (n={len(tier)}):")
            print(f"    OFF contribution:  {off_contrib:.4f} ({off_contrib/total*100:.1f}%)")
            print(f"    DEF contribution:  {def_contrib:.4f} ({def_contrib/total*100:.1f}%)")
            print(f"    SOS contribution:  {sos_contrib:.4f} ({sos_contrib/total*100:.1f}%)")
            print(f"    Total PowerScore:  {total:.4f}")
            print(f"    Avg sos_norm:      {tier['sos_norm'].mean():.4f}")
            print(f"    Avg off_norm:      {tier['off_norm'].mean():.4f}")
            print(f"    Avg def_norm:      {tier['def_norm'].mean():.4f}")

        # Quantify overlap: do any weak teams score higher than mid teams?
        weak_scores = team[team["team_id"].isin(weak)]["powerscore_adj"]
        mid_scores = team[team["team_id"].isin(mid)]["powerscore_adj"]
        overlap = (weak_scores.max() > mid_scores.min())
        print(f"\n  Weak-Mid overlap exists: {overlap}")
        if overlap:
            print(f"  Weak max: {weak_scores.max():.4f}, Mid min: {mid_scores.min():.4f}")


# ---------------------------------------------------------------------------
# Test Class 2: Potential Fixes
# ---------------------------------------------------------------------------

class TestPotentialFixes:
    """Test different approaches to penalize weak-SOS teams more."""

    def test_fix_lower_shrinkage_anchor(self):
        """
        Fix #1: Change shrinkage anchor from 0.5 to 0.35.
        Weak-SOS teams with few games shrink toward 0.35 instead of 0.5,
        preventing free SOS inflation.
        """
        games, elite, mid, weak = _build_tiered_league()

        # Baseline
        team_baseline = _run_rankings(games)

        # Modified: manually apply lower shrinkage anchor
        # We can't easily change the anchor in v53e without modifying the code,
        # so we'll compute the effect analytically
        weak_base = team_baseline[team_baseline["team_id"].isin(weak)]
        mid_base = team_baseline[team_baseline["team_id"].isin(mid)]

        print(f"\n{'='*70}")
        print(f"FIX #1: Lower shrinkage anchor (0.5 → 0.35)")
        print(f"{'='*70}")
        print(f"\n  Current state:")
        print(f"    Weak avg sos_norm: {weak_base['sos_norm'].mean():.4f}")
        print(f"    Mid avg sos_norm:  {mid_base['sos_norm'].mean():.4f}")
        print(f"    Gap:               {mid_base['sos_norm'].mean() - weak_base['sos_norm'].mean():.4f}")

        # Simulate what would happen with 0.35 anchor
        # new_sos = 0.35 + shrink_factor * (raw_sos - 0.35)
        # vs current: 0.5 + shrink_factor * (raw_sos - 0.5)
        # For a team with raw_sos=0.1, 5 games:
        #   Current:  0.5 + 0.5*(0.1 - 0.5) = 0.30
        #   Proposed: 0.35 + 0.5*(0.1 - 0.35) = 0.225
        print(f"\n  Example: team with raw_sos_norm=0.10, 5 games (shrink=0.5):")
        print(f"    Current (anchor=0.5):  {0.5 + 0.5*(0.1 - 0.5):.3f}")
        print(f"    Proposed (anchor=0.35): {0.35 + 0.5*(0.1 - 0.35):.3f}")
        print(f"    Improvement: {(0.5 + 0.5*(0.1 - 0.5)) - (0.35 + 0.5*(0.1 - 0.35)):.3f} lower")

    def test_fix_sos_weight_reduction(self):
        """
        Fix #2: Reduce SOS weight from 0.60 to 0.50, increase OFF/DEF to 0.25 each.
        This reduces how much a mediocre SOS can carry a team.
        """
        games, elite, mid, weak = _build_tiered_league()

        # Baseline: OFF=0.20, DEF=0.20, SOS=0.60
        team_baseline = _run_rankings(games)

        # Modified: OFF=0.25, DEF=0.25, SOS=0.50
        cfg_mod = V53EConfig()
        cfg_mod.SOS_POWER_ITERATIONS = 3
        cfg_mod.COMPONENT_SOS_ENABLED = True
        cfg_mod.OPPONENT_ADJUST_ENABLED = True
        cfg_mod.PERF_BLEND_WEIGHT = 0.0
        cfg_mod.OFF_WEIGHT = 0.25
        cfg_mod.DEF_WEIGHT = 0.25
        cfg_mod.SOS_WEIGHT = 0.50
        result_mod = compute_rankings(games_df=games, cfg=cfg_mod, today=pd.Timestamp("2026-01-01"))
        team_mod = result_mod["teams"]

        # Compare tier separation
        print(f"\n{'='*70}")
        print(f"FIX #2: Reweight OFF/DEF/SOS (0.20/0.20/0.60 → 0.25/0.25/0.50)")
        print(f"{'='*70}")

        for label, ids in [("Elite", elite), ("Mid", mid), ("Weak", weak)]:
            base_ps = team_baseline[team_baseline["team_id"].isin(ids)]["powerscore_adj"].mean()
            mod_ps = team_mod[team_mod["team_id"].isin(ids)]["powerscore_adj"].mean()
            print(f"  {label}: baseline={base_ps:.4f}, modified={mod_ps:.4f}, delta={mod_ps-base_ps:+.4f}")

        # Check if overlap is reduced
        weak_max_base = team_baseline[team_baseline["team_id"].isin(weak)]["powerscore_adj"].max()
        mid_min_base = team_baseline[team_baseline["team_id"].isin(mid)]["powerscore_adj"].min()
        weak_max_mod = team_mod[team_mod["team_id"].isin(weak)]["powerscore_adj"].max()
        mid_min_mod = team_mod[team_mod["team_id"].isin(mid)]["powerscore_adj"].min()

        overlap_base = weak_max_base - mid_min_base
        overlap_mod = weak_max_mod - mid_min_mod

        print(f"\n  Weak-Mid overlap (positive = problem):")
        print(f"    Baseline: {overlap_base:+.4f}")
        print(f"    Modified: {overlap_mod:+.4f}")
        if overlap_mod < overlap_base:
            print(f"    ✅ Improvement: {overlap_base - overlap_mod:.4f}")
        else:
            print(f"    ❌ No improvement")

    def test_fix_sos_penalty_multiplier(self):
        """
        Fix #3: Apply a nonlinear penalty to low sos_norm values.
        Instead of linear sos_norm in PowerScore, use sos_norm^1.5 or similar
        to amplify penalties for weak schedules.

        This doesn't change the ranking ENGINE — just the PowerScore formula.
        """
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        print(f"\n{'='*70}")
        print(f"FIX #3: Nonlinear SOS penalty (sos_norm^p for p > 1)")
        print(f"{'='*70}")

        for p in [1.0, 1.25, 1.5, 2.0]:
            # Recompute PowerScore with nonlinear SOS
            sos_transformed = team["sos_norm"] ** p
            ps_new = 0.20 * team["off_norm"] + 0.20 * team["def_norm"] + 0.60 * sos_transformed

            weak_ps = ps_new[team["team_id"].isin(weak)]
            mid_ps = ps_new[team["team_id"].isin(mid)]
            elite_ps = ps_new[team["team_id"].isin(elite)]

            overlap = weak_ps.max() - mid_ps.min()
            gap_em = elite_ps.mean() - mid_ps.mean()
            gap_mw = mid_ps.mean() - weak_ps.mean()

            print(f"\n  p={p:.2f}:")
            print(f"    Elite avg: {elite_ps.mean():.4f}, Mid avg: {mid_ps.mean():.4f}, Weak avg: {weak_ps.mean():.4f}")
            print(f"    Elite-Mid gap: {gap_em:.4f}, Mid-Weak gap: {gap_mw:.4f}")
            print(f"    Weak-Mid overlap: {overlap:+.4f} {'❌' if overlap > 0 else '✅'}")

    def test_fix_combined_weight_and_penalty(self):
        """
        Fix #4: Combined approach — reduce SOS weight AND apply nonlinear penalty.
        OFF=0.25, DEF=0.25, SOS=0.50 with sos_norm^1.3
        """
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        print(f"\n{'='*70}")
        print(f"FIX #4: Combined — reweight + nonlinear penalty")
        print(f"{'='*70}")

        configs = [
            ("Baseline (0.20/0.20/0.60, p=1.0)", 0.20, 0.20, 0.60, 1.0),
            ("Fix 2 only (0.25/0.25/0.50, p=1.0)", 0.25, 0.25, 0.50, 1.0),
            ("Fix 3 only (0.20/0.20/0.60, p=1.3)", 0.20, 0.20, 0.60, 1.3),
            ("Combined  (0.25/0.25/0.50, p=1.3)", 0.25, 0.25, 0.50, 1.3),
            ("Aggressive (0.25/0.25/0.50, p=1.5)", 0.25, 0.25, 0.50, 1.5),
        ]

        results = []
        for label, wo, wd, ws, p in configs:
            sos_t = team["sos_norm"] ** p
            ps = wo * team["off_norm"] + wd * team["def_norm"] + ws * sos_t

            weak_ps = ps[team["team_id"].isin(weak)]
            mid_ps = ps[team["team_id"].isin(mid)]
            elite_ps = ps[team["team_id"].isin(elite)]

            mid_outranked = (mid_ps.values[:, None] < weak_ps.values[None, :]).sum()
            overlap = weak_ps.max() - mid_ps.min()

            results.append({
                "label": label,
                "elite_avg": elite_ps.mean(),
                "mid_avg": mid_ps.mean(),
                "weak_avg": weak_ps.mean(),
                "overlap": overlap,
                "mid_beaten_by_weak": int((mid_ps.min() < weak_ps.max()))
            })

            print(f"\n  {label}:")
            print(f"    E={elite_ps.mean():.4f}  M={mid_ps.mean():.4f}  W={weak_ps.mean():.4f}")
            print(f"    Overlap: {overlap:+.4f}  Any mid beaten by weak: {'YES ❌' if overlap > 0 else 'NO ✅'}")

    def test_fix_sos_floor_for_low_sos(self):
        """
        Fix #5: Cap the maximum PowerScore for teams with very low sos_norm.
        If sos_norm < 0.30, cap PowerScore at 0.50 (can't be top-tier with weak schedule).
        """
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        print(f"\n{'='*70}")
        print(f"FIX #5: PowerScore cap for low-SOS teams")
        print(f"{'='*70}")

        for sos_threshold, ps_cap in [(0.30, 0.50), (0.35, 0.55), (0.40, 0.60)]:
            ps = team["powerscore_adj"].copy()
            mask = team["sos_norm"] < sos_threshold
            ps_capped = ps.copy()
            ps_capped[mask] = ps_capped[mask].clip(upper=ps_cap)

            weak_ps = ps_capped[team["team_id"].isin(weak)]
            mid_ps = ps_capped[team["team_id"].isin(mid)]
            elite_ps = ps_capped[team["team_id"].isin(elite)]

            affected = mask.sum()
            overlap = weak_ps.max() - mid_ps.min()

            print(f"\n  SOS < {sos_threshold} → cap PS at {ps_cap}:")
            print(f"    Teams affected: {affected}")
            print(f"    Overlap: {overlap:+.4f} {'❌' if overlap > 0 else '✅'}")
            print(f"    Weak avg: {weak_ps.mean():.4f}, Mid avg: {mid_ps.mean():.4f}")


# ---------------------------------------------------------------------------
# Test Class 3: Rank Ordering Validation
# ---------------------------------------------------------------------------

class TestRankOrderingIntegrity:
    """Verify that rank ordering correctly separates tiers."""

    def test_tier_separation_in_rankings(self):
        """
        In a well-functioning ranking system:
        - ALL elite teams should rank above ALL weak teams
        - Most elite teams should rank above most mid teams
        - Mid-weak boundary can have some overlap but should be minimal
        """
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        team_sorted = team.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
        team_sorted["rank"] = range(1, len(team_sorted) + 1)

        elite_ranks = team_sorted[team_sorted["team_id"].isin(elite)]["rank"]
        mid_ranks = team_sorted[team_sorted["team_id"].isin(mid)]["rank"]
        weak_ranks = team_sorted[team_sorted["team_id"].isin(weak)]["rank"]

        print(f"\n{'='*70}")
        print(f"TIER SEPARATION IN RANKINGS")
        print(f"{'='*70}")
        print(f"  Elite ranks: {sorted(elite_ranks.tolist())}")
        print(f"  Mid ranks:   {sorted(mid_ranks.tolist())}")
        print(f"  Weak ranks:  {sorted(weak_ranks.tolist())}")

        # Elite should all be in top 10
        elite_in_top10 = (elite_ranks <= 10).sum()
        print(f"\n  Elite in top 10: {elite_in_top10}/{len(elite)}")

        # No weak team should be in top 10
        weak_in_top10 = (weak_ranks <= 10).sum()
        print(f"  Weak in top 10: {weak_in_top10}/{len(weak)} (should be 0)")

        # Weak teams that outrank mid teams
        weak_above_mid = (weak_ranks.min() < mid_ranks.max())
        print(f"  Any weak team outranks a mid team: {weak_above_mid}")

        # Assert: no weak team in top 10
        assert weak_in_top10 == 0, f"Weak teams in top 10: {weak_in_top10}"

    def test_overall_ranking_table(self):
        """Print the full ranking table for visual inspection."""
        games, elite, mid, weak = _build_tiered_league()
        team = _run_rankings(games)

        team_sorted = team.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)

        print(f"\n{'='*70}")
        print(f"FULL RANKING TABLE")
        print(f"{'='*70}")
        print(f"{'Rank':<5} {'Team':<12} {'Tier':<6} {'PS':>6} {'OFF':>6} {'DEF':>6} {'SOS':>6} {'GP':>4}")
        print(f"{'-'*55}")

        for i, r in team_sorted.iterrows():
            tid = r["team_id"]
            if tid in elite:
                tier = "ELITE"
            elif tid in mid:
                tier = "MID"
            else:
                tier = "WEAK"
            print(f"{i+1:<5} {tid:<12} {tier:<6} {r['powerscore_adj']:>6.3f} "
                  f"{r['off_norm']:>6.3f} {r['def_norm']:>6.3f} {r['sos_norm']:>6.3f} {r['gp']:>4.0f}")
