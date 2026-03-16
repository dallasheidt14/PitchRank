#!/usr/bin/env python3
"""
Rankings Weight Simulator
=========================
Replay the PowerScore blend with different OFF/DEF/SOS/PERF/ML weights
without re-running the full pipeline. Uses existing normalized components
from rankings_full.

Usage:
    python scripts/rankings_weight_simulator.py

Edit the SCENARIOS list at the bottom to try different weight combos.
"""

# AZ U12 Male top teams — normalized components from rankings_full
TEAMS = [
    {
        "name": "FC Tucson 2014 Pre-MLSN #1",
        "team_id": "ffa679df",
        "off_norm": 0.9737, "def_norm": 0.9891, "sos_norm": 0.9364,
        "perf_centered": 0.4357, "ml_norm": 0.1218, "games_played": 30,
    },
    {
        "name": "Phoenix United 2014 Academy",
        "team_id": "5a9dac52",
        "off_norm": 0.9777, "def_norm": 0.9891, "sos_norm": 0.9155,
        "perf_centered": 0.3002, "ml_norm": 0.3008, "games_played": 18,
    },
    {
        "name": "Phoenix United 2014 Elite ⭐",
        "team_id": "691eb36d",
        "off_norm": 0.8905, "def_norm": 0.9891, "sos_norm": 0.9921,
        "perf_centered": -0.0373, "ml_norm": 0.1968, "games_played": 30,
    },
    {
        "name": "Dynamos SC 2014 SC",
        "team_id": "c2f8e0aa",
        "off_norm": 0.7760, "def_norm": 0.9891, "sos_norm": 0.9633,
        "perf_centered": 0.3560, "ml_norm": -0.2737, "games_played": 30,
    },
    {
        "name": "RSL Arizona North 2014 GSA",
        "team_id": "291aa4d2",
        "off_norm": 0.9486, "def_norm": 0.9131, "sos_norm": 0.9378,
        "perf_centered": 0.1755, "ml_norm": -0.1890, "games_played": 30,
    },
    {
        "name": "Next Level Southeast 2014 Black",
        "team_id": "448ebe45",
        "off_norm": 0.8295, "def_norm": 0.9891, "sos_norm": 0.9346,
        "perf_centered": -0.2864, "ml_norm": 0.2872, "games_played": 30,
    },
    {
        "name": "Playmaker PRE-ECNL 2014",
        "team_id": "a8e57856",
        "off_norm": 0.9449, "def_norm": 0.8233, "sos_norm": 0.8566,
        "perf_centered": 0.2502, "ml_norm": -0.1015, "games_played": 30,
    },
    {
        "name": "Excel Soccer Academy 2014 Red",
        "team_id": "929083d0",
        "off_norm": 0.7898, "def_norm": 0.7909, "sos_norm": 0.9421,
        "perf_centered": 0.0156, "ml_norm": 0.1425, "games_played": 30,
    },
    {
        "name": "BRAZAS FC 2014 Black",
        "team_id": "a180387c",
        "off_norm": 0.8538, "def_norm": 0.9739, "sos_norm": 0.9206,
        "perf_centered": 0.0278, "ml_norm": -0.3110, "games_played": 30,
    },
    {
        "name": "Tuzos Royals 2014",
        "team_id": "5981ccbc",
        "off_norm": 0.6055, "def_norm": 0.9481, "sos_norm": 0.9080,
        "perf_centered": 0.3630, "ml_norm": -0.2426, "games_played": 30,
    },
]

MIN_GAMES_PROVISIONAL = 8


def provisional_mult(gp: int) -> float:
    if gp >= MIN_GAMES_PROVISIONAL:
        return 1.0
    return 0.6 + 0.4 * (gp / MIN_GAMES_PROVISIONAL)


def simulate(off_w, def_w, sos_w, perf_w, ml_alpha):
    """Re-blend PowerScore with custom weights and return ranked list."""
    max_ps_theoretical = 1.0 + 0.5 * perf_w  # normalization ceiling
    max_ml_theoretical = 1.0 + 0.5 * ml_alpha

    results = []
    for t in TEAMS:
        # Step 1: powerscore_core (same as v53e Layer 10)
        ps_core = (
            off_w * t["off_norm"]
            + def_w * t["def_norm"]
            + sos_w * t["sos_norm"]
            + t["perf_centered"] * perf_w
        ) / max_ps_theoretical

        # Step 2: provisional multiplier
        ps_adj = ps_core * provisional_mult(t["games_played"])

        # Step 3: ML blend (Layer 13)
        ps_ml = (ps_adj + ml_alpha * t["ml_norm"]) / max_ml_theoretical
        ps_ml = max(0.0, min(1.0, ps_ml))

        # Display score (x55 like frontend)
        display = round(ps_ml * 55, 2)

        results.append({
            "name": t["name"],
            "ps_adj": round(ps_adj, 4),
            "ps_ml": round(ps_ml, 4),
            "display": display,
            "off": t["off_norm"],
            "sos": t["sos_norm"],
            "ml_norm": t["ml_norm"],
        })

    results.sort(key=lambda x: x["ps_ml"], reverse=True)
    return results


def print_results(label, off_w, def_w, sos_w, perf_w, ml_alpha):
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"  OFF={off_w}  DEF={def_w}  SOS={sos_w}  PERF={perf_w}  ML_ALPHA={ml_alpha}")
    print(f"{'='*80}")
    print(f"  {'#':<3} {'Team':<38} {'Base':>7} {'ML':>7} {'Display':>8}  {'OFF':>6} {'SOS':>6} {'ML_N':>7}")
    print(f"  {'-'*3} {'-'*38} {'-'*7} {'-'*7} {'-'*8}  {'-'*6} {'-'*6} {'-'*7}")

    results = simulate(off_w, def_w, sos_w, perf_w, ml_alpha)
    for i, r in enumerate(results, 1):
        star = " ⭐" if "Elite" in r["name"] else ""
        print(
            f"  {i:<3} {r['name']:<38} {r['ps_adj']:>7.4f} {r['ps_ml']:>7.4f} "
            f"{r['display']:>8.2f}  {r['off']:>6.3f} {r['sos']:>6.3f} {r['ml_norm']:>+7.3f}"
        )


if __name__ == "__main__":
    # =====================================================================
    # SCENARIOS — Edit these to test different weight combinations
    # =====================================================================

    print("\n" + "🏆" * 40)
    print("  PitchRank Weight Simulator — AZ U12 Male Top 10")
    print("🏆" * 40)

    # Current production weights
    print_results(
        "CURRENT PRODUCTION",
        off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15,
    )

    # Scenario 1: Increase SOS to 0.60
    print_results(
        "SCENARIO 1: Higher SOS (0.60), lower OFF/DEF (0.20)",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.15, ml_alpha=0.15,
    )

    # Scenario 2: Higher SOS + lower ML alpha
    print_results(
        "SCENARIO 2: Higher SOS (0.60) + reduced ML alpha (0.08)",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.15, ml_alpha=0.08,
    )

    # Scenario 3: SOS dominant
    print_results(
        "SCENARIO 3: SOS dominant (0.65), OFF/DEF (0.175)",
        off_w=0.175, def_w=0.175, sos_w=0.65, perf_w=0.15, ml_alpha=0.15,
    )

    # Scenario 4: Higher SOS + higher ML alpha (reward overperformance)
    print_results(
        "SCENARIO 4: SOS 0.60 + higher ML alpha (0.20)",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.15, ml_alpha=0.20,
    )

    # Scenario 5: Balanced increase SOS + reduce PERF
    print_results(
        "SCENARIO 5: SOS 0.60, OFF/DEF 0.20, no PERF, ML 0.15",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.00, ml_alpha=0.15,
    )

    # Scenario 6: Extreme SOS test
    print_results(
        "SCENARIO 6: SOS 0.70, OFF/DEF 0.15",
        off_w=0.15, def_w=0.15, sos_w=0.70, perf_w=0.15, ml_alpha=0.15,
    )

    print("\n")
