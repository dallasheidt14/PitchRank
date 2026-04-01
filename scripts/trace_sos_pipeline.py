#!/usr/bin/env python3
"""
Diagnostic: Trace the SOS normalization pipeline for U15M to find where
monotonicity (ordering) is lost.

Symptom:
  - Raw SOS 0.8628 -> sos_norm 1.000
  - Raw SOS 0.8513 -> sos_norm 0.867
  - Raw SOS 0.8355 -> sos_norm 1.000 (team with 0% win rate)

This script runs compute_rankings for U15M (single cohort, no cross-age)
and inspects intermediate values at every SOS stage to identify the first
point where raw-SOS ordering diverges from sos_norm ordering.

Usage:
    python scripts/trace_sos_pipeline.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.append(str(Path(__file__).parent.parent))

from src.etl.v53e import V53EConfig, compute_rankings
from src.rankings.data_adapter import fetch_games_for_rankings

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Show v53e engine logs at INFO level for diagnostic context
logging.basicConfig(level=logging.WARNING, format="%(message)s")
logging.getLogger("src.etl.v53e").setLevel(logging.INFO)

COHORT_AGE = "15"
COHORT_GENDER = "Male"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def rank_corr(a: pd.Series, b: pd.Series) -> float:
    """Spearman rank correlation between two aligned series."""
    valid = a.notna() & b.notna()
    if valid.sum() < 3:
        return float("nan")
    return a[valid].rank().corr(b[valid].rank())


def count_violations(raw: pd.Series, norm: pd.Series) -> int:
    """Count adjacent-pair monotonicity violations when sorted by raw desc."""
    df = pd.DataFrame({"raw": raw.values, "norm": norm.values})
    df = df.sort_values("raw", ascending=False).reset_index(drop=True)
    n = 0
    for i in range(len(df) - 1):
        if df.loc[i, "raw"] > df.loc[i + 1, "raw"] + 1e-8:
            if df.loc[i, "norm"] < df.loc[i + 1, "norm"] - 1e-8:
                n += 1
    return n


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        sys.exit(1)

    from supabase import create_client

    supabase = create_client(supabase_url, supabase_key)

    print("=" * 80)
    print("SOS PIPELINE MONOTONICITY DIAGNOSTIC -- U15 Male")
    print("=" * 80)

    # ---- Step 1: Fetch games ----
    print("\n[1/7] Fetching games from Supabase...")
    games_df = await fetch_games_for_rankings(
        supabase_client=supabase,
        lookback_days=365,
    )
    print(f"  Total game perspectives: {len(games_df)}")

    # Filter to U15M only (team age=15, gender=Male)
    u15m = games_df[(games_df["age"].astype(str) == COHORT_AGE) & (games_df["gender"] == COHORT_GENDER)].copy()
    print(f"  U15M game perspectives: {len(u15m)}")

    if u15m.empty:
        print("ERROR: No U15M games found")
        sys.exit(1)

    # ---- Step 2: Fetch team_state_map for SCF ----
    print("\n[2/7] Fetching team state map for SCF...")
    team_ids_in_games = set(u15m["team_id"].unique()) | set(u15m["opp_id"].unique())
    team_state_map = {}
    try:
        # Fetch in batches
        all_team_ids = list(team_ids_in_games)
        batch_size = 500
        for i in range(0, len(all_team_ids), batch_size):
            batch = all_team_ids[i : i + batch_size]
            resp = supabase.table("teams").select("id, state_code").in_("id", batch).execute()
            if resp.data:
                for row in resp.data:
                    tid = row.get("id")
                    sc = row.get("state_code")
                    if tid and sc:
                        team_state_map[str(tid)] = sc
        print(f"  Fetched state codes for {len(team_state_map)} teams")
    except Exception as e:
        print(f"  WARNING: Failed to fetch state map: {e}")
        team_state_map = None

    # ---- Step 3: Run compute_rankings (single cohort, Pass 1 style) ----
    print("\n[3/7] Running compute_rankings for U15M (single pass, no cross-age)...")
    result = compute_rankings(
        games_df=u15m,
        cfg=V53EConfig(),
        team_state_map=team_state_map,
        pass_label="U15M-diag",
    )
    teams = result["teams"]
    print(f"  Teams: {len(teams)}")

    if teams.empty:
        print("ERROR: No teams returned")
        sys.exit(1)

    # ---- Step 4: Available columns ----
    print("\n[4/7] Available SOS-related columns:")
    sos_cols = sorted(
        [
            c
            for c in teams.columns
            if any(kw in c.lower() for kw in ["sos", "component", "scf", "bridge", "isolated", "alpha"])
        ]
    )
    for c in sos_cols:
        print(f"  {c}: dtype={teams[c].dtype}, non-null={teams[c].notna().sum()}")

    # ---- Step 5: Filter to active, show top 30 ----
    print("\n[5/7] Top 30 active teams by raw SOS")
    active = teams[teams["status"] == "Active"].copy()
    print(f"  Active teams: {len(active)}")

    top30 = active.nlargest(30, "sos").copy()
    hdr = (
        f"  {'#':>3} | {'Team ID':>36} | {'RawSOS':>7} | {'sos_norm':>8} | "
        f"{'CompID':>6} | {'CompSz':>6} | {'SCF':>5} | {'GP':>3} | {'WR':>5} | "
        f"{'sn_global':>9} | {'sn_comp':>7} | {'alpha':>5}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    prev_norm = None
    for i, (_, r) in enumerate(top30.iterrows()):
        wr = r.get("wins", 0) / max(r.get("gp", 1), 1) if r.get("gp", 0) > 0 else 0
        comp_id = r.get("component_id", "?")
        comp_sz = r.get("component_size", "?")
        scf_val = f"{r['scf']:.2f}" if "scf" in r.index and pd.notna(r.get("scf")) else "?"
        sn_g = (
            f"{r['sos_norm_global']:.4f}"
            if "sos_norm_global" in r.index and pd.notna(r.get("sos_norm_global"))
            else "?"
        )
        sn_c = (
            f"{r['sos_norm_component']:.4f}"
            if "sos_norm_component" in r.index and pd.notna(r.get("sos_norm_component"))
            else "?"
        )
        alpha = f"{r['_sos_alpha']:.2f}" if "_sos_alpha" in r.index and pd.notna(r.get("_sos_alpha")) else "?"

        flag = ""
        if prev_norm is not None and r["sos_norm"] > prev_norm + 1e-6:
            flag = " <<< VIOLATION"
        prev_norm = r["sos_norm"]

        print(
            f"  {i + 1:>3} | {str(r['team_id'])[:36]:>36} | {r['sos']:.4f} | {r['sos_norm']:.4f} | "
            f"{comp_id:>6} | {comp_sz:>6} | {scf_val:>5} | {int(r.get('gp', 0)):>3} | {wr:.3f} | "
            f"{sn_g:>9} | {sn_c:>7} | {alpha:>5}{flag}"
        )

    # ---- Step 6: Monotonicity analysis ----
    print("\n[6/7] Monotonicity analysis (all active teams)")

    spearman_global = rank_corr(active["sos"], active.get("sos_norm_global", active["sos_norm"]))
    spearman_comp = rank_corr(active["sos"], active.get("sos_norm_component", active["sos_norm"]))
    spearman_hybrid = rank_corr(active["sos"], active["sos_norm"])

    print(f"  Spearman(raw SOS, sos_norm_global)    = {spearman_global:.4f}")
    print(f"  Spearman(raw SOS, sos_norm_component) = {spearman_comp:.4f}")
    print(f"  Spearman(raw SOS, sos_norm_hybrid)    = {spearman_hybrid:.4f}")

    v_global = count_violations(active["sos"], active.get("sos_norm_global", active["sos_norm"]))
    v_comp = count_violations(active["sos"], active.get("sos_norm_component", active["sos_norm"]))
    v_hybrid = count_violations(active["sos"], active["sos_norm"])
    print("\n  Adjacent-pair violations (sorted by raw SOS desc):")
    print(f"    sos_norm_global:    {v_global}")
    print(f"    sos_norm_component: {v_comp}")
    print(f"    sos_norm (hybrid):  {v_hybrid}")

    # Unshrunk only
    unshrunk = active[active["gp"] >= 10].copy()
    if len(unshrunk) > 10:
        print(f"\n  Among unshrunk teams (GP >= 10, n={len(unshrunk)}):")
        print(
            f"    Spearman(raw SOS, sos_norm_global)    = "
            f"{rank_corr(unshrunk['sos'], unshrunk.get('sos_norm_global', unshrunk['sos_norm'])):.4f}"
        )
        print(
            f"    Spearman(raw SOS, sos_norm_component) = "
            f"{rank_corr(unshrunk['sos'], unshrunk.get('sos_norm_component', unshrunk['sos_norm'])):.4f}"
        )
        print(f"    Spearman(raw SOS, sos_norm_hybrid)    = {rank_corr(unshrunk['sos'], unshrunk['sos_norm']):.4f}")
        v_g_u = count_violations(unshrunk["sos"], unshrunk.get("sos_norm_global", unshrunk["sos_norm"]))
        v_c_u = count_violations(unshrunk["sos"], unshrunk.get("sos_norm_component", unshrunk["sos_norm"]))
        v_h_u = count_violations(unshrunk["sos"], unshrunk["sos_norm"])
        print(f"    Violations (global): {v_g_u}, (component): {v_c_u}, (hybrid): {v_h_u}")

    # ---- Step 7: Connected component analysis ----
    print("\n[7/7] Connected component analysis")
    if "component_id" in active.columns:
        n_comps = active["component_id"].nunique()
        comp_stats = (
            active.groupby("component_id")
            .agg(
                n_teams=("team_id", "count"),
                sos_min=("sos", "min"),
                sos_max=("sos", "max"),
                sos_norm_min=("sos_norm", "min"),
                sos_norm_max=("sos_norm", "max"),
                mean_gp=("gp", "mean"),
            )
            .sort_values("n_teams", ascending=False)
        )

        print(f"  Total components: {n_comps}")
        print(f"  {'CompID':>6} | {'Teams':>5} | {'RawSOS range':>18} | {'sos_norm range':>18} | {'mean GP':>7}")
        for cid, row in comp_stats.head(15).iterrows():
            print(
                f"  {cid:>6} | {row['n_teams']:>5} | "
                f"[{row['sos_min']:.4f}, {row['sos_max']:.4f}] | "
                f"[{row['sos_norm_min']:.4f}, {row['sos_norm_max']:.4f}] | "
                f"{row['mean_gp']:.1f}"
            )

        # Cross-component violations
        if n_comps > 1:
            sorted_by_sos = active.sort_values("sos", ascending=False).reset_index(drop=True)
            cross_comp_violations = []
            same_comp_violations = []
            for i in range(len(sorted_by_sos) - 1):
                a = sorted_by_sos.iloc[i]
                b = sorted_by_sos.iloc[i + 1]
                if a["sos"] > b["sos"] + 1e-6 and a["sos_norm"] < b["sos_norm"] - 1e-6:
                    entry = {
                        "a_comp": a.get("component_id"),
                        "a_sos": a["sos"],
                        "a_norm": a["sos_norm"],
                        "a_tid": str(a["team_id"])[:20],
                        "b_comp": b.get("component_id"),
                        "b_sos": b["sos"],
                        "b_norm": b["sos_norm"],
                        "b_tid": str(b["team_id"])[:20],
                    }
                    if a.get("component_id") != b.get("component_id"):
                        cross_comp_violations.append(entry)
                    else:
                        same_comp_violations.append(entry)

            print(f"\n  Cross-component ordering violations: {len(cross_comp_violations)}")
            for v in cross_comp_violations[:5]:
                print(
                    f"    A: comp={v['a_comp']} raw={v['a_sos']:.4f} norm={v['a_norm']:.4f} ({v['a_tid']})"
                    f"  >  B: comp={v['b_comp']} raw={v['b_sos']:.4f} norm={v['b_norm']:.4f} ({v['b_tid']})"
                )

            print(f"  Same-component ordering violations:  {len(same_comp_violations)}")
            for v in same_comp_violations[:5]:
                print(
                    f"    A: comp={v['a_comp']} raw={v['a_sos']:.4f} norm={v['a_norm']:.4f} ({v['a_tid']})"
                    f"  >  B: comp={v['b_comp']} raw={v['b_sos']:.4f} norm={v['b_norm']:.4f} ({v['b_tid']})"
                )

    # ---- VERDICT ----
    print("\n" + "=" * 80)
    print("VERDICT")
    print("=" * 80)

    n_comps = active["component_id"].nunique() if "component_id" in active.columns else 1

    print(f"""
Pipeline stages and their monotonicity behavior:

  Stage 1: Direct SOS (weighted mean of opp strengths)  -> MONOTONIC
  Stage 2: SOS trimming (bottom 25% downweighted)       -> Per-team, preserves global order
  Stage 3: PageRank dampening (linear: 0.15*0.5 + 0.85*sos) -> MONOTONIC (linear transform)
  Stage 4: SCF dampening (sos = 0.5 + scf*(sos - 0.5)) -> BREAKS ORDER (team-specific scf)
  Stage 5: Hybrid norm (alpha*global + (1-alpha)*comp)  -> BREAKS ORDER (different reference groups)
  Stage 6: Low-sample shrinkage (toward 0.35)           -> BREAKS ORDER (GP-dependent)
  Stage 7: GP-SOS decorrelation (OLS residualization)   -> BREAKS ORDER (regression adjustment)
  Stage 8: Power-SOS iterations (3x re-norm)            -> COMPOUNDS all breaks

Components found: {n_comps}

PRIMARY CAUSE: _apply_hybrid_norm blends global percentile (across all teams in
cohort) with component percentile (across only teams in same connected component).

For small components (< ~30 teams), alpha = clip(log10(size)/2, 0.35, 1.0):
  - 5-team component: alpha=0.35 -> 65% weight on component percentile
  - 10-team component: alpha=0.50 -> 50% weight on component percentile
  - 100-team component: alpha=1.00 -> 100% weight on global percentile

The #1 team in a 5-team weak cluster gets component_norm=1.0, which inflates
their hybrid sos_norm even though their raw SOS is lower than hundreds of teams
in the main component.

SECONDARY CAUSES:
  - SCF dampening: Different SCF values per team break monotonicity
  - GP-SOS decorrelation: OLS residualization shifts teams differently by GP
  - Low-sample shrinkage: Teams with GP < 10 get pulled toward 0.35

RECOMMENDATION: The hybrid blend was designed to prevent cross-ecosystem bias
(ECNL vs MLS NEXT HD). But for small satellite components (3-10 teams), it
creates artificial sos_norm inflation. Consider either:
  (a) Setting a minimum component size below which teams use ONLY global norm
  (b) Using weighted blend where tiny components get alpha closer to 1.0
  (c) Capping component_norm at the team's global_norm + epsilon for small components
""")


if __name__ == "__main__":
    asyncio.run(main())
