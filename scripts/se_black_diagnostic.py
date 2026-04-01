"""Deep diagnostic for Southeast 2012 Black (U14M, AZ) — team_id 05e9e6aa-fba6-40c2-a995-25826d5c3cb8.

Investigates why they rank #6 in AZ by powerscore_ml despite being clearly #1 in real life.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from supabase import create_client

# ── Setup ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb = create_client(url, key)

TEAM_ID = "05e9e6aa-fba6-40c2-a995-25826d5c3cb8"
COHORT_AGE = "u14"
COHORT_GENDER = "Male"
COHORT_STATE = "AZ"

pd.set_option("display.max_columns", 40)
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 35)
pd.set_option("display.float_format", "{:.4f}".format)


# ── Helpers ────────────────────────────────────────────────────────────────────


def fetch_all(table: str, query_fn):
    """Paginate Supabase select (1000-row limit) until exhausted."""
    rows = []
    offset = 0
    page = 1000
    while True:
        resp = query_fn(table, offset, page)
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def section(title: str):
    print(f"\n{'=' * 100}")
    print(f"  {title}")
    print(f"{'=' * 100}\n")


# ── 1. Fetch SE Black's games ─────────────────────────────────────────────────
section("1. FULL GAME LOG WITH OPPONENT ANALYSIS")

# Games where SE Black is home
home_games = (
    sb.table("games").select("*").eq("home_team_master_id", TEAM_ID).eq("is_excluded", False).execute().data or []
)
# Games where SE Black is away
away_games = (
    sb.table("games").select("*").eq("away_team_master_id", TEAM_ID).eq("is_excluded", False).execute().data or []
)

print(f"Home games: {len(home_games)}, Away games: {len(away_games)}, Total: {len(home_games) + len(away_games)}")

# Build unified game list
game_rows = []
for g in home_games:
    gf, ga = g["home_score"], g["away_score"]
    result = "W" if gf > ga else ("L" if gf < ga else "D")
    game_rows.append(
        {
            "game_id": g["id"],
            "game_date": g["game_date"],
            "goals_for": gf,
            "goals_against": ga,
            "margin": gf - ga,
            "result": result,
            "opp_id": g["away_team_master_id"],
            "side": "home",
            "competition": g.get("competition"),
            "division": g.get("division_name"),
        }
    )
for g in away_games:
    gf, ga = g["away_score"], g["home_score"]
    result = "W" if gf > ga else ("L" if gf < ga else "D")
    game_rows.append(
        {
            "game_id": g["id"],
            "game_date": g["game_date"],
            "goals_for": gf,
            "goals_against": ga,
            "margin": gf - ga,
            "result": result,
            "opp_id": g["home_team_master_id"],
            "side": "away",
            "competition": g.get("competition"),
            "division": g.get("division_name"),
        }
    )

games_df = pd.DataFrame(game_rows)
if games_df.empty:
    print("ERROR: No games found for SE Black!")
    sys.exit(1)

games_df["game_date"] = pd.to_datetime(games_df["game_date"])
games_df.sort_values("game_date", ascending=False, inplace=True)

# ── Fetch opponent info from teams table ───────────────────────────────────────
opp_ids = games_df["opp_id"].dropna().unique().tolist()
print(f"Unique opponents: {len(opp_ids)}")

# Fetch team info for all opponents
opp_teams = []
for oid in opp_ids:
    resp = (
        sb.table("teams")
        .select("team_id_master, team_name, age_group, gender, state_code")
        .eq("team_id_master", oid)
        .eq("is_deprecated", False)
        .limit(1)
        .execute()
    )
    if resp.data:
        opp_teams.append(resp.data[0])

opp_df = pd.DataFrame(opp_teams)
if not opp_df.empty:
    opp_df.rename(columns={"team_id_master": "opp_id"}, inplace=True)

# Fetch rankings for all opponents
opp_rankings = []
for oid in opp_ids:
    resp = (
        sb.table("rankings_full")
        .select(
            "team_id, age_group, gender, powerscore_adj, powerscore_ml, rank_in_cohort, "
            "abs_strength, off_norm, def_norm, sos_norm, games_played, status"
        )
        .eq("team_id", oid)
        .limit(1)
        .execute()
    )
    if resp.data:
        opp_rankings.append(resp.data[0])

opp_rank_df = pd.DataFrame(opp_rankings)
if not opp_rank_df.empty:
    opp_rank_df.rename(columns={"team_id": "opp_id"}, inplace=True)

# Merge into games
if not opp_df.empty:
    games_df = games_df.merge(opp_df, on="opp_id", how="left")
if not opp_rank_df.empty:
    games_df = games_df.merge(opp_rank_df, on="opp_id", how="left", suffixes=("", "_opp_rank"))

# Determine cross-age
games_df["opp_age"] = games_df.get("age_group", pd.Series(dtype=str))
games_df["cross_age"] = games_df["opp_age"].apply(
    lambda x: "cross-age" if pd.notna(x) and str(x).lower() != COHORT_AGE else "same-age"
)

# Print game log
print("\nFull Game Log (most recent first):")
display_cols = [
    "game_date",
    "result",
    "goals_for",
    "goals_against",
    "margin",
    "team_name",
    "opp_age",
    "state_code",
    "cross_age",
    "powerscore_adj",
    "powerscore_ml",
    "rank_in_cohort",
    "abs_strength",
    "off_norm",
    "def_norm",
]
avail_cols = [c for c in display_cols if c in games_df.columns]
print(games_df[avail_cols].to_string(index=False))

# Summary
print(
    f"\nRecord: {(games_df['result'] == 'W').sum()}W-"
    f"{(games_df['result'] == 'L').sum()}L-{(games_df['result'] == 'D').sum()}D"
)
print(
    f"Goals: {games_df['goals_for'].sum()} for, {games_df['goals_against'].sum()} against "
    f"(GD: +{games_df['goals_for'].sum() - games_df['goals_against'].sum()})"
)
print(
    f"Cross-age games: {(games_df['cross_age'] == 'cross-age').sum()} / {len(games_df)} "
    f"({(games_df['cross_age'] == 'cross-age').mean():.0%})"
)

# ── 2. Opponent Strength Analysis ─────────────────────────────────────────────
section("2. OPPONENT STRENGTH ANALYSIS")

ranked_opps = games_df[games_df["powerscore_adj"].notna()].copy()
unranked_opps = games_df[games_df["powerscore_adj"].isna()].copy()

print(f"Ranked opponents: {len(ranked_opps)}, Unranked opponents: {len(unranked_opps)}")
if not unranked_opps.empty:
    print(f"  Unranked opponent names: {unranked_opps['team_name'].unique().tolist()}")

if not ranked_opps.empty:
    print("\nSE Black opponent averages (ranked opponents only):")
    print(f"  Avg powerscore_adj: {ranked_opps['powerscore_adj'].mean():.4f}")
    print(f"  Avg powerscore_ml:  {ranked_opps['powerscore_ml'].mean():.4f}")
    print(f"  Avg rank_in_cohort: {ranked_opps['rank_in_cohort'].mean():.1f}")
    print(f"  Avg abs_strength:   {ranked_opps['abs_strength'].mean():.4f}")
    print(f"  Avg off_norm:       {ranked_opps['off_norm'].mean():.4f}")
    print(f"  Avg def_norm:       {ranked_opps['def_norm'].mean():.4f}")

# Compare to top 5 AZ U14M teams
print("\n--- Top 6 AZ U14M by powerscore_ml ---")
top_az = (
    sb.table("rankings_full")
    .select("*")
    .eq("age_group", COHORT_AGE)
    .eq("gender", COHORT_GENDER)
    .eq("state_code", COHORT_STATE)
    .order("powerscore_ml", desc=True)
    .limit(6)
    .execute()
    .data
    or []
)
top_az_df = pd.DataFrame(top_az)

if not top_az_df.empty:
    top_cols = [
        "team_id",
        "powerscore_adj",
        "powerscore_ml",
        "rank_in_cohort",
        "abs_strength",
        "off_norm",
        "def_norm",
        "sos_norm",
        "sos",
        "games_played",
        "wins",
        "losses",
        "draws",
        "status",
    ]
    avail = [c for c in top_cols if c in top_az_df.columns]
    print(top_az_df[avail].to_string(index=False))

# For each of the top 5 (excluding SE Black), compute their opponent avg stats
print("\n--- Opponent Quality Comparison: SE Black vs Top 5 ---")
top5_ids = [t["team_id"] for t in top_az if t["team_id"] != TEAM_ID][:5]

comparison_rows = []
# SE Black first
if not ranked_opps.empty:
    comparison_rows.append(
        {
            "team": "SE 2012 Black",
            "n_games": len(games_df),
            "n_ranked_opp": len(ranked_opps),
            "avg_opp_ps_adj": ranked_opps["powerscore_adj"].mean(),
            "avg_opp_ps_ml": ranked_opps["powerscore_ml"].mean(),
            "avg_opp_abs_str": ranked_opps["abs_strength"].mean(),
            "avg_opp_rank": ranked_opps["rank_in_cohort"].mean(),
            "pct_cross_age": (games_df["cross_age"] == "cross-age").mean(),
        }
    )

for tid in top5_ids:
    t_home = (
        sb.table("games")
        .select("home_score, away_score, away_team_master_id")
        .eq("home_team_master_id", tid)
        .eq("is_excluded", False)
        .execute()
        .data
        or []
    )
    t_away = (
        sb.table("games")
        .select("home_score, away_score, home_team_master_id")
        .eq("away_team_master_id", tid)
        .eq("is_excluded", False)
        .execute()
        .data
        or []
    )

    t_opp_ids = [g["away_team_master_id"] for g in t_home] + [g["home_team_master_id"] for g in t_away]
    t_opp_ids_unique = list(set(t_opp_ids))

    t_opp_ranks = []
    for oid in t_opp_ids_unique:
        resp = (
            sb.table("rankings_full")
            .select("team_id, powerscore_adj, powerscore_ml, rank_in_cohort, abs_strength, age_group")
            .eq("team_id", oid)
            .limit(1)
            .execute()
        )
        if resp.data:
            t_opp_ranks.append(resp.data[0])

    t_opp_rank_df = pd.DataFrame(t_opp_ranks)
    t_ranked = t_opp_rank_df[t_opp_rank_df["powerscore_adj"].notna()] if not t_opp_rank_df.empty else pd.DataFrame()

    # Get team name
    t_info = (
        sb.table("teams").select("team_name").eq("team_id_master", tid).eq("is_deprecated", False).limit(1).execute()
    )
    t_name = t_info.data[0]["team_name"] if t_info.data else tid[:12]

    # Cross-age %
    if not t_opp_rank_df.empty and "age_group" in t_opp_rank_df.columns:
        cross_pct = (t_opp_rank_df["age_group"].str.lower() != COHORT_AGE).mean()
    else:
        cross_pct = 0.0

    comparison_rows.append(
        {
            "team": t_name[:25],
            "n_games": len(t_home) + len(t_away),
            "n_ranked_opp": len(t_ranked),
            "avg_opp_ps_adj": t_ranked["powerscore_adj"].mean() if not t_ranked.empty else None,
            "avg_opp_ps_ml": t_ranked["powerscore_ml"].mean() if not t_ranked.empty else None,
            "avg_opp_abs_str": t_ranked["abs_strength"].mean() if not t_ranked.empty else None,
            "avg_opp_rank": t_ranked["rank_in_cohort"].mean() if not t_ranked.empty else None,
            "pct_cross_age": cross_pct,
        }
    )

comp_df = pd.DataFrame(comparison_rows)
print(comp_df.to_string(index=False))

# ── 3. SOS Deep Dive ──────────────────────────────────────────────────────────
section("3. SOS DEEP DIVE")

# SE Black's ranking row
se_rank = sb.table("rankings_full").select("*").eq("team_id", TEAM_ID).execute().data
se_rank_df = pd.DataFrame(se_rank) if se_rank else pd.DataFrame()

if not se_rank_df.empty:
    print("SE Black ranking metrics:")
    key_cols = [
        "powerscore_adj",
        "powerscore_ml",
        "rank_in_cohort",
        "off_norm",
        "def_norm",
        "sos",
        "sos_norm",
        "abs_strength",
        "power_presos",
        "games_played",
        "wins",
        "losses",
        "draws",
        "status",
        "ml_overperf",
        "ml_norm",
    ]
    for col in key_cols:
        if col in se_rank_df.columns:
            print(f"  {col:25s}: {se_rank_df[col].iloc[0]}")

# BRAZAS comparison
print("\n--- BRAZAS FC 2012 Black (likely #1 AZ) comparison ---")
brazas_row = top_az_df.iloc[0] if not top_az_df.empty else None
if brazas_row is not None:
    brazas_id = brazas_row["team_id"]
    brazas_rank = sb.table("rankings_full").select("*").eq("team_id", brazas_id).execute().data
    if brazas_rank:
        brazas_df = pd.DataFrame(brazas_rank)
        print(f"BRAZAS team_id: {brazas_id}")
        for col in key_cols:
            if col in brazas_df.columns:
                val_se = se_rank_df[col].iloc[0] if col in se_rank_df.columns else "N/A"
                val_br = brazas_df[col].iloc[0]
                print(f"  {col:25s}: SE={val_se:>10}  BRAZAS={val_br:>10}")

# Opponent strength breakdown
print("\n--- SE Black Opponent Strength Breakdown ---")
same_age = games_df[games_df["cross_age"] == "same-age"]
cross_age = games_df[games_df["cross_age"] == "cross-age"]

for label, subset in [("Same-age (U14)", same_age), ("Cross-age (non-U14)", cross_age), ("All", games_df)]:
    ranked_sub = subset[subset["abs_strength"].notna()]
    if not ranked_sub.empty:
        print(
            f"  {label}: n={len(subset)}, ranked={len(ranked_sub)}, "
            f"avg_abs_str={ranked_sub['abs_strength'].mean():.4f}, "
            f"avg_ps_adj={ranked_sub['powerscore_adj'].mean():.4f}"
        )
    else:
        print(f"  {label}: n={len(subset)}, ranked=0")

# ── 4. Cross-Age SOS Credit Check ─────────────────────────────────────────────
section("4. CROSS-AGE SOS CREDIT CHECK")

cross_age_opps = games_df[games_df["cross_age"] == "cross-age"].copy()
print(f"Cross-age games: {len(cross_age_opps)}")

if not cross_age_opps.empty:
    print("\nCross-age opponent details:")
    ca_cols = [
        "team_name",
        "opp_age",
        "state_code",
        "abs_strength",
        "off_norm",
        "def_norm",
        "powerscore_adj",
        "powerscore_ml",
        "rank_in_cohort",
    ]
    ca_avail = [c for c in ca_cols if c in cross_age_opps.columns]
    # Deduplicate by opponent
    ca_deduped = cross_age_opps.drop_duplicates(subset=["opp_id"])[ca_avail]
    print(ca_deduped.to_string(index=False))

    # Check if cross-age opponents are ranked
    ca_ranked = cross_age_opps[cross_age_opps["abs_strength"].notna()]
    ca_unranked = cross_age_opps[cross_age_opps["abs_strength"].isna()]
    print(f"\nCross-age: {len(ca_ranked)} games vs ranked opponents, {len(ca_unranked)} vs unranked")

    if not ca_ranked.empty:
        print(f"Cross-age avg abs_strength: {ca_ranked['abs_strength'].mean():.4f}")
    if not same_age.empty:
        sa_ranked = same_age[same_age["abs_strength"].notna()]
        if not sa_ranked.empty:
            print(f"Same-age avg abs_strength:  {sa_ranked['abs_strength'].mean():.4f}")
            gap = ca_ranked["abs_strength"].mean() - sa_ranked["abs_strength"].mean() if not ca_ranked.empty else 0
            print(f"Gap (cross - same):         {gap:+.4f}")

    # Check what the SOS algorithm would see for these opponents
    # In v53e, cross-age opponents get looked up in global_strength_map (abs_strength from their cohort)
    print("\n--- How SOS algorithm handles these cross-age opponents ---")
    print("The SOS calculation uses get_opponent_strength():")
    print("  1. First checks base_strength_map (same-cohort teams only)")
    print("  2. Falls back to global_strength_map (all cohorts, keyed by string team_id)")
    print("  3. If not found → UNRANKED_SOS_BASE (typically 0.35)")
    print()
    print("For SE Black's cross-age opponents, the question is:")
    print("  - Are these U15 opponents in global_strength_map? (Yes, if they appear in rankings_full)")
    print("  - What abs_strength do they have?")

    for _, row in ca_deduped.iterrows():
        name = row.get("team_name", "Unknown")
        abs_str = row.get("abs_strength")
        ranked = "RANKED" if pd.notna(abs_str) else "UNRANKED (gets 0.35)"
        print(f"  {name:35s}  abs_strength={abs_str if pd.notna(abs_str) else 'N/A':>8}  [{ranked}]")

# ── 5. Why #6 and not #1 ──────────────────────────────────────────────────────
section("5. WHY #6 AND NOT #1 — TOP 6 AZ U14M SIDE BY SIDE")

if not top_az_df.empty:
    # Get team names
    top_names = {}
    for tid in top_az_df["team_id"]:
        resp = (
            sb.table("teams")
            .select("team_name")
            .eq("team_id_master", tid)
            .eq("is_deprecated", False)
            .limit(1)
            .execute()
        )
        if resp.data:
            top_names[tid] = resp.data[0]["team_name"]

    top_az_df["team_name"] = top_az_df["team_id"].map(top_names)
    top_az_df["is_se_black"] = top_az_df["team_id"] == TEAM_ID

    compare_cols = [
        "team_name",
        "is_se_black",
        "powerscore_ml",
        "powerscore_adj",
        "rank_in_cohort",
        "off_norm",
        "def_norm",
        "sos_norm",
        "sos",
        "abs_strength",
        "power_presos",
        "games_played",
        "wins",
        "losses",
        "draws",
        "ml_overperf",
        "ml_norm",
    ]
    avail = [c for c in compare_cols if c in top_az_df.columns]
    print(top_az_df[avail].to_string(index=False))

    # Identify the gap
    se_row = top_az_df[top_az_df["team_id"] == TEAM_ID]
    top1_row = top_az_df.iloc[0]

    if not se_row.empty:
        print("\n--- Gap Analysis: SE Black vs #1 AZ ---")
        gap_cols = [
            "powerscore_ml",
            "powerscore_adj",
            "off_norm",
            "def_norm",
            "sos_norm",
            "sos",
            "abs_strength",
            "ml_overperf",
        ]
        for col in gap_cols:
            if col in se_row.columns and col in top1_row.index:
                se_val = se_row[col].iloc[0]
                t1_val = top1_row[col]
                if pd.notna(se_val) and pd.notna(t1_val):
                    diff = se_val - t1_val
                    print(f"  {col:20s}: SE={se_val:.4f}  #1={t1_val:.4f}  gap={diff:+.4f}")

    # What would need to change?
    print("\n--- What would need to change for SE Black to reach #1 ---")
    if not se_row.empty and not top_az_df.empty:
        se_ps_ml = se_row["powerscore_ml"].iloc[0]
        t1_ps_ml = top1_row["powerscore_ml"]
        se_sos = se_row["sos_norm"].iloc[0] if "sos_norm" in se_row.columns else None
        t1_sos = top1_row["sos_norm"] if "sos_norm" in top1_row.index else None
        se_off = se_row["off_norm"].iloc[0] if "off_norm" in se_row.columns else None
        se_def = se_row["def_norm"].iloc[0] if "def_norm" in se_row.columns else None

        print(f"  Current powerscore_ml gap: {se_ps_ml - t1_ps_ml:+.4f}")
        if se_sos is not None and t1_sos is not None:
            print(f"  SOS_norm gap: {se_sos - t1_sos:+.4f}")
            # Rough estimate: powerscore_adj = OFF_W*off + DEF_W*def + SOS_W*sos + PERF_W*perf
            # Typical weights from v53e config
            print(f"  If SOS_norm matched #1 (delta={t1_sos - se_sos:+.4f}), approximate powerscore_adj boost:")
            print(f"    At SOS weight ~0.20: +{(t1_sos - se_sos) * 0.20:.4f}")
            print(f"    At SOS weight ~0.25: +{(t1_sos - se_sos) * 0.25:.4f}")

# ── 6. Recommendations ────────────────────────────────────────────────────────
section("6. RECOMMENDATIONS")

print("""Based on the analysis above, consider the following:

1. SOS FAIRNESS CHECK
   - SE Black's sos_norm = 0.784 is the weakest among top 6 AZ U14M.
   - They play ~39% cross-age games (mostly U15).
   - If those U15 opponents are strong but belong to a different cohort,
     their abs_strength is used via global_strength_map — which is correct.
   - However, if U15 cohort normalization produces lower abs_strength than
     comparable U14 opponents, cross-age play is systematically penalized.

2. CROSS-AGE SOS BIAS (potential)
   - The offense path got a cross-age fix (opponent adjustment scaling).
   - The SOS path uses global_strength_map for cross-age lookups.
   - If U15 opponents have LOWER abs_strength than their actual quality
     (because U15 normalization is different), SE Black's SOS is suppressed.
   - This is the SAME cross-age bias pattern, just on a different code path.

3. POSSIBLE FIX
   - Apply cross-age anchor scaling to SOS opponent lookups (similar to
     how offense opponent adjustment was fixed).
   - OR normalize opponent strength BEFORE SOS calculation so that a
     0.6 abs_strength in U15 means the same quality as 0.6 in U14.

4. IS THE RANKING FAIR?
   - If SE Black is beating strong U15 opponents but those opponents
     register as weaker in the SOS calculation than comparable U14 opponents,
     the ranking systematically undervalues their schedule.
   - This would explain why a dominant team with a strong real-world record
     sits at #6 instead of #1.
""")

print("\n" + "=" * 100)
print("  DIAGNOSTIC COMPLETE")
print("=" * 100)
