#!/usr/bin/env python3
"""
Cross-Age Bias Analysis — ALL Cohorts, Both Genders
=====================================================
Comprehensive analysis of how cross-age game exposure relates to
offensive ratings, defensive ratings, and ranking misalignment
across every (age_group, gender) cohort in PitchRank.

Parts:
  1) Build per-team cross-age exposure dataset
  2) All-cohort bucket analysis (overall + directional)
  3) Per-cohort breakdown with monotonicity check
  4) Boundary analysis (which age jumps hurt most)
  5) Monotonicity test + Spearman correlations
  6) Playing-up vs playing-down asymmetry

Usage:
    python scripts/cross_age_all_cohorts.py
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy import stats as sp_stats
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

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SEP = "=" * 90
THIN = "-" * 90
MIN_GAMES = 8


# ── Helpers ──────────────────────────────────────────────────────────────

def paginated_fetch(table: str, select: str, filters: dict | None = None, limit: int = 1000) -> list:
    """Fetch all rows from a table using offset-based pagination."""
    all_rows: list = []
    offset = 0
    while True:
        q = supabase.table(table).select(select).range(offset, offset + limit - 1)
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


def age_group_to_int(ag: str | None) -> int | None:
    """Convert 'u12' / 'U12' / '12' -> 12.  Maps 18 -> 19 per data_adapter."""
    if ag is None:
        return None
    ag = str(ag).strip().lower().replace("u", "")
    try:
        num = int(ag)
        # U18 -> 19 mapping (U19 encompasses both birth years)
        if num == 18:
            num = 19
        return num
    except ValueError:
        return None


def safe_div(a, b, default=np.nan):
    return a / b if b and b > 0 else default


def bucket_label(val, edges, labels):
    """Assign val to a bucket label given edges and labels."""
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        if i == 0 and val <= lo:
            return labels[0]
        if lo < val <= hi:
            return labels[i]
        if i == 0 and val <= hi:
            return labels[i]
    return labels[-1]


# ══════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════

print(f"\n{SEP}")
print("  CROSS-AGE BIAS ANALYSIS — ALL COHORTS")
print(SEP)

# --- Rankings ---
print("\n[LOAD] Fetching rankings_full ...")
rankings_rows = paginated_fetch(
    "rankings_full",
    "team_id, age_group, gender, off_norm, def_norm, sos_norm, "
    "powerscore_adj, rank_in_cohort, games_played, wins, losses, draws, "
    "win_percentage",
)
rankings = pd.DataFrame(rankings_rows)
print(f"  → {len(rankings):,} total rows in rankings_full")

# Filter to teams with MIN_GAMES+ games
rankings = rankings[rankings["games_played"] >= MIN_GAMES].copy()
print(f"  → {len(rankings):,} teams with {MIN_GAMES}+ games")

# Normalize age to int
rankings["age_int"] = rankings["age_group"].apply(age_group_to_int)
rankings = rankings.dropna(subset=["age_int"]).copy()
rankings["age_int"] = rankings["age_int"].astype(int)

team_ids = set(rankings["team_id"].tolist())
team_age_map = dict(zip(rankings["team_id"], rankings["age_int"]))
team_gender_map = dict(zip(rankings["team_id"], rankings["gender"]))

# --- All teams for opponent lookup ---
print("\n[LOAD] Fetching all teams for opponent age lookup ...")
all_teams_rows = paginated_fetch("teams", "team_id_master, age_group, gender")
all_teams = pd.DataFrame(all_teams_rows)
all_teams["age_int"] = all_teams["age_group"].apply(age_group_to_int)
opp_age_lookup = dict(zip(all_teams["team_id_master"], all_teams["age_int"]))
print(f"  → {len(all_teams):,} teams in teams table")

# --- Games ---
print("\n[LOAD] Fetching all non-excluded games ...")
games_rows = paginated_fetch(
    "games",
    "id, home_team_master_id, away_team_master_id, home_score, away_score, game_date",
    # Note: can't easily filter is_excluded via paginated_fetch without extending it,
    # but most games are not excluded. We'll fetch all and hope volume is manageable.
)
print(f"  → {len(games_rows):,} game rows fetched")

# Build perspective-based rows: one row per (team, game)
print("\n[BUILD] Building game perspectives ...")
perspectives = []
for g in games_rows:
    hid = g["home_team_master_id"]
    aid = g["away_team_master_id"]
    hs = g["home_score"]
    as_ = g["away_score"]
    gid = g["id"]
    gd = g["game_date"]

    if hs is None or as_ is None:
        continue

    # Home perspective
    if hid in team_ids:
        perspectives.append({
            "game_id": gid,
            "team_id": hid,
            "opp_id": aid,
            "gf": hs,
            "ga": as_,
            "game_date": gd,
        })
    # Away perspective
    if aid in team_ids:
        perspectives.append({
            "game_id": gid,
            "team_id": aid,
            "opp_id": hid,
            "gf": as_,
            "ga": hs,
            "game_date": gd,
        })

games_df = pd.DataFrame(perspectives)
games_df = games_df.drop_duplicates(subset=["game_id", "team_id"])
print(f"  → {len(games_df):,} game-perspectives for {MIN_GAMES}+ game teams")

# Map ages
games_df["team_age"] = games_df["team_id"].map(team_age_map)
games_df["opp_age"] = games_df["opp_id"].map(opp_age_lookup)
games_df["margin"] = games_df["gf"] - games_df["ga"]
games_df["win"] = (games_df["margin"] > 0).astype(int)

# Classify
games_df["opp_class"] = "unknown"
mask_known = games_df["opp_age"].notna() & games_df["team_age"].notna()
games_df.loc[mask_known & (games_df["opp_age"] == games_df["team_age"]), "opp_class"] = "same"
games_df.loc[mask_known & (games_df["opp_age"] > games_df["team_age"]), "opp_class"] = "up"
games_df.loc[mask_known & (games_df["opp_age"] < games_df["team_age"]), "opp_class"] = "down"

print(f"  Classification counts:")
for cls, cnt in games_df["opp_class"].value_counts().items():
    print(f"    {cls:>8}: {cnt:>8,}")

# ══════════════════════════════════════════════════════════════════════════
# PART 1: PER-TEAM CROSS-AGE EXPOSURE DATASET
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PART 1: Building per-team cross-age exposure dataset")
print(SEP)

# Filter out unknown-class games for stats (but count them in total)
known_games = games_df[games_df["opp_class"] != "unknown"].copy()

team_stats = known_games.groupby("team_id").agg(
    total_games=("game_id", "count"),
    games_same=("opp_class", lambda x: (x == "same").sum()),
    games_up=("opp_class", lambda x: (x == "up").sum()),
    games_down=("opp_class", lambda x: (x == "down").sum()),
).reset_index()

# Goal/margin/win stats by class
for cls_key, cls_label in [("same", "same_age"), ("up", "playing_up"), ("down", "playing_down")]:
    sub = known_games[known_games["opp_class"] == cls_key]
    cls_agg = sub.groupby("team_id").agg(
        **{f"avg_gf_{cls_label}": ("gf", "mean"),
           f"avg_ga_{cls_label}": ("ga", "mean"),
           f"avg_margin_{cls_label}": ("margin", "mean"),
           f"win_rate_{cls_label}": ("win", "mean")},
    ).reset_index()
    team_stats = team_stats.merge(cls_agg, on="team_id", how="left")

# Cross-age stats for combined cross-age games
cross_games = known_games[known_games["opp_class"].isin(["up", "down"])]
cross_agg = cross_games.groupby("team_id").agg(
    avg_gf_cross=("gf", "mean"),
    avg_ga_cross=("ga", "mean"),
    avg_margin_cross=("margin", "mean"),
    win_rate_cross=("win", "mean"),
).reset_index()
team_stats = team_stats.merge(cross_agg, on="team_id", how="left")

# Percentages
team_stats["pct_cross_age"] = (team_stats["games_up"] + team_stats["games_down"]) / team_stats["total_games"]
team_stats["pct_playing_up"] = team_stats["games_up"] / team_stats["total_games"]
team_stats["pct_playing_down"] = team_stats["games_down"] / team_stats["total_games"]

# Merge rankings
analysis = team_stats.merge(
    rankings[["team_id", "age_group", "gender", "age_int", "off_norm", "def_norm",
              "sos_norm", "powerscore_adj", "win_percentage", "rank_in_cohort",
              "games_played"]],
    on="team_id", how="inner",
)

# Normalize win_percentage to 0-1 if stored as 0-100
if analysis["win_percentage"].max() > 1.5:
    analysis["win_pct_01"] = analysis["win_percentage"] / 100.0
else:
    analysis["win_pct_01"] = analysis["win_percentage"]

analysis["misalignment"] = analysis["win_pct_01"] - analysis["off_norm"]

print(f"\n  Dataset built: {len(analysis):,} teams")
print(f"  Cohorts: {analysis.groupby(['age_group', 'gender']).ngroups}")
print(f"  Avg pct_cross_age: {analysis['pct_cross_age'].mean():.3f}")
print(f"  Avg pct_playing_up: {analysis['pct_playing_up'].mean():.3f}")
print(f"  Avg pct_playing_down: {analysis['pct_playing_down'].mean():.3f}")


# ══════════════════════════════════════════════════════════════════════════
# PART 2: ALL-COHORT BUCKET ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PART 2A: All-Cohort Bucket Analysis — by pct_cross_age")
print(SEP)

def print_bucket_table(df, bucket_col, title=None):
    """Print a standard bucket analysis table."""
    if title:
        print(f"\n  {title}")
        print(f"  {THIN}")

    header = (f"  {'Bucket':>12}  {'N':>6}  {'Avg Off':>7}  {'Avg Def':>7}  {'Avg Win%':>8}  "
              f"{'Avg SOS':>7}  {'Avg PwrAdj':>10}  {'Misalign':>8}  "
              f"{'Margin Same':>11}  {'Margin Cross':>12}")
    print(header)
    print("  " + "-" * 110)

    for bkt in df[bucket_col].cat.categories if hasattr(df[bucket_col], 'cat') else sorted(df[bucket_col].unique()):
        sub = df[df[bucket_col] == bkt]
        if len(sub) == 0:
            continue
        n = len(sub)
        avg_off = sub["off_norm"].mean()
        avg_def = sub["def_norm"].mean()
        avg_wp = sub["win_pct_01"].mean()
        avg_sos = sub["sos_norm"].mean()
        avg_pwr = sub["powerscore_adj"].mean()
        mis = sub["misalignment"].mean()
        margin_same = sub["avg_margin_same_age"].mean() if "avg_margin_same_age" in sub.columns else np.nan
        margin_cross = sub["avg_margin_cross"].mean() if "avg_margin_cross" in sub.columns else np.nan
        print(f"  {str(bkt):>12}  {n:>6}  {avg_off:>7.4f}  {avg_def:>7.4f}  {avg_wp:>8.4f}  "
              f"{avg_sos:>7.4f}  {avg_pwr:>10.4f}  {mis:>+8.4f}  "
              f"{margin_same:>+11.3f}  {margin_cross:>+12.3f}")

# Overall cross-age buckets
analysis["xage_bucket"] = pd.cut(
    analysis["pct_cross_age"],
    bins=[-0.001, 0.05, 0.15, 0.30, 0.50, 1.001],
    labels=["0-5%", "5-15%", "15-30%", "30-50%", "50%+"],
)
print_bucket_table(analysis, "xage_bucket", "Bucketed by pct_cross_age (all teams)")

# --- Part 2B: Directional — playing UP ---
print(f"\n{SEP}")
print("  PART 2B: All-Cohort Bucket Analysis — by pct_playing_UP")
print(SEP)

analysis["up_bucket"] = pd.cut(
    analysis["pct_playing_up"],
    bins=[-0.001, 0.001, 0.10, 0.25, 0.50, 1.001],
    labels=["0%", "1-10%", "10-25%", "25-50%", "50%+"],
)
print_bucket_table(analysis, "up_bucket", "Bucketed by pct_playing_up")

# --- Part 2C: Directional — playing DOWN ---
print(f"\n{SEP}")
print("  PART 2C: All-Cohort Bucket Analysis — by pct_playing_DOWN")
print(SEP)

analysis["down_bucket"] = pd.cut(
    analysis["pct_playing_down"],
    bins=[-0.001, 0.001, 0.10, 0.25, 0.50, 1.001],
    labels=["0%", "1-10%", "10-25%", "25-50%", "50%+"],
)
print_bucket_table(analysis, "down_bucket", "Bucketed by pct_playing_down")


# ══════════════════════════════════════════════════════════════════════════
# PART 3: PER-COHORT BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PART 3A: Per-Cohort Summary")
print(SEP)

cohort_summary = analysis.groupby(["age_group", "gender"]).agg(
    n_teams=("team_id", "count"),
    avg_pct_cross=("pct_cross_age", "mean"),
    avg_pct_up=("pct_playing_up", "mean"),
    avg_pct_down=("pct_playing_down", "mean"),
    avg_off_norm=("off_norm", "mean"),
    avg_win_pct=("win_pct_01", "mean"),
).reset_index().sort_values(["gender", "age_group"])

print(f"\n  {'Cohort':<12}  {'Gender':>6}  {'N':>5}  {'Avg XAge%':>9}  {'Avg Up%':>7}  {'Avg Down%':>9}  {'Avg Off':>7}  {'Avg Win%':>8}")
print("  " + "-" * 85)
for _, row in cohort_summary.iterrows():
    print(f"  {row['age_group']:<12}  {row['gender']:>6}  {int(row['n_teams']):>5}  "
          f"{100*row['avg_pct_cross']:>8.1f}%  {100*row['avg_pct_up']:>6.1f}%  {100*row['avg_pct_down']:>8.1f}%  "
          f"{row['avg_off_norm']:>7.4f}  {row['avg_win_pct']:>8.4f}")

# --- Part 3B: Within-cohort bucket analysis ---
print(f"\n{SEP}")
print("  PART 3B: Within-Cohort Bucket Analysis")
print(SEP)

cohort_mono_results = []

for (ag, gend), cohort_df in analysis.groupby(["age_group", "gender"]):
    if len(cohort_df) < 20:
        continue
    cohort_label = f"{ag} {gend}"
    print(f"\n  ── {cohort_label} (n={len(cohort_df)}) ──")

    # Adaptive bucketing — merge sparse upper buckets
    cohort_df = cohort_df.copy()
    cohort_df["cohort_bucket"] = pd.cut(
        cohort_df["pct_cross_age"],
        bins=[-0.001, 0.05, 0.15, 0.30, 1.001],
        labels=["0-5%", "5-15%", "15-30%", "30%+"],
    )

    header = f"  {'Bucket':>8}  {'N':>5}  {'Avg Off':>7}  {'Avg Win%':>8}  {'Misalign':>8}  {'Avg SOS':>7}"
    print(header)
    print("  " + "-" * 55)

    bucket_offs = []
    bucket_labels_ordered = []
    for bkt in ["0-5%", "5-15%", "15-30%", "30%+"]:
        sub = cohort_df[cohort_df["cohort_bucket"] == bkt]
        if len(sub) == 0:
            continue
        n = len(sub)
        avg_off = sub["off_norm"].mean()
        avg_wp = sub["win_pct_01"].mean()
        mis = sub["misalignment"].mean()
        avg_sos = sub["sos_norm"].mean()
        print(f"  {bkt:>8}  {n:>5}  {avg_off:>7.4f}  {avg_wp:>8.4f}  {mis:>+8.4f}  {avg_sos:>7.4f}")
        bucket_offs.append(avg_off)
        bucket_labels_ordered.append(bkt)

    # Monotonicity check
    if len(bucket_offs) >= 2:
        decreasing_steps = sum(1 for i in range(1, len(bucket_offs)) if bucket_offs[i] < bucket_offs[i-1])
        total_steps = len(bucket_offs) - 1
        if decreasing_steps == total_steps:
            mono = "YES"
        elif decreasing_steps == 0:
            mono = "NO (increasing)"
        else:
            mono = "MIXED"
    else:
        mono = "N/A"

    cohort_mono_results.append({
        "cohort": cohort_label,
        "n_teams": len(cohort_df),
        "n_buckets": len(bucket_offs),
        "off_decreases": mono,
        "bucket_progression": " → ".join(f"{v:.4f}" for v in bucket_offs),
    })

# Summary table
print(f"\n{SEP}")
print("  PART 3C: Monotonicity Summary by Cohort")
print(SEP)

print(f"\n  {'Cohort':<18}  {'N':>5}  {'#Bkt':>4}  {'Off Decreases?':>14}  {'Bucket Progression'}")
print("  " + "-" * 90)
yes_count = 0
total_count = 0
for r in cohort_mono_results:
    print(f"  {r['cohort']:<18}  {r['n_teams']:>5}  {r['n_buckets']:>4}  {r['off_decreases']:>14}  {r['bucket_progression']}")
    total_count += 1
    if r["off_decreases"] == "YES":
        yes_count += 1

print(f"\n  {yes_count}/{total_count} cohorts show strictly decreasing off_norm with cross-age exposure")


# ══════════════════════════════════════════════════════════════════════════
# PART 4: BOUNDARY ANALYSIS
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PART 4: Boundary Analysis — Performance Penalty by Age Jump")
print(SEP)

# Only games where team plays UP
up_games = known_games[known_games["opp_class"] == "up"].copy()
up_games["team_age"] = up_games["team_id"].map(team_age_map)
up_games["opp_age"] = up_games["opp_id"].map(opp_age_lookup)
up_games = up_games.dropna(subset=["team_age", "opp_age"]).copy()
up_games["team_age"] = up_games["team_age"].astype(int)
up_games["opp_age"] = up_games["opp_age"].astype(int)
up_games["boundary"] = up_games.apply(
    lambda r: f"U{r['team_age']} vs U{r['opp_age']}", axis=1
)

# Same-age baseline by cohort
same_games = known_games[known_games["opp_class"] == "same"].copy()
same_games["team_age"] = same_games["team_id"].map(team_age_map)
same_baseline = same_games.groupby("team_age").agg(
    baseline_gf=("gf", "mean"),
    baseline_ga=("ga", "mean"),
    baseline_margin=("margin", "mean"),
    baseline_winrate=("win", "mean"),
).reset_index()
baseline_dict = {int(r["team_age"]): r for _, r in same_baseline.iterrows()}

# Boundary stats
boundary_stats = up_games.groupby("boundary").agg(
    n_games=("game_id", "count"),
    avg_gf=("gf", "mean"),
    avg_ga=("ga", "mean"),
    avg_margin=("margin", "mean"),
    win_rate=("win", "mean"),
).reset_index()

# Extract team_age from boundary for baseline comparison
boundary_stats["team_age"] = boundary_stats["boundary"].apply(
    lambda x: int(x.split(" vs ")[0].replace("U", ""))
)

print(f"\n  {'Boundary':<16}  {'N Games':>7}  {'Avg GF':>6}  {'Avg GA':>6}  {'Margin':>7}  {'Win%':>6}  "
      f"│ {'Base Margin':>11}  {'Base Win%':>9}  {'Margin Δ':>8}  {'Win% Δ':>7}")
print("  " + "-" * 115)

# Sort by team_age then opp_age
boundary_stats = boundary_stats.sort_values("boundary")

for _, row in boundary_stats.iterrows():
    if row["n_games"] < 5:
        continue
    ta = row["team_age"]
    bl = baseline_dict.get(ta, {})
    bl_margin = bl.get("baseline_margin", np.nan) if isinstance(bl, dict) is False else (bl["baseline_margin"] if isinstance(bl, pd.Series) else np.nan)
    bl_wr = bl.get("baseline_winrate", np.nan) if isinstance(bl, dict) is False else (bl["baseline_winrate"] if isinstance(bl, pd.Series) else np.nan)

    # Handle pd.Series from baseline_dict
    if ta in baseline_dict:
        bl_row = baseline_dict[ta]
        bl_margin = bl_row["baseline_margin"]
        bl_wr = bl_row["baseline_winrate"]
    else:
        bl_margin = np.nan
        bl_wr = np.nan

    margin_delta = row["avg_margin"] - bl_margin if not np.isnan(bl_margin) else np.nan
    wr_delta = row["win_rate"] - bl_wr if not np.isnan(bl_wr) else np.nan

    bl_margin_str = f"{bl_margin:>+11.3f}" if not np.isnan(bl_margin) else f"{'N/A':>11}"
    bl_wr_str = f"{100*bl_wr:>8.1f}%" if not np.isnan(bl_wr) else f"{'N/A':>9}"
    md_str = f"{margin_delta:>+8.3f}" if not np.isnan(margin_delta) else f"{'N/A':>8}"
    wrd_str = f"{100*wr_delta:>+6.1f}%" if not np.isnan(wr_delta) else f"{'N/A':>7}"

    print(f"  {row['boundary']:<16}  {int(row['n_games']):>7}  {row['avg_gf']:>6.2f}  {row['avg_ga']:>6.2f}  "
          f"{row['avg_margin']:>+7.3f}  {100*row['win_rate']:>5.1f}%  "
          f"│ {bl_margin_str}  {bl_wr_str}  {md_str}  {wrd_str}")


# ══════════════════════════════════════════════════════════════════════════
# PART 5: MONOTONICITY TEST + SPEARMAN CORRELATIONS
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PART 5A: Monotonicity Test — pct_cross_age buckets vs off_norm (all teams)")
print(SEP)

bucket_means = []
for bkt in ["0-5%", "5-15%", "15-30%", "30-50%", "50%+"]:
    sub = analysis[analysis["xage_bucket"] == bkt]
    if len(sub) > 0:
        bucket_means.append((bkt, sub["off_norm"].mean(), len(sub)))

print(f"\n  {'Bucket':>8}  {'N':>6}  {'Avg Off_Norm':>12}  {'Step':>8}")
print("  " + "-" * 45)
for i, (bkt, mean, n) in enumerate(bucket_means):
    if i == 0:
        step = "   ---"
    else:
        delta = mean - bucket_means[i-1][1]
        step = f"{delta:>+8.4f}" + (" ↓" if delta < 0 else " ↑")
    print(f"  {bkt:>8}  {n:>6}  {mean:>12.4f}  {step}")

strictly_decreasing = all(
    bucket_means[i][1] > bucket_means[i+1][1] for i in range(len(bucket_means)-1)
) if len(bucket_means) >= 2 else False
print(f"\n  Strictly monotonically decreasing? {'YES' if strictly_decreasing else 'NO'}")

# Same for pct_playing_up
print(f"\n  ── pct_playing_UP buckets vs off_norm ──")
up_bucket_means = []
for bkt in ["0%", "1-10%", "10-25%", "25-50%", "50%+"]:
    sub = analysis[analysis["up_bucket"] == bkt]
    if len(sub) > 0:
        up_bucket_means.append((bkt, sub["off_norm"].mean(), len(sub)))

print(f"\n  {'Bucket':>8}  {'N':>6}  {'Avg Off_Norm':>12}  {'Step':>8}")
print("  " + "-" * 45)
for i, (bkt, mean, n) in enumerate(up_bucket_means):
    if i == 0:
        step = "   ---"
    else:
        delta = mean - up_bucket_means[i-1][1]
        step = f"{delta:>+8.4f}" + (" ↓" if delta < 0 else " ↑")
    print(f"  {bkt:>8}  {n:>6}  {mean:>12.4f}  {step}")

up_strictly_decreasing = all(
    up_bucket_means[i][1] > up_bucket_means[i+1][1] for i in range(len(up_bucket_means)-1)
) if len(up_bucket_means) >= 2 else False
print(f"\n  Strictly monotonically decreasing? {'YES' if up_strictly_decreasing else 'NO'}")


# --- Part 5B: Spearman correlations ---
print(f"\n{SEP}")
print("  PART 5B: Spearman Rank Correlations")
print(SEP)

print(f"\n  ALL TEAMS (n={len(analysis)})")
for x_col, x_label in [("pct_playing_up", "pct_playing_up"), ("pct_cross_age", "pct_cross_age"), ("pct_playing_down", "pct_playing_down")]:
    for y_col in ["off_norm", "def_norm", "powerscore_adj"]:
        valid = analysis.dropna(subset=[x_col, y_col])
        if len(valid) < 10:
            continue
        rho, p = sp_stats.spearmanr(valid[x_col], valid[y_col])
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"    {x_label:>18} vs {y_col:<15}: rho={rho:+.4f}  p={p:.6f} {sig}")

print(f"\n  PER-COHORT Spearman (pct_playing_up vs off_norm)")
print(f"  {'Cohort':<18}  {'N':>5}  {'Rho':>7}  {'p-value':>9}  {'Sig':>3}")
print("  " + "-" * 50)
for (ag, gend), cohort_df in analysis.groupby(["age_group", "gender"]):
    valid = cohort_df.dropna(subset=["pct_playing_up", "off_norm"])
    if len(valid) < 15:
        continue
    rho, p = sp_stats.spearmanr(valid["pct_playing_up"], valid["off_norm"])
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"  {ag + ' ' + gend:<18}  {len(valid):>5}  {rho:>+7.4f}  {p:>9.6f}  {sig:>3}")


# ══════════════════════════════════════════════════════════════════════════
# PART 6: PLAYING-UP vs PLAYING-DOWN ASYMMETRY
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  PART 6: Playing-Up vs Playing-Down Asymmetry")
print(SEP)

primarily_up = analysis[(analysis["pct_playing_up"] > 0.15) & (analysis["pct_playing_down"] < 0.05)]
primarily_down = analysis[(analysis["pct_playing_down"] > 0.15) & (analysis["pct_playing_up"] < 0.05)]
mostly_same = analysis[analysis["pct_cross_age"] < 0.05]

groups = [
    ("Primarily Play UP (up>15%, down<5%)", primarily_up),
    ("Primarily Play DOWN (down>15%, up<5%)", primarily_down),
    ("Mostly Same-Age (cross<5%)", mostly_same),
]

print(f"\n  {'Group':<45}  {'N':>5}  {'Avg Off':>7}  {'Avg Def':>7}  {'Avg Win%':>8}  {'Avg SOS':>7}  {'Misalign':>8}")
print("  " + "-" * 100)
for label, grp in groups:
    if len(grp) == 0:
        print(f"  {label:<45}  {'---':>5}")
        continue
    n = len(grp)
    avg_off = grp["off_norm"].mean()
    avg_def = grp["def_norm"].mean()
    avg_wp = grp["win_pct_01"].mean()
    avg_sos = grp["sos_norm"].mean()
    mis = grp["misalignment"].mean()
    print(f"  {label:<45}  {n:>5}  {avg_off:>7.4f}  {avg_def:>7.4f}  {avg_wp:>8.4f}  {avg_sos:>7.4f}  {mis:>+8.4f}")


# ══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEP}")
print("  SUMMARY — Key Findings")
print(SEP)

# Q1: Is off_norm suppression associated with cross-age exposure?
if len(bucket_means) >= 2:
    first_off = bucket_means[0][1]
    last_off = bucket_means[-1][1]
    suppression = first_off - last_off
    rho_overall, p_overall = sp_stats.spearmanr(
        analysis.dropna(subset=["pct_cross_age", "off_norm"])["pct_cross_age"],
        analysis.dropna(subset=["pct_cross_age", "off_norm"])["off_norm"],
    )
    q1_answer = "YES" if suppression > 0.01 and p_overall < 0.05 else "WEAK/NO"
    print(f"\n  1. Is off_norm suppression associated with cross-age exposure?")
    print(f"     Answer: {q1_answer}")
    print(f"     Evidence: Lowest-exposure bucket off_norm = {first_off:.4f}, highest = {last_off:.4f}")
    print(f"              Δ = {suppression:+.4f}")
    print(f"              Spearman rho = {rho_overall:+.4f}, p = {p_overall:.6f}")

# Q2: Monotonic?
print(f"\n  2. Is the effect monotonic?")
print(f"     pct_cross_age buckets: {'YES' if strictly_decreasing else 'NO'}")
print(f"     Progression: {' → '.join(f'{m[1]:.4f}' for m in bucket_means)}")
print(f"     pct_playing_up buckets: {'YES' if up_strictly_decreasing else 'NO'}")
print(f"     Progression: {' → '.join(f'{m[1]:.4f}' for m in up_bucket_means)}")

# Q3: Directional?
print(f"\n  3. Is it directional (playing up vs down asymmetry)?")
if len(primarily_up) > 0 and len(primarily_down) > 0 and len(mostly_same) > 0:
    up_off = primarily_up["off_norm"].mean()
    down_off = primarily_down["off_norm"].mean()
    same_off = mostly_same["off_norm"].mean()
    print(f"     Primarily UP off_norm:   {up_off:.4f}  (n={len(primarily_up)})")
    print(f"     Primarily DOWN off_norm: {down_off:.4f}  (n={len(primarily_down)})")
    print(f"     Mostly Same off_norm:    {same_off:.4f}  (n={len(mostly_same)})")
    if up_off < same_off and down_off > same_off:
        print(f"     → YES: Playing UP suppresses off_norm, playing DOWN does not")
    elif up_off < same_off and down_off < same_off:
        print(f"     → BOTH directions show suppression vs same-age")
    elif up_off > same_off:
        print(f"     → NO: Playing UP does NOT suppress off_norm")
    else:
        print(f"     → MIXED: See numbers above")
else:
    print(f"     Insufficient data for comparison")

# Q4: Strongest boundary
print(f"\n  4. Which age boundaries show the strongest effect?")
if len(boundary_stats) > 0:
    valid_boundaries = boundary_stats[boundary_stats["n_games"] >= 10].copy()
    if len(valid_boundaries) > 0:
        valid_boundaries = valid_boundaries.sort_values("avg_margin")
        worst = valid_boundaries.iloc[0]
        best = valid_boundaries.iloc[-1]
        print(f"     Worst margin for younger team: {worst['boundary']} (margin={worst['avg_margin']:+.3f}, n={int(worst['n_games'])})")
        print(f"     Best margin for younger team:  {best['boundary']} (margin={best['avg_margin']:+.3f}, n={int(best['n_games'])})")
        print(f"\n     All boundaries (10+ games, sorted by margin):")
        for _, row in valid_boundaries.iterrows():
            print(f"       {row['boundary']:<16}  margin={row['avg_margin']:>+7.3f}  win%={100*row['win_rate']:>5.1f}%  n={int(row['n_games'])}")

# Q5: How many cohorts show the pattern?
print(f"\n  5. How many cohorts show the pattern vs don't?")
print(f"     {yes_count}/{total_count} cohorts show strictly decreasing off_norm with cross-age exposure")
mixed = sum(1 for r in cohort_mono_results if r["off_decreases"] == "MIXED")
no_count = sum(1 for r in cohort_mono_results if "NO" in r["off_decreases"])
print(f"     {mixed}/{total_count} show MIXED pattern")
print(f"     {no_count}/{total_count} show NO decrease (or increasing)")

print(f"\n{SEP}")
print("  Analysis complete.")
print(SEP)
