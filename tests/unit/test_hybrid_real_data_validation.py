"""
Real-data validation: Hybrid SOS normalization vs pure percentile.

Uses cached v53e-format game data (parquet) from actual ranking runs.
These are real PitchRank games — thousands of teams per cohort, real
scores, real schedule structures.

This validates that the synthetic-league findings hold on production data.
"""

import os
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from scipy import stats as sp_stats

from src.etl.v53e import V53EConfig, compute_rankings


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"

# Map of cohort → (games parquet filename, label)
# All 12 cohorts from cached production data
COHORT_FILES = {
    "12 male": "rankings_108fe84b0d904b3467bf05d42fa019ff_games.parquet",
    "13 male": "rankings_dcc3fc9976bd4bcc6e6ea63c61c3a759_games.parquet",
    "11 male": "rankings_8b6fe036a69281b692d93e2676ed1169_games.parquet",
    "14 male": "rankings_bfa0b2debbc9f73f7f0d74b3d4e8c601_games.parquet",
    "15 male": "rankings_21c4f3864e1be9622831a87a6ae0494a_games.parquet",
    "12 female": "rankings_c02154a64733e3d90f494a5d25ef591e_games.parquet",
    "13 female": "rankings_93c7ba1817dfeb316bb8897192cac3c2_games.parquet",
    "11 female": "rankings_a2ccf7dc89751df7527e34dd3dabb3e0_games.parquet",
    "14 female": "rankings_59f547805bfc962af51bae0383804ebd_games.parquet",
    "15 female": "rankings_c87b9565fead104d2e1e4a333a73f22d_games.parquet",
    "10 male": "rankings_b9bd491bd0e48272757e99db8671e05f_games.parquet",
    "10 female": "rankings_88f9af04e08e3a507f08816ad5497020_games.parquet",
}


def _load_cohort(cohort_key):
    """Load cached v53e game data for a cohort."""
    fname = COHORT_FILES.get(cohort_key)
    if not fname:
        return None
    path = CACHE_DIR / fname
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _run_cohort(games_df, hybrid_enabled=False, zscore_blend=0.15):
    """Run rankings with specified normalization mode."""
    cfg = V53EConfig(
        SOS_POWER_ITERATIONS=3,
        COMPONENT_SOS_ENABLED=True,
        OPPONENT_ADJUST_ENABLED=True,
        PERF_BLEND_WEIGHT=0.0,
        SCF_ENABLED=True,
        PAGERANK_DAMPENING_ENABLED=True,
        SOS_NORM_HYBRID_ENABLED=hybrid_enabled,
        SOS_NORM_HYBRID_ZSCORE_BLEND=zscore_blend,
    )
    result = compute_rankings(games_df=games_df, cfg=cfg, today=pd.Timestamp("2026-03-20"))
    return result["teams"]


def _cohort_metrics(teams, top_n=30):
    """Compute quality metrics for a cohort ranking result."""
    active = teams[teams["status"] == "Active"].copy()
    if len(active) < 10:
        return None

    active = active.sort_values("powerscore_adj", ascending=False).reset_index(drop=True)
    n_active = len(active)

    # Top N = min(top_n, 20% of cohort)
    top_n = min(top_n, max(10, n_active // 5))
    top = active.head(top_n)

    # 1. PowerScore spread & CV in top N
    top_spread = top["powerscore_adj"].max() - top["powerscore_adj"].min()
    top_cv = top["powerscore_adj"].std() / top["powerscore_adj"].mean() if top["powerscore_adj"].mean() > 0 else 0

    # 2. sos_norm statistics in top N
    top_sos_std = top["sos_norm"].std()
    top_sos_range = top["sos_norm"].max() - top["sos_norm"].min()
    top_sos_iqr = top["sos_norm"].quantile(0.75) - top["sos_norm"].quantile(0.25)

    # 3. Effective variance decomposition (top N)
    off_var = (0.20 * top["off_norm"]).var()
    def_var = (0.20 * top["def_norm"]).var()
    sos_var = (0.60 * top["sos_norm"]).var()
    total_var = off_var + def_var + sos_var

    sos_share = sos_var / total_var if total_var > 0 else 0
    off_share = off_var / total_var if total_var > 0 else 0
    def_share = def_var / total_var if total_var > 0 else 0

    # 4. Full-cohort sos_norm stats
    all_sos_std = active["sos_norm"].std()
    all_sos_skew = active["sos_norm"].skew()

    # 5. GP-SOS correlation
    gp_sos_corr = active[["gp", "sos_norm"]].corr().iloc[0, 1]

    # 6. Top 100 analysis (for larger cohorts)
    top100 = active.head(min(100, n_active))
    top100_spread = top100["powerscore_adj"].max() - top100["powerscore_adj"].min()
    top100_sos_std = top100["sos_norm"].std()

    return {
        "n_active": n_active,
        "top_n": top_n,
        "top_spread": top_spread,
        "top_cv": top_cv,
        "top_sos_std": top_sos_std,
        "top_sos_range": top_sos_range,
        "top_sos_iqr": top_sos_iqr,
        "sos_share_top": sos_share,
        "off_share_top": off_share,
        "def_share_top": def_share,
        "all_sos_std": all_sos_std,
        "all_sos_skew": all_sos_skew,
        "gp_sos_corr": gp_sos_corr,
        "top100_spread": top100_spread,
        "top100_sos_std": top100_sos_std,
        "teams": active,
    }


def _compare_rank_changes(pct_teams, hyb_teams):
    """Compare rank orderings between percentile and hybrid."""
    pct = pct_teams.set_index("team_id")[["powerscore_adj"]].rename(
        columns={"powerscore_adj": "ps_pct"}
    )
    hyb = hyb_teams.set_index("team_id")[["powerscore_adj"]].rename(
        columns={"powerscore_adj": "ps_hyb"}
    )
    merged = pct.join(hyb, how="inner")

    merged["rank_pct"] = merged["ps_pct"].rank(ascending=False, method="min").astype(int)
    merged["rank_hyb"] = merged["ps_hyb"].rank(ascending=False, method="min").astype(int)
    merged["rank_change"] = merged["rank_pct"] - merged["rank_hyb"]
    merged["ps_delta"] = merged["ps_hyb"] - merged["ps_pct"]

    rank_corr, _ = sp_stats.spearmanr(merged["rank_pct"], merged["rank_hyb"])
    return merged, rank_corr


# ===========================================================================
# Tests
# ===========================================================================

class TestHybridRealData:
    """Validate hybrid normalization against real cached game data."""

    @pytest.fixture(scope="class")
    def cohort_data(self):
        """Load all cohort game data."""
        data = {}
        for key in COHORT_FILES:
            games = _load_cohort(key)
            if games is not None and len(games) > 0:
                data[key] = games
        if not data:
            pytest.skip("No cached game data found in data/cache/")
        return data

    def test_multi_cohort_comparison(self, cohort_data):
        """
        Compare percentile vs hybrid-15% across 5 real cohorts.
        """
        print(f"\n{'='*130}")
        print(f"REAL DATA VALIDATION — Hybrid vs Percentile (15% blend)")
        print(f"{'='*130}")

        results = []
        for cohort_key, games in cohort_data.items():
            n_teams = games["team_id"].nunique()
            n_games = len(games) // 2  # perspective rows → actual games
            print(f"\n  Running {cohort_key}: {n_teams:,} teams, {n_games:,} games...")

            teams_pct = _run_cohort(games, hybrid_enabled=False)
            teams_hyb = _run_cohort(games, hybrid_enabled=True, zscore_blend=0.15)

            m_pct = _cohort_metrics(teams_pct)
            m_hyb = _cohort_metrics(teams_hyb)

            if m_pct is None or m_hyb is None:
                continue

            merged, rank_corr = _compare_rank_changes(m_pct["teams"], m_hyb["teams"])

            results.append({
                "cohort": cohort_key,
                "n": m_pct["n_active"],
                "pct": m_pct,
                "hyb": m_hyb,
                "rank_corr": rank_corr,
                "merged": merged,
            })

        # Print main comparison table
        print(f"\n{'='*130}")
        print(f"TOP-30 DIFFERENTIATION")
        print(f"{'='*130}")
        print(f"\n{'Cohort':<15} {'N':<7} {'Mode':<14} {'Top-N':<7} {'Spread':<10} "
              f"{'CV':<8} {'SOS std':<10} {'SOS range':<10} {'SOS IQR':<10} "
              f"{'SOS share':<10} {'GP-SOS r':<10}")
        print(f"{'-'*125}")

        for r in results:
            for mode, m in [("percentile", r["pct"]), ("hybrid-15%", r["hyb"])]:
                print(f"{r['cohort']:<15} {r['n']:<7} {mode:<14} "
                      f"{m['top_n']:<7} "
                      f"{m['top_spread']:.4f}    "
                      f"{m['top_cv']:.4f}  "
                      f"{m['top_sos_std']:.4f}    "
                      f"{m['top_sos_range']:.4f}    "
                      f"{m['top_sos_iqr']:.4f}    "
                      f"{m['sos_share_top']:.1%}      "
                      f"{m['gp_sos_corr']:+.3f}")

        # Print variance decomposition
        print(f"\n{'='*130}")
        print(f"VARIANCE DECOMPOSITION (Top-N)")
        print(f"{'='*130}")
        print(f"\n{'Cohort':<15} {'Mode':<14} {'OFF share':<12} {'DEF share':<12} {'SOS share':<12} {'Nominal':<12}")
        print(f"{'-'*80}")

        for r in results:
            for mode, m in [("percentile", r["pct"]), ("hybrid-15%", r["hyb"])]:
                print(f"{r['cohort']:<15} {mode:<14} "
                      f"{m['off_share_top']:.1%}         "
                      f"{m['def_share_top']:.1%}         "
                      f"{m['sos_share_top']:.1%}         "
                      f"20/20/60")

        # Print rank stability
        print(f"\n{'='*130}")
        print(f"RANK STABILITY — How much do rankings change?")
        print(f"{'='*130}")

        for r in results:
            merged = r["merged"]
            top30 = merged[merged["rank_pct"] <= 30]
            top100 = merged[merged["rank_pct"] <= 100]

            print(f"\n  {r['cohort']} ({r['n']:,} teams)")
            print(f"    Spearman rank correlation:  {r['rank_corr']:.4f}")
            print(f"    Mean |rank change| (all):   {merged['rank_change'].abs().mean():.1f}")
            print(f"    Mean |rank change| (top30): {top30['rank_change'].abs().mean():.1f}")
            print(f"    Mean |rank change| (top100):{top100['rank_change'].abs().mean():.1f}")
            print(f"    Max rank change:            {merged['rank_change'].abs().max():.0f}")

            big_movers_t30 = top30[top30["rank_change"].abs() >= 3].sort_values(
                "rank_change", key=abs, ascending=False
            )
            if len(big_movers_t30) > 0:
                print(f"    Top-30 movers (3+ spots):")
                for _, mv in big_movers_t30.head(5).iterrows():
                    direction = "↑" if mv["rank_change"] > 0 else "↓"
                    print(f"      {mv.name[:12]}...: #{int(mv['rank_pct'])} → #{int(mv['rank_hyb'])} "
                          f"({direction}{abs(mv['rank_change']):.0f})")

        # Summary
        print(f"\n{'='*130}")
        print(f"SUMMARY ACROSS {len(results)} REAL COHORTS")
        print(f"{'='*130}")

        spread_deltas = []
        cv_deltas = []
        sos_std_deltas = []
        gp_sos_safe = True

        for r in results:
            pct_s = r["pct"]["top_spread"]
            hyb_s = r["hyb"]["top_spread"]
            spread_deltas.append((hyb_s - pct_s) / pct_s if pct_s > 0 else 0)

            pct_cv = r["pct"]["top_cv"]
            hyb_cv = r["hyb"]["top_cv"]
            cv_deltas.append((hyb_cv - pct_cv) / pct_cv if pct_cv > 0 else 0)

            pct_sos = r["pct"]["top_sos_std"]
            hyb_sos = r["hyb"]["top_sos_std"]
            sos_std_deltas.append((hyb_sos - pct_sos) / pct_sos if pct_sos > 0 else 0)

            # Check GP-SOS correlation didn't get worse
            if abs(r["hyb"]["gp_sos_corr"]) > abs(r["pct"]["gp_sos_corr"]) + 0.05:
                gp_sos_safe = False

        print(f"\n  Top-N spread change:   {np.mean(spread_deltas):+.1%} avg "
              f"({min(spread_deltas):+.1%} to {max(spread_deltas):+.1%})")
        print(f"  Top-N CV change:       {np.mean(cv_deltas):+.1%} avg "
              f"({min(cv_deltas):+.1%} to {max(cv_deltas):+.1%})")
        print(f"  Top-N SOS std change:  {np.mean(sos_std_deltas):+.1%} avg "
              f"({min(sos_std_deltas):+.1%} to {max(sos_std_deltas):+.1%})")
        print(f"  GP-SOS bias safe:      {'YES' if gp_sos_safe else 'NO — regression detected!'}")
        print(f"  Avg rank correlation:  {np.mean([r['rank_corr'] for r in results]):.4f}")

    def test_blend_sweep_largest_cohort(self, cohort_data):
        """
        Sweep zscore blend 0%-40% on the largest cohort (12 male, ~7600 teams).
        """
        # Use the largest cohort
        largest_key = max(cohort_data.keys(), key=lambda k: len(cohort_data[k]))
        games = cohort_data[largest_key]
        n_teams = games["team_id"].nunique()

        print(f"\n{'='*100}")
        print(f"BLEND SWEEP — {largest_key} ({n_teams:,} teams)")
        print(f"{'='*100}")
        print(f"\n{'Blend':<8} {'Top30 Spread':<14} {'Top30 CV':<10} {'Top30 SOS std':<14} "
              f"{'SOS share':<10} {'T100 Spread':<12} {'T100 SOS std':<13} {'GP-SOS r':<10}")
        print(f"{'-'*100}")

        for blend_pct in [0, 5, 10, 15, 20, 25, 30, 40]:
            blend = blend_pct / 100
            teams = _run_cohort(
                games,
                hybrid_enabled=(blend > 0),
                zscore_blend=blend,
            )

            m = _cohort_metrics(teams)
            if m is None:
                continue

            marker = " ← current" if blend == 0 else ""
            print(f"{blend:.0%}      "
                  f"{m['top_spread']:.4f}        "
                  f"{m['top_cv']:.4f}    "
                  f"{m['top_sos_std']:.4f}        "
                  f"{m['sos_share_top']:.1%}      "
                  f"{m['top100_spread']:.4f}      "
                  f"{m['top100_sos_std']:.4f}       "
                  f"{m['gp_sos_corr']:+.3f}    {marker}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
