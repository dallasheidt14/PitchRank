#!/usr/bin/env python3
"""
Rankings Weight Simulator
=========================
Replay the PowerScore blend with different OFF/DEF/SOS/PERF/ML weights
without re-running the full pipeline. Uses existing normalized components
from rankings_full.

Also simulates an SOS-weighted performance layer where overperformance
against strong opponents counts more than stat-padding against weak ones.

Usage:
    python scripts/rankings_weight_simulator.py <team_uuid1> <team_uuid2> ...
    python scripts/rankings_weight_simulator.py --demo  # hardcoded fallback data

Edit the SCENARIOS list at the bottom to try different weight combos.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

# ─── Hardcoded demo data ─────────────────────────────────────────────────────
# AZ U12 Male top teams — fresh from rankings_full (2026-03-17)
DEMO_TEAMS = [
    {
        "name": "FC Tucson 2014 Pre-MLSN",
        "team_id": "ffa679df",
        "off_norm": 0.9735, "def_norm": 0.9890, "sos_norm": 0.9361,
        "perf_centered": 0.1500, "perf_raw": None,
        "ml_norm": 0.2256, "ml_overperf": 0.4276, "games_played": 30,
    },
    {
        "name": "Phoenix United 2014 Elite ⭐",
        "team_id": "691eb36d",
        "off_norm": 0.8913, "def_norm": 0.9890, "sos_norm": 0.9892,
        "perf_centered": -0.0362, "perf_raw": None,
        "ml_norm": 0.1392, "ml_overperf": 0.1408, "games_played": 30,
    },
    {
        "name": "Phoenix United 2014 Academy",
        "team_id": "5a9dac52",
        "off_norm": 0.9731, "def_norm": 0.9890, "sos_norm": 0.8756,
        "perf_centered": 0.1500, "perf_raw": None,
        "ml_norm": 0.3815, "ml_overperf": 1.1581, "games_played": 16,
    },
    {
        "name": "Next Level Southeast 2014 Black",
        "team_id": "448ebe45",
        "off_norm": 0.8310, "def_norm": 0.9890, "sos_norm": 0.9128,
        "perf_centered": -0.1500, "perf_raw": None,
        "ml_norm": 0.1212, "ml_overperf": 0.0805, "games_played": 30,
    },
    {
        "name": "RSL Arizona North 2014 GSA",
        "team_id": "291aa4d2",
        "off_norm": 0.9491, "def_norm": 0.9155, "sos_norm": 0.9276,
        "perf_centered": 0.1500, "perf_raw": None,
        "ml_norm": -0.1160, "ml_overperf": -0.0601, "games_played": 30,
    },
    {
        "name": "Dynamos SC 2014 SC",
        "team_id": "c2f8e0aa",
        "off_norm": 0.7774, "def_norm": 0.9890, "sos_norm": 0.9581,
        "perf_centered": 0.1500, "perf_raw": None,
        "ml_norm": -0.1495, "ml_overperf": -0.1630, "games_played": 30,
    },
    {
        "name": "Playmaker PRE-ECNL 2014",
        "team_id": "a8e57856",
        "off_norm": 0.9475, "def_norm": 0.8528, "sos_norm": 0.8468,
        "perf_centered": 0.1500, "perf_raw": None,
        "ml_norm": 0.1795, "ml_overperf": 0.2658, "games_played": 30,
    },
    {
        "name": "Tuzos Royals 2014",
        "team_id": "5981ccbc",
        "off_norm": 0.6070, "def_norm": 0.9479, "sos_norm": 0.9097,
        "perf_centered": 0.1500, "perf_raw": None,
        "ml_norm": 0.1368, "ml_overperf": 0.1326, "games_played": 30,
    },
    {
        "name": "Excel Soccer Academy 2014 Red",
        "team_id": "929083d0",
        "off_norm": 0.7914, "def_norm": 0.7923, "sos_norm": 0.9413,
        "perf_centered": 0.0161, "perf_raw": None,
        "ml_norm": -0.1545, "ml_overperf": -0.1800, "games_played": 30,
    },
    {
        "name": "BRAZAS FC 2014 Black",
        "team_id": "a180387c",
        "off_norm": 0.8537, "def_norm": 0.9742, "sos_norm": 0.9115,
        "perf_centered": 0.0309, "perf_raw": None,
        "ml_norm": -0.3417, "ml_overperf": -0.9007, "games_played": 30,
    },
]

# Module-level teams list — populated by load_teams_from_supabase() or set to DEMO_TEAMS
TEAMS: list[dict] = []

# Columns needed from rankings_full to populate each team dict
SIMULATOR_COLS = [
    "team_id",
    "off_norm",
    "def_norm",
    "sos_norm",
    "perf_centered",
    "perf_raw",
    "ml_norm",
    "ml_overperf",
    "games_played",
]

MIN_GAMES_PROVISIONAL = 6


# ─── Supabase helpers (mirrors diagnose_ranking.py) ──────────────────────────

def get_supabase():
    """Create a Supabase client from .env.local credentials."""
    from dotenv import load_dotenv
    from supabase import create_client

    load_dotenv(Path(__file__).parent.parent / ".env.local")

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("ERROR: Missing SUPABASE_URL or SUPABASE_KEY in .env.local")
        sys.exit(1)
    return create_client(url, key)


def fetch_team_names(supabase, team_ids: list[str]) -> dict[str, str]:
    """Batch-fetch display names for teams from the teams table."""
    names = {}
    batch_size = 100
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i : i + batch_size]
        result = (
            supabase.table("teams")
            .select("team_id_master, team_name, club_name")
            .in_("team_id_master", batch)
            .execute()
        )
        for r in result.data or []:
            tid = r["team_id_master"]
            names[tid] = f"{r.get('team_name', '?')} ({r.get('club_name', '')})"
    return names


def load_teams_from_supabase(team_ids: list[str]) -> list[dict]:
    """Fetch team data from rankings_full and return list of team dicts.

    Mirrors the fetch pattern from diagnose_ranking.py but selects only
    the columns needed for the weight simulator.
    """
    supabase = get_supabase()

    # Batch .in_() queries to <= 100 IDs per call (Supabase URI length limit)
    cols = ", ".join(SIMULATOR_COLS)
    all_rows = []
    batch_size = 100
    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i : i + batch_size]
        result = (
            supabase.table("rankings_full")
            .select(cols)
            .in_("team_id", batch)
            .execute()
        )
        all_rows.extend(result.data or [])

    if not all_rows:
        print(f"ERROR: No rankings data found for team IDs: {team_ids}")
        sys.exit(1)

    # Batch-fetch display names
    found_ids = [row["team_id"] for row in all_rows]
    name_map = fetch_team_names(supabase, found_ids)

    # Build team dicts
    teams = []
    for row in all_rows:
        name = name_map.get(row["team_id"], f"Unknown ({row['team_id'][:8]}...)")
        teams.append({
            "name": name,
            "team_id": row["team_id"],
            "off_norm": row.get("off_norm", 0.0) or 0.0,
            "def_norm": row.get("def_norm", 0.0) or 0.0,
            "sos_norm": row.get("sos_norm", 0.0) or 0.0,
            "perf_centered": row.get("perf_centered", 0.0) or 0.0,
            "perf_raw": row.get("perf_raw"),
            "ml_norm": row.get("ml_norm", 0.0) or 0.0,
            "ml_overperf": row.get("ml_overperf", 0.0) or 0.0,
            "games_played": row.get("games_played", 0) or 0,
        })

    found_ids = {t["team_id"] for t in teams}
    missing = [tid for tid in team_ids if tid not in found_ids]
    if missing:
        print(f"WARNING: No rankings data for {len(missing)} team(s): {missing}")

    print(f"  Loaded {len(teams)} team(s) from Supabase rankings_full")
    return teams


# ─── Simulation engine ───────────────────────────────────────────────────────

def provisional_mult(gp: int) -> float:
    """Smooth linear ramp from 0.85 (0 games) to 1.0 (15 games).
    Mirrors _provisional_multiplier in src/etl/v53e.py."""
    max_games = 15
    if gp >= max_games:
        return 1.0
    if gp <= 0:
        return 0.85
    return 0.85 + (gp / max_games) * 0.15


def simulate(off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf=False, perf_cap=0.50):
    """Re-blend PowerScore with custom weights and return ranked list.

    If sos_weighted_perf=True, replaces perf_centered with an SOS-weighted
    version: perf_adjusted = perf_centered * sos_norm. This means overperformance
    against tough schedules gets amplified, while stat-padding against weak
    schedules gets dampened.

    perf_cap: Symmetric cap on perf_centered (default ±0.50 = no effective cap
    since perf_centered is already [-0.5, +0.5]). Lower values like 0.25 clip
    outlier overperformers while leaving mid-range teams unaffected.
    """
    # Matches v53e.py: MAX_POWERSCORE_THEORETICAL = 1.0 + PERF_CAP * PERF_BLEND_WEIGHT
    max_ps_theoretical = 1.0 + perf_cap * perf_w

    results = []
    for t in TEAMS:
        # Optionally weight perf by SOS
        perf = t["perf_centered"]
        if sos_weighted_perf:
            # Multiply perf by sos_norm: high SOS amplifies, low SOS dampens
            perf = perf * t["sos_norm"]

        # Apply perf cap — clips outliers symmetrically
        perf = max(-perf_cap, min(perf_cap, perf))

        # Matches v53e.py powerscore_core formula
        ps_core = (
            off_w * t["off_norm"]
            + def_w * t["def_norm"]
            + sos_w * t["sos_norm"]
            + perf * perf_w
        ) / max_ps_theoretical

        ps_adj = ps_core * provisional_mult(t["games_played"])

        # Matches layer13: powerscore_ml = (powerscore_adj + alpha * ml_norm).clip(0, 1)
        # No normalization — just additive blend + clip
        ps_ml = max(0.0, min(1.0, ps_adj + ml_alpha * t["ml_norm"]))

        display = round(ps_ml * 55, 2)

        results.append({
            "name": t["name"],
            "ps_adj": round(ps_adj, 4),
            "ps_ml": round(ps_ml, 4),
            "display": display,
            "off": t["off_norm"],
            "sos": t["sos_norm"],
            "perf": round(perf, 4),
            "ml_norm": t["ml_norm"],
        })

    results.sort(key=lambda x: x["ps_ml"], reverse=True)
    return results


def print_results(label, off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf=False, perf_cap=0.50):
    print(f"\n{'='*90}")
    print(f"  {label}")
    weights_str = f"  OFF={off_w}  DEF={def_w}  SOS={sos_w}  PERF={perf_w}  ML_ALPHA={ml_alpha}"
    if sos_weighted_perf:
        weights_str += "  [SOS-weighted PERF]"
    if perf_cap < 0.50:
        weights_str += f"  [PERF cap=+/-{perf_cap}]"
    print(weights_str)
    print(f"{'='*90}")
    print(f"  {'#':<3} {'Team':<38} {'Base':>7} {'ML':>7} {'Disp':>6}  {'OFF':>6} {'SOS':>6} {'PERF':>7} {'ML_N':>7}")
    print(f"  {'-'*3} {'-'*38} {'-'*7} {'-'*7} {'-'*6}  {'-'*6} {'-'*6} {'-'*7} {'-'*7}")

    results = simulate(off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf, perf_cap)
    for i, r in enumerate(results, 1):
        print(
            f"  {i:<3} {r['name']:<38} {r['ps_adj']:>7.4f} {r['ps_ml']:>7.4f} "
            f"{r['display']:>6.2f}  {r['off']:>6.3f} {r['sos']:>6.3f} {r['perf']:>+7.4f} {r['ml_norm']:>+7.3f}"
        )


# ─── Quality scoring ─────────────────────────────────────────────────────────

def find_elite_rank(off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf=False, perf_cap=0.50):
    """Return the rank of Phoenix United Elite for a given config (demo mode only)."""
    results = simulate(off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf, perf_cap)
    for i, r in enumerate(results, 1):
        if "Elite" in r["name"]:
            return i
    return 99


def score_ranking_quality_demo(results):
    """Score how 'correct' a ranking feels based on domain knowledge (demo mode).

    Heuristics (higher = better):
    - Elite #1 = ideal (SOS king with best defense should lead)
    - Academy top-3 = good (strong off/def, decent SOS, 18 games = slight uncertainty)
    - Tucson top-3 = acceptable (great off/def, but perf is inflated by weak SOS)
    - Dynamos/Tuzos NOT top-3 = good (high perf but low offense or SOS)
    - Reasonable spread (top 3 not bunched within 0.005 of each other)
    - No absurd inversions (e.g., Playmaker #1 despite 0.857 SOS)
    """
    score = 0.0
    rank_map = {}
    for i, r in enumerate(results, 1):
        if "Elite" in r["name"]:
            rank_map["elite"] = (i, r["ps_ml"])
        elif "Academy" in r["name"]:
            rank_map["academy"] = (i, r["ps_ml"])
        elif "Tucson" in r["name"]:
            rank_map["tucson"] = (i, r["ps_ml"])
        elif "Dynamos" in r["name"]:
            rank_map["dynamos"] = (i, r["ps_ml"])
        elif "Tuzos" in r["name"]:
            rank_map["tuzos"] = (i, r["ps_ml"])
        elif "Playmaker" in r["name"]:
            rank_map["playmaker"] = (i, r["ps_ml"])

    # Elite should be #1 (10 pts), #2 okay (6 pts), #3 meh (2 pts)
    er = rank_map.get("elite", (99, 0))[0]
    if er == 1: score += 10
    elif er == 2: score += 6
    elif er == 3: score += 2

    # Academy should be top 3
    ar = rank_map.get("academy", (99, 0))[0]
    if ar <= 3: score += 4
    elif ar <= 5: score += 2

    # Tucson should be top 4 (good team, just perf-inflated)
    tr = rank_map.get("tucson", (99, 0))[0]
    if tr <= 4: score += 3
    elif tr <= 6: score += 1

    # Dynamos/Tuzos should NOT be top 3 (inflated perf, weak offense)
    dr = rank_map.get("dynamos", (99, 0))[0]
    tzr = rank_map.get("tuzos", (99, 0))[0]
    if dr > 3: score += 2
    if tzr > 5: score += 2

    # Spread: top 3 should have visible gaps (not all bunched at same score)
    if len(results) >= 3:
        top3_scores = [results[i]["ps_ml"] for i in range(3)]
        gap_1_2 = top3_scores[0] - top3_scores[1]
        gap_2_3 = top3_scores[1] - top3_scores[2]
        if gap_1_2 > 0.005: score += 1  # meaningful #1 vs #2 gap
        if gap_2_3 > 0.005: score += 1  # meaningful #2 vs #3 gap

    return round(score, 1)


def score_ranking_quality_live(results):
    """Generic quality metric for live data (no domain-specific team name matching).

    Measures:
    - Spread: top 3 should have visible gaps (not all bunched at same score)
    - Monotonicity: scores should decrease smoothly (no large inversions)
    - Range: reasonable spread between #1 and last place
    """
    score = 0.0

    # Spread: top 3 should have visible gaps
    if len(results) >= 3:
        top3_scores = [results[i]["ps_ml"] for i in range(3)]
        gap_1_2 = top3_scores[0] - top3_scores[1]
        gap_2_3 = top3_scores[1] - top3_scores[2]
        if gap_1_2 > 0.005: score += 2  # meaningful #1 vs #2 gap
        if gap_2_3 > 0.005: score += 2  # meaningful #2 vs #3 gap

    # Score uniqueness: bonus if all teams have distinct scores (no ties)
    if len(results) >= 2:
        distinct_scores = len(set(r["ps_ml"] for r in results))
        if distinct_scores == len(results):
            score += 2  # all teams have unique scores

    # Range: top vs bottom spread
    if len(results) >= 2:
        total_range = results[0]["ps_ml"] - results[-1]["ps_ml"]
        if total_range > 0.05: score += 2  # meaningful separation
        if total_range > 0.10: score += 2  # strong separation

    return round(score, 1)


# ─── CLI argument parsing ────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay the PowerScore blend with different weights using live or demo data.",
    )
    parser.add_argument(
        "team_ids",
        nargs="*",
        help="Team UUIDs to fetch from Supabase rankings_full",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use hardcoded demo data instead of fetching from Supabase",
    )
    return parser.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()

    # Determine data source
    if not args.demo and not args.team_ids:
        print("No team IDs provided. Use --demo for hardcoded data or pass team UUIDs.")
        print("Usage:")
        print("  python scripts/rankings_weight_simulator.py <uuid1> <uuid2> ...")
        print("  python scripts/rankings_weight_simulator.py --demo")
        sys.exit(1)

    if args.demo:
        TEAMS = DEMO_TEAMS
        score_ranking_quality = score_ranking_quality_demo
        data_label = "Demo Data (AZ U12 Male Top 10)"
    else:
        TEAMS = load_teams_from_supabase(args.team_ids)
        score_ranking_quality = score_ranking_quality_live
        data_label = f"Live Data ({len(TEAMS)} teams from Supabase)"

    print("\n" + "=" * 90)
    print(f"  PitchRank Weight Simulator — {data_label}")
    print("  EXHAUSTIVE GRID SEARCH: All Levers")
    print("=" * 90)

    # =====================================================================
    # SECTION 1: Current production baseline (updated 2026-03-17)
    # =====================================================================
    PROD_OFF = 0.20
    PROD_DEF = 0.20
    PROD_SOS = 0.60
    PROD_PERF = 0.00
    PROD_ML = 0.08
    print_results(
        "CURRENT PRODUCTION (60/20/20, PERF=0, ML=0.08)",
        off_w=PROD_OFF, def_w=PROD_DEF, sos_w=PROD_SOS, perf_w=PROD_PERF, ml_alpha=PROD_ML,
    )
    baseline_results = simulate(PROD_OFF, PROD_DEF, PROD_SOS, PROD_PERF, PROD_ML)
    baseline_score = score_ranking_quality(baseline_results)
    max_quality = 23 if is_demo else 10
    print(f"\n  Quality Score: {baseline_score}/{max_quality}")

    # =====================================================================
    # SECTION 2: EXHAUSTIVE GRID SEARCH
    # Sweep ALL levers: SOS weight, PERF weight, PERF cap, ML alpha,
    # SOS-weighted PERF toggle, and OFF/DEF balance.
    # =====================================================================
    print("\n" + "=" * 90)
    print("  EXHAUSTIVE GRID SEARCH")
    print("  6 levers: SOS_W, OFF/DEF split, PERF_W, PERF_CAP, ML_ALPHA, SOS-weighted PERF")
    print("=" * 90)

    all_results = []

    # Parameter ranges — expanded with asymmetric OFF/DEF and finer SOS granularity
    sos_weights = [0.40, 0.45, 0.50, 0.55, 0.58, 0.60, 0.62, 0.65, 0.68, 0.70, 0.75]
    off_def_ratios = [0.50]  # equal OFF/DEF only (user constraint)
    perf_weights = [0.00, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15]
    perf_caps = [0.15, 0.20, 0.25, 0.35, 0.50]
    ml_alphas = [0.08, 0.10, 0.12, 0.15, 0.18]
    sos_perf_modes = [False, True]

    total_combos = (len(sos_weights) * len(off_def_ratios) * len(perf_weights)
                    * len(perf_caps) * len(ml_alphas) * len(sos_perf_modes))
    print(f"\n  Searching {total_combos:,} combinations...\n")

    for sos_w in sos_weights:
        for od_ratio in off_def_ratios:
            remaining = 1.0 - sos_w
            off_w = remaining * od_ratio
            def_w = remaining * (1.0 - od_ratio)
            for perf_w in perf_weights:
                for cap in perf_caps:
                    for ml_a in ml_alphas:
                        for sos_perf in sos_perf_modes:
                            results = simulate(off_w, def_w, sos_w, perf_w, ml_a,
                                               sos_weighted_perf=sos_perf, perf_cap=cap)
                            quality = score_ranking_quality(results)

                            # In demo mode, track Elite rank; in live mode, track #1
                            top_rank_name = results[0]["name"] if results else "?"
                            top_score = results[0]["ps_ml"] if results else 0

                            all_results.append({
                                "off_w": round(off_w, 3),
                                "def_w": round(def_w, 3),
                                "sos_w": sos_w,
                                "perf_w": perf_w,
                                "perf_cap": cap,
                                "ml_alpha": ml_a,
                                "sos_perf": sos_perf,
                                "top_name": top_rank_name,
                                "top_score": top_score,
                                "quality": quality,
                                "results": results,
                            })

    # Sort by quality score descending
    all_results.sort(key=lambda x: -x["quality"])

    # =====================================================================
    # SECTION 3: TOP 30 COMBINATIONS BY QUALITY SCORE
    # =====================================================================
    print("=" * 110)
    print("  TOP 30 COMBINATIONS (sorted by quality score)")
    print("=" * 110)
    print(f"  {'#':>3} {'Q':>4} {'#1':>3} {'SOS_W':>6} {'OFF':>6} {'DEF':>6} {'PERF_W':>7} {'CAP':>5} "
          f"{'ML_A':>6} {'SOS-P':>5}  {'Top 3 teams':<50}")
    print(f"  {'-'*3} {'-'*4} {'-'*3} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*5} "
          f"{'-'*6} {'-'*5}  {'-'*50}")

    seen = set()
    shown = 0
    for entry in all_results:
        # Deduplicate by ranking order (some param combos produce identical rankings)
        order_key = tuple(r["name"] for r in entry["results"])
        if order_key in seen:
            continue
        seen.add(order_key)

        top3 = ", ".join(r["name"][:20] for r in entry["results"][:3])
        sp = "Y" if entry["sos_perf"] else "N"
        print(
            f"  {shown+1:>3} {entry['quality']:>4.0f} {'1':>3} "
            f"{entry['sos_w']:>6.2f} {entry['off_w']:>6.3f} {entry['def_w']:>6.3f} "
            f"{entry['perf_w']:>7.02f} {entry['perf_cap']:>5.2f} {entry['ml_alpha']:>6.2f} "
            f"{sp:>5}  {top3:<50}"
        )
        shown += 1
        if shown >= 30:
            break

    # =====================================================================
    # SECTION 4: #1 STABILITY — all combos where the same team leads
    # =====================================================================
    # Find the most common #1 team across all configs
    from collections import Counter
    top1_counts = Counter(e["top_name"] for e in all_results)
    most_common_top1, _ = top1_counts.most_common(1)[0]

    top1_stable = [e for e in all_results if e["top_name"] == most_common_top1]
    print(f"\n{'=' * 110}")
    print(f"  COMBINATIONS WHERE '{most_common_top1[:30]}' = #1  ({len(top1_stable)} of {len(all_results)})")
    print(f"{'=' * 110}")

    if top1_stable:
        print(f"  {'Q':>4} {'SOS_W':>6} {'OFF':>6} {'DEF':>6} {'PERF_W':>7} {'CAP':>5} "
              f"{'ML_A':>6} {'SOS-P':>5}  {'#2 team':<25} {'Gap':>6}")
        print(f"  {'-'*4} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*5} "
              f"{'-'*6} {'-'*5}  {'-'*25} {'-'*6}")

        seen_s = set()
        shown_s = 0
        for entry in top1_stable:
            order_key = tuple(r["name"] for r in entry["results"][:3])
            if order_key in seen_s:
                continue
            seen_s.add(order_key)

            r2 = entry["results"][1] if len(entry["results"]) > 1 else {"name": "?", "ps_ml": 0}
            gap = entry["results"][0]["ps_ml"] - r2["ps_ml"]
            sp = "Y" if entry["sos_perf"] else "N"
            print(
                f"  {entry['quality']:>4.0f} {entry['sos_w']:>6.2f} {entry['off_w']:>6.3f} "
                f"{entry['def_w']:>6.3f} {entry['perf_w']:>7.02f} {entry['perf_cap']:>5.2f} "
                f"{entry['ml_alpha']:>6.2f} {sp:>5}  {r2['name'][:25]:<25} {gap:>6.4f}"
            )
            shown_s += 1
            if shown_s >= 30:
                break

    # =====================================================================
    # SECTION 5: BEST OVERALL PICK — print full rankings for top candidates
    # =====================================================================
    print(f"\n{'=' * 90}")
    print(f"  DETAILED VIEW: Top 5 unique ranking orders by quality score")
    print(f"{'=' * 90}")

    seen_detail = set()
    detail_count = 0
    for entry in all_results:
        order_key = tuple(r["name"] for r in entry["results"])
        if order_key in seen_detail:
            continue
        seen_detail.add(order_key)

        sp_label = "SOS-weighted" if entry["sos_perf"] else "raw"
        cap_label = f"cap=+/-{entry['perf_cap']}" if entry["perf_cap"] < 0.50 else "no cap"
        label = (f"CANDIDATE #{detail_count+1} (Quality={entry['quality']}/{max_quality}): "
                 f"SOS={entry['sos_w']}, PERF={entry['perf_w']} ({sp_label}, {cap_label}), "
                 f"ML={entry['ml_alpha']}")
        print_results(label, entry["off_w"], entry["def_w"], entry["sos_w"],
                      entry["perf_w"], entry["ml_alpha"], entry["sos_perf"], entry["perf_cap"])
        print(f"  Quality: {entry['quality']}/{max_quality} | #1: {entry['top_name'][:30]}")

        detail_count += 1
        if detail_count >= 5:
            break

    # =====================================================================
    # SECTION 6: SENSITIVITY ANALYSIS — how far is current from optimal?
    # =====================================================================
    print(f"\n{'=' * 90}")
    print("  SENSITIVITY: Current production vs best candidate")
    print(f"{'=' * 90}")

    best = all_results[0]
    print(f"\n  {'Parameter':<20} {'Current':>10} {'Optimal':>10} {'Delta':>10}")
    print(f"  {'-'*20} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'SOS_WEIGHT':<20} {PROD_SOS:>10.2f} {best['sos_w']:>10.2f} {best['sos_w'] - PROD_SOS:>+10.2f}")
    print(f"  {'OFF_WEIGHT':<20} {PROD_OFF:>10.3f} {best['off_w']:>10.3f} {best['off_w'] - PROD_OFF:>+10.3f}")
    print(f"  {'DEF_WEIGHT':<20} {PROD_DEF:>10.3f} {best['def_w']:>10.3f} {best['def_w'] - PROD_DEF:>+10.3f}")
    print(f"  {'PERF_BLEND_WEIGHT':<20} {PROD_PERF:>10.02f} {best['perf_w']:>10.02f} {best['perf_w'] - PROD_PERF:>+10.02f}")
    print(f"  {'PERF_CAP':<20} {'0.15':>10} {best['perf_cap']:>10.2f} {best['perf_cap'] - 0.15:>+10.2f}")
    print(f"  {'ML_ALPHA':<20} {PROD_ML:>10.2f} {best['ml_alpha']:>10.2f} {best['ml_alpha'] - PROD_ML:>+10.2f}")
    sp_cur = "No"
    sp_best = "Yes" if best["sos_perf"] else "No"
    print(f"  {'SOS_WEIGHTED_PERF':<20} {sp_cur:>10} {sp_best:>10} {'CHANGE' if sp_cur != sp_best else 'same':>10}")

    # Find the current production config in the grid results
    prod_in_grid = [e for e in all_results
                    if abs(e['sos_w'] - PROD_SOS) < 0.01
                    and abs(e['off_w'] - PROD_OFF) < 0.01
                    and abs(e['perf_w'] - PROD_PERF) < 0.01
                    and abs(e['ml_alpha'] - PROD_ML) < 0.01]
    prod_grid_score = prod_in_grid[0]['quality'] if prod_in_grid else baseline_score
    prod_top1 = prod_in_grid[0]['top_name'] if prod_in_grid else "?"

    print(f"\n  Quality: {prod_grid_score}/{max_quality} -> {best['quality']}/{max_quality}")
    print(f"  #1 team: {prod_top1[:30]} -> {best['top_name'][:30]}")

    print("\n")
