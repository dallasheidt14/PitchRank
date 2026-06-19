#!/usr/bin/env python3
"""
Bubble-Team Attribution Diagnostic — is the ranking inflation from ML, the cap, or base/SCF?
============================================================================================
Read-only forensic decomposition of the published board. Flags "bubble teams"
— ranked very high inside their own age/gender cohort, on a harder-than-usual
schedule, but only a middle-or-worse record for that cohort — then attributes
each one's high rank to ML, the publication cap, or base/SCF publish shaping.

A bubble team (per cohort = age_group x gender), defaults below:
    status = 'Active'
    games_played            >= 12
    rank_in_cohort_final    <= 50
    sos_norm                >= 75th percentile of the cohort
    win_percentage          <= median of the cohort
Percentiles are computed per cohort over the Active, >=12-game population, so a
"mediocre record on a hard schedule" means mediocre *for that cohort* — u12 girls
are compared to u12 girls, not to u16 boys.

Three views:
  1. Guardrail — count of flagged bubble teams per cohort (the metric to track
     before/after any future engine change; a fix should drive it DOWN).
  2. Attribution verdict — over the flagged set: applied ML push, cap-binding,
     and an engine-wide counterfactual (strip positive ML from every team,
     re-rank each cohort). If the flagged teams mostly have tiny ML push and are
     not cap-bound, ML is not the lever and the heat is on SCF / base shaping.
  3. Human-review list — the ugliest cases (stricter subset) with names, for fast
     eyeballing.

The ML push is reconstructed from persisted columns exactly as the publish path
applies it (src/rankings/calculator.py:2999): negative ML applies at full
authority; positive ML is gated by the SOS ramp x positive_ml_evidence_scale.
Validated against power_score_true on the 2026-06-16 snapshot (uncapped avg
residual 0.005). Cap-binding is detected as power_score_true pinned to
publication_cap_score, NOT merely publication_cap_rank being non-null (which is
set for ~99% of teams as a usually-non-binding ceiling).

Verified baseline (full board, 2026-06-16 snapshot, default filter):
    27 bubble teams across 12 cohorts | avg applied ML -0.025 | 3 ML-lifted (>=0.01)
    | 0 cap-bound | only 2 would leave the top 50 if positive ML were stripped.

Usage:
    python scripts/diagnose_bubble_teams.py                      # all Active cohorts
    python scripts/diagnose_bubble_teams.py --age u14 --gender Female
    python scripts/diagnose_bubble_teams.py --top-n 50 --min-games 12
Read-only: issues SELECTs only, writes nothing.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

sys.path.append(str(Path(__file__).parent.parent))

from src.rankings.constants import SOS_ML_THRESHOLD_HIGH, SOS_ML_THRESHOLD_LOW

# ── Setup ────────────────────────────────────────────────────────────────
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SEP = "=" * 78
THIN = "-" * 78

# Bubble filter defaults (per cohort). Percentiles are fractions in [0, 1].
DEFAULT_TOP_N = 50
DEFAULT_MIN_GAMES = 12
DEFAULT_SOS_PCT = 0.75
DEFAULT_WIN_PCT = 0.50

# Stricter human-review subset — surfaces only the most indefensible cases.
REVIEW_TOP_N = 25
REVIEW_SOS_PCT = 0.85
REVIEW_WIN_PCT = 0.40

# A positive ML lift this small is not what put a team near the top.
ML_LIFT_THRESHOLD = 0.01
# power_score_true within this of the cap ceiling means the cap is binding.
CAP_EPS = 0.0005
# If ML-lifted + cap-bound is below this share of the flagged set, the bubble
# problem lives in base/SCF shaping, not in ML or the cap.
DRIVER_MINORITY_FRAC = 0.25

verdicts: list[tuple[str, str, str]] = []


def verdict(name: str, status: str, reason: str = "") -> None:
    verdicts.append((name, status, reason))
    msg = f"  [{status}] {name}"
    if reason:
        msg += f" -- {reason}"
    print(msg)


def _cohort_filter(age: str | None, gender: str | None) -> tuple[str, dict]:
    if age and gender:
        return " AND age_group = %(age)s AND gender = %(gender)s", {"age": age, "gender": gender}
    return "", {}


def _open_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment (.env / .env.local)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def _decomp_cte(cohort_sql: str, table: str) -> str:
    """Shared CTE chain: decompose every Active team, build the engine-wide
    positive-ML-stripped counterfactual rank, then derive `flagged` (the bubble
    set) and `review` (the stricter subset). Each check selects from these.

    ``table`` is a pre-quoted, whitelist-validated board identifier (default
    rankings_full); pass a staging board to score it with the same SQL."""
    return f"""
    WITH board AS (
        SELECT team_id, age_group, gender, games_played, win_percentage, rank_in_cohort_final,
               sos_norm, powerscore_adj, powerscore_ml, positive_ml_evidence_scale,
               publication_cap_score, power_score_true,
               (powerscore_ml - powerscore_adj) AS ml_delta,
               GREATEST(0, LEAST(1, (sos_norm - %(sos_low)s) / (%(sos_high)s - %(sos_low)s))) AS ml_scale
        FROM {table}
        WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL
          AND powerscore_adj IS NOT NULL AND powerscore_ml IS NOT NULL AND sos_norm IS NOT NULL{cohort_sql}
    ),
    decomp AS (
        SELECT *,
            CASE WHEN ml_delta >= 0
                 THEN ml_delta * ml_scale * COALESCE(positive_ml_evidence_scale, 1.0)
                 ELSE ml_delta END AS applied_ml,
            (publication_cap_score IS NOT NULL
             AND abs(power_score_true - publication_cap_score) <= %(cap_eps)s) AS cap_bound
        FROM board
    ),
    ranked AS (
        SELECT *,
            rank() OVER (PARTITION BY age_group, gender ORDER BY
                CASE WHEN publication_cap_score IS NOT NULL
                     THEN LEAST(publication_cap_score, GREATEST(0, LEAST(1, powerscore_adj + LEAST(applied_ml, 0))))
                     ELSE GREATEST(0, LEAST(1, powerscore_adj + LEAST(applied_ml, 0))) END DESC
            ) AS cf_rank
        FROM decomp
    ),
    pct AS (
        SELECT age_group, gender,
            percentile_cont(%(sos_pct)s) WITHIN GROUP (ORDER BY sos_norm) AS sos_thresh,
            percentile_cont(%(win_pct)s) WITHIN GROUP (ORDER BY win_percentage) AS win_thresh,
            percentile_cont(%(rev_sos_pct)s) WITHIN GROUP (ORDER BY sos_norm) AS rev_sos_thresh,
            percentile_cont(%(rev_win_pct)s) WITHIN GROUP (ORDER BY win_percentage) AS rev_win_thresh
        FROM ranked
        WHERE games_played >= %(min_games)s
        GROUP BY age_group, gender
    ),
    flagged AS (
        SELECT r.*, p.rev_sos_thresh, p.rev_win_thresh
        FROM ranked r JOIN pct p USING (age_group, gender)
        WHERE r.games_played >= %(min_games)s
          AND r.rank_in_cohort_final <= %(top_n)s
          AND r.sos_norm >= p.sos_thresh
          AND r.win_percentage <= p.win_thresh
    ),
    review AS (
        SELECT * FROM flagged
        WHERE rank_in_cohort_final <= %(rev_top_n)s
          AND sos_norm >= rev_sos_thresh
          AND win_percentage <= rev_win_thresh
    )
    """


# ── View 1: Guardrail — bubble count per cohort ──────────────────────────
def check_guardrail(cur, cte: str, params: dict) -> int:
    print(f"\n{SEP}\n  VIEW 1: Bubble-team guardrail (count per cohort, the metric to track)\n{SEP}")
    cur.execute(
        cte + "SELECT age_group, gender, count(*) AS bubble_n "
        "FROM flagged GROUP BY age_group, gender ORDER BY bubble_n DESC, age_group, gender",
        params,
    )
    rows = cur.fetchall()
    total = sum(n for _, _, n in rows)
    if not rows:
        verdict("Bubble guardrail", "PASS", "no bubble teams flagged in scope")
        return 0
    print(f"\n  {'Cohort':<18} {'Bubble teams in top ' + str(params['top_n']):>26}")
    print(f"  {THIN}")
    for age_group, gender, n in rows:
        print(f"  {age_group + '/' + gender:<18} {n:>26}")
    print(f"  {THIN}")
    print(f"  {'TOTAL':<18} {total:>26}  across {len(rows)} cohort(s)")
    verdict("Bubble guardrail", "INFO", f"{total} flagged across {len(rows)} cohort(s) — track this over runs")
    return total


# ── View 2: Attribution verdict — ML vs cap vs base/SCF ──────────────────
def check_attribution(cur, cte: str, params: dict, total: int) -> None:
    print(f"\n{SEP}\n  VIEW 2: Attribution — is the inflation from ML, the cap, or base/SCF?\n{SEP}")
    if total == 0:
        verdict("Attribution", "INFO", "no flagged teams to attribute")
        return
    cur.execute(
        cte
        + """
        SELECT count(*),
               round(avg(applied_ml)::numeric, 4),
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY applied_ml)::numeric, 4),
               sum((applied_ml >= %(ml_lift)s)::int),
               sum(cap_bound::int),
               sum((cf_rank > %(top_n)s)::int),
               round(avg(cf_rank - rank_in_cohort_final)::numeric, 1)
        FROM flagged
        """,
        params,
    )
    n, avg_ml, med_ml, n_ml, n_cap, n_dropout, avg_shift = cur.fetchone()
    n_base = n - n_ml - n_cap
    print(f"\n  flagged bubble teams: {n}")
    print(f"  applied ML push:      avg {avg_ml:+.4f} | median {med_ml:+.4f}  (max possible ~+0.040)")
    print(f"  ML-lifted (>= {ML_LIFT_THRESHOLD}):   {n_ml:>3} / {n}")
    print(f"  cap-bound:            {n_cap:>3} / {n}   (pinned at publication_cap_score)")
    print(f"  base / SCF-driven:    {n_base:>3} / {n}   (high rank comes from powerscore_adj)")
    print("\n  Counterfactual — strip positive ML engine-wide, re-rank each cohort:")
    print(f"    would leave the top {params['top_n']}: {n_dropout} / {n}")
    print(f"    avg rank change of flagged teams: {avg_shift:+.1f}  (negative = they rise as rivals fall)")

    if (n_ml + n_cap) <= DRIVER_MINORITY_FRAC * n and n_dropout <= DRIVER_MINORITY_FRAC * n:
        verdict(
            "Attribution",
            "INFO",
            f"ML/cap NOT the driver ({n_ml} ML-lifted, {n_cap} cap-bound, {n_dropout} drop out) "
            f"— bubble problem lives in SCF / base publish shaping",
        )
    else:
        verdict(
            "Attribution",
            "WARN",
            f"ML/cap contributes materially ({n_ml} ML-lifted, {n_cap} cap-bound, {n_dropout} drop out) "
            f"— inspect before concluding SCF is the lever",
        )


# ── View 3: Human-review list — the ugliest cases ────────────────────────
def check_review_list(cur, cte: str, params: dict) -> None:
    print(
        f"\n{SEP}\n  VIEW 3: Human-review list (rank <= {REVIEW_TOP_N}, SOS >= P{int(REVIEW_SOS_PCT * 100)}, "
        f"win% <= P{int(REVIEW_WIN_PCT * 100)})\n{SEP}"
    )
    cur.execute(
        cte
        + """
        SELECT v.age_group, v.gender, v.rank_in_cohort_final,
               t.team_name, t.state_code,
               round(v.sos_norm::numeric, 3), round(v.win_percentage::numeric, 1),
               round(v.powerscore_adj::numeric, 4), round(v.applied_ml::numeric, 4),
               v.cap_bound, v.cf_rank
        FROM review v LEFT JOIN teams t ON t.team_id_master = v.team_id
        ORDER BY v.age_group, v.gender, v.rank_in_cohort_final
        """,
        params,
    )
    rows = cur.fetchall()
    if not rows:
        verdict("Human-review list", "INFO", "no teams in the stricter subset")
        return
    print(
        f"\n  {'Cohort':<11}{'Rk':>3} {'Team':<26}{'St':>3} {'SOS':>6}{'Win%':>6}"
        f"{'adj':>7}{'ML':>8} {'cap':>4}{'cfRk':>6}  driver"
    )
    print(f"  {THIN}")
    for ag, g, rk, name, st, sos, winp, adj, aml, capb, cfrk in rows:
        name = (name or "?")[:25]
        driver = "cap" if capb else ("ML" if aml >= ML_LIFT_THRESHOLD else "base/SCF")
        print(
            f"  {ag + '/' + g:<11}{rk:>3} {name:<26}{st or '?':>3} {sos:>6}{winp:>6}"
            f"{adj:>7}{aml:>+8.4f} {('Y' if capb else '-'):>4}{cfrk:>6}  {driver}"
        )
    verdict("Human-review list", "INFO", f"{len(rows)} teams for inspection")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attribute high-ranked / hard-schedule / mediocre-record bubble teams."
    )
    parser.add_argument("--age", help="Restrict to one age_group (e.g. u14). Requires --gender.")
    parser.add_argument("--gender", help="Restrict to one gender (Male/Female). Requires --age.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="Published-rank ceiling for a bubble team.")
    parser.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES, help="Minimum games_played.")
    parser.add_argument("--sos-pct", type=float, default=DEFAULT_SOS_PCT, help="Cohort SOS percentile floor (0-1).")
    parser.add_argument("--win-pct", type=float, default=DEFAULT_WIN_PCT, help="Cohort win%% percentile ceiling (0-1).")
    parser.add_argument(
        "--rankings-table",
        default="rankings_full",
        help="Board table to read (default: rankings_full). Pass a staging board to score it.",
    )
    args = parser.parse_args()
    if bool(args.age) != bool(args.gender):
        parser.error("--age and --gender must be used together (pass both to scope to one cohort, or neither)")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", args.rankings_table):
        parser.error(f"--rankings-table must match [a-z_][a-z0-9_]* (got {args.rankings_table!r})")

    cohort_sql, cohort_params = _cohort_filter(args.age, args.gender)
    scope = f"{args.age}/{args.gender}" if cohort_sql else "all Active cohorts"
    params = {
        "sos_low": SOS_ML_THRESHOLD_LOW,
        "sos_high": SOS_ML_THRESHOLD_HIGH,
        "cap_eps": CAP_EPS,
        "ml_lift": ML_LIFT_THRESHOLD,
        "top_n": args.top_n,
        "min_games": args.min_games,
        "sos_pct": args.sos_pct,
        "win_pct": args.win_pct,
        "rev_top_n": REVIEW_TOP_N,
        "rev_sos_pct": REVIEW_SOS_PCT,
        "rev_win_pct": REVIEW_WIN_PCT,
        **cohort_params,
    }
    conn = _open_connection()
    try:
        cte = _decomp_cte(cohort_sql, sql.Identifier(args.rankings_table).as_string(conn))
        with conn.cursor() as cur:
            print(
                f"\n{SEP}\n  Bubble-Team Attribution — board: {args.rankings_table} | scope: {scope} | "
                f"top {args.top_n}, >= {args.min_games} games, SOS >= P{int(args.sos_pct * 100)}, "
                f"win%% <= P{int(args.win_pct * 100)}\n{SEP}"
            )
            total = check_guardrail(cur, cte, params)
            check_attribution(cur, cte, params, total)
            check_review_list(cur, cte, params)
    finally:
        conn.close()

    print(f"\n{SEP}\n  SUMMARY\n{SEP}")
    for name, status, reason in verdicts:
        print(f"  [{status}] {name}" + (f" -- {reason}" if reason else ""))
    print()


if __name__ == "__main__":
    main()
