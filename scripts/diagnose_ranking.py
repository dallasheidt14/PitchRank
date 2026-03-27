#!/usr/bin/env python3
"""
Diagnose why a team is or isn't #1 in their cohort.

Cross-references ranking output against the v53e algorithm design to verify
the engine is producing results consistent with its documented behavior.

Usage:
    python scripts/diagnose_ranking.py <team_uuid> [<team_uuid> ...]

Example:
    python scripts/diagnose_ranking.py 691eb36d-95b2-4a08-bd59-13c1b0e830bb
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.rankings.constants import AGE_TO_ANCHOR, SOS_ML_THRESHOLD_HIGH, SOS_ML_THRESHOLD_LOW
from src.rankings.shared import sos_ml_blend
from supabase import create_client

load_dotenv()
console = Console()

# ─── Algorithm constants (from V53EConfig + Layer13Config) ───────────────────
# Shared constants imported from src.rankings.constants; local values are
# script-specific and not duplicated elsewhere.
ALGORITHM = {
    "OFF_WEIGHT": 0.20,
    "DEF_WEIGHT": 0.20,
    "SOS_WEIGHT": 0.60,
    "GOAL_DIFF_CAP": 6,
    "ML_ALPHA": 0.08,
    "SOS_ML_THRESHOLD_LOW": SOS_ML_THRESHOLD_LOW,
    "SOS_ML_THRESHOLD_HIGH": SOS_ML_THRESHOLD_HIGH,
    "MIN_GAMES_PROVISIONAL": 6,
    "PERF_BLEND_WEIGHT": 0.00,  # Performance layer disabled in final score
    "SHRINK_TAU": 8.0,
    "RECENCY_DECAY_RATE": 0.08,
    "UNRANKED_SOS_BASE": 0.35,
    "ANCHORS": AGE_TO_ANCHOR,
}

# Metric columns to fetch from rankings_full
METRIC_COLS = [
    "team_id",
    "age_group",
    "gender",
    "state_code",
    "status",
    "games_played",
    "wins",
    "losses",
    "draws",
    "goals_for",
    "goals_against",
    "win_percentage",
    "games_last_180_days",
    "last_game",
    "sample_flag",
    # Offense/Defense
    "off_raw",
    "sad_raw",
    "off_shrunk",
    "sad_shrunk",
    "def_shrunk",
    "off_norm",
    "def_norm",
    # SOS
    "sos",
    "sos_norm",
    "sos_raw",
    "sos_norm_national",
    "sos_norm_state",
    "sos_rank_national",
    "sos_rank_state",
    # Performance
    "perf_raw",
    "perf_centered",
    # Power scores (layer by layer)
    "power_presos",
    "powerscore_core",
    "provisional_mult",
    "powerscore_adj",
    "anchor",
    "abs_strength",
    # ML Layer
    "ml_overperf",
    "ml_norm",
    "powerscore_ml",
    # Final scores
    "national_power_score",
    "power_score_final",
    # Ranks
    "rank_in_cohort",
    "rank_in_cohort_ml",
    "national_rank",
    "state_rank",
    "rank_change_7d",
    "rank_change_30d",
    "last_calculated",
]

LAYER_BREAKDOWN = [
    ("Record", ["games_played", "wins", "losses", "draws", "win_percentage"]),
    ("Offense (Layers 2-5,7,9)", ["off_raw", "off_shrunk", "off_norm"]),
    ("Defense (Layers 2-5,7,9)", ["sad_raw", "sad_shrunk", "def_shrunk", "def_norm"]),
    ("SOS (Layer 8)", ["sos", "sos_norm", "sos_norm_national", "sos_rank_national"]),
    ("Performance (Layer 6)", ["perf_raw", "perf_centered"]),
    ("Pre-ML Score (Layer 10)", ["power_presos", "powerscore_core", "provisional_mult", "powerscore_adj"]),
    ("ML Layer 13", ["ml_overperf", "ml_norm", "powerscore_ml"]),
    ("Final (anchor-scaled)", ["power_score_final", "national_power_score", "anchor", "national_rank", "state_rank"]),
]


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        console.print("[red]Missing SUPABASE_URL or SUPABASE_KEY in .env[/red]")
        sys.exit(1)
    return create_client(url, key)


def fetch_team_name(supabase, team_id: str) -> str:
    result = (
        supabase.table("teams")
        .select("team_name, club_name, age_group, gender, state_code")
        .eq("team_id_master", team_id)
        .execute()
    )
    if result.data:
        r = result.data[0]
        return f"{r.get('team_name', '?')} ({r.get('club_name', '')}) — {r.get('age_group', '?')} {r.get('gender', '?')}, {r.get('state_code', '?')}"
    return f"Unknown ({team_id[:8]}...)"


def fetch_team_ranking(supabase, team_id: str) -> dict | None:
    cols = ", ".join(METRIC_COLS)
    result = supabase.table("rankings_full").select(cols).eq("team_id", team_id).execute()
    return result.data[0] if result.data else None


def fetch_cohort_top(supabase, age_group: str, gender: str, limit: int = 10) -> list:
    cols = ", ".join(METRIC_COLS)
    result = (
        supabase.table("rankings_full")
        .select(cols)
        .eq("age_group", age_group)
        .eq("gender", gender)
        .eq("status", "Active")
        .order("power_score_final", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def fetch_cohort_stats(supabase, age_group: str, gender: str) -> dict:
    """Fetch cohort-wide stats for context (total teams, score ranges)."""
    result = (
        supabase.table("rankings_full")
        .select("team_id, power_score_final, powerscore_adj, sos_norm, status")
        .eq("age_group", age_group)
        .eq("gender", gender)
        .eq("status", "Active")
        .execute()
    )
    rows = result.data or []
    if not rows:
        return {}
    scores = [r["power_score_final"] for r in rows if r.get("power_score_final") is not None]
    sos_vals = [r["sos_norm"] for r in rows if r.get("sos_norm") is not None]
    return {
        "total_active": len(rows),
        "score_min": min(scores) if scores else 0,
        "score_max": max(scores) if scores else 0,
        "score_mean": sum(scores) / len(scores) if scores else 0,
        "sos_mean": sum(sos_vals) / len(sos_vals) if sos_vals else 0,
    }


def fetch_team_games(supabase, team_id: str, limit: int = 15) -> list:
    result = (
        supabase.table("games")
        .select("game_date, home_team_master_id, away_team_master_id, home_score, away_score")
        .or_(f"home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}")
        .order("game_date", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def fetch_opponent_rankings(supabase, opponent_ids: list) -> dict:
    """Fetch power_score_final for a batch of opponents to show schedule quality."""
    if not opponent_ids:
        return {}
    rankings = {}
    batch_size = 100
    for i in range(0, len(opponent_ids), batch_size):
        batch = opponent_ids[i : i + batch_size]
        result = (
            supabase.table("rankings_full")
            .select("team_id, power_score_final, powerscore_adj, status, national_rank, age_group, gender")
            .in_("team_id", batch)
            .execute()
        )
        for r in result.data or []:
            rankings[r["team_id"]] = r
    return rankings


def fmt(val, decimals=3) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def arrow(team_val, top_val) -> str:
    if team_val is None or top_val is None:
        return ""
    try:
        diff = float(team_val) - float(top_val)
    except (ValueError, TypeError):
        return ""
    if abs(diff) < 0.001:
        return "  ="
    return f" [green]▲{diff:+.3f}[/green]" if diff > 0 else f" [red]▼{diff:+.3f}[/red]"


# ─── Algorithm Validation ────────────────────────────────────────────────────


def validate_algorithm(team: dict, cohort_stats: dict) -> list:
    """
    Check ranking output against v53e algorithm invariants.
    Returns list of (severity, message) tuples.
    severity: 'OK', 'WARN', 'FAIL'
    """
    checks = []

    # --- PowerScore bounds [0.0, 1.0] ---
    for col in ["powerscore_core", "powerscore_adj", "powerscore_ml", "power_score_final", "national_power_score"]:
        val = team.get(col)
        if val is not None:
            if val < 0.0 or val > 1.0:
                checks.append(("FAIL", f"{col} = {val:.4f} is OUT OF BOUNDS [0.0, 1.0]"))
            elif val != val:  # NaN check
                checks.append(("FAIL", f"{col} is NaN"))

    # --- SOS norm should be [0.0, 1.0] ---
    sos_norm = team.get("sos_norm")
    if sos_norm is not None:
        if sos_norm < 0.0 or sos_norm > 1.0:
            checks.append(("FAIL", f"sos_norm = {sos_norm:.4f} is OUT OF BOUNDS"))

    # --- off_norm and def_norm should be [0.0, 1.0] ---
    for col in ["off_norm", "def_norm"]:
        val = team.get(col)
        if val is not None and (val < 0.0 or val > 1.0):
            checks.append(("WARN", f"{col} = {val:.4f} outside expected [0.0, 1.0]"))

    # --- PowerScore blend formula: core ≈ OFF*0.20 + DEF*0.20 + SOS*0.60 ---
    off_n = team.get("off_norm")
    def_n = team.get("def_norm")
    sos_n = team.get("sos_norm")
    ps_core = team.get("powerscore_core")
    if all(v is not None for v in [off_n, def_n, sos_n, ps_core]):
        expected_core = (
            off_n * ALGORITHM["OFF_WEIGHT"] + def_n * ALGORITHM["DEF_WEIGHT"] + sos_n * ALGORITHM["SOS_WEIGHT"]
        )
        diff = abs(ps_core - expected_core)
        if diff > 0.05:
            checks.append(
                (
                    "WARN",
                    f"powerscore_core ({ps_core:.4f}) differs from expected "
                    f"OFF*0.20 + DEF*0.20 + SOS*0.60 = {expected_core:.4f} by {diff:.4f}. "
                    f"May indicate hybrid SOS norm or rounding.",
                )
            )
        else:
            checks.append(("OK", f"PowerScore blend verified: {ps_core:.4f} ≈ {expected_core:.4f} (diff {diff:.4f})"))

    # --- Provisional multiplier ---
    gp = team.get("games_played") or 0
    prov = team.get("provisional_mult")
    if prov is not None:
        if gp < ALGORITHM["MIN_GAMES_PROVISIONAL"] and prov >= 1.0:
            checks.append(("WARN", f"Team has {gp} games but provisional_mult = {prov:.2f} (expected < 1.0)"))
        elif gp >= 15 and prov < 1.0:
            checks.append(("WARN", f"Team has {gp} games but provisional_mult = {prov:.2f} (expected 1.0)"))
        else:
            checks.append(("OK", f"Provisional multiplier {prov:.3f} correct for {gp} games"))

    # --- ML blend: powerscore_ml ≈ powerscore_adj + alpha * ml_norm ---
    ps_adj = team.get("powerscore_adj")
    ml_norm = team.get("ml_norm")
    ps_ml = team.get("powerscore_ml")
    if all(v is not None for v in [ps_adj, ml_norm, ps_ml]):
        expected_ml = min(1.0, max(0.0, ps_adj + ALGORITHM["ML_ALPHA"] * ml_norm))
        diff = abs(ps_ml - expected_ml)
        if diff > 0.02:
            checks.append(
                (
                    "WARN",
                    f"powerscore_ml ({ps_ml:.4f}) differs from expected "
                    f"adj + 0.08 * ml_norm = {expected_ml:.4f} by {diff:.4f}. "
                    f"May be SOS-conditioned scaling (weak SOS dampens ML authority).",
                )
            )
        else:
            checks.append(("OK", f"ML blend verified: {ps_ml:.4f} ≈ {expected_ml:.4f}"))

    # --- SOS-conditioned ML scaling ---
    if sos_n is not None and ml_norm is not None and ps_adj is not None and ps_ml is not None:
        if sos_n < SOS_ML_THRESHOLD_LOW:
            # ML should have NO authority — powerscore_ml should equal powerscore_adj
            if abs(ps_ml - ps_adj) > 0.005:
                checks.append(
                    (
                        "WARN",
                        f"SOS={sos_n:.3f} is below {SOS_ML_THRESHOLD_LOW} threshold — "
                        f"ML should have no authority, but ps_ml ({ps_ml:.4f}) ≠ ps_adj ({ps_adj:.4f})",
                    )
                )
            else:
                checks.append(("OK", f"ML correctly suppressed for weak SOS ({sos_n:.3f})"))
        elif sos_n >= SOS_ML_THRESHOLD_HIGH:
            checks.append(("OK", f"ML has full authority — SOS ({sos_n:.3f}) above threshold"))
        else:
            scale = (sos_n - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)
            checks.append(("OK", f"ML partial authority ({scale:.0%}) — SOS ({sos_n:.3f}) in transition zone"))

    # --- Age anchor scaling ---
    age_str = team.get("age_group", "")
    try:
        age_num = int(age_str.replace("u", "").replace("U", ""))
    except (ValueError, TypeError):
        age_num = None
    if age_num and age_num in ALGORITHM["ANCHORS"]:
        expected_anchor = ALGORITHM["ANCHORS"][age_num]
        ps_final = team.get("power_score_final")
        if ps_final is not None and ps_final > expected_anchor + 0.001:
            checks.append(
                (
                    "FAIL",
                    f"power_score_final ({ps_final:.4f}) exceeds age anchor ceiling "
                    f"({expected_anchor:.3f} for {age_str})",
                )
            )
        elif ps_final is not None:
            checks.append(("OK", f"Final score ({ps_final:.4f}) within anchor ceiling ({expected_anchor:.3f})"))

    # --- Performance layer should be disabled (PERF_BLEND_WEIGHT = 0.00) ---
    perf = team.get("perf_centered")
    if perf is not None and abs(perf) > 0.001:
        checks.append(("OK", f"perf_centered = {perf:.4f} (computed but NOT blended — PERF_BLEND_WEIGHT=0.00)"))

    # --- Bayesian shrinkage: low-sample teams should have shrunk offense/defense ---
    if gp is not None and gp < ALGORITHM["SHRINK_TAU"]:
        off_raw = team.get("off_raw")
        off_shrunk = team.get("off_shrunk")
        if off_raw is not None and off_shrunk is not None:
            if abs(off_raw - off_shrunk) < 0.001:
                checks.append(
                    (
                        "WARN",
                        f"Team has only {gp} games but off_raw ≈ off_shrunk — "
                        f"Bayesian shrinkage may not be applying (tau={ALGORITHM['SHRINK_TAU']})",
                    )
                )
            else:
                checks.append(
                    (
                        "OK",
                        f"Bayesian shrinkage active: off_raw={off_raw:.3f} → off_shrunk={off_shrunk:.3f} "
                        f"({gp} games, tau={ALGORITHM['SHRINK_TAU']})",
                    )
                )

    # --- Win percentage sanity ---
    wins = team.get("wins") or 0
    losses = team.get("losses") or 0
    draws = team.get("draws") or 0
    wp = team.get("win_percentage")
    if gp and gp > 0 and wp is not None:
        expected_wp = (wins / gp) * 100
        if abs(wp - expected_wp) > 1.0:
            checks.append(("WARN", f"win_percentage ({wp:.1f}%) doesn't match W/GP ({expected_wp:.1f}%)"))

    # --- Status consistency ---
    if status := team.get("status"):
        if status == "Active" and gp < ALGORITHM["MIN_GAMES_PROVISIONAL"]:
            checks.append(
                ("WARN", f"Status is 'Active' but only {gp} games (threshold={ALGORITHM['MIN_GAMES_PROVISIONAL']})")
            )

    return checks


# ─── Accurate Simulator (mirrors v53e + Layer 13 exactly) ────────────────────


def simulate_powerscore(
    off_norm: float, def_norm: float, sos_norm: float, games_played: int, ml_norm: float, age_num: int
) -> dict:
    """
    Reproduce the full v53e → ML → anchor pipeline from normalized components.
    This matches the actual engine — no shortcuts, no display multipliers.

    Returns dict with every intermediate value for transparency.
    """
    # Layer 10: PowerScore blend (OFF:0.20, DEF:0.20, SOS:0.60)
    # Note: PERF_BLEND_WEIGHT = 0.00, so performance is NOT in the blend
    ps_core = (
        off_norm * ALGORITHM["OFF_WEIGHT"] + def_norm * ALGORITHM["DEF_WEIGHT"] + sos_norm * ALGORITHM["SOS_WEIGHT"]
    )

    # Provisional multiplier: linear ramp 0.85 → 1.0 over 0-15 games
    max_gp = 15
    if games_played >= max_gp:
        prov = 1.0
    elif games_played <= 0:
        prov = 0.85
    else:
        prov = 0.85 + (games_played / max_gp) * 0.15

    ps_adj = min(1.0, max(0.0, ps_core * prov))

    # ML Layer 13: additive blend with SOS-conditioned scaling
    ml_delta = ALGORITHM["ML_ALPHA"] * ml_norm
    ps_ml_raw = ps_adj + ml_delta
    ps_ml = sos_ml_blend(ps_adj, ps_ml_raw, sos_norm)
    ml_scale = max(
        0.0,
        min(1.0, (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)),
    )

    # Age anchor scaling: final = ps_ml * anchor, capped at anchor
    anchor = ALGORITHM["ANCHORS"].get(age_num, 1.0)
    ps_final = min(anchor, ps_ml * anchor)

    return {
        "ps_core": round(ps_core, 6),
        "prov": round(prov, 4),
        "ps_adj": round(ps_adj, 6),
        "ml_delta": round(ml_delta, 6),
        "ml_scale": round(ml_scale, 4),
        "ps_ml": round(ps_ml, 6),
        "anchor": anchor,
        "ps_final": round(ps_final, 6),
    }


def simulate_what_if(team: dict, top1: dict, cohort_top: list) -> list:
    """
    Generate concrete "what-if" scenarios showing what metric changes
    would move this team to #1.

    Returns list of (scenario_name, description, simulated_final, would_be_rank) tuples.
    """
    age_str = team.get("age_group", "u14")
    try:
        age_num = int(age_str.replace("u", "").replace("U", ""))
    except (ValueError, TypeError):
        age_num = 14

    target_final = top1.get("power_score_final", 0)
    team_off = team.get("off_norm") or 0.5
    team_def = team.get("def_norm") or 0.5
    team_sos = team.get("sos_norm") or 0.5
    team_gp = team.get("games_played") or 0
    team_ml = team.get("ml_norm") or 0.0

    # Build cohort finals for ranking
    cohort_finals = []
    for t in cohort_top:
        tid = t.get("team_id")
        pf = t.get("power_score_final") or 0
        cohort_finals.append((tid, pf))

    def sim_rank(ps_final):
        """What rank would this final score achieve in the cohort?"""
        rank = 1
        for _, pf in cohort_finals:
            if pf > ps_final:
                rank += 1
        return rank

    scenarios = []

    # Scenario 1: Current (baseline)
    current = simulate_powerscore(team_off, team_def, team_sos, team_gp, team_ml, age_num)
    scenarios.append(("Current", "No changes", current["ps_final"], sim_rank(current["ps_final"])))

    # Scenario 2: Max out SOS (play the toughest schedule possible)
    s = simulate_powerscore(team_off, team_def, 1.0, team_gp, team_ml, age_num)
    scenarios.append(
        ("Max SOS", "sos_norm → 1.000 (hardest schedule in cohort)", s["ps_final"], sim_rank(s["ps_final"]))
    )

    # Scenario 3: Max out offense
    s = simulate_powerscore(1.0, team_def, team_sos, team_gp, team_ml, age_num)
    scenarios.append(
        ("Max Offense", "off_norm → 1.000 (best scoring in cohort)", s["ps_final"], sim_rank(s["ps_final"]))
    )

    # Scenario 4: Max out defense
    s = simulate_powerscore(team_off, 1.0, team_sos, team_gp, team_ml, age_num)
    scenarios.append(
        ("Max Defense", "def_norm → 1.000 (best defense in cohort)", s["ps_final"], sim_rank(s["ps_final"]))
    )

    # Scenario 5: Match #1's exact metrics
    top_off = top1.get("off_norm") or 0.5
    top_def = top1.get("def_norm") or 0.5
    top_sos = top1.get("sos_norm") or 0.5
    top_gp = top1.get("games_played") or 30
    top_ml = top1.get("ml_norm") or 0.0
    s = simulate_powerscore(top_off, top_def, top_sos, top_gp, top_ml, age_num)
    scenarios.append(
        ("Clone #1's metrics", f"Copy all normalized values from #1", s["ps_final"], sim_rank(s["ps_final"]))
    )

    # Scenario 6: Improve SOS to match #1's SOS only
    s = simulate_powerscore(team_off, team_def, top_sos, team_gp, team_ml, age_num)
    scenarios.append(
        ("Match #1's SOS", f"sos_norm → {top_sos:.3f} (keep everything else)", s["ps_final"], sim_rank(s["ps_final"]))
    )

    # Scenario 7: Best realistic improvement (+10% on weakest metric)
    weakest_metric = min([("off", team_off), ("def", team_def), ("sos", team_sos)], key=lambda x: x[1])
    boosted = min(1.0, weakest_metric[1] + 0.10)
    off_b = boosted if weakest_metric[0] == "off" else team_off
    def_b = boosted if weakest_metric[0] == "def" else team_def
    sos_b = boosted if weakest_metric[0] == "sos" else team_sos
    s = simulate_powerscore(off_b, def_b, sos_b, team_gp, team_ml, age_num)
    scenarios.append(
        (
            f"Boost weakest ({weakest_metric[0]})",
            f"{weakest_metric[0]}_norm {weakest_metric[1]:.3f} → {boosted:.3f} (+0.100)",
            s["ps_final"],
            sim_rank(s["ps_final"]),
        )
    )

    # Scenario 8: More games (if provisional penalty applies)
    if team_gp < 15:
        s = simulate_powerscore(team_off, team_def, team_sos, 30, team_ml, age_num)
        scenarios.append(
            (
                "Full season (30 GP)",
                f"games_played {team_gp} → 30 (removes provisional penalty)",
                s["ps_final"],
                sim_rank(s["ps_final"]),
            )
        )

    # Scenario 9: ML boost (strong recent form)
    better_ml = min(0.5, team_ml + 0.20)
    s = simulate_powerscore(team_off, team_def, team_sos, team_gp, better_ml, age_num)
    scenarios.append(
        (
            "Strong ML form",
            f"ml_norm {team_ml:+.3f} → {better_ml:+.3f} (beat expectations recently)",
            s["ps_final"],
            sim_rank(s["ps_final"]),
        )
    )

    # Scenario 10: Find minimum SOS needed to reach #1
    # Binary search for the SOS that makes ps_final >= target
    lo, hi = team_sos, 1.0
    needed_sos = None
    for _ in range(50):
        mid = (lo + hi) / 2
        s = simulate_powerscore(team_off, team_def, mid, team_gp, team_ml, age_num)
        if s["ps_final"] >= target_final:
            needed_sos = mid
            hi = mid
        else:
            lo = mid
    if needed_sos is not None and needed_sos <= 1.0:
        s = simulate_powerscore(team_off, team_def, needed_sos, team_gp, team_ml, age_num)
        scenarios.append(
            (
                "Min SOS for #1",
                f"sos_norm needs to reach {needed_sos:.3f} (currently {team_sos:.3f})",
                s["ps_final"],
                sim_rank(s["ps_final"]),
            )
        )
    else:
        # SOS alone can't do it — find combo
        scenarios.append(
            (
                "Min SOS for #1",
                "SOS alone cannot close the gap — need offense/defense improvement too",
                current["ps_final"],
                sim_rank(current["ps_final"]),
            )
        )

    return scenarios


def explain_ranking_position(team: dict, top1: dict, cohort_stats: dict) -> list:
    """
    Plain-English explanation of why a team is or isn't #1.
    Uses the algorithm's documented weight formula to attribute the gap.
    """
    explanations = []

    ps_final_team = team.get("power_score_final") or 0
    ps_final_top = top1.get("power_score_final") or 0
    gap = ps_final_top - ps_final_team

    if gap <= 0:
        return ["This team has the highest power_score_final in the cohort."]

    # Decompose the gap through the formula layers
    # Final score comes from: anchor * (ps_adj + SOS-scaled ML delta)
    # ps_adj comes from: ps_core * provisional_mult (approximately)
    # ps_core ≈ OFF*0.20 + DEF*0.20 + SOS*0.60

    off_gap = (top1.get("off_norm") or 0) - (team.get("off_norm") or 0)
    def_gap = (top1.get("def_norm") or 0) - (team.get("def_norm") or 0)
    sos_gap = (top1.get("sos_norm") or 0) - (team.get("sos_norm") or 0)

    # Weighted contribution to the gap
    off_contrib = off_gap * ALGORITHM["OFF_WEIGHT"]
    def_contrib = def_gap * ALGORITHM["DEF_WEIGHT"]
    sos_contrib = sos_gap * ALGORITHM["SOS_WEIGHT"]

    total_contrib = off_contrib + def_contrib + sos_contrib

    explanations.append(f"Total gap to #1: {gap:.4f} in power_score_final")
    explanations.append("")
    explanations.append("Gap decomposition (pre-ML, by algorithm weight):")

    components = [
        ("SOS (60% weight)", sos_contrib, sos_gap),
        ("Offense (20% weight)", off_contrib, off_gap),
        ("Defense (20% weight)", def_contrib, def_gap),
    ]
    components.sort(key=lambda x: abs(x[1]), reverse=True)

    for label, contrib, raw_gap in components:
        if abs(contrib) < 0.0001:
            explanations.append(f"  {label}: negligible")
        else:
            direction = "hurting" if contrib > 0 else "helping"
            explanations.append(f"  {label}: {contrib:+.4f} ({direction}) — raw gap: {raw_gap:+.4f}")

    # ML impact
    ml_team = team.get("ml_norm") or 0
    ml_top = top1.get("ml_norm") or 0
    ml_gap = (ml_top - ml_team) * ALGORITHM["ML_ALPHA"]
    if abs(ml_gap) > 0.001:
        direction = "hurting" if ml_gap > 0 else "helping"
        explanations.append(f"  ML Layer ({direction}): {ml_gap:+.4f} (ml_norm gap: {ml_top - ml_team:+.4f})")

    # Provisional impact
    prov_team = team.get("provisional_mult") or 1.0
    prov_top = top1.get("provisional_mult") or 1.0
    if prov_team < prov_top:
        explanations.append(
            f"  Provisional penalty: your mult={prov_team:.3f} vs #1={prov_top:.3f} (you have fewer games)"
        )

    # The biggest factor
    explanations.append("")
    biggest = max(components, key=lambda x: abs(x[1]))
    if abs(biggest[1]) > abs(ml_gap):
        explanations.append(f"PRIMARY FACTOR: {biggest[0]} accounts for most of the gap")
    else:
        explanations.append("PRIMARY FACTOR: ML adjustment is the dominant differentiator")

    # Actionable insight
    explanations.append("")
    if sos_contrib > 0.01:
        explanations.append(
            "💡 INSIGHT: SOS is the biggest drag. The algorithm weights schedule strength at 60%. "
            "Playing stronger opponents (tournament teams, out-of-state competition) would help."
        )
    elif off_contrib > 0.01:
        explanations.append(
            "💡 INSIGHT: Offense is the gap. More decisive wins (larger margins) against similar opponents."
        )
    elif def_contrib > 0.01:
        explanations.append("💡 INSIGHT: Defense is the gap. Allowing fewer goals would improve the ranking.")
    elif ml_gap > 0.005:
        explanations.append(
            "💡 INSIGHT: The ML model favors #1 based on patterns in game features (power diff, recency). "
            "Recent form and beating higher-ranked opponents matter here."
        )

    return explanations


def diagnose_team(supabase, team_id: str):
    """Run full diagnostic for a single team."""
    team_name = fetch_team_name(supabase, team_id)
    console.print(Panel(f"[bold]{team_name}[/bold]\n{team_id}", title="Diagnosing Team"))

    team = fetch_team_ranking(supabase, team_id)
    if not team:
        console.print(f"[red]Team {team_id} not found in rankings_full. Not ranked yet or wrong ID.[/red]")
        return

    age_group = team.get("age_group")
    gender = team.get("gender")
    status = team.get("status", "Unknown")
    current_rank = team.get("national_rank") or team.get("rank_in_cohort_ml") or "?"

    console.print(
        f"  Cohort: [cyan]{age_group} {gender}[/cyan]  |  "
        f"Status: [cyan]{status}[/cyan]  |  "
        f"Rank: [bold yellow]#{current_rank}[/bold yellow]  |  "
        f"State: [cyan]{team.get('state_code', '?')}[/cyan]"
    )
    console.print(f"  Last calculated: {team.get('last_calculated', '?')}")
    console.print()

    # ── Algorithm Validation ──────────────────────────────────────────────
    console.print("[bold underline]Algorithm Validation[/bold underline]")
    cohort_stats = fetch_cohort_stats(supabase, age_group, gender)
    checks = validate_algorithm(team, cohort_stats)

    for severity, msg in checks:
        if severity == "OK":
            console.print(f"  [green]✓[/green] {msg}")
        elif severity == "WARN":
            console.print(f"  [yellow]⚠[/yellow] {msg}")
        elif severity == "FAIL":
            console.print(f"  [red]✗[/red] {msg}")
    console.print()

    if cohort_stats:
        console.print(
            f"  Cohort: {cohort_stats.get('total_active', '?')} active teams  |  "
            f"Score range: [{fmt(cohort_stats.get('score_min'), 4)} – {fmt(cohort_stats.get('score_max'), 4)}]  |  "
            f"Mean: {fmt(cohort_stats.get('score_mean'), 4)}"
        )
        console.print()

    # ── Cohort Top 10 ────────────────────────────────────────────────────
    top = fetch_cohort_top(supabase, age_group, gender, limit=10)
    if not top:
        console.print("[red]No active teams found in this cohort.[/red]")
        return

    top1 = top[0]
    top1_id = top1.get("team_id")
    top1_name = fetch_team_name(supabase, top1_id) if top1_id != team_id else team_name

    is_number_one = top1_id == team_id
    if is_number_one:
        console.print("[bold green]✅ This team IS #1 in their cohort![/bold green]")
    else:
        console.print(f"[bold red]❌ #1 is: {top1_name}[/bold red]")
    console.print()

    # ── Plain-English Explanation ─────────────────────────────────────────
    if not is_number_one:
        console.print("[bold underline]Why Not #1?[/bold underline]")
        explanations = explain_ranking_position(team, top1, cohort_stats)
        for line in explanations:
            console.print(f"  {line}")
        console.print()

    # ── Layer-by-Layer Comparison ─────────────────────────────────────────
    console.print("[bold underline]Layer-by-Layer Breakdown[/bold underline]")
    console.print()

    compare_to = top1 if not is_number_one else (top[1] if len(top) > 1 else None)
    compare_label = "#1" if not is_number_one else "#2"

    for layer_name, metrics in LAYER_BREAKDOWN:
        table = Table(title=layer_name, box=box.SIMPLE_HEAVY, show_header=True)
        table.add_column("Metric", style="dim", width=22)
        table.add_column("Your Team", justify="right", width=12)
        if compare_to:
            table.add_column(f"vs {compare_label}", justify="right", width=18)

        for col in metrics:
            team_val = team.get(col)
            row = [col, fmt(team_val)]
            if compare_to:
                cmp_val = compare_to.get(col)
                if "rank" in col and team_val is not None and cmp_val is not None:
                    diff_str = arrow(cmp_val, team_val)
                else:
                    diff_str = arrow(team_val, cmp_val)
                row.append(f"{fmt(cmp_val)}{diff_str}")
            table.add_row(*row)

        console.print(table)
        console.print()

    # ── Cohort Leaderboard ────────────────────────────────────────────────
    console.print("[bold underline]Cohort Top 10[/bold underline]")
    lb = Table(box=box.ROUNDED, show_header=True)
    lb.add_column("#", width=3)
    lb.add_column("Team", width=40)
    lb.add_column("State", width=5)
    lb.add_column("GP", justify="right", width=4)
    lb.add_column("W-L-D", justify="center", width=9)
    lb.add_column("SOS", justify="right", width=6)
    lb.add_column("PS_adj", justify="right", width=7)
    lb.add_column("PS_ml", justify="right", width=7)
    lb.add_column("Final", justify="right", width=7)

    for i, t in enumerate(top, 1):
        tid = t.get("team_id", "")
        name = fetch_team_name(supabase, tid)
        if len(name) > 40:
            name = name[:37] + "..."
        is_target = tid == team_id
        style = "bold yellow" if is_target else ""

        wld = f"{t.get('wins', 0)}-{t.get('losses', 0)}-{t.get('draws', 0)}"
        lb.add_row(
            str(i),
            name,
            t.get("state_code", "?"),
            str(t.get("games_played", 0)),
            wld,
            fmt(t.get("sos_norm"), 3),
            fmt(t.get("powerscore_adj"), 4),
            fmt(t.get("powerscore_ml"), 4),
            fmt(t.get("power_score_final"), 4),
            style=style,
        )
    console.print(lb)
    console.print()

    # ── Simulator: Path to #1 ────────────────────────────────────────────
    if not is_number_one:
        console.print("[bold underline]Simulator: Path to #1[/bold underline]")
        console.print("[dim]  Uses the exact v53e formula: core = OFF*0.20 + DEF*0.20 + SOS*0.60,[/dim]")
        console.print("[dim]  then provisional mult, SOS-conditioned ML blend, age anchor scaling.[/dim]")
        console.print()

        # First verify simulator matches actual output
        age_str = team.get("age_group", "u14")
        try:
            age_num = int(age_str.replace("u", "").replace("U", ""))
        except (ValueError, TypeError):
            age_num = 14

        current_sim = simulate_powerscore(
            team.get("off_norm") or 0.5,
            team.get("def_norm") or 0.5,
            team.get("sos_norm") or 0.5,
            team.get("games_played") or 0,
            team.get("ml_norm") or 0.0,
            age_num,
        )
        actual_final = team.get("power_score_final") or 0
        sim_diff = abs(current_sim["ps_final"] - actual_final)
        if sim_diff > 0.01:
            console.print(
                f"  [yellow]⚠ Simulator drift: simulated {current_sim['ps_final']:.4f} vs "
                f"actual {actual_final:.4f} (diff {sim_diff:.4f}). "
                f"Hybrid SOS norm or rounding may cause small differences.[/yellow]"
            )
        else:
            console.print(
                f"  [green]✓ Simulator accuracy: {current_sim['ps_final']:.4f} vs actual "
                f"{actual_final:.4f} (diff {sim_diff:.4f})[/green]"
            )
        console.print()

        scenarios = simulate_what_if(team, top1, top)
        st = Table(box=box.ROUNDED, show_header=True, title="What-If Scenarios")
        st.add_column("Scenario", width=24)
        st.add_column("Change", width=52)
        st.add_column("Simulated", justify="right", width=10)
        st.add_column("Rank", justify="right", width=5)

        for name, desc, ps_final, rank in scenarios:
            rank_str = f"#{rank}"
            if rank == 1:
                style = "bold green"
                rank_str = "[bold green]#1 ✓[/bold green]"
            elif rank <= 3:
                style = "yellow"
            else:
                style = ""
            st.add_row(name, desc, fmt(ps_final, 4), rank_str, style=style)

        console.print(st)

        # Summary: what's the easiest path?
        winning_scenarios = [(n, d, p, r) for n, d, p, r in scenarios if r == 1 and n != "Current"]
        if winning_scenarios:
            console.print()
            console.print("  [bold]Paths to #1:[/bold]")
            for name, desc, ps, _ in winning_scenarios:
                console.print(f"    [green]→[/green] {name}: {desc}")
        else:
            console.print()
            console.print("  [yellow]No single-metric change reaches #1. Multiple improvements needed.[/yellow]")
        console.print()

    # ── Biggest Gaps ──────────────────────────────────────────────────────
    if not is_number_one and compare_to:
        console.print("[bold underline]Biggest Gaps vs #1[/bold underline]")
        gaps = []
        key_metrics = [
            ("off_norm", "Offense"),
            ("def_norm", "Defense"),
            ("sos_norm", "SOS"),
            ("perf_centered", "Performance"),
            ("ml_norm", "ML Adjustment"),
            ("powerscore_adj", "PowerScore (pre-ML)"),
            ("power_score_final", "Final Score"),
        ]
        for col, label in key_metrics:
            tv, cv = team.get(col), compare_to.get(col)
            if tv is not None and cv is not None:
                try:
                    gaps.append((label, col, float(tv) - float(cv), tv, cv))
                except (ValueError, TypeError):
                    pass
        gaps.sort(key=lambda x: abs(x[2]), reverse=True)
        for label, col, diff, tv, cv in gaps:
            color = "green" if diff > 0 else "red"
            direction = "ahead" if diff > 0 else "behind"
            console.print(
                f"  [{color}]{label}: {diff:+.4f} ({direction})[/{color}]  (you: {fmt(tv, 4)}, #1: {fmt(cv, 4)})"
            )
        console.print()

    # ── Recent Games with Opponent Strength ───────────────────────────────
    console.print("[bold underline]Recent Games (schedule quality)[/bold underline]")
    games = fetch_team_games(supabase, team_id, limit=15)
    if games:
        # Collect opponent IDs
        opp_ids = []
        for g in games:
            if g.get("home_team_master_id") == team_id:
                opp_ids.append(g.get("away_team_master_id"))
            else:
                opp_ids.append(g.get("home_team_master_id"))
        opp_ids = [oid for oid in opp_ids if oid]

        opp_rankings = fetch_opponent_rankings(supabase, opp_ids)

        gt = Table(box=box.SIMPLE, show_header=True)
        gt.add_column("Date", width=12)
        gt.add_column("Result", width=8)
        gt.add_column("Score", width=7)
        gt.add_column("Opp Rank", justify="right", width=8)
        gt.add_column("Opp Score", justify="right", width=9)
        gt.add_column("Side", width=6)

        for g in games:
            date = g.get("game_date", "?")[:10]
            is_home = g.get("home_team_master_id") == team_id
            if is_home:
                gf = g.get("home_score", 0) or 0
                ga = g.get("away_score", 0) or 0
                opp_id = g.get("away_team_master_id")
                side = "Home"
            else:
                gf = g.get("away_score", 0) or 0
                ga = g.get("home_score", 0) or 0
                opp_id = g.get("home_team_master_id")
                side = "Away"

            if gf > ga:
                result = "[green]Win[/green]"
            elif gf < ga:
                result = "[red]Loss[/red]"
            else:
                result = "[yellow]Draw[/yellow]"

            opp_data = opp_rankings.get(opp_id, {})
            opp_rank = opp_data.get("national_rank")
            opp_score = opp_data.get("power_score_final")
            opp_rank_str = f"#{opp_rank}" if opp_rank else "unranked"
            opp_score_str = fmt(opp_score, 3) if opp_score else "—"

            gt.add_row(date, result, f"{gf}-{ga}", opp_rank_str, opp_score_str, side)

        console.print(gt)

        # Schedule quality summary
        ranked_opps = [
            opp_rankings[oid] for oid in opp_ids if oid in opp_rankings and opp_rankings[oid].get("power_score_final")
        ]
        if ranked_opps:
            avg_opp = sum(r["power_score_final"] for r in ranked_opps) / len(ranked_opps)
            top_opps = sum(1 for r in ranked_opps if (r.get("national_rank") or 999) <= 20)
            console.print(
                f"\n  Schedule quality: avg opponent score = {avg_opp:.3f} | "
                f"top-20 opponents: {top_opps}/{len(ranked_opps)}"
            )
    else:
        console.print("  No recent games found.")

    console.print()
    console.print("─" * 80)
    console.print()


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose why a team is or isn't #1 in their cohort. "
        "Cross-references ranking output against v53e algorithm design."
    )
    parser.add_argument("team_ids", nargs="+", help="One or more team UUIDs to diagnose")
    args = parser.parse_args()

    supabase = get_supabase()

    console.print(
        Panel(
            f"[bold]PitchRank Ranking Diagnostic[/bold]\n"
            f"Teams: {len(args.team_ids)}  |  "
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"[dim]Algorithm: v53e (OFF:20% DEF:20% SOS:60%) + ML Layer 13 (α=0.08)\n"
            f"SOS-conditioned ML: suppressed below SOS 0.45, full above 0.60\n"
            f"Age anchors: U10=0.40 → U19=1.00[/dim]",
            title="🔍 Ranking Diagnostic",
        )
    )
    console.print()

    for team_id in args.team_ids:
        diagnose_team(supabase, team_id.strip())


if __name__ == "__main__":
    main()
