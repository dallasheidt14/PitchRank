#!/usr/bin/env python3
"""
Post-Ranking-Run Validation — Cross-Age Fix
=============================================
Runs 6 checks against the Supabase database after a ranking run completes
with the cross-age opponent adjustment fix enabled.

Checks:
  1. Phoenix United Elite sanity check
  2. Cohort-wide stability (current + vs previous snapshot)
  3. Cross-age team improvement (top 20 most helped)
  4. Playing-down deflation check (top 20 most hurt)
  5. ML residual shift (high vs low cross-age exposure)
  6. Top-of-cohort stability (top 10 churn per cohort)

Usage:
    python scripts/validate_post_ranking_run.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

# ── Setup ────────────────────────────────────────────────────────────────
sys.path.append(str(Path(__file__).resolve().parent.parent))

env_local = Path(__file__).resolve().parent.parent / ".env.local"
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Missing SUPABASE_URL or SUPABASE_KEY in environment")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Constants ────────────────────────────────────────────────────────────
PHOENIX_TEAM_ID = "691eb36d-95b2-4a08-bd59-13c1b0e830bb"
SEP = "=" * 90
THIN = "-" * 90

# Pre-fix known values for Phoenix United Elite (U12M, AZ)
PREFIX_OFF_NORM = 0.318
PREFIX_POWERSCORE_ADJ = 0.787
PREFIX_AZ_RANK = 5

# Verdict tracking
verdicts: list[tuple[str, str, str]] = []  # (check_name, verdict, reason)


# ── Helpers ──────────────────────────────────────────────────────────────

def paginated_fetch(table: str, select: str, filters: dict | None = None,
                    limit: int = 1000) -> list:
    """Fetch all rows from a Supabase table with offset-based pagination."""
    all_rows: list = []
    offset = 0
    while True:
        q = sb.table(table).select(select).range(offset, offset + limit - 1)
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        result = q.execute()
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < limit:
            break
        offset += limit
    return all_rows


def verdict(check_name: str, status: str, reason: str = ""):
    """Record and print a verdict for a check."""
    verdicts.append((check_name, status, reason))
    label = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}.get(status, status)
    msg = f"  [{label}] {check_name}"
    if reason:
        msg += f" -- {reason}"
    print(msg)


def fetch_rankings_full() -> pd.DataFrame:
    """Fetch all rows from rankings_full."""
    rows = paginated_fetch("rankings_full", "*")
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_ranking_history() -> pd.DataFrame:
    """Fetch all rows from ranking_history."""
    rows = paginated_fetch(
        "ranking_history",
        "team_id, snapshot_date, age_group, gender, rank_in_cohort, "
        "rank_in_cohort_ml, power_score_final, powerscore_ml",
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_teams_lookup() -> pd.DataFrame:
    """Fetch team metadata for name/age/gender/state lookups."""
    rows = paginated_fetch(
        "teams",
        "team_id_master, team_name, age_group, gender, state_code",
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fetch_games() -> pd.DataFrame:
    """Fetch games for cross-age exposure calculation."""
    rows = paginated_fetch(
        "games",
        "home_team_master_id, away_team_master_id",
    )
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def compute_cross_age_pct(team_ids: list[str], games_df: pd.DataFrame,
                          teams_df: pd.DataFrame) -> dict[str, float]:
    """Compute cross-age game percentage for a set of teams.

    Returns dict of team_id -> pct_cross_age (0.0-1.0).
    """
    if games_df.empty or teams_df.empty:
        return {}

    # Build age lookup from teams table
    age_map = dict(zip(
        teams_df["team_id_master"].astype(str),
        teams_df["age_group"].astype(str),
    ))

    result = {}
    for tid in team_ids:
        # Games where this team is home or away
        home_mask = games_df["home_team_master_id"].astype(str) == str(tid)
        away_mask = games_df["away_team_master_id"].astype(str) == str(tid)

        team_games = games_df[home_mask | away_mask].copy()
        if team_games.empty:
            result[str(tid)] = 0.0
            continue

        total = len(team_games)
        cross_age = 0

        team_age = age_map.get(str(tid), "")

        for _, g in team_games.iterrows():
            h_id = str(g["home_team_master_id"])
            a_id = str(g["away_team_master_id"])
            opp_id = a_id if h_id == str(tid) else h_id
            opp_age = age_map.get(opp_id, "")
            if team_age and opp_age and team_age != opp_age:
                cross_age += 1

        result[str(tid)] = cross_age / total if total > 0 else 0.0

    return result


# ── Check 1: Phoenix United Elite Sanity Check ──────────────────────────

def check_1_phoenix(rf: pd.DataFrame):
    print(f"\n{SEP}")
    print("  CHECK 1: Phoenix United Elite Sanity Check")
    print(SEP)

    row = rf[rf["team_id"].astype(str) == PHOENIX_TEAM_ID]
    if row.empty:
        verdict("Check 1: Phoenix", "FAIL", "Team not found in rankings_full")
        return
    row = row.iloc[0]

    cols = [
        "off_norm", "off_raw", "def_norm", "sos_norm",
        "powerscore_adj", "powerscore_ml", "rank_in_cohort",
        "rank_in_cohort_ml", "national_rank", "state_rank",
    ]
    print(f"\n  {'Metric':<22} {'Value':>12}")
    print(f"  {THIN}")
    for c in cols:
        val = row.get(c)
        if val is not None:
            try:
                print(f"  {c:<22} {float(val):>12.4f}")
            except (ValueError, TypeError):
                print(f"  {c:<22} {val!s:>12}")
        else:
            print(f"  {c:<22} {'N/A':>12}")

    # Compare to pre-fix values
    current_off_norm = float(row.get("off_norm", 0))
    delta_off = current_off_norm - PREFIX_OFF_NORM
    print(f"\n  Pre-fix off_norm:     {PREFIX_OFF_NORM:.3f}")
    print(f"  Current off_norm:     {current_off_norm:.4f}")
    print(f"  Delta:                {delta_off:+.4f}")

    current_ps = float(row.get("powerscore_adj", 0))
    print(f"\n  Pre-fix powerscore:   {PREFIX_POWERSCORE_ADJ:.3f}")
    print(f"  Current powerscore:   {current_ps:.4f}")

    state_rank = row.get("state_rank")
    if state_rank is not None:
        print(f"\n  Pre-fix AZ rank:      #{PREFIX_AZ_RANK}")
        print(f"  Current state rank:   #{int(state_rank)}")

    if delta_off > 0:
        verdict("Check 1: Phoenix", "PASS",
                f"off_norm improved by {delta_off:+.4f} (was {PREFIX_OFF_NORM}, now {current_off_norm:.4f})")
    elif delta_off == 0:
        verdict("Check 1: Phoenix", "WARN", "off_norm unchanged from pre-fix value")
    else:
        verdict("Check 1: Phoenix", "WARN",
                f"off_norm decreased by {delta_off:+.4f} -- may need investigation")


# ── Check 2: Cohort-Wide Stability ──────────────────────────────────────

def check_2_cohort_stability(rf: pd.DataFrame, rh: pd.DataFrame):
    print(f"\n{SEP}")
    print("  CHECK 2: Cohort-Wide Stability")
    print(SEP)

    # Current snapshot summary
    print("\n  Current rankings_full summary by cohort:\n")
    cohorts = rf.groupby(["age_group", "gender"])
    print(f"  {'Cohort':<16} {'Teams':>6} {'Mean PS_adj':>12} {'Mean off_n':>12} {'Mean def_n':>12}")
    print(f"  {THIN}")

    cohort_stats = {}
    for (ag, gen), grp in sorted(cohorts):
        n = len(grp)
        mean_ps = grp["powerscore_adj"].astype(float).mean()
        mean_off = grp["off_norm"].astype(float).mean()
        mean_def = grp["def_norm"].astype(float).mean()
        label = f"{ag}/{gen}"
        cohort_stats[(ag, gen)] = {"mean_ps_adj": mean_ps}
        print(f"  {label:<16} {n:>6} {mean_ps:>12.4f} {mean_off:>12.4f} {mean_def:>12.4f}")

    # Compare to previous snapshot in ranking_history
    if rh.empty:
        verdict("Check 2: Cohort Stability", "WARN", "No ranking_history data to compare")
        return

    rh["snapshot_date"] = pd.to_datetime(rh["snapshot_date"])
    today = pd.Timestamp.now("UTC").normalize()
    # Get the most recent snapshot BEFORE today
    prev_dates = rh[rh["snapshot_date"] < today]["snapshot_date"].unique()
    if len(prev_dates) == 0:
        verdict("Check 2: Cohort Stability", "WARN", "No previous snapshot found in ranking_history")
        return

    prev_date = max(prev_dates)
    prev_snap = rh[rh["snapshot_date"] == prev_date]
    print(f"\n  Previous snapshot date: {prev_date.date()}")

    print(f"\n  Mean powerscore_ml comparison (current vs previous):\n")
    print(f"  {'Cohort':<16} {'Prev ML':>10} {'Curr ML':>10} {'Delta':>10} {'Status':>8}")
    print(f"  {THIN}")

    any_flagged = False
    for (ag, gen), grp in sorted(cohorts):
        prev_cohort = prev_snap[
            (prev_snap["age_group"] == ag) & (prev_snap["gender"] == gen)
        ]
        if prev_cohort.empty or "powerscore_ml" not in prev_cohort.columns:
            continue

        prev_ml = prev_cohort["powerscore_ml"].astype(float).mean()
        curr_ml = grp["powerscore_ml"].astype(float).mean()
        delta = curr_ml - prev_ml
        status = "OK" if abs(delta) <= 0.01 else "FLAGGED"
        if status == "FLAGGED":
            any_flagged = True
        label = f"{ag}/{gen}"
        print(f"  {label:<16} {prev_ml:>10.4f} {curr_ml:>10.4f} {delta:>+10.4f} {status:>8}")

    if any_flagged:
        verdict("Check 2: Cohort Stability", "WARN",
                "One or more cohorts shifted mean powerscore_ml by >0.01")
    else:
        verdict("Check 2: Cohort Stability", "PASS",
                "All cohorts within 0.01 mean powerscore_ml of previous snapshot")


# ── Check 3: Cross-Age Team Improvement (Top 20 Most Helped) ────────────

def check_3_cross_age_improvement(rf: pd.DataFrame, rh: pd.DataFrame,
                                  teams_df: pd.DataFrame, games_df: pd.DataFrame):
    print(f"\n{SEP}")
    print("  CHECK 3: Cross-Age Team Improvement (Top 20 Most Helped)")
    print(SEP)

    if rh.empty:
        verdict("Check 3: Cross-Age Improvement", "WARN", "No ranking_history for comparison")
        return

    rh["snapshot_date"] = pd.to_datetime(rh["snapshot_date"])
    today = pd.Timestamp.now("UTC").normalize()
    prev_dates = rh[rh["snapshot_date"] < today]["snapshot_date"].unique()
    if len(prev_dates) == 0:
        verdict("Check 3: Cross-Age Improvement", "WARN", "No previous snapshot")
        return

    prev_date = max(prev_dates)
    prev_snap = rh[rh["snapshot_date"] == prev_date][["team_id", "rank_in_cohort"]].copy()
    prev_snap = prev_snap.rename(columns={"rank_in_cohort": "old_rank"})

    current = rf[["team_id", "age_group", "gender", "rank_in_cohort"]].copy()
    current = current.rename(columns={"rank_in_cohort": "new_rank"})

    merged = current.merge(prev_snap, on="team_id", how="inner")
    merged["old_rank"] = pd.to_numeric(merged["old_rank"], errors="coerce")
    merged["new_rank"] = pd.to_numeric(merged["new_rank"], errors="coerce")
    merged = merged.dropna(subset=["old_rank", "new_rank"])
    merged["rank_change"] = merged["old_rank"] - merged["new_rank"]  # positive = improved

    # Top 20 most improved
    top20 = merged.nlargest(20, "rank_change")

    # Get team names
    name_map = dict(zip(
        teams_df["team_id_master"].astype(str),
        teams_df["team_name"].astype(str),
    ))

    # Compute cross-age % for these teams
    team_ids = top20["team_id"].astype(str).tolist()
    cross_age_map = compute_cross_age_pct(team_ids, games_df, teams_df)

    print(f"\n  Previous snapshot: {prev_date.date()}")
    print(f"\n  {'#':<4} {'Team':<32} {'AG':<6} {'Gen':<8} {'Old':>5} {'New':>5} "
          f"{'Chg':>5} {'%XAge':>7}")
    print(f"  {THIN}")

    high_cross_age_count = 0
    for i, (_, row) in enumerate(top20.iterrows(), 1):
        tid = str(row["team_id"])
        name = name_map.get(tid, tid[:12] + "...")[:30]
        pct = cross_age_map.get(tid, 0.0)
        if pct > 0.15:
            high_cross_age_count += 1
        print(f"  {i:<4} {name:<32} {row['age_group']:<6} {row['gender']:<8} "
              f"{int(row['old_rank']):>5} {int(row['new_rank']):>5} "
              f"{int(row['rank_change']):>+5} {pct:>6.1%}")

    pct_high = high_cross_age_count / len(top20) if len(top20) > 0 else 0
    print(f"\n  {high_cross_age_count}/{len(top20)} most-improved teams have >15% cross-age exposure")

    if pct_high >= 0.5:
        verdict("Check 3: Cross-Age Improvement", "PASS",
                f"{pct_high:.0%} of most-improved teams have high cross-age exposure")
    else:
        verdict("Check 3: Cross-Age Improvement", "WARN",
                f"Only {pct_high:.0%} of most-improved teams have high cross-age exposure")


# ── Check 4: Playing-Down Deflation Check ────────────────────────────────

def check_4_deflation(rf: pd.DataFrame, rh: pd.DataFrame,
                      teams_df: pd.DataFrame, games_df: pd.DataFrame):
    print(f"\n{SEP}")
    print("  CHECK 4: Playing-Down Deflation Check (Top 20 Most Hurt)")
    print(SEP)

    if rh.empty:
        verdict("Check 4: Deflation Check", "WARN", "No ranking_history for comparison")
        return

    rh["snapshot_date"] = pd.to_datetime(rh["snapshot_date"])
    today = pd.Timestamp.now("UTC").normalize()
    prev_dates = rh[rh["snapshot_date"] < today]["snapshot_date"].unique()
    if len(prev_dates) == 0:
        verdict("Check 4: Deflation Check", "WARN", "No previous snapshot")
        return

    prev_date = max(prev_dates)
    prev_snap = rh[rh["snapshot_date"] == prev_date][["team_id", "rank_in_cohort"]].copy()
    prev_snap = prev_snap.rename(columns={"rank_in_cohort": "old_rank"})

    current = rf[["team_id", "age_group", "gender", "rank_in_cohort"]].copy()
    current = current.rename(columns={"rank_in_cohort": "new_rank"})

    merged = current.merge(prev_snap, on="team_id", how="inner")
    merged["old_rank"] = pd.to_numeric(merged["old_rank"], errors="coerce")
    merged["new_rank"] = pd.to_numeric(merged["new_rank"], errors="coerce")
    merged = merged.dropna(subset=["old_rank", "new_rank"])
    merged["rank_drop"] = merged["new_rank"] - merged["old_rank"]  # positive = worsened

    # Top 20 most dropped
    top20 = merged.nlargest(20, "rank_drop")

    name_map = dict(zip(
        teams_df["team_id_master"].astype(str),
        teams_df["team_name"].astype(str),
    ))

    team_ids = top20["team_id"].astype(str).tolist()
    cross_age_map = compute_cross_age_pct(team_ids, games_df, teams_df)

    print(f"\n  Previous snapshot: {prev_date.date()}")
    print(f"\n  {'#':<4} {'Team':<32} {'AG':<6} {'Gen':<8} {'Old':>5} {'New':>5} "
          f"{'Drop':>5} {'%XAge':>7}")
    print(f"  {THIN}")

    flagged_teams = []
    for i, (_, row) in enumerate(top20.iterrows(), 1):
        tid = str(row["team_id"])
        name = name_map.get(tid, tid[:12] + "...")[:30]
        pct = cross_age_map.get(tid, 0.0)
        drop = int(row["rank_drop"])
        flag = ""
        if pct < 0.05 and drop > 50:
            flag = " ** FLAGGED"
            flagged_teams.append(name)
        print(f"  {i:<4} {name:<32} {row['age_group']:<6} {row['gender']:<8} "
              f"{int(row['old_rank']):>5} {int(row['new_rank']):>5} "
              f"{drop:>+5} {pct:>6.1%}{flag}")

    if flagged_teams:
        verdict("Check 4: Deflation Check", "FAIL",
                f"{len(flagged_teams)} team(s) with <5% cross-age dropped 50+ positions")
    else:
        verdict("Check 4: Deflation Check", "PASS",
                "No teams with <5% cross-age exposure dropped 50+ positions")


# ── Check 5: ML Residual Shift ──────────────────────────────────────────

def check_5_ml_residual(rf: pd.DataFrame, teams_df: pd.DataFrame,
                        games_df: pd.DataFrame):
    print(f"\n{SEP}")
    print("  CHECK 5: ML Residual Shift (ml_overperf by Cross-Age Exposure)")
    print(SEP)

    if "ml_overperf" not in rf.columns:
        verdict("Check 5: ML Residual", "WARN", "ml_overperf column not found in rankings_full")
        return

    # Compute cross-age % for all teams in rankings_full
    all_team_ids = rf["team_id"].astype(str).tolist()
    cross_age_map = compute_cross_age_pct(all_team_ids, games_df, teams_df)

    rf = rf.copy()
    rf["pct_cross_age"] = rf["team_id"].astype(str).map(cross_age_map).fillna(0.0)
    rf["ml_overperf"] = pd.to_numeric(rf["ml_overperf"], errors="coerce")

    high = rf[rf["pct_cross_age"] > 0.30]
    low = rf[rf["pct_cross_age"] < 0.05]

    high_mean = high["ml_overperf"].mean() if not high.empty else float("nan")
    low_mean = low["ml_overperf"].mean() if not low.empty else float("nan")

    print(f"\n  High cross-age exposure (>30%): {len(high)} teams, "
          f"mean ml_overperf = {high_mean:.4f}")
    print(f"  Low cross-age exposure (<5%):   {len(low)} teams, "
          f"mean ml_overperf = {low_mean:.4f}")

    if pd.notna(high_mean) and pd.notna(low_mean):
        diff = high_mean - low_mean
        print(f"  Difference (high - low):        {diff:+.4f}")

    if pd.notna(high_mean) and high_mean > 0.5:
        verdict("Check 5: ML Residual", "WARN",
                f"High-cross-age teams still have unusually high ml_overperf ({high_mean:.4f} > 0.5)")
    elif pd.isna(high_mean):
        verdict("Check 5: ML Residual", "WARN", "No teams with >30% cross-age exposure found")
    else:
        verdict("Check 5: ML Residual", "PASS",
                f"High-cross-age ml_overperf ({high_mean:.4f}) is within normal range (<= 0.5)")


# ── Check 6: Top-of-Cohort Stability ────────────────────────────────────

def check_6_top_stability(rf: pd.DataFrame, rh: pd.DataFrame):
    print(f"\n{SEP}")
    print("  CHECK 6: Top-of-Cohort Stability (Top 10 Churn)")
    print(SEP)

    if rh.empty:
        verdict("Check 6: Top Stability", "WARN", "No ranking_history for comparison")
        return

    rh["snapshot_date"] = pd.to_datetime(rh["snapshot_date"])
    today = pd.Timestamp.now("UTC").normalize()
    prev_dates = rh[rh["snapshot_date"] < today]["snapshot_date"].unique()
    if len(prev_dates) == 0:
        verdict("Check 6: Top Stability", "WARN", "No previous snapshot")
        return

    prev_date = max(prev_dates)
    prev_snap = rh[rh["snapshot_date"] == prev_date]

    # Use powerscore_adj for current top 10; fall back to power_score_final
    score_col = "powerscore_adj"
    if score_col not in rf.columns:
        score_col = "power_score_final"
    if score_col not in rf.columns:
        verdict("Check 6: Top Stability", "FAIL",
                "Neither powerscore_adj nor power_score_final found in rankings_full")
        return

    cohorts = rf.groupby(["age_group", "gender"])

    print(f"\n  Previous snapshot: {prev_date.date()}")
    print(f"\n  {'Cohort':<16} {'Retained':>10} {'Status':>8}")
    print(f"  {THIN}")

    any_flagged = False
    for (ag, gen), grp in sorted(cohorts):
        # Current top 10
        grp_sorted = grp.sort_values(score_col, ascending=False).head(10)
        current_top10_ids = set(grp_sorted["team_id"].astype(str).tolist())

        # Previous top 10 by rank_in_cohort
        prev_cohort = prev_snap[
            (prev_snap["age_group"] == ag) & (prev_snap["gender"] == gen)
        ]
        if prev_cohort.empty:
            continue

        prev_cohort_sorted = prev_cohort.sort_values(
            "rank_in_cohort", ascending=True
        ).head(10)
        prev_top10_ids = set(prev_cohort_sorted["team_id"].astype(str).tolist())

        retained = len(current_top10_ids & prev_top10_ids)
        status = "OK" if retained >= 6 else "FLAGGED"
        if status == "FLAGGED":
            any_flagged = True
        label = f"{ag}/{gen}"
        print(f"  {label:<16} {retained:>7}/10 {status:>8}")

    if any_flagged:
        verdict("Check 6: Top Stability", "WARN",
                "One or more cohorts had <6/10 top-team retention")
    else:
        verdict("Check 6: Top Stability", "PASS",
                "All cohorts retained >= 6/10 top teams from previous snapshot")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print(f"\n{SEP}")
    print("  Post-Ranking-Run Validation — Cross-Age Fix")
    print(SEP)

    # ── Fetch data ───────────────────────────────────────────────────
    print("\n  Fetching rankings_full...")
    rf = fetch_rankings_full()
    if rf.empty:
        print("  ERROR: rankings_full is empty. Aborting.")
        sys.exit(1)
    print(f"  Loaded {len(rf):,} rows from rankings_full")

    print("  Fetching ranking_history...")
    rh = fetch_ranking_history()
    print(f"  Loaded {len(rh):,} rows from ranking_history")

    print("  Fetching teams...")
    teams_df = fetch_teams_lookup()
    print(f"  Loaded {len(teams_df):,} rows from teams")

    print("  Fetching games...")
    games_df = fetch_games()
    print(f"  Loaded {len(games_df):,} rows from games")

    # ── Run checks ───────────────────────────────────────────────────
    check_1_phoenix(rf)
    check_2_cohort_stability(rf, rh)
    check_3_cross_age_improvement(rf, rh, teams_df, games_df)
    check_4_deflation(rf, rh, teams_df, games_df)
    check_5_ml_residual(rf, teams_df, games_df)
    check_6_top_stability(rf, rh)

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  VALIDATION SUMMARY")
    print(SEP)

    pass_count = sum(1 for _, s, _ in verdicts if s == "PASS")
    warn_count = sum(1 for _, s, _ in verdicts if s == "WARN")
    fail_count = sum(1 for _, s, _ in verdicts if s == "FAIL")

    for name, status, reason in verdicts:
        tag = f"[{status}]"
        line = f"  {tag:<8} {name}"
        if reason:
            line += f" -- {reason}"
        print(line)

    print(f"\n  Total: {pass_count} PASS, {warn_count} WARN, {fail_count} FAIL "
          f"(out of {len(verdicts)} checks)")

    if fail_count > 0:
        print("\n  RESULT: FAILURES DETECTED -- review flagged checks above")
        sys.exit(1)
    elif warn_count > 0:
        print("\n  RESULT: PASSED WITH WARNINGS -- review flagged checks above")
    else:
        print("\n  RESULT: ALL CHECKS PASSED")

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    main()
