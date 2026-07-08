#!/usr/bin/env python3
"""
Ranking Stability Check — Publish-Path Reshuffle Detector
=========================================================
Quantifies how much a ranking run reshuffled the PUBLISHED standings versus the
previous snapshot, independent of game results. Built after the 2026-06-15 run
(first run on #885 publish-only SCF) scrambled the board: u14F teams that did not
play a single game still moved a median of 387 ranks.

Three checks, all keyed off the published rank (rank_in_cohort_final):
  1. Non-playing-team churn  — teams with no game since the prior snapshot should
     not move. Movement here is pure engine/publish-path effect.
  2. mu -> published stage shift — distance between raw-strength order
     (rank_in_cohort, mu) and published order (rank_in_cohort_final). A
     characterization metric: large values mean the publish chain has decoupled
     the standings from team strength. Compare across runs (it should DROP after a
     rollback), not against an absolute bar.
  3. Top-100 churn — new entrants into each cohort's published top 100 vs the
     prior snapshot.

Runs the same SQL verified live against project pfkrhmprwxtghtpinrot on 2026-06-15.
Verified baseline (u14F, prev snapshot 2026-06-08, the BROKEN #885 run):
    non-playing teams = 2787, avg move 479.6, median 387
    mu -> published avg stage shift = 246.8
    top-100 new entrants (u14F) = 28

Usage:
    python scripts/ranking_stability_check.py                       # all Active cohorts
    python scripts/ranking_stability_check.py --age u14 --gender Female
    python scripts/ranking_stability_check.py --prev-date 2026-06-08
Exit code is non-zero if any check FAILs, so this can gate a ranking run.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

# ── Setup ────────────────────────────────────────────────────────────────
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SEP = "=" * 78
THIN = "-" * 78

# Verdict thresholds (median absolute rank move for non-playing teams; per-cohort
# new top-100 entrants). Defaults are deliberately strict — a healthy week moves
# non-playing teams a handful of ranks at most.
NONPLAY_MEDIAN_WARN = 10
NONPLAY_MEDIAN_FAIL = 30
TOP100_ENTRANTS_WARN = 10
TOP100_ENTRANTS_FAIL = 20

verdicts: list[tuple[str, str, str]] = []


def verdict(name: str, status: str, reason: str = "") -> None:
    verdicts.append((name, status, reason))
    msg = f"  [{status}] {name}"
    if reason:
        msg += f" -- {reason}"
    print(msg)


def _cohort_filter(age: str | None, gender: str | None) -> tuple[str, dict]:
    """Return an optional 'AND age_group=.. AND gender=..' clause and its params."""
    if age and gender:
        return " AND age_group = %(age)s AND gender = %(gender)s", {"age": age, "gender": gender}
    return "", {}


def _open_connection():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set in environment (.env / .env.local)")
        sys.exit(1)
    return psycopg2.connect(database_url)


def _resolve_prev_date(cur) -> str:
    cur.execute("SELECT max(snapshot_date) FROM ranking_history WHERE snapshot_date < current_date")
    row = cur.fetchone()
    if not row or row[0] is None:
        print("ERROR: no prior ranking_history snapshot found")
        sys.exit(1)
    return str(row[0])


# ── Check 1: Non-playing-team churn ──────────────────────────────────────
def check_nonplaying_churn(cur, prev_date: str, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  CHECK 1: Non-playing-team churn (pure engine effect)\n{SEP}")
    cur.execute(
        f"""
        WITH prev AS (
            SELECT team_id, rank_in_cohort_final AS r_prev
            FROM ranking_history WHERE snapshot_date = %(prev)s AND rank_in_cohort_final IS NOT NULL
        ),
        cur AS (
            SELECT team_id, rank_in_cohort_final AS r_now, last_game
            FROM rankings_full
            WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL{cohort_sql}
        )
        SELECT count(*),
               round(avg(abs(r_now - r_prev))::numeric, 1),
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(r_now - r_prev))::numeric, 0),
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY abs(r_now - r_prev))::numeric, 0),
               sum((abs(r_now - r_prev) >= 50)::int),
               sum((abs(r_now - r_prev) >= 100)::int),
               max(abs(r_now - r_prev))
        FROM cur JOIN prev USING (team_id)
        WHERE cur.last_game <= %(prev)s
        """,
        {"prev": prev_date, **params},
    )
    n, avg_move, median, p90, moved50, moved100, worst = cur.fetchone()
    if not n:
        verdict("Non-playing churn", "WARN", "no non-playing teams matched")
        return
    print(f"\n  teams that did not play since {prev_date}: {n:,}")
    print(f"  avg move {avg_move}  |  median {median}  |  p90 {p90}  |  worst {worst}")
    print(f"  moved >=50: {moved50:,} ({moved50 / n:.0%})   moved >=100: {moved100:,} ({moved100 / n:.0%})")
    median = float(median)
    if median <= NONPLAY_MEDIAN_WARN:
        verdict("Non-playing churn", "PASS", f"median move {median:.0f} <= {NONPLAY_MEDIAN_WARN}")
    elif median <= NONPLAY_MEDIAN_FAIL:
        verdict("Non-playing churn", "WARN", f"median move {median:.0f} (teams that did not play are drifting)")
    else:
        verdict("Non-playing churn", "FAIL", f"median move {median:.0f} — standings scrambled independent of results")


# ── Check 2: mu -> published stage shift ─────────────────────────────────
def _stage_shift(cur, table_sql: str, cohort_sql: str, params: dict) -> tuple:
    """avg + median |rank_in_cohort - rank_in_cohort_final| over Active teams on one board."""
    cur.execute(
        f"""
        SELECT round(avg(abs(rank_in_cohort - rank_in_cohort_final))::numeric, 1),
               round(percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY abs(rank_in_cohort - rank_in_cohort_final))::numeric, 0)
        FROM {table_sql}
        WHERE status = 'Active'
          AND rank_in_cohort IS NOT NULL AND rank_in_cohort_final IS NOT NULL{cohort_sql}
        """,
        params,
    )
    return cur.fetchone()


def check_stage_shift(cur, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  CHECK 2: mu -> published stage shift (characterization)\n{SEP}")
    avg_shift, median_shift = _stage_shift(cur, "rankings_full", cohort_sql, params)
    print(f"\n  avg |raw-strength rank - published rank| = {avg_shift}   (median {median_shift})")
    print("  (informational: compare across runs — a rollback that re-couples standings")
    print("   to strength should make this DROP. High values = publish chain dominates mu.)")
    verdict("mu->published stage shift", "INFO", f"avg {avg_shift}, median {median_shift}")


# ── Check 3: Top-100 churn ───────────────────────────────────────────────
def check_top100_churn(cur, prev_date: str, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  CHECK 3: Top-100 churn (new entrants per cohort)\n{SEP}")
    cur.execute(
        f"""
        WITH prev AS (
            SELECT team_id, rank_in_cohort_final AS r_prev
            FROM ranking_history WHERE snapshot_date = %(prev)s
        ),
        cur AS (
            SELECT team_id, age_group, gender, rank_in_cohort_final AS r_now
            FROM rankings_full
            WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL{cohort_sql}
        ),
        j AS (SELECT cur.*, prev.r_prev FROM cur LEFT JOIN prev USING (team_id))
        SELECT age_group, gender,
               sum((r_now <= 100 AND (r_prev IS NULL OR r_prev > 100))::int) AS new_entrants
        FROM j
        GROUP BY age_group, gender
        HAVING sum((r_now <= 100 AND (r_prev IS NULL OR r_prev > 100))::int) > 0
        ORDER BY new_entrants DESC
        """,
        {"prev": prev_date, **params},
    )
    rows = cur.fetchall()
    if not rows:
        verdict("Top-100 churn", "PASS", "no new entrants into any cohort top 100")
        return
    print(f"\n  {'Cohort':<18} {'New top-100 entrants':>22}")
    print(f"  {THIN}")
    worst = 0
    for age_group, gender, entrants in rows[:15]:
        worst = max(worst, entrants)
        print(f"  {age_group + '/' + gender:<18} {entrants:>22}")
    if worst <= TOP100_ENTRANTS_WARN:
        verdict("Top-100 churn", "PASS", f"worst cohort {worst} new entrants")
    elif worst <= TOP100_ENTRANTS_FAIL:
        verdict("Top-100 churn", "WARN", f"worst cohort {worst} new entrants")
    else:
        verdict("Top-100 churn", "FAIL", f"worst cohort {worst} new entrants into the top 100")


# ── Compare mode: board-vs-board (a baseline table vs a candidate table) ──
# A legitimate engine change is EXPECTED to move teams, so these checks are
# characterization (INFO), never FAIL. Baseline = the --baseline-table board
# (default rankings_full; pass a same-snapshot SCF-on board to avoid stale prod);
# candidate = the table passed via --compare-table. No ranking_history is read.
def compare_movement(cur, cand_ident: str, base_ident: str, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  COMPARE 1: rank movement, candidate vs baseline (same snapshot)\n{SEP}")
    cur.execute(
        f"""
        WITH prod AS (
            SELECT team_id, rank_in_cohort_final AS r_prod
            FROM {base_ident}
            WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL{cohort_sql}
        ),
        cand AS (
            SELECT team_id, rank_in_cohort_final AS r_cand
            FROM {cand_ident}
            WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL
        ),
        j AS (SELECT (c.r_cand - p.r_prod) AS delta FROM prod p JOIN cand c USING (team_id))
        SELECT count(*),
               round(avg(abs(delta))::numeric, 1),
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY abs(delta))::numeric, 0),
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY abs(delta))::numeric, 0),
               max(abs(delta)),
               sum((delta < 0)::int),
               sum((delta > 0)::int)
        FROM j
        """,
        params,
    )
    n, avg_move, median, p90, worst, rose, dropped = cur.fetchone()
    if not n:
        verdict("Board movement", "INFO", "no teams matched between boards")
        return
    print(f"\n  teams on both boards: {n:,}")
    print(f"  avg |Δrank| {avg_move}  |  median {median}  |  p90 {p90}  |  worst {worst}")
    print(f"  rose toward #1: {rose:,} ({rose / n:.0%})   dropped: {dropped:,} ({dropped / n:.0%})")
    verdict("Board movement", "INFO", f"median |Δrank| {float(median):.0f} across {n:,} teams (movement expected)")


def compare_top_movers(cur, cand_ident: str, base_ident: str, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  COMPARE 1b: biggest movers with schedule/record (eyeball bubble demotions)\n{SEP}")
    cur.execute(
        f"""
        WITH prod AS (
            SELECT team_id, age_group, gender, rank_in_cohort_final AS r_prod
            FROM {base_ident}
            WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL{cohort_sql}
        ),
        cand AS (
            SELECT team_id, rank_in_cohort_final AS r_cand, sos_norm, win_percentage
            FROM {cand_ident}
            WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL
        ),
        j AS (
            SELECT p.age_group, p.gender, p.team_id, p.r_prod, c.r_cand,
                   (c.r_cand - p.r_prod) AS delta, c.sos_norm, c.win_percentage
            FROM prod p JOIN cand c USING (team_id)
        ),
        movers AS (
            (SELECT 'DROP' AS dir, * FROM j ORDER BY delta DESC LIMIT 15)
            UNION ALL
            (SELECT 'RISE' AS dir, * FROM j ORDER BY delta ASC LIMIT 15)
        )
        SELECT m.dir, m.age_group, m.gender, t.team_name, m.r_prod, m.r_cand, m.delta,
               round(m.sos_norm::numeric, 3), round(m.win_percentage::numeric, 1)
        FROM movers m LEFT JOIN teams t ON t.team_id_master = m.team_id
        ORDER BY m.dir, abs(m.delta) DESC
        """,
        params,
    )
    rows = cur.fetchall()
    if not rows:
        verdict("Top movers", "INFO", "no overlapping teams to rank by movement")
        return
    print(f"\n  {'Dir':<5}{'Cohort':<11}{'Team':<26}{'prod->cand':>12}{'Δ':>7}{'SOS':>7}{'Win%':>7}")
    print(f"  {THIN}")
    for d, ag, g, name, r_prod, r_cand, delta, sosn, winp in rows:
        name = (name or "?")[:25]
        path = f"{r_prod}->{r_cand}"
        print(f"  {d:<5}{ag + '/' + g:<11}{name:<26}{path:>12}{delta:>+7}{sosn:>7}{winp:>7}")
    verdict("Top movers", "INFO", "DROP movers should be high-SOS / mediocre-record bubble teams")


def compare_stage_shift(cur, cand_ident: str, base_ident: str, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  COMPARE 2: mu->published decoupling, candidate vs baseline (within-board)\n{SEP}")
    prod_avg, prod_med = _stage_shift(cur, base_ident, cohort_sql, params)
    cand_avg, cand_med = _stage_shift(cur, cand_ident, cohort_sql, params)
    print(f"\n  baseline  : avg {prod_avg}, median {prod_med}")
    print(f"  candidate : avg {cand_avg}, median {cand_med}")
    print("  (a healthy candidate should NOT decouple mu from the published order more than the baseline)")
    verdict("Stage-shift delta", "INFO", f"baseline avg {prod_avg} vs candidate avg {cand_avg}")


def compare_topn_composition(cur, cand_ident: str, base_ident: str, cohort_sql: str, params: dict) -> None:
    print(f"\n{SEP}\n  COMPARE 3: top-N composition delta, candidate vs baseline\n{SEP}")
    for n in (50, 100):
        cur.execute(
            f"""
            WITH prod AS (
                SELECT team_id, age_group, gender, rank_in_cohort_final AS r_prod
                FROM {base_ident} WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL{cohort_sql}
            ),
            cand AS (
                SELECT team_id, age_group, gender, rank_in_cohort_final AS r_cand
                FROM {cand_ident} WHERE status = 'Active' AND rank_in_cohort_final IS NOT NULL{cohort_sql}
            ),
            j AS (
                SELECT COALESCE(c.age_group, p.age_group) AS ag,
                       COALESCE(c.gender, p.gender) AS g,
                       p.r_prod, c.r_cand
                FROM cand c FULL OUTER JOIN prod p USING (team_id)
            )
            SELECT ag, g,
                   sum((r_cand <= %(n)s AND (r_prod IS NULL OR r_prod > %(n)s))::int) AS entrants,
                   sum((r_prod <= %(n)s AND (r_cand IS NULL OR r_cand > %(n)s))::int) AS exits
            FROM j GROUP BY ag, g
            HAVING sum((r_cand <= %(n)s AND (r_prod IS NULL OR r_prod > %(n)s))::int) > 0
                OR sum((r_prod <= %(n)s AND (r_cand IS NULL OR r_cand > %(n)s))::int) > 0
            ORDER BY entrants DESC, ag, g
            """,
            {**params, "n": n},
        )
        rows = cur.fetchall()
        print(f"\n  top {n}: {len(rows)} cohort(s) with churn")
        if rows:
            print(f"  {'Cohort':<18}{'entrants':>10}{'exits':>8}")
            print(f"  {THIN}")
            for ag, g, entrants, exits in rows[:15]:
                print(f"  {ag + '/' + g:<18}{entrants:>10}{exits:>8}")
        worst = max((entrants for _, _, entrants, _ in rows), default=0)
        verdict(f"Top-{n} composition", "INFO", f"worst cohort {worst} new entrants vs baseline")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quantify published-ranking reshuffle vs the prior snapshot.")
    parser.add_argument("--age", help="Restrict to one age_group (e.g. u14). Requires --gender.")
    parser.add_argument("--gender", help="Restrict to one gender (e.g. Female). Requires --age.")
    parser.add_argument("--prev-date", help="Prior snapshot date (YYYY-MM-DD). Default: latest before today.")
    parser.add_argument(
        "--compare-table",
        help="Board-vs-board mode: characterize this candidate table against the baseline "
        "(additive; reads no ranking_history, never FAILs).",
    )
    parser.add_argument(
        "--baseline-table",
        default="rankings_full",
        help="Baseline board the candidate is compared against in --compare-table mode "
        "(default: rankings_full). Pass a same-snapshot SCF-on board to avoid a stale-prod confound.",
    )
    args = parser.parse_args()
    if bool(args.age) != bool(args.gender):
        parser.error("--age and --gender must be used together (pass both to scope to one cohort, or neither)")
    if args.compare_table and not re.fullmatch(r"[a-z_][a-z0-9_]*", args.compare_table):
        parser.error(f"--compare-table must match [a-z_][a-z0-9_]* (got {args.compare_table!r})")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", args.baseline_table):
        parser.error(f"--baseline-table must match [a-z_][a-z0-9_]* (got {args.baseline_table!r})")

    cohort_sql, params = _cohort_filter(args.age, args.gender)
    scope = f"{args.age}/{args.gender}" if cohort_sql else "all Active cohorts"

    conn = _open_connection()
    try:
        with conn.cursor() as cur:
            if args.compare_table:
                cand_ident = sql.Identifier(args.compare_table).as_string(conn)
                base_ident = sql.Identifier(args.baseline_table).as_string(conn)
                print(
                    f"\n{SEP}\n  Board-vs-Board Stability — candidate {args.compare_table} "
                    f"vs baseline {args.baseline_table} | scope: {scope}\n{SEP}"
                )
                compare_movement(cur, cand_ident, base_ident, cohort_sql, params)
                compare_top_movers(cur, cand_ident, base_ident, cohort_sql, params)
                compare_stage_shift(cur, cand_ident, base_ident, cohort_sql, params)
                compare_topn_composition(cur, cand_ident, base_ident, cohort_sql, params)
            else:
                prev_date = args.prev_date or _resolve_prev_date(cur)
                print(f"\n{SEP}\n  Ranking Stability Check — scope: {scope} | prior snapshot: {prev_date}\n{SEP}")
                check_nonplaying_churn(cur, prev_date, cohort_sql, params)
                check_stage_shift(cur, cohort_sql, params)
                check_top100_churn(cur, prev_date, cohort_sql, params)
    finally:
        conn.close()

    print(f"\n{SEP}\n  SUMMARY\n{SEP}")
    fail = sum(1 for _, s, _ in verdicts if s == "FAIL")
    warn = sum(1 for _, s, _ in verdicts if s == "WARN")
    for name, status, reason in verdicts:
        print(f"  [{status}] {name}" + (f" -- {reason}" if reason else ""))
    print(f"\n  {fail} FAIL, {warn} WARN out of {len(verdicts)} checks")
    if fail:
        print("\n  RESULT: UNSTABLE — published standings reshuffled. Investigate before publishing.\n")
        sys.exit(1)
    print("\n  RESULT: within stability thresholds\n")


if __name__ == "__main__":
    main()
