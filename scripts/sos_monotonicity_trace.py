"""SOS Pipeline Monotonicity Trace — U15M

Re-runs compute_rankings for U15M to capture intermediate SOS values
at each pipeline stage, identifying where raw SOS ordering diverges from sos_norm.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from supabase import create_client

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env.local")

from src.etl.v53e import V53EConfig, compute_rankings  # noqa: E402
from src.rankings.data_adapter import age_group_to_age, normalize_gender  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

pd.set_option("display.max_columns", 50)
pd.set_option("display.width", 280)
pd.set_option("display.max_colwidth", 30)
pd.set_option("display.float_format", "{:.4f}".format)

COHORT_AGE = "15"
COHORT_GENDER = "male"
TOP_N = 30
TODAY = pd.Timestamp("2026-03-30")

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
sb = create_client(url, key)


def section(title):
    print(f"\n{'=' * 120}")
    print(f"  {title}")
    print(f"{'=' * 120}\n")


# ── 1. Fetch U15M team IDs ───────────────────────────────────────────────────

section("1. FETCHING U15M TEAMS")

team_rows = []
offset = 0
while True:
    resp = (
        sb.table("teams")
        .select("team_id_master, age_group, gender, state_code")
        .eq("age_group", "u15")
        .eq("gender", "Male")
        .range(offset, offset + 999)
        .execute()
    )
    batch = resp.data or []
    team_rows.extend(batch)
    if len(batch) < 1000:
        break
    offset += 1000
    print(f"  Fetched {len(team_rows)} teams...")

print(f"  Total U15M teams: {len(team_rows)}")
u15m_ids = {r["team_id_master"] for r in team_rows}
team_state = {r["team_id_master"]: r.get("state_code", "") for r in team_rows if r.get("state_code")}

# Also fetch metadata for potential cross-age opponents (broader set)
# We'll fetch ALL teams' age/gender for the perspective builder
print("  Fetching all team metadata for age/gender mapping...")
all_meta = []
offset = 0
while True:
    resp = sb.table("teams").select("team_id_master, age_group, gender").range(offset, offset + 999).execute()
    batch = resp.data or []
    all_meta.extend(batch)
    if len(batch) < 1000:
        break
    offset += 1000
    if offset % 10000 == 0:
        print(f"  ... {len(all_meta)} teams fetched")

print(f"  Total teams with metadata: {len(all_meta)}")
team_age = {}
team_gender = {}
for r in all_meta:
    tid = r["team_id_master"]
    age = age_group_to_age(r["age_group"])
    gen = normalize_gender(pd.Series([r["gender"]])).iloc[0]
    if age and gen:
        team_age[tid] = age
        team_gender[tid] = gen

# ── 2. Fetch games involving U15M teams ──────────────────────────────────────

section("2. FETCHING GAMES")

cutoff = (TODAY - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
today_str = TODAY.strftime("%Y-%m-%d")

# Fetch in batches of team IDs (home + away)
u15m_list = list(u15m_ids)
all_games_raw = []

print(f"  Fetching games for {len(u15m_list)} U15M teams...")
for i in range(0, len(u15m_list), 50):
    batch_ids = u15m_list[i : i + 50]

    # Home games
    offset = 0
    while True:
        resp = (
            sb.table("games")
            .select("id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score")
            .in_("home_team_master_id", batch_ids)
            .gte("game_date", cutoff)
            .lte("game_date", today_str)
            .eq("is_excluded", False)
            .range(offset, offset + 999)
            .execute()
        )
        rows = resp.data or []
        all_games_raw.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000

    # Away games
    offset = 0
    while True:
        resp = (
            sb.table("games")
            .select("id, game_uid, game_date, home_team_master_id, away_team_master_id, home_score, away_score")
            .in_("away_team_master_id", batch_ids)
            .gte("game_date", cutoff)
            .lte("game_date", today_str)
            .eq("is_excluded", False)
            .range(offset, offset + 999)
            .execute()
        )
        rows = resp.data or []
        all_games_raw.extend(rows)
        if len(rows) < 1000:
            break
        offset += 1000

    if (i + 50) % 500 == 0 or (i + 50) >= len(u15m_list):
        print(
            f"  ... processed {min(i + 50, len(u15m_list))}/{len(u15m_list)} teams, {len(all_games_raw)} games so far"
        )

# Deduplicate
gdf = pd.DataFrame(all_games_raw).drop_duplicates(subset=["id"])
print(f"  Unique games involving U15M teams: {len(gdf)}")

# ── 3. Build v53e perspectives ────────────────────────────────────────────────

section("3. BUILDING GAME PERSPECTIVES")

perspectives = []
for _, row in gdf.iterrows():
    h, a = row["home_team_master_id"], row["away_team_master_id"]
    h_age, a_age = team_age.get(h), team_age.get(a)
    h_gen, a_gen = team_gender.get(h), team_gender.get(a)
    if not all([h_age, a_age, h_gen, a_gen]):
        continue
    gid = str(row.get("game_uid") or row["id"])
    dt = row["game_date"]
    hs, aws = row["home_score"], row["away_score"]
    perspectives.append(
        {
            "game_id": gid,
            "date": dt,
            "team_id": h,
            "opp_id": a,
            "age": h_age,
            "gender": h_gen,
            "opp_age": a_age,
            "opp_gender": a_gen,
            "gf": hs,
            "ga": aws,
        }
    )
    perspectives.append(
        {
            "game_id": gid,
            "date": dt,
            "team_id": a,
            "opp_id": h,
            "age": a_age,
            "gender": a_gen,
            "opp_age": h_age,
            "opp_gender": h_gen,
            "gf": aws,
            "ga": hs,
        }
    )

all_games = pd.DataFrame(perspectives)
all_games["date"] = pd.to_datetime(all_games["date"])
print(f"  Total perspectives: {len(all_games)}")

# Filter to U15M cohort (team is U15M, opponents can be any age)
cohort_games = all_games[
    (all_games["age"].astype(str) == COHORT_AGE) & (all_games["gender"].str.lower() == COHORT_GENDER)
].copy()
print(f"  U15M perspectives: {len(cohort_games)}")
print(f"  Unique U15M teams in games: {cohort_games['team_id'].nunique()}")

# ── 4. Run compute_rankings ──────────────────────────────────────────────────

section("4. RUNNING COMPUTE_RANKINGS")

import src.etl.v53e as v53e_mod  # noqa: E402

captures = {}
_orig_apply_scf = v53e_mod.apply_scf_to_sos


def _patched_apply_scf(team_df, scf_data, cfg_arg):
    captures["pre_scf"] = team_df[["team_id", "sos"]].copy().set_index("team_id")
    result = _orig_apply_scf(team_df, scf_data, cfg_arg)
    captures["post_scf"] = result[["team_id", "sos"]].copy().set_index("team_id")
    return result


v53e_mod.apply_scf_to_sos = _patched_apply_scf

cfg = V53EConfig()
result = compute_rankings(
    games_df=cohort_games,
    today=TODAY,
    cfg=cfg,
    team_state_map=team_state,
)

v53e_mod.apply_scf_to_sos = _orig_apply_scf

teams = result["teams"]
print(f"  Ranked {len(teams)} teams")

# ── 5. Stage-by-stage trace ──────────────────────────────────────────────────

section("5. DIAGNOSTIC COLUMNS AVAILABLE")

diag_cols = [
    c
    for c in teams.columns
    if any(k in c.lower() for k in ["sos", "component", "alpha", "scf", "bridge", "sample", "gp", "win"])
]
print(f"  {diag_cols}")

section("6. TOP 30 BY RAW SOS — FULL TRACE")

top30 = teams.sort_values("sos", ascending=False).head(TOP_N).copy()
top30["raw_rank"] = range(1, len(top30) + 1)

norm_ranks = teams["sos_norm"].rank(ascending=False, method="min")
top30["norm_rank"] = top30["team_id"].map(dict(zip(teams["team_id"], norm_ranks)))
top30["rank_delta"] = top30["norm_rank"] - top30["raw_rank"]

if "pre_scf" in captures:
    top30["sos_pre_scf"] = top30["team_id"].map(captures["pre_scf"]["sos"])

display_cols = ["raw_rank", "norm_rank", "rank_delta", "team_id"]
for c in [
    "sos_pre_scf",
    "sos",
    "component_id",
    "component_size",
    "sos_norm_global",
    "sos_norm_component",
    "_sos_alpha",
    "sos_norm",
    "gp",
    "sample_flag",
    "win_rate",
    "off_norm",
    "def_norm",
]:
    if c in top30.columns:
        display_cols.append(c)

print(top30[display_cols].to_string(index=False))

# ── 6. Monotonicity analysis ─────────────────────────────────────────────────

section("7. MONOTONICITY ANALYSIS")

all_t = teams.copy()
all_t["raw_rank"] = all_t["sos"].rank(ascending=False, method="min")
all_t["norm_rank"] = all_t["sos_norm"].rank(ascending=False, method="min")
all_t["rank_delta"] = all_t["norm_rank"] - all_t["raw_rank"]

top_inv = all_t.nsmallest(TOP_N, "raw_rank").sort_values("raw_rank")
worst = top_inv[top_inv["rank_delta"].abs() > 3].sort_values("rank_delta", key=abs, ascending=False)

if not worst.empty:
    print(f"  Significant inversions in top {TOP_N} (|delta| > 3):")
    cols = [
        "team_id",
        "raw_rank",
        "norm_rank",
        "rank_delta",
        "sos",
        "sos_norm",
        "component_id",
        "component_size",
        "gp",
        "sample_flag",
    ]
    cols = [c for c in cols if c in worst.columns]
    print(worst[cols].to_string(index=False))
else:
    print(f"  No significant inversions in top {TOP_N}")

try:
    from scipy.stats import spearmanr

    top100 = all_t.nsmallest(100, "raw_rank")
    rho, _ = spearmanr(top100["raw_rank"], top100["norm_rank"])
    print(f"\n  Spearman rank corr (top 100): {rho:.4f}")
    rho30, _ = spearmanr(top_inv["raw_rank"], top_inv["norm_rank"])
    print(f"  Spearman rank corr (top 30):  {rho30:.4f}")
except ImportError:
    print("  (scipy not installed, skipping Spearman)")

# ── 7. Connected component analysis ──────────────────────────────────────────

section("8. CONNECTED COMPONENT ANALYSIS")

if "component_id" in teams.columns:
    comp_stats = (
        teams.groupby("component_id")
        .agg(
            n=("team_id", "count"),
            mean_sos=("sos", "mean"),
            std_sos=("sos", "std"),
            mean_norm=("sos_norm", "mean"),
            min_norm=("sos_norm", "min"),
            max_norm=("sos_norm", "max"),
        )
        .sort_values("n", ascending=False)
    )
    print(comp_stats.head(20).to_string())

    n_comps = len(comp_stats)
    if n_comps > 1:
        print(f"\n  ⚠️  {n_comps} connected components")

        top30_ids = set(top30["team_id"])
        for cid in sorted(top30["component_id"].unique()):
            ct = teams[teams["component_id"] == cid]
            ct_top = sum(1 for t in ct["team_id"] if t in top30_ids)
            print(f"\n  Component {cid}: size={len(ct)}, {ct_top} in top 30")
            print(f"    raw SOS: [{ct['sos'].min():.4f}, {ct['sos'].max():.4f}]")
            print(f"    sos_norm: [{ct['sos_norm'].min():.4f}, {ct['sos_norm'].max():.4f}]")

        # Smoking gun: small-component teams with high sos_norm
        small_high = teams[(teams["component_size"] < 30) & (teams["sos_norm"] > 0.9)]
        if not small_high.empty:
            print(f"\n  🔴 {len(small_high)} teams in small components (<30) with sos_norm > 0.9")
            cols = [
                "team_id",
                "component_id",
                "component_size",
                "sos",
                "sos_norm",
                "sos_norm_global",
                "sos_norm_component",
                "_sos_alpha",
                "gp",
                "win_rate",
            ]
            cols = [c for c in cols if c in small_high.columns]
            print(small_high.sort_values("sos_norm", ascending=False).head(10)[cols].to_string(index=False))

# ── 8. Blending verification ─────────────────────────────────────────────────

section("9. BLEND VERIFICATION: sos_norm = alpha * global + (1-alpha) * component")

if all(c in top30.columns for c in ["sos_norm_global", "sos_norm_component", "_sos_alpha"]):
    top30["expected"] = (
        top30["_sos_alpha"] * top30["sos_norm_global"] + (1 - top30["_sos_alpha"]) * top30["sos_norm_component"]
    )
    top30["gap"] = top30["sos_norm"] - top30["expected"]

    cols = [
        "raw_rank",
        "norm_rank",
        "team_id",
        "sos_norm_global",
        "sos_norm_component",
        "_sos_alpha",
        "expected",
        "sos_norm",
        "gap",
        "sample_flag",
    ]
    cols = [c for c in cols if c in top30.columns]
    print(top30[cols].to_string(index=False))

    big_gap = top30[top30["gap"].abs() > 0.01]
    if not big_gap.empty:
        print(f"\n  ⚠️  {len(big_gap)} teams: sos_norm ≠ blend (modified by Power-SOS / shrinkage / decorrelation)")

# ── 9. Summary ────────────────────────────────────────────────────────────────

section("10. DIAGNOSIS SUMMARY")

sos_range = top30["sos"].max() - top30["sos"].min()
norm_range = top30["sos_norm"].max() - top30["sos_norm"].min()
print(f"  Top {TOP_N} raw SOS spread:  {sos_range:.4f}")
print(f"  Top {TOP_N} sos_norm spread: {norm_range:.4f}")

if "component_id" in teams.columns:
    n_comps = teams["component_id"].nunique()
    n_comps_top = top30["component_id"].nunique()
    print(f"  Total components: {n_comps}")
    print(f"  Components in top {TOP_N}: {n_comps_top}")

    if n_comps_top > 1:
        print(f"\n  🔴 ROOT CAUSE: Multiple connected components in top {TOP_N}")
        print("     Per-component normalization breaks cross-component monotonicity.")
