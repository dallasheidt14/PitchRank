#!/usr/bin/env python3
"""
Diagnose bad-SOS teams ranking too high in production data.

Queries rankings_full from Supabase and analyzes the top 30 teams per cohort
to find teams that rank highly despite weak SOS. Flags anomalies and prints
detailed reports.

Usage:
    python scripts/diagnose_bad_sos_rankings.py
    python scripts/diagnose_bad_sos_rankings.py --top 50
    python scripts/diagnose_bad_sos_rankings.py --cohort "u14 Male"
    python scripts/diagnose_bad_sos_rankings.py --sos-threshold 0.35
"""

import os
import sys
import argparse
from pathlib import Path
from collections import defaultdict

import pandas as pd
import numpy as np

# Load env
env_local = Path('.env.local')
if env_local.exists():
    from dotenv import load_dotenv
    load_dotenv(env_local, override=True)
else:
    from dotenv import load_dotenv
    load_dotenv()

from supabase import create_client

# ── Supabase client ──────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Data fetch ────────────────────────────────────────────────────────────────

COLUMNS = (
    "team_id, age_group, gender, state_code, status, "
    "games_played, wins, losses, draws, win_percentage, "
    "off_raw, off_norm, def_norm, sad_raw, "
    "sos, sos_norm, "
    "powerscore_core, powerscore_adj, powerscore_ml, "
    "power_score_final, national_power_score, "
    "rank_in_cohort, rank_in_cohort_ml, "
    "ml_overperf, ml_norm, "
    "perf_centered, provisional_mult, anchor, "
    "goals_for, goals_against"
)


def fetch_all_rankings():
    """Fetch all rankings_full rows with pagination."""
    all_rows = []
    batch_size = 1000
    offset = 0

    while True:
        result = (
            supabase.table("rankings_full")
            .select(COLUMNS)
            .eq("status", "Active")
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows = result.data
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < batch_size:
            break
        offset += batch_size
        print(f"  Fetched {len(all_rows)} rows...", end="\r")

    print(f"  Fetched {len(all_rows)} active rankings total.")
    return pd.DataFrame(all_rows)


# ── Analysis functions ────────────────────────────────────────────────────────

def analyze_cohort(df, age_group, gender, top_n=30, sos_threshold=0.35):
    """
    Analyze a single cohort for bad-SOS teams ranking too high.

    Returns a dict with findings.
    """
    cohort = df[(df["age_group"] == age_group) & (df["gender"] == gender)].copy()
    if len(cohort) < 10:
        return None

    # Use rank_in_cohort_ml if available, else rank_in_cohort
    rank_col = "rank_in_cohort_ml" if cohort["rank_in_cohort_ml"].notna().any() else "rank_in_cohort"
    cohort = cohort.sort_values(rank_col, ascending=True)

    top = cohort.head(top_n)
    rest = cohort.iloc[top_n:]

    # Find teams in top N with low SOS
    bad_sos_in_top = top[top["sos_norm"] < sos_threshold]

    # PowerScore decomposition for top teams
    # Formula: 0.20 * off_norm + 0.20 * def_norm + 0.60 * sos_norm
    top_off_contrib = 0.20 * top["off_norm"]
    top_def_contrib = 0.20 * top["def_norm"]
    top_sos_contrib = 0.60 * top["sos_norm"]

    # Median SOS of top vs bottom half
    half = len(cohort) // 2
    top_half_sos = cohort.head(half)["sos_norm"].median()
    bot_half_sos = cohort.tail(half)["sos_norm"].median()

    # Teams with high off/def but low SOS that rank well
    high_talent_low_sos = top[
        (top["off_norm"] > 0.70) &
        (top["sos_norm"] < sos_threshold)
    ]

    # Win % vs SOS correlation in top N
    if len(top) >= 5 and top["sos_norm"].std() > 0:
        wp_sos_corr = top[["win_percentage", "sos_norm"]].corr().iloc[0, 1]
    else:
        wp_sos_corr = float("nan")

    # Find "schedule dodgers": high win %, low SOS, ranked in top N
    schedule_dodgers = top[
        (top["win_percentage"] > 0.70) &
        (top["sos_norm"] < 0.40)
    ]

    return {
        "age_group": age_group,
        "gender": gender,
        "cohort_size": len(cohort),
        "top_n": top_n,
        "bad_sos_in_top": bad_sos_in_top,
        "high_talent_low_sos": high_talent_low_sos,
        "schedule_dodgers": schedule_dodgers,
        "top_avg_sos": top["sos_norm"].mean(),
        "cohort_avg_sos": cohort["sos_norm"].mean(),
        "top_half_sos": top_half_sos,
        "bot_half_sos": bot_half_sos,
        "wp_sos_corr": wp_sos_corr,
        "top_teams": top,
        "rank_col": rank_col,
    }


def print_cohort_report(findings):
    """Print a detailed report for one cohort."""
    if findings is None:
        return

    ag = findings["age_group"]
    g = findings["gender"]
    n = findings["cohort_size"]
    top_n = findings["top_n"]
    rank_col = findings["rank_col"]

    print(f"\n{'='*80}")
    print(f"  {ag} {g}  ({n} teams, analyzing top {top_n})")
    print(f"{'='*80}")

    # SOS distribution summary
    print(f"\n  SOS Distribution:")
    print(f"    Top {top_n} avg sos_norm:   {findings['top_avg_sos']:.3f}")
    print(f"    Cohort avg sos_norm:        {findings['cohort_avg_sos']:.3f}")
    print(f"    Top half median sos_norm:   {findings['top_half_sos']:.3f}")
    print(f"    Bottom half median sos_norm: {findings['bot_half_sos']:.3f}")
    print(f"    Win% ↔ SOS correlation (top {top_n}): {findings['wp_sos_corr']:.3f}")

    # Bad SOS in top N
    bad = findings["bad_sos_in_top"]
    if len(bad) > 0:
        print(f"\n  ⚠️  {len(bad)} team(s) in top {top_n} with sos_norm < threshold:")
        print(f"  {'Rank':<6} {'Team ID':<40} {'PS':>6} {'OFF':>6} {'DEF':>6} {'SOS':>6} {'Win%':>6} {'GP':>4}")
        print(f"  {'-'*76}")
        for _, r in bad.iterrows():
            ps = r.get("powerscore_ml") or r.get("power_score_final") or r.get("powerscore_adj") or 0
            print(f"  {int(r[rank_col]):<6} {str(r['team_id']):<40} "
                  f"{ps:>6.3f} {r['off_norm']:>6.3f} {r['def_norm']:>6.3f} "
                  f"{r['sos_norm']:>6.3f} {r['win_percentage']:>6.1%} {int(r['games_played']):>4}")
    else:
        print(f"\n  ✅ No low-SOS teams in top {top_n}")

    # Schedule dodgers
    dodgers = findings["schedule_dodgers"]
    if len(dodgers) > 0:
        print(f"\n  🏃 {len(dodgers)} schedule dodger(s) (win% > 70%, sos_norm < 0.40):")
        for _, r in dodgers.iterrows():
            ps = r.get("powerscore_ml") or r.get("power_score_final") or r.get("powerscore_adj") or 0
            print(f"    Rank {int(r[rank_col])}: PS={ps:.3f}, SOS={r['sos_norm']:.3f}, "
                  f"Win%={r['win_percentage']:.1%}, GP={int(r['games_played'])}")

    # Full top N table
    top = findings["top_teams"]
    print(f"\n  Top {min(top_n, len(top))} Rankings:")
    print(f"  {'Rk':<4} {'PS':>6} {'OFF':>6} {'DEF':>6} {'SOS':>6} {'W%':>6} {'GP':>4} {'W-L-D':>9} {'St':>3} {'Team ID'}")
    print(f"  {'-'*80}")
    for _, r in top.iterrows():
        ps = r.get("powerscore_ml") or r.get("power_score_final") or r.get("powerscore_adj") or 0
        wld = f"{int(r['wins'])}-{int(r['losses'])}-{int(r['draws'])}"
        st = r.get("state_code", "") or ""
        flag = " ⚠️" if r["sos_norm"] < 0.35 else ""
        print(f"  {int(r[rank_col]):<4} {ps:>6.3f} {r['off_norm']:>6.3f} {r['def_norm']:>6.3f} "
              f"{r['sos_norm']:>6.3f} {r['win_percentage']:>6.1%} {int(r['games_played']):>4} "
              f"{wld:>9} {st:>3} {str(r['team_id'])[:36]}{flag}")


def print_summary(all_findings):
    """Print cross-cohort summary."""
    print(f"\n{'='*80}")
    print(f"  CROSS-COHORT SUMMARY")
    print(f"{'='*80}")

    total_bad = 0
    total_dodgers = 0
    worst_cohorts = []

    for f in all_findings:
        if f is None:
            continue
        n_bad = len(f["bad_sos_in_top"])
        n_dodgers = len(f["schedule_dodgers"])
        total_bad += n_bad
        total_dodgers += n_dodgers
        if n_bad > 0:
            worst_cohorts.append((f["age_group"], f["gender"], n_bad, n_dodgers))

    print(f"\n  Total low-SOS teams in top rankings: {total_bad}")
    print(f"  Total schedule dodgers:              {total_dodgers}")

    if worst_cohorts:
        print(f"\n  Cohorts with low-SOS teams in top rankings:")
        worst_cohorts.sort(key=lambda x: -x[2])
        for ag, g, n_bad, n_dodgers in worst_cohorts:
            print(f"    {ag} {g}: {n_bad} low-SOS, {n_dodgers} dodgers")

    # Global SOS stats
    print(f"\n  Average top-{all_findings[0]['top_n'] if all_findings else 30} SOS by cohort:")
    for f in sorted(all_findings, key=lambda x: x["top_avg_sos"] if x else 999):
        if f is None:
            continue
        bar = "█" * int(f["top_avg_sos"] * 40)
        print(f"    {f['age_group']:>4} {f['gender']:<7} avg_sos={f['top_avg_sos']:.3f} {bar}")

    # PowerScore component analysis across all cohorts
    print(f"\n  PowerScore Component Weights (actual contribution, top teams):")
    all_top = pd.concat([f["top_teams"] for f in all_findings if f is not None])
    if len(all_top) > 0:
        off_c = (0.20 * all_top["off_norm"]).mean()
        def_c = (0.20 * all_top["def_norm"]).mean()
        sos_c = (0.60 * all_top["sos_norm"]).mean()
        total = off_c + def_c + sos_c
        print(f"    OFF: {off_c:.3f} ({off_c/total*100:.1f}%)")
        print(f"    DEF: {def_c:.3f} ({def_c/total*100:.1f}%)")
        print(f"    SOS: {sos_c:.3f} ({sos_c/total*100:.1f}%)")

    # SOS distribution anomaly: check if SOS clusters near 0.5
    print(f"\n  SOS Clustering Analysis (all active teams):")
    all_teams = pd.concat([f["top_teams"] for f in all_findings if f is not None])
    # Can only analyze top teams since we're printing per-cohort
    sos_vals = all_teams["sos_norm"]
    pct_near_half = ((sos_vals > 0.40) & (sos_vals < 0.60)).mean()
    print(f"    % of top teams with sos_norm in [0.40, 0.60]: {pct_near_half:.1%}")
    print(f"    sos_norm std (top teams): {sos_vals.std():.3f}")
    print(f"    sos_norm range: [{sos_vals.min():.3f}, {sos_vals.max():.3f}]")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Diagnose bad-SOS teams ranking too high")
    parser.add_argument("--top", type=int, default=30, help="Analyze top N teams per cohort (default: 30)")
    parser.add_argument("--cohort", type=str, default=None, help='Filter to specific cohort, e.g. "u14 Male"')
    parser.add_argument("--sos-threshold", type=float, default=0.35,
                        help="SOS norm threshold below which a team is 'bad SOS' (default: 0.35)")
    parser.add_argument("--min-cohort-size", type=int, default=30,
                        help="Skip cohorts smaller than this (default: 30)")
    args = parser.parse_args()

    print("Fetching rankings from Supabase...")
    df = fetch_all_rankings()

    if df.empty:
        print("No data returned from rankings_full.")
        sys.exit(1)

    # Clean up types
    numeric_cols = [
        "games_played", "wins", "losses", "draws", "win_percentage",
        "off_raw", "off_norm", "def_norm", "sad_raw",
        "sos", "sos_norm",
        "powerscore_core", "powerscore_adj", "powerscore_ml",
        "power_score_final", "national_power_score",
        "rank_in_cohort", "rank_in_cohort_ml",
        "ml_overperf", "ml_norm",
        "perf_centered", "provisional_mult", "anchor",
        "goals_for", "goals_against",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Fill NaN win_percentage
    if "win_percentage" in df.columns:
        mask = df["win_percentage"].isna() & (df["games_played"] > 0)
        df.loc[mask, "win_percentage"] = df.loc[mask, "wins"] / df.loc[mask, "games_played"]
        df["win_percentage"] = df["win_percentage"].fillna(0)

    print(f"\nTotal active teams: {len(df)}")
    print(f"Cohorts: {df.groupby(['age_group', 'gender']).size().shape[0]}")
    print(f"SOS threshold: {args.sos_threshold}")

    # Determine cohorts to analyze
    if args.cohort:
        parts = args.cohort.strip().split()
        if len(parts) == 2:
            cohorts = [(parts[0].lower(), parts[1])]
        else:
            print(f"Invalid cohort format: '{args.cohort}'. Use 'u14 Male' format.")
            sys.exit(1)
    else:
        cohorts = (
            df.groupby(["age_group", "gender"])
            .size()
            .reset_index(name="count")
            .query(f"count >= {args.min_cohort_size}")
            .apply(lambda r: (r["age_group"], r["gender"]), axis=1)
            .tolist()
        )
        # Sort by age group
        cohorts.sort(key=lambda x: (x[1], x[0]))

    print(f"Analyzing {len(cohorts)} cohort(s)...")

    all_findings = []
    for age_group, gender in cohorts:
        findings = analyze_cohort(df, age_group, gender, top_n=args.top, sos_threshold=args.sos_threshold)
        if findings:
            all_findings.append(findings)
            print_cohort_report(findings)

    if all_findings:
        print_summary(all_findings)
    else:
        print("No cohorts with enough data to analyze.")


if __name__ == "__main__":
    main()
