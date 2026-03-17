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
    python scripts/rankings_weight_simulator.py

Edit the SCENARIOS list at the bottom to try different weight combos.
"""

# AZ U12 Male top teams — normalized components from rankings_full
# power_presos = 0.5 * off_norm + 0.5 * def_norm (used for perf expected margin)
TEAMS = [
    {
        "name": "FC Tucson 2014 Pre-MLSN #1",
        "team_id": "ffa679df",
        "off_norm": 0.9737, "def_norm": 0.9891, "sos_norm": 0.9364,
        "perf_centered": 0.4357, "perf_raw": None,  # high perf = beating weak teams by lots
        "ml_norm": 0.1218, "ml_overperf": 0.0719, "games_played": 30,
    },
    {
        "name": "Phoenix United 2014 Academy",
        "team_id": "5a9dac52",
        "off_norm": 0.9777, "def_norm": 0.9891, "sos_norm": 0.9155,
        "perf_centered": 0.3002, "perf_raw": None,
        "ml_norm": 0.3008, "ml_overperf": 0.5167, "games_played": 18,
    },
    {
        "name": "Phoenix United 2014 Elite ⭐",
        "team_id": "691eb36d",
        "off_norm": 0.8905, "def_norm": 0.9891, "sos_norm": 0.9921,
        "perf_centered": -0.0373, "perf_raw": None,
        "ml_norm": 0.1968, "ml_overperf": 0.2411, "games_played": 30,
    },
    {
        "name": "Dynamos SC 2014 SC",
        "team_id": "c2f8e0aa",
        "off_norm": 0.7760, "def_norm": 0.9891, "sos_norm": 0.9633,
        "perf_centered": 0.3560, "perf_raw": None,
        "ml_norm": -0.2737, "ml_overperf": -0.4287, "games_played": 30,
    },
    {
        "name": "RSL Arizona North 2014 GSA",
        "team_id": "291aa4d2",
        "off_norm": 0.9486, "def_norm": 0.9131, "sos_norm": 0.9378,
        "perf_centered": 0.1755, "perf_raw": None,
        "ml_norm": -0.1890, "ml_overperf": -0.2021, "games_played": 30,
    },
    {
        "name": "Next Level Southeast 2014 Black",
        "team_id": "448ebe45",
        "off_norm": 0.8295, "def_norm": 0.9891, "sos_norm": 0.9346,
        "perf_centered": -0.2864, "perf_raw": None,
        "ml_norm": 0.2872, "ml_overperf": 0.4811, "games_played": 30,
    },
    {
        "name": "Playmaker PRE-ECNL 2014",
        "team_id": "a8e57856",
        "off_norm": 0.9449, "def_norm": 0.8233, "sos_norm": 0.8566,
        "perf_centered": 0.2502, "perf_raw": None,
        "ml_norm": -0.1015, "ml_overperf": -0.0074, "games_played": 30,
    },
    {
        "name": "Excel Soccer Academy 2014 Red",
        "team_id": "929083d0",
        "off_norm": 0.7898, "def_norm": 0.7909, "sos_norm": 0.9421,
        "perf_centered": 0.0156, "perf_raw": None,
        "ml_norm": 0.1425, "ml_overperf": 0.1136, "games_played": 30,
    },
    {
        "name": "BRAZAS FC 2014 Black",
        "team_id": "a180387c",
        "off_norm": 0.8538, "def_norm": 0.9739, "sos_norm": 0.9206,
        "perf_centered": 0.0278, "perf_raw": None,
        "ml_norm": -0.3110, "ml_overperf": -0.5272, "games_played": 30,
    },
    {
        "name": "Tuzos Royals 2014",
        "team_id": "5981ccbc",
        "off_norm": 0.6055, "def_norm": 0.9481, "sos_norm": 0.9080,
        "perf_centered": 0.3630, "perf_raw": None,
        "ml_norm": -0.2426, "ml_overperf": -0.3392, "games_played": 30,
    },
]

MIN_GAMES_PROVISIONAL = 8


def provisional_mult(gp: int) -> float:
    if gp >= MIN_GAMES_PROVISIONAL:
        return 1.0
    return 0.6 + 0.4 * (gp / MIN_GAMES_PROVISIONAL)


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
    max_ps_theoretical = 1.0 + perf_cap * perf_w
    max_ml_theoretical = 1.0 + perf_cap * ml_alpha

    results = []
    for t in TEAMS:
        # Optionally weight perf by SOS
        perf = t["perf_centered"]
        if sos_weighted_perf:
            # Multiply perf by sos_norm: high SOS amplifies, low SOS dampens
            perf = perf * t["sos_norm"]

        # Apply perf cap — clips outliers symmetrically
        perf = max(-perf_cap, min(perf_cap, perf))

        ps_core = (
            off_w * t["off_norm"]
            + def_w * t["def_norm"]
            + sos_w * t["sos_norm"]
            + perf * perf_w
        ) / max_ps_theoretical

        ps_adj = ps_core * provisional_mult(t["games_played"])

        ps_ml = (ps_adj + ml_alpha * t["ml_norm"]) / max_ml_theoretical
        ps_ml = max(0.0, min(1.0, ps_ml))

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


def find_elite_rank(off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf=False, perf_cap=0.50):
    """Return the rank of Phoenix United Elite for a given config."""
    results = simulate(off_w, def_w, sos_w, perf_w, ml_alpha, sos_weighted_perf, perf_cap)
    for i, r in enumerate(results, 1):
        if "Elite" in r["name"]:
            return i
    return 99


if __name__ == "__main__":
    print("\n" + "🏆" * 40)
    print("  PitchRank Weight Simulator — AZ U12 Male Top 10")
    print("🏆" * 40)

    # =====================================================================
    # SECTION 1: Current production baseline
    # =====================================================================
    print_results(
        "CURRENT PRODUCTION",
        off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15,
    )

    # =====================================================================
    # SECTION 2: PERF weight sweep (keep OFF/DEF/SOS same)
    # The key question: what PERF weight keeps overperformance signal
    # without letting stat-padding dominate?
    # =====================================================================
    for pw in [0.12, 0.10, 0.08, 0.05, 0.03]:
        rank = find_elite_rank(0.25, 0.25, 0.50, pw, 0.15)
        label = f"PERF SWEEP: PERF={pw} (Elite rank: #{rank})"
        print_results(label, off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=pw, ml_alpha=0.15)

    # =====================================================================
    # SECTION 3: SOS-weighted PERF (the fix)
    # Instead of reducing PERF weight, multiply perf_centered by sos_norm.
    # This preserves the overperformance signal but weights it by schedule
    # strength — beating expectations vs tough opponents matters more.
    # =====================================================================
    print("\n" + "⚡" * 40)
    print("  SOS-WEIGHTED PERFORMANCE SCENARIOS")
    print("  perf_adjusted = perf_centered * sos_norm")
    print("  (overperformance vs tough schedule = amplified)")
    print("  (stat-padding vs weak schedule = dampened)")
    print("⚡" * 40)

    print_results(
        "SOS-WEIGHTED PERF: Current weights (0.25/0.25/0.50, PERF=0.15)",
        off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15,
        sos_weighted_perf=True,
    )

    print_results(
        "SOS-WEIGHTED PERF: Higher SOS (0.20/0.20/0.60, PERF=0.15)",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.15, ml_alpha=0.15,
        sos_weighted_perf=True,
    )

    print_results(
        "SOS-WEIGHTED PERF: SOS 0.60, PERF=0.10",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.10, ml_alpha=0.15,
        sos_weighted_perf=True,
    )

    # =====================================================================
    # SECTION 4: Combined tuning — SOS weight + PERF fix + ML alpha
    # =====================================================================
    print("\n" + "🎯" * 40)
    print("  COMBINED TUNING SCENARIOS")
    print("🎯" * 40)

    print_results(
        "COMBO A: SOS 0.55, PERF 0.10 (SOS-weighted), ML 0.15",
        off_w=0.225, def_w=0.225, sos_w=0.55, perf_w=0.10, ml_alpha=0.15,
        sos_weighted_perf=True,
    )

    print_results(
        "COMBO B: SOS 0.55, PERF 0.10 (SOS-weighted), ML 0.10",
        off_w=0.225, def_w=0.225, sos_w=0.55, perf_w=0.10, ml_alpha=0.10,
        sos_weighted_perf=True,
    )

    print_results(
        "COMBO C: SOS 0.60, PERF 0.08 (SOS-weighted), ML 0.12",
        off_w=0.20, def_w=0.20, sos_w=0.60, perf_w=0.08, ml_alpha=0.12,
        sos_weighted_perf=True,
    )

    print_results(
        "COMBO D: SOS 0.55, PERF 0.12 (SOS-weighted), ML 0.15",
        off_w=0.225, def_w=0.225, sos_w=0.55, perf_w=0.12, ml_alpha=0.15,
        sos_weighted_perf=True,
    )

    # =====================================================================
    # SECTION 5: Quick grid search — find all combos where Elite is #1
    # =====================================================================
    print("\n" + "🔍" * 40)
    print("  GRID SEARCH: All combos where Phoenix United Elite = #1")
    print("  (SOS-weighted PERF enabled)")
    print("🔍" * 40)

    winners = []
    for sos_w in [0.45, 0.50, 0.55, 0.60, 0.65]:
        remaining = 1.0 - sos_w
        off_w = remaining / 2
        def_w = remaining / 2
        for perf_w in [0.00, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15]:
            for ml_a in [0.08, 0.10, 0.12, 0.15, 0.18, 0.20]:
                rank = find_elite_rank(off_w, def_w, sos_w, perf_w, ml_a, sos_weighted_perf=True)
                if rank == 1:
                    winners.append((off_w, def_w, sos_w, perf_w, ml_a, rank))

    if winners:
        print(f"\n  Found {len(winners)} winning combinations:\n")
        print(f"  {'OFF':>6} {'DEF':>6} {'SOS':>6} {'PERF':>6} {'ML_A':>6}")
        print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
        for w in winners:
            print(f"  {w[0]:>6.3f} {w[1]:>6.3f} {w[2]:>6.3f} {w[3]:>6.3f} {w[4]:>6.3f}")
    else:
        print("\n  No combinations found where Elite is #1 with SOS-weighted PERF.")
        print("  Showing combos where Elite is #1 WITHOUT SOS-weighted PERF:\n")
        for sos_w in [0.45, 0.50, 0.55, 0.60, 0.65]:
            remaining = 1.0 - sos_w
            off_w = remaining / 2
            def_w = remaining / 2
            for perf_w in [0.00, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15]:
                for ml_a in [0.08, 0.10, 0.12, 0.15, 0.18, 0.20]:
                    rank = find_elite_rank(off_w, def_w, sos_w, perf_w, ml_a, sos_weighted_perf=False)
                    if rank == 1:
                        winners.append((off_w, def_w, sos_w, perf_w, ml_a, rank))
        if winners:
            print(f"  Found {len(winners)} combos (no SOS-weighted PERF):\n")
            print(f"  {'OFF':>6} {'DEF':>6} {'SOS':>6} {'PERF':>6} {'ML_A':>6}")
            print(f"  {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
            for w in winners:
                print(f"  {w[0]:>6.3f} {w[1]:>6.3f} {w[2]:>6.3f} {w[3]:>6.3f} {w[4]:>6.3f}")

    # =====================================================================
    # SECTION 6: PERF CAP scenarios — clip perf_centered tighter
    # Current: perf_centered is [-0.5, +0.5] (percentile-based, no clip)
    # These scenarios add a symmetric cap to limit outlier influence.
    # =====================================================================
    print("\n" + "=" * 40)
    print("  PERF CAP SCENARIOS")
    print("  Clip perf_centered to +/-cap before blending")
    print("=" * 40)

    # A) Tighter cap only (keep current PERF weight 0.15)
    for cap in [0.40, 0.30, 0.25, 0.20, 0.15]:
        rank = find_elite_rank(0.25, 0.25, 0.50, 0.15, 0.15, perf_cap=cap)
        label = f"CAP ONLY: perf_cap=+/-{cap}, PERF=0.15 (Elite #{rank})"
        print_results(label, off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15, perf_cap=cap)

    # B) Lower PERF weight only (no cap change)
    print("\n" + "-" * 40)
    print("  LOWER WEIGHT ONLY (no cap)")
    print("-" * 40)
    for pw in [0.10, 0.08, 0.05]:
        rank = find_elite_rank(0.25, 0.25, 0.50, pw, 0.15)
        label = f"WEIGHT ONLY: PERF={pw}, no cap (Elite #{rank})"
        print_results(label, off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=pw, ml_alpha=0.15)

    # C) Both — tighter cap + lower weight
    print("\n" + "-" * 40)
    print("  BOTH: TIGHTER CAP + LOWER WEIGHT")
    print("-" * 40)
    combos = [
        (0.10, 0.30),  # moderate weight, moderate cap
        (0.10, 0.25),  # moderate weight, tight cap
        (0.08, 0.25),  # low weight, tight cap
        (0.05, 0.25),  # very low weight, tight cap
        (0.05, 0.20),  # very low weight, very tight cap
    ]
    for pw, cap in combos:
        rank = find_elite_rank(0.25, 0.25, 0.50, pw, 0.15, perf_cap=cap)
        label = f"BOTH: PERF={pw}, cap=+/-{cap} (Elite #{rank})"
        print_results(label, off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=pw, ml_alpha=0.15, perf_cap=cap)

    # D) Cap + SOS-weighted PERF (best of all worlds?)
    print("\n" + "-" * 40)
    print("  CAP + SOS-WEIGHTED PERF")
    print("-" * 40)
    combos_sos = [
        (0.15, 0.25),  # current weight, tight cap, SOS-weighted
        (0.10, 0.25),  # lower weight, tight cap, SOS-weighted
        (0.10, 0.30),  # lower weight, moderate cap, SOS-weighted
    ]
    for pw, cap in combos_sos:
        rank = find_elite_rank(0.25, 0.25, 0.50, pw, 0.15, sos_weighted_perf=True, perf_cap=cap)
        label = f"CAP+SOS-W: PERF={pw}, cap=+/-{cap}, SOS-weighted (Elite #{rank})"
        print_results(label, off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=pw, ml_alpha=0.15,
                      sos_weighted_perf=True, perf_cap=cap)

    # =====================================================================
    # SECTION 7: Summary comparison table
    # =====================================================================
    print("\n" + "=" * 90)
    print("  SUMMARY: Elite rank across all approaches")
    print("=" * 90)
    print(f"  {'Scenario':<55} {'Elite #':>7}")
    print(f"  {'-'*55} {'-'*7}")

    scenarios = [
        ("Current production (PERF=0.15, no cap)", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15)),
        ("Lower weight: PERF=0.10", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.10, ml_alpha=0.15)),
        ("Lower weight: PERF=0.05", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.05, ml_alpha=0.15)),
        ("Tighter cap: +/-0.30", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15, perf_cap=0.30)),
        ("Tighter cap: +/-0.25", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15, perf_cap=0.25)),
        ("Tighter cap: +/-0.20", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15, perf_cap=0.20)),
        ("Both: PERF=0.10, cap=+/-0.25", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.10, ml_alpha=0.15, perf_cap=0.25)),
        ("Both: PERF=0.05, cap=+/-0.25", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.05, ml_alpha=0.15, perf_cap=0.25)),
        ("SOS-weighted PERF=0.15", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15, sos_weighted_perf=True)),
        ("SOS-weighted + cap=+/-0.25", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.15, ml_alpha=0.15, sos_weighted_perf=True, perf_cap=0.25)),
        ("SOS-weighted PERF=0.10 + cap=+/-0.25", dict(off_w=0.25, def_w=0.25, sos_w=0.50, perf_w=0.10, ml_alpha=0.15, sos_weighted_perf=True, perf_cap=0.25)),
    ]
    for name, kw in scenarios:
        rank = find_elite_rank(**kw)
        print(f"  {name:<55} {'#' + str(rank):>7}")

    print("\n")
