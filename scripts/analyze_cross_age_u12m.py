#!/usr/bin/env python3
"""
Cross-Age Play Pattern Analysis for U12 Male Cohort
====================================================
Analyzes how cross-age games affect offensive ratings and rankings
for U12M teams in the PitchRank system.

Sections:
  A) Cross-age game frequency for all U12M teams
  B) Performance split by opponent age
  C) Correlation analysis (cross-age % vs off_norm, powerscore_adj)
  D) Top 20 U12M teams with cross-age breakdown
  E) Residual analysis — teams where off_norm misaligns with win%

Usage:
    python scripts/analyze_cross_age_u12m.py
"""

import os
import sys
from pathlib import Path

import numpy as np
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
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

SEPARATOR = "=" * 80


def paginated_fetch(table: str, select: str, filters: dict | None = None, limit: int = 1000) -> list:
    """Fetch all rows from a table using offset-based pagination."""
    all_rows = []
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


def age_group_number(ag: str | None) -> int | None:
    """Convert 'u12' -> 12, '12' -> 12, etc."""
    if ag is None:
        return None
    ag = str(ag).strip().lower().replace("u", "")
    try:
        return int(ag)
    except ValueError:
        return None


# ── Step 1: Fetch all U12M team IDs and their rankings ──────────────────
print(f"\n{SEPARATOR}")
print("  CROSS-AGE PLAY ANALYSIS — U12 MALE COHORT")
print(SEPARATOR)

print("\n[1/5] Fetching U12M rankings from rankings_full ...")
rankings_rows = paginated_fetch(
    "rankings_full",
    "team_id, age_group, gender, state_code, off_norm, def_norm, sos_norm, "
    "powerscore_adj, rank_in_cohort, games_played, wins, losses, draws, "
    "win_percentage, goals_for, goals_against, status, power_score_final",
    filters={"age_group": "u12", "gender": "Male"},
)
rankings = pd.DataFrame(rankings_rows)
print(f"  → {len(rankings)} U12M teams in rankings_full")

# We also need team names
print("  Fetching team names ...")
u12m_ids = rankings["team_id"].tolist()
# Fetch team names in batches (Supabase IN filter has limits)
team_name_rows = []
batch_size = 200
for i in range(0, len(u12m_ids), batch_size):
    batch = u12m_ids[i : i + batch_size]
    result = (
        supabase.table("teams")
        .select("team_id_master, team_name")
        .in_("team_id_master", batch)
        .execute()
    )
    if result.data:
        team_name_rows.extend(result.data)

team_names = pd.DataFrame(team_name_rows).rename(columns={"team_id_master": "team_id"})
rankings = rankings.merge(team_names, on="team_id", how="left")

# ── Step 2: Fetch ALL games involving U12M teams ────────────────────────
print("\n[2/5] Fetching games involving U12M teams ...")
# Fetch games where U12M team is home
home_games_rows = []
for i in range(0, len(u12m_ids), batch_size):
    batch = u12m_ids[i : i + batch_size]
    rows = paginated_fetch(
        "games",
        "id, home_team_master_id, away_team_master_id, home_score, away_score, game_date",
        filters=None,
    )
    # Can't combine IN with paginated_fetch easily — use a different approach
    break

# Simpler: fetch all games for U12M teams using RPC or direct queries
# Let's fetch home and away separately with IN filter batches
home_games_all = []
away_games_all = []
for i in range(0, len(u12m_ids), batch_size):
    batch = u12m_ids[i : i + batch_size]
    h = (
        supabase.table("games")
        .select("id, home_team_master_id, away_team_master_id, home_score, away_score, game_date")
        .in_("home_team_master_id", batch)
        .eq("is_excluded", False)
        .limit(5000)
        .execute()
    )
    if h.data:
        home_games_all.extend(h.data)

    a = (
        supabase.table("games")
        .select("id, home_team_master_id, away_team_master_id, home_score, away_score, game_date")
        .in_("away_team_master_id", batch)
        .eq("is_excluded", False)
        .limit(5000)
        .execute()
    )
    if a.data:
        away_games_all.extend(a.data)

print(f"  → {len(home_games_all)} home game rows, {len(away_games_all)} away game rows")

# Build a unified game-perspective dataframe: one row per (u12m_team, game)
rows = []
for g in home_games_all:
    rows.append({
        "game_id": g["id"],
        "team_id": g["home_team_master_id"],
        "opp_id": g["away_team_master_id"],
        "gf": g["home_score"],
        "ga": g["away_score"],
        "game_date": g["game_date"],
    })
for g in away_games_all:
    rows.append({
        "game_id": g["id"],
        "team_id": g["away_team_master_id"],
        "opp_id": g["home_team_master_id"],
        "gf": g["away_score"],
        "ga": g["home_score"],
        "game_date": g["game_date"],
    })

games_df = pd.DataFrame(rows)
# Only keep rows where team_id is a U12M team
games_df = games_df[games_df["team_id"].isin(set(u12m_ids))].copy()
# Deduplicate (a game could appear twice if both teams are U12M, but we want one row per team per game)
games_df = games_df.drop_duplicates(subset=["game_id", "team_id"])
print(f"  → {len(games_df)} total game-perspectives for U12M teams")

# ── Step 3: Look up opponent age groups ─────────────────────────────────
print("\n[3/5] Looking up opponent age groups ...")
all_opp_ids = [oid for oid in games_df["opp_id"].unique() if oid is not None]
print(f"  → {len(all_opp_ids)} unique opponents to look up")

opp_info_rows = []
for i in range(0, len(all_opp_ids), batch_size):
    batch = all_opp_ids[i : i + batch_size]
    result = (
        supabase.table("teams")
        .select("team_id_master, age_group, gender")
        .in_("team_id_master", batch)
        .execute()
    )
    if result.data:
        opp_info_rows.extend(result.data)

opp_info = pd.DataFrame(opp_info_rows).rename(columns={"team_id_master": "opp_id"})
opp_info = opp_info.drop_duplicates(subset=["opp_id"])
games_df = games_df.merge(opp_info, on="opp_id", how="left")
games_df.rename(columns={"age_group": "opp_age_group", "gender": "opp_gender"}, inplace=True)

# Parse age numbers
games_df["opp_age_num"] = games_df["opp_age_group"].apply(age_group_number)

# Classify opponent
def classify_opp(row):
    opp_age = row["opp_age_num"]
    if opp_age is None:
        return "unknown"
    if opp_age == 12:
        return "same_age"
    elif opp_age > 12:
        return "older"
    else:
        return "younger"

games_df["opp_class"] = games_df.apply(classify_opp, axis=1)

# Add result column
games_df["margin"] = games_df["gf"] - games_df["ga"]
games_df["result"] = games_df["margin"].apply(lambda m: "W" if m > 0 else ("L" if m < 0 else "D"))

# ══════════════════════════════════════════════════════════════════════════
# SECTION A: Cross-age game frequency
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEPARATOR}")
print("  SECTION A: Cross-Age Game Frequency for U12M")
print(SEPARATOR)

total = len(games_df)
by_class = games_df["opp_class"].value_counts()
same_age = by_class.get("same_age", 0)
older = by_class.get("older", 0)
younger = by_class.get("younger", 0)
unknown = by_class.get("unknown", 0)
cross_age = older + younger

print(f"\n  Total game-perspectives:  {total:,}")
print(f"  vs Same-age (U12):       {same_age:,}  ({100*same_age/total:.1f}%)")
print(f"  vs Older (U13+):         {older:,}  ({100*older/total:.1f}%)")
print(f"  vs Younger (U11-):       {younger:,}  ({100*younger/total:.1f}%)")
print(f"  vs Unknown age:          {unknown:,}  ({100*unknown/total:.1f}%)")
print(f"  ────────────────────────")
print(f"  Total cross-age:         {cross_age:,}  ({100*cross_age/total:.1f}%)")

# Breakdown by specific age group
print("\n  Breakdown by opponent age group:")
opp_age_counts = games_df.groupby("opp_age_group").size().sort_values(ascending=False)
for ag, cnt in opp_age_counts.items():
    print(f"    {ag or 'NULL':>5}: {cnt:>6,}  ({100*cnt/total:.1f}%)")

# ══════════════════════════════════════════════════════════════════════════
# SECTION B: Performance split by opponent age
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEPARATOR}")
print("  SECTION B: Performance Split by Opponent Age (U12M cohort aggregate)")
print(SEPARATOR)

for cls_label, cls_key in [("Same-age (U12)", "same_age"), ("Older (U13+)", "older"), ("Younger (U11-)", "younger")]:
    subset = games_df[games_df["opp_class"] == cls_key]
    n = len(subset)
    if n == 0:
        print(f"\n  {cls_label}: no games")
        continue
    avg_gf = subset["gf"].mean()
    avg_ga = subset["ga"].mean()
    avg_margin = subset["margin"].mean()
    win_rate = (subset["result"] == "W").sum() / n
    draw_rate = (subset["result"] == "D").sum() / n
    loss_rate = (subset["result"] == "L").sum() / n

    print(f"\n  {cls_label}  (n={n:,} games)")
    print(f"    Avg goals_for:       {avg_gf:.2f}")
    print(f"    Avg goals_against:   {avg_ga:.2f}")
    print(f"    Avg goal margin:     {avg_margin:+.2f}")
    print(f"    Win rate:            {100*win_rate:.1f}%")
    print(f"    Draw rate:           {100*draw_rate:.1f}%")
    print(f"    Loss rate:           {100*loss_rate:.1f}%")

# Detailed by specific older age groups
older_games = games_df[games_df["opp_class"] == "older"]
if len(older_games) > 0:
    print(f"\n  Detailed breakdown vs older opponents:")
    for ag in sorted(older_games["opp_age_group"].unique(), key=lambda x: age_group_number(x) or 99):
        sub = older_games[older_games["opp_age_group"] == ag]
        n = len(sub)
        if n < 5:
            continue
        avg_gf = sub["gf"].mean()
        avg_ga = sub["ga"].mean()
        avg_margin = sub["margin"].mean()
        win_rate = (sub["result"] == "W").sum() / n
        print(f"    vs {ag}: n={n:>4}, avg_gf={avg_gf:.2f}, avg_ga={avg_ga:.2f}, margin={avg_margin:+.2f}, win%={100*win_rate:.1f}%")


# ══════════════════════════════════════════════════════════════════════════
# SECTION C: Correlation analysis
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEPARATOR}")
print("  SECTION C: Correlation — Cross-Age % vs Rankings Metrics")
print(SEPARATOR)

# For each U12M team, compute pct_cross_age_games
team_game_stats = (
    games_df.groupby("team_id")
    .agg(
        total_games=("game_id", "count"),
        cross_age_games=("opp_class", lambda x: ((x == "older") | (x == "younger")).sum()),
        older_games=("opp_class", lambda x: (x == "older").sum()),
        younger_games=("opp_class", lambda x: (x == "younger").sum()),
    )
    .reset_index()
)
team_game_stats["pct_cross_age"] = team_game_stats["cross_age_games"] / team_game_stats["total_games"]
team_game_stats["pct_older"] = team_game_stats["older_games"] / team_game_stats["total_games"]

# Merge with rankings
analysis = rankings.merge(team_game_stats, on="team_id", how="inner")
# Filter to teams with enough games
analysis = analysis[analysis["games_played"] >= 6].copy()

print(f"\n  Teams with 6+ games for correlation: {len(analysis)}")

# Compute correlations
from scipy import stats as sp_stats

for metric in ["off_norm", "def_norm", "sos_norm", "powerscore_adj", "win_percentage", "rank_in_cohort"]:
    valid = analysis.dropna(subset=["pct_cross_age", metric])
    if len(valid) < 10:
        print(f"  pct_cross_age vs {metric}: insufficient data (n={len(valid)})")
        continue
    r, p = sp_stats.pearsonr(valid["pct_cross_age"], valid[metric])
    rho, p_rho = sp_stats.spearmanr(valid["pct_cross_age"], valid[metric])
    print(f"  pct_cross_age vs {metric:20s}: Pearson r={r:+.4f} (p={p:.4f}), Spearman rho={rho:+.4f} (p={p_rho:.4f})")

# Also: pct_older specifically (excluding younger)
print()
for metric in ["off_norm", "powerscore_adj"]:
    valid = analysis.dropna(subset=["pct_older", metric])
    if len(valid) < 10:
        continue
    r, p = sp_stats.pearsonr(valid["pct_older"], valid[metric])
    print(f"  pct_OLDER vs {metric:20s}: Pearson r={r:+.4f} (p={p:.4f})")


# ══════════════════════════════════════════════════════════════════════════
# SECTION D: Top 20 U12M teams by powerscore_adj with cross-age %
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEPARATOR}")
print("  SECTION D: Top 20 U12M Teams by powerscore_adj — Cross-Age Breakdown")
print(SEPARATOR)

top20 = analysis.nsmallest(20, "rank_in_cohort")

print(f"\n  {'Rank':>4}  {'Team Name':<42}  {'St':>2}  {'GP':>3}  {'Off':>5}  {'Def':>5}  {'SOS':>5}  {'PwrAdj':>6}  {'XAge%':>5}  {'Old%':>5}")
print("  " + "-" * 120)
for _, row in top20.iterrows():
    name = (row.get("team_name") or "???")[:42]
    print(
        f"  {int(row['rank_in_cohort']):>4}  {name:<42}  {row.get('state_code','??'):>2}  "
        f"{int(row['games_played']):>3}  {row['off_norm']:.3f}  {row['def_norm']:.3f}  "
        f"{row['sos_norm']:.3f}  {row['powerscore_adj']:.4f}  "
        f"{100*row['pct_cross_age']:.1f}%  {100*row['pct_older']:.1f}%"
    )


# ══════════════════════════════════════════════════════════════════════════
# SECTION E: Residual analysis — off_norm misaligned with win%
# ══════════════════════════════════════════════════════════════════════════
print(f"\n{SEPARATOR}")
print("  SECTION E: Residual Analysis — Win% vs off_norm Misalignment (10+ games)")
print(SEPARATOR)

resid = analysis[analysis["games_played"] >= 10].copy()
resid = resid.dropna(subset=["win_percentage", "off_norm"])

# Normalize both to 0-1 scale for comparison
# win_percentage is stored as 0-100; off_norm is 0-1 (percentile-based)
resid["win_pct_01"] = resid["win_percentage"] / 100.0
resid["misalignment"] = resid["win_pct_01"] - resid["off_norm"]

# Also compute cross-age percentage for context
top_misaligned = resid.nlargest(20, "misalignment")

print(f"\n  Teams with 10+ games: {len(resid)}")
print(f"  Showing top 20 where win% >> off_norm (candidates for cross-age suppression)\n")

print(f"  {'Rank':>4}  {'Team Name':<38}  {'St':>2}  {'GP':>3}  {'Win%':>5}  {'Off':>5}  {'Gap':>6}  {'XAge%':>5}  {'Old%':>5}  {'SOS':>5}")
print("  " + "-" * 115)
for _, row in top_misaligned.iterrows():
    name = (row.get("team_name") or "???")[:38]
    print(
        f"  {int(row['rank_in_cohort']):>4}  {name:<38}  {row.get('state_code','??'):>2}  "
        f"{int(row['games_played']):>3}  {row['win_pct_01']:.3f}  {row['off_norm']:.3f}  "
        f"{row['misalignment']:+.3f}  "
        f"{100*row['pct_cross_age']:.1f}%  {100*row['pct_older']:.1f}%  {row['sos_norm']:.3f}"
    )

# Summary stats on misalignment by cross-age buckets
print(f"\n  Misalignment by cross-age game percentage buckets:")
resid["xage_bucket"] = pd.cut(
    resid["pct_cross_age"],
    bins=[0, 0.05, 0.15, 0.30, 0.50, 1.0],
    labels=["0-5%", "5-15%", "15-30%", "30-50%", "50%+"],
    include_lowest=True,
)
bucket_stats = resid.groupby("xage_bucket", observed=True).agg(
    n=("team_id", "count"),
    avg_misalignment=("misalignment", "mean"),
    avg_off_norm=("off_norm", "mean"),
    avg_win_pct=("win_pct_01", "mean"),
    avg_pct_cross_age=("pct_cross_age", "mean"),
).reset_index()

print(f"\n  {'Bucket':>8}  {'N':>5}  {'Avg Misalign':>12}  {'Avg Off':>7}  {'Avg Win%':>8}  {'Avg XAge%':>9}")
print("  " + "-" * 60)
for _, b in bucket_stats.iterrows():
    print(
        f"  {b['xage_bucket']:>8}  {int(b['n']):>5}  {b['avg_misalignment']:>+12.4f}  "
        f"{b['avg_off_norm']:>7.3f}  {b['avg_win_pct']:>8.3f}  {100*b['avg_pct_cross_age']:>8.1f}%"
    )

print(f"\n{SEPARATOR}")
print("  Analysis complete.")
print(SEPARATOR)
