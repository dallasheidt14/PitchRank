#!/usr/bin/env python3
"""
Pull all available data for a specific team from PitchRank Supabase.

Usage:
    python scripts/pull_team_data.py
"""

import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).parent.parent / ".env.local")

TEAM_ID = "691eb36d-95b2-4a08-bd59-13c1b0e830bb"

# ─── Connect ─────────────────────────────────────────────────────────────────

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("Missing SUPABASE_URL or SUPABASE_KEY in .env")
    sys.exit(1)

sb = create_client(url, key)

# ═══════════════════════════════════════════════════════════════════════════════
# A) Current ranking from rankings_full
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("A) CURRENT RANKING — Phoenix United Elite (U12M)")
print("=" * 90)

row = sb.table("rankings_full").select("*").eq("team_id", TEAM_ID).execute()

if not row.data:
    print("  *** No ranking data found for this team_id ***")
else:
    r = row.data[0]
    # Print all columns for reference
    print("\n--- All columns ---")
    for k in sorted(r.keys()):
        print(f"  {k:30s} = {r[k]}")

    # Key metrics summary
    key_fields = [
        "rank_in_cohort", "off_raw", "off_norm", "def_norm", "sos", "sos_norm",
        "powerscore_adj", "powerscore_ml", "national_rank", "state_rank",
        "games_played", "wins", "losses", "draws", "goals_for", "goals_against",
        "win_percentage", "abs_strength", "power_presos", "perf_centered",
        "ml_overperf", "ml_norm",
    ]
    print("\n--- Key Metrics ---")
    for f in key_fields:
        val = r.get(f, "N/A")
        if isinstance(val, float):
            print(f"  {f:25s} = {val:.4f}")
        else:
            print(f"  {f:25s} = {val}")

# ═══════════════════════════════════════════════════════════════════════════════
# B) All games for this team (home or away)
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("B) ALL GAMES — sorted by date DESC")
print("=" * 90)

# Home games
home = (
    sb.table("games")
    .select("id, game_date, home_score, away_score, away_team_master_id, age_group, ml_overperformance")
    .eq("home_team_master_id", TEAM_ID)
    .order("game_date", desc=True)
    .execute()
)

# Away games
away = (
    sb.table("games")
    .select("id, game_date, home_score, away_score, home_team_master_id, age_group, ml_overperformance")
    .eq("away_team_master_id", TEAM_ID)
    .order("game_date", desc=True)
    .execute()
)

# Build unified game list
games = []
for g in home.data:
    games.append({
        "game_id": g["id"],
        "game_date": g["game_date"],
        "gf": g["home_score"],
        "ga": g["away_score"],
        "opp_id": g["away_team_master_id"],
        "age_group": g["age_group"],
        "gender": None,
        "ml_overperformance": g.get("ml_overperformance"),
        "side": "home",
    })
for g in away.data:
    games.append({
        "game_id": g["id"],
        "game_date": g["game_date"],
        "gf": g["away_score"],
        "ga": g["home_score"],
        "opp_id": g["home_team_master_id"],
        "age_group": g["age_group"],
        "gender": None,
        "ml_overperformance": g.get("ml_overperformance"),
        "side": "away",
    })

games.sort(key=lambda x: x["game_date"] or "", reverse=True)

# Fetch opponent names
opp_ids = list({g["opp_id"] for g in games if g["opp_id"]})
opp_map = {}
if opp_ids:
    # Fetch in batches to avoid URL length limits
    for i in range(0, len(opp_ids), 50):
        batch = opp_ids[i : i + 50]
        res = sb.table("teams").select("team_id_master, team_name, age_group, gender").in_("team_id_master", batch).execute()
        for t in res.data:
            opp_map[t["team_id_master"]] = t

# Fetch opponent rankings for abs_strength (section E)
opp_rankings = {}
if opp_ids:
    for i in range(0, len(opp_ids), 50):
        batch = opp_ids[i : i + 50]
        res = sb.table("rankings_full").select("team_id, abs_strength").in_("team_id", batch).execute()
        for t in res.data:
            opp_rankings[t["team_id"]] = t

print(f"\nTotal games: {len(games)}")
print(f"{'Date':12s} {'GF':>3s} {'GA':>3s} {'Side':5s} {'Opp Age':7s} {'ML OverPerf':>12s}  Opponent")
print("-" * 90)

for g in games:
    opp_info = opp_map.get(g["opp_id"], {})
    opp_name = opp_info.get("team_name", g["opp_id"] or "???")
    opp_age = opp_info.get("age_group", g["age_group"] or "?")
    ml_op = g.get("ml_overperformance")
    ml_str = f"{ml_op:+.3f}" if ml_op is not None else "N/A"
    print(f"{g['game_date'] or 'N/A':12s} {g['gf'] or 0:3d} {g['ga'] or 0:3d} {g['side']:5s} {str(opp_age):7s} {ml_str:>12s}  {opp_name}")

# ═══════════════════════════════════════════════════════════════════════════════
# C) Summary stats by opponent age group
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("C) SUMMARY STATS — by opponent age group")
print("=" * 90)

from collections import defaultdict

age_buckets = defaultdict(lambda: {"games": 0, "gf": 0, "ga": 0, "wins": 0, "draws": 0, "losses": 0})

for g in games:
    opp_info = opp_map.get(g["opp_id"], {})
    opp_age = opp_info.get("age_group", g["age_group"] or "unknown")
    b = age_buckets[opp_age]
    gf = g["gf"] or 0
    ga = g["ga"] or 0
    b["games"] += 1
    b["gf"] += gf
    b["ga"] += ga
    if gf > ga:
        b["wins"] += 1
    elif gf == ga:
        b["draws"] += 1
    else:
        b["losses"] += 1

# Also compute same-age vs older buckets
same_age_stats = {"games": 0, "gf": 0, "ga": 0, "wins": 0, "draws": 0, "losses": 0}
older_stats = {"games": 0, "gf": 0, "ga": 0, "wins": 0, "draws": 0, "losses": 0}

for age_key, b in age_buckets.items():
    age_str = str(age_key).lower().replace("u", "")
    try:
        age_num = int(age_str)
    except ValueError:
        age_num = 0
    if age_num == 12:
        for k in same_age_stats:
            same_age_stats[k] += b[k]
    elif age_num > 12:
        for k in older_stats:
            older_stats[k] += b[k]

print(f"\n{'Age Group':12s} {'Games':>6s} {'W':>4s} {'D':>4s} {'L':>4s} {'GF':>5s} {'GA':>5s} {'Margin':>7s} {'WinRate':>8s}")
print("-" * 70)
for age_key in sorted(age_buckets.keys(), key=lambda x: str(x)):
    b = age_buckets[age_key]
    margin = b["gf"] - b["ga"]
    wr = b["wins"] / b["games"] * 100 if b["games"] else 0
    avg_gf = b["gf"] / b["games"] if b["games"] else 0
    avg_ga = b["ga"] / b["games"] if b["games"] else 0
    avg_margin = margin / b["games"] if b["games"] else 0
    print(f"{str(age_key):12s} {b['games']:6d} {b['wins']:4d} {b['draws']:4d} {b['losses']:4d} {b['gf']:5d} {b['ga']:5d} {margin:+7d} {wr:7.1f}%")

print("\n--- Same-age (U12) vs Older opponents ---")
for label, s in [("Same-age (U12)", same_age_stats), ("Older (U13+)", older_stats)]:
    if s["games"] == 0:
        print(f"  {label:20s}: No games")
        continue
    avg_gf = s["gf"] / s["games"]
    avg_ga = s["ga"] / s["games"]
    avg_margin = (s["gf"] - s["ga"]) / s["games"]
    wr = s["wins"] / s["games"] * 100
    print(f"  {label:20s}: {s['games']:3d} games | Avg GF {avg_gf:.2f} | Avg GA {avg_ga:.2f} | Avg Margin {avg_margin:+.2f} | Win Rate {wr:.1f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# D) Top 10 U12M Arizona teams
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("D) TOP 10 U12M ARIZONA TEAMS (by powerscore_adj)")
print("=" * 90)

top10 = (
    sb.table("rankings_full")
    .select("team_id, rank_in_cohort, off_norm, def_norm, sos_norm, powerscore_adj, games_played, goals_for, goals_against")
    .eq("age_group", "u12")
    .eq("gender", "Male")
    .eq("state_code", "AZ")
    .order("powerscore_adj", desc=True)
    .limit(10)
    .execute()
)

# Look up team names
top10_ids = [t["team_id"] for t in top10.data]
top10_names = {}
if top10_ids:
    res = sb.table("teams").select("team_id_master, team_name").in_("team_id_master", top10_ids).execute()
    for t in res.data:
        top10_names[t["team_id_master"]] = t["team_name"]

print(f"\n{'#':>3s} {'Team':40s} {'Cohort':>7s} {'Off':>6s} {'Def':>6s} {'SOS':>6s} {'PwrAdj':>8s} {'GP':>4s} {'GF':>4s} {'GA':>4s}")
print("-" * 100)
for i, t in enumerate(top10.data, 1):
    marker = " <--" if t["team_id"] == TEAM_ID else ""
    tname = top10_names.get(t["team_id"], t["team_id"][:20])
    off = t.get("off_norm") or 0
    def_ = t.get("def_norm") or 0
    sos = t.get("sos_norm") or 0
    ps = t.get("powerscore_adj") or 0
    ric = t.get("rank_in_cohort", "N/A")
    print(
        f"{i:3d} {tname[:40]:40s} "
        f"{ric:>7} "
        f"{off:6.3f} {def_:6.3f} {sos:6.3f} {ps:8.4f} "
        f"{t.get('games_played', 0) or 0:4d} {t.get('goals_for', 0) or 0:4d} {t.get('goals_against', 0) or 0:4d}"
        f"{marker}"
    )

# ═══════════════════════════════════════════════════════════════════════════════
# E) Opponent strength by age bucket
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 90)
print("E) OPPONENT ABS_STRENGTH — by age bucket")
print("=" * 90)

same_age_strengths = []
older_strengths = []
all_opp_details = []

for g in games:
    opp_info = opp_map.get(g["opp_id"], {})
    opp_age = opp_info.get("age_group", g["age_group"] or "unknown")
    opp_rank = opp_rankings.get(g["opp_id"], {})
    abs_str = opp_rank.get("abs_strength")
    opp_name = opp_info.get("team_name", "???")

    age_str = str(opp_age).lower().replace("u", "")
    try:
        age_num = int(age_str)
    except ValueError:
        age_num = 0

    all_opp_details.append({
        "date": g["game_date"],
        "opponent": opp_name,
        "opp_age": opp_age,
        "abs_strength": abs_str,
        "gf": g["gf"],
        "ga": g["ga"],
    })

    if abs_str is not None:
        if age_num == 12:
            same_age_strengths.append(abs_str)
        elif age_num > 12:
            older_strengths.append(abs_str)

print(f"\n{'Date':12s} {'GF':>3s} {'GA':>3s} {'OppAge':7s} {'AbsStr':>8s}  Opponent")
print("-" * 80)
for d in all_opp_details:
    abs_s = f"{d['abs_strength']:.4f}" if d['abs_strength'] is not None else "N/A"
    print(f"{d['date'] or 'N/A':12s} {d['gf'] or 0:3d} {d['ga'] or 0:3d} {str(d['opp_age']):7s} {abs_s:>8s}  {d['opponent']}")

print("\n--- Average opponent abs_strength ---")
if same_age_strengths:
    print(f"  Same-age (U12): {sum(same_age_strengths)/len(same_age_strengths):.4f}  ({len(same_age_strengths)} games with ranked opponents)")
else:
    print("  Same-age (U12): No ranked opponents found")
if older_strengths:
    print(f"  Older (U13+):   {sum(older_strengths)/len(older_strengths):.4f}  ({len(older_strengths)} games with ranked opponents)")
else:
    print("  Older (U13+):   No ranked opponents found")

all_strengths = same_age_strengths + older_strengths
if all_strengths:
    print(f"  Overall:        {sum(all_strengths)/len(all_strengths):.4f}  ({len(all_strengths)} total ranked opponents)")

print("\nDone.")
