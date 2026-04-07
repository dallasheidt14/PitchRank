#!/usr/bin/env python3
"""Read-only audit helper for investigating potentially overranked teams."""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from rich.console import Console
from supabase import create_client

sys.path.append(str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env.local")
load_dotenv(Path(__file__).parent.parent / ".env")
if not os.environ.get("SUPABASE_KEY") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_KEY"] = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_game_explainability, compute_scf, select_games
from src.rankings.data_adapter import batch_fetch_rows, fetch_games_for_rankings
from src.utils.merge_resolver import MergeResolver

console = Console()

PUBLISHED_COLS = ",".join(
    [
        "team_id",
        "age_group",
        "gender",
        "state_code",
        "status",
        "games_played",
        "wins",
        "losses",
        "draws",
        "sos_norm",
        "powerscore_adj",
        "powerscore_ml",
        "ml_norm",
        "power_score_true",
        "rank_in_cohort_final",
        "glicko_rating",
        "glicko_rd",
        "glicko_volatility",
        "last_calculated",
    ]
)

COHORT_COLS = ",".join(
    [
        "team_id",
        "age_group",
        "gender",
        "state_code",
        "status",
        "powerscore_adj",
        "powerscore_ml",
        "ml_norm",
        "power_score_true",
        "rank_in_cohort_final",
        "glicko_rating",
        "glicko_rd",
        "glicko_volatility",
    ]
)

TEAM_META_COLS = "team_id_master,team_name,club_name,league,age_group,gender,state_code"


@dataclass
class ScheduleMetrics:
    team_id: str
    window_games: int
    unique_opponents: int
    ranked_opponents: int
    unranked_opponents: int
    top20_count: int
    top100_count: int
    top500_count: int
    avg_opp_rank: float | None
    avg_opp_power_true: float | None
    bridge_games: int
    unique_opp_states: int
    cross_age_games: int
    cross_age_share: float
    max_repeat_count: int
    repeat_opponents_3plus: int
    repeat_share: float
    strongest_opponents: list[dict[str, Any]]


@dataclass
class ClassificationResult:
    primary_driver: str
    why_high: str
    evidence_notes: list[str]


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY / SUPABASE_KEY")
    return create_client(url, key)


def normalize_age(age_group: Any) -> int | None:
    if age_group is None:
        return None
    digits = "".join(ch for ch in str(age_group) if ch.isdigit())
    if not digits:
        return None
    age = int(digits)
    return 19 if age == 18 else age


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_mean(values: list[float | int | None]) -> float | None:
    clean = [float(v) for v in values if v is not None and not pd.isna(v)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def safe_median(values: list[float | int | None]) -> float | None:
    clean = sorted(float(v) for v in values if v is not None and not pd.isna(v))
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def fmt_num(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except TypeError:
        pass
    return f"{float(value):.{digits}f}"


def fmt_int(value: Any) -> str:
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except TypeError:
        pass
    return str(int(round(float(value))))


def fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except TypeError:
        pass
    return f"{float(value) * 100:.{digits}f}%"


def batch_fetch_rankings_rows(client, team_ids: list[str], cols: str) -> dict[str, dict[str, Any]]:
    rows = batch_fetch_rows(client, "rankings_full", cols, "team_id", team_ids)
    return {str(row["team_id"]): row for row in rows if row.get("team_id")}


def batch_fetch_team_meta(client, team_ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = batch_fetch_rows(client, "teams", TEAM_META_COLS, "team_id_master", team_ids)
    return {str(row["team_id_master"]): row for row in rows if row.get("team_id_master")}


def fetch_all_cohort_rows(client, age_group: str, gender: str) -> pd.DataFrame:
    all_rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    while True:
        result = (
            client.table("rankings_full")
            .select(COHORT_COLS)
            .eq("age_group", age_group)
            .eq("gender", gender)
            .eq("status", "Active")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    if not all_rows:
        return pd.DataFrame(columns=COHORT_COLS.split(","))
    df = pd.DataFrame(all_rows)
    for col in ["powerscore_adj", "powerscore_ml", "ml_norm", "power_score_true", "rank_in_cohort_final", "glicko_rating", "glicko_rd", "glicko_volatility"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["team_id"] = df["team_id"].astype(str)
    return df


def build_team_windows(
    games_df: pd.DataFrame,
    team_ids: list[str],
    cfg: GlickoConfig,
    today: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    team_games: dict[str, pd.DataFrame] = {}
    for team_id in team_ids:
        window = select_games(games_df, team_id, cfg.MAX_GAMES, cfg.WINDOW_DAYS, today).copy()
        if not window.empty:
            window["team_id"] = window["team_id"].astype(str)
            window["opp_id"] = window["opp_id"].astype(str)
        team_games[team_id] = window
    return team_games


def compute_base_rank_map(cohort_rows: pd.DataFrame) -> dict[str, int]:
    if cohort_rows.empty:
        return {}
    ranked = (
        cohort_rows[["team_id", "powerscore_adj"]]
        .dropna(subset=["powerscore_adj"])
        .sort_values(["powerscore_adj", "team_id"], ascending=[False, True])
        .reset_index(drop=True)
    )
    ranked["base_rank"] = ranked.index + 1
    return dict(zip(ranked["team_id"], ranked["base_rank"]))


def build_comparison_ids(cohort_rows: pd.DataFrame, team_id: str, nearby: int = 5) -> list[str]:
    if cohort_rows.empty:
        return []
    cohort_sorted = cohort_rows.sort_values(["rank_in_cohort_final", "team_id"], ascending=[True, True]).reset_index(drop=True)
    top_ids = cohort_sorted.head(10)["team_id"].astype(str).tolist()
    if team_id not in set(cohort_sorted["team_id"].astype(str)):
        return top_ids
    idx = cohort_sorted.index[cohort_sorted["team_id"].astype(str) == team_id][0]
    lo = max(0, idx - nearby)
    hi = min(len(cohort_sorted), idx + nearby + 1)
    nearby_ids = cohort_sorted.iloc[lo:hi]["team_id"].astype(str).tolist()
    ordered = []
    seen: set[str] = set()
    for candidate in top_ids + nearby_ids:
        if candidate not in seen:
            ordered.append(candidate)
            seen.add(candidate)
    return ordered


def compute_schedule_metrics(
    team_id: str,
    team_window: pd.DataFrame,
    rankings_map: dict[str, dict[str, Any]],
    team_meta_map: dict[str, dict[str, Any]],
    team_state_map: dict[str, str],
) -> ScheduleMetrics:
    if team_window.empty:
        return ScheduleMetrics(team_id, 0, 0, 0, 0, 0, 0, 0, None, None, 0, 0, 0, 0.0, 0, 0, 0.0, [])

    opp_ids = team_window["opp_id"].astype(str).tolist()
    unique_opponents = len(set(opp_ids))
    counts = team_window["opp_id"].astype(str).value_counts()
    ranked_rows = [rankings_map[opp_id] for opp_id in opp_ids if opp_id in rankings_map]
    ranked_unique_rows = [rankings_map[opp_id] for opp_id in counts.index if opp_id in rankings_map]
    valid_states = [team_state_map.get(opp_id) for opp_id in opp_ids if team_state_map.get(opp_id) not in (None, "", "UNKNOWN")]
    team_state = team_state_map.get(team_id)
    bridge_games = sum(1 for state in valid_states if state != team_state)
    unique_states = len(set(valid_states))
    cross_age_mask = (
        team_window["age"].astype(str).ne(team_window["opp_age"].astype(str))
        | team_window["gender"].astype(str).ne(team_window["opp_gender"].astype(str))
    )
    top_rows = sorted(
        ranked_unique_rows,
        key=lambda row: (
            float(row.get("rank_in_cohort_final") or math.inf),
            -float(row.get("power_score_true") or 0.0),
        ),
    )[:5]
    strongest = []
    for row in top_rows:
        opp_id = str(row["team_id"])
        meta = team_meta_map.get(opp_id, {})
        strongest.append(
            {
                "team_id": opp_id,
                "team_name": meta.get("team_name") or opp_id,
                "club_name": meta.get("club_name") or "",
                "age_group": meta.get("age_group") or row.get("age_group"),
                "gender": meta.get("gender") or row.get("gender"),
                "state_code": meta.get("state_code") or row.get("state_code"),
                "rank_in_cohort_final": safe_float(row.get("rank_in_cohort_final")),
                "power_score_true": safe_float(row.get("power_score_true")),
            }
        )

    return ScheduleMetrics(
        team_id=team_id,
        window_games=len(team_window),
        unique_opponents=unique_opponents,
        ranked_opponents=len(ranked_rows),
        unranked_opponents=max(0, len(opp_ids) - len(ranked_rows)),
        top20_count=sum(1 for row in ranked_rows if safe_float(row.get("rank_in_cohort_final")) is not None and safe_float(row.get("rank_in_cohort_final")) <= 20),
        top100_count=sum(1 for row in ranked_rows if safe_float(row.get("rank_in_cohort_final")) is not None and safe_float(row.get("rank_in_cohort_final")) <= 100),
        top500_count=sum(1 for row in ranked_rows if safe_float(row.get("rank_in_cohort_final")) is not None and safe_float(row.get("rank_in_cohort_final")) <= 500),
        avg_opp_rank=safe_mean([safe_float(row.get("rank_in_cohort_final")) for row in ranked_rows]),
        avg_opp_power_true=safe_mean([safe_float(row.get("power_score_true")) for row in ranked_rows]),
        bridge_games=bridge_games,
        unique_opp_states=unique_states,
        cross_age_games=int(cross_age_mask.sum()),
        cross_age_share=float(cross_age_mask.mean()) if len(team_window) else 0.0,
        max_repeat_count=int(counts.max()) if not counts.empty else 0,
        repeat_opponents_3plus=int((counts >= 3).sum()),
        repeat_share=float((counts[counts >= 2].sum() / len(team_window))) if len(team_window) else 0.0,
        strongest_opponents=strongest,
    )


def peer_metric_medians(metrics_list: list[ScheduleMetrics]) -> dict[str, float | None]:
    return {
        "top100_count": safe_median([m.top100_count for m in metrics_list]),
        "top500_count": safe_median([m.top500_count for m in metrics_list]),
        "avg_opp_rank": safe_median([m.avg_opp_rank for m in metrics_list]),
        "avg_opp_power_true": safe_median([m.avg_opp_power_true for m in metrics_list]),
        "bridge_games": safe_median([m.bridge_games for m in metrics_list]),
        "unique_opp_states": safe_median([m.unique_opp_states for m in metrics_list]),
        "cross_age_share": safe_median([m.cross_age_share for m in metrics_list]),
        "repeat_share": safe_median([m.repeat_share for m in metrics_list]),
    }


def attach_cross_age_flags(explain_df: pd.DataFrame, team_games: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if explain_df.empty:
        return explain_df
    window_rows = []
    for team_id, window in team_games.items():
        if window.empty or "id" not in window.columns:
            continue
        subset = window[["team_id", "id", "age", "gender", "opp_age", "opp_gender"]].copy()
        subset["id"] = subset["id"].astype(str)
        subset["team_id"] = subset["team_id"].astype(str)
        window_rows.append(subset)
    if not window_rows:
        explain_df["is_cross_age"] = False
        return explain_df
    meta_df = pd.concat(window_rows, ignore_index=True).drop_duplicates(subset=["team_id", "id"])
    merged = explain_df.copy()
    merged["id"] = merged["id"].astype(str)
    merged["team_id"] = merged["team_id"].astype(str)
    merged = merged.merge(meta_df, on=["team_id", "id"], how="left")
    merged["is_cross_age"] = merged["age"].astype(str).ne(merged["opp_age"].astype(str)) | merged["gender"].astype(str).ne(
        merged["opp_gender"].astype(str)
    )
    return merged


def classify_team(
    team_row: dict[str, Any],
    base_rank: int | None,
    schedule: ScheduleMetrics,
    peer_medians: dict[str, float | None],
    scf_row: dict[str, Any],
    explain_df: pd.DataFrame,
) -> ClassificationResult:
    published_rank = int(safe_float(team_row.get("rank_in_cohort_final")) or 0)
    ml_lift = (safe_float(team_row.get("power_score_true")) or 0.0) - (safe_float(team_row.get("powerscore_adj")) or 0.0)
    rank_gain_from_ml = (base_rank - published_rank) if base_rank and published_rank else 0

    explain = explain_df.copy() if explain_df is not None else pd.DataFrame()
    if not explain.empty:
        explain["abs_contribution"] = explain["rating_contribution"].abs()
    total_abs = float(explain["abs_contribution"].sum()) if not explain.empty else 0.0
    cross_age_abs = (
        float(explain.loc[explain["is_cross_age"].fillna(False), "abs_contribution"].sum()) if not explain.empty else 0.0
    )
    cross_age_contrib_share = (cross_age_abs / total_abs) if total_abs > 0 else 0.0

    weak_opp_strength = (
        peer_medians.get("avg_opp_power_true") is not None
        and schedule.avg_opp_power_true is not None
        and schedule.avg_opp_power_true + 0.05 < peer_medians["avg_opp_power_true"]
    )
    few_top_opponents = (
        (peer_medians.get("top100_count") or 0) >= 1
        and schedule.top100_count == 0
    )
    cross_age_heavy = (
        schedule.cross_age_share >= 0.25
        and peer_medians.get("cross_age_share") is not None
        and schedule.cross_age_share > peer_medians["cross_age_share"] + 0.10
    )
    repeat_heavy = (
        schedule.repeat_share >= 0.25
        and peer_medians.get("repeat_share") is not None
        and schedule.repeat_share > peer_medians["repeat_share"] + 0.08
    )
    scf = safe_float(scf_row.get("scf"))
    low_connectivity = bool(
        scf_row.get("is_isolated")
        or (scf is not None and scf < 0.70)
        or schedule.bridge_games < 3
        or schedule.unique_opp_states < 3
    )

    notes: list[str] = [
        f"published rank {published_rank}",
        f"base rank {base_rank if base_rank is not None else '-'}",
        f"ML lift {fmt_num(ml_lift)}",
        f"top-100 opponents {schedule.top100_count}",
        f"avg opponent power {fmt_num(schedule.avg_opp_power_true)}",
        f"cross-age share {fmt_pct(schedule.cross_age_share)}",
        f"repeat-opponent share {fmt_pct(schedule.repeat_share)}",
        f"SCF {fmt_num(scf)}",
    ]

    if ml_lift >= 0.020 and rank_gain_from_ml >= 3:
        why = (
            f"ML moved this team from a pre-ML base rank of {base_rank} to a published rank of {published_rank}, "
            f"adding {fmt_num(ml_lift)} on top of powerscore_adj."
        )
        return ClassificationResult("ML amplification", why, notes)

    if cross_age_heavy and cross_age_contrib_share >= 0.35:
        why = (
            f"A large share of the window is cross-age ({fmt_pct(schedule.cross_age_share)}), and "
            f"{fmt_pct(cross_age_contrib_share)} of absolute rating contribution comes from those cross-age games."
        )
        return ClassificationResult("cross-age contamination", why, notes)

    if low_connectivity and (repeat_heavy or weak_opp_strength or few_top_opponents):
        why = (
            f"The schedule shows weak connectivity (SCF {fmt_num(scf)}, {schedule.bridge_games} bridge games, "
            f"{schedule.unique_opp_states} opponent states) while also leaning on softer or repetitive opponent evidence."
        )
        return ClassificationResult("schedule-connectivity / repeat-opponent inflation", why, notes)

    if base_rank is not None and published_rank and base_rank <= published_rank + 1 and (weak_opp_strength or few_top_opponents):
        why = (
            f"This team is already ranked unusually high before ML (base rank {base_rank}) even though its "
            f"opponent evidence is weaker than the comparison set."
        )
        return ClassificationResult("base Glicko inflation", why, notes)

    why = (
        "The current evidence does not isolate one dominant driver cleanly enough to label this team beyond an "
        "investigation-only inconclusive result."
    )
    return ClassificationResult("inconclusive", why, notes)


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, divider, *body]) if body else "\n".join([header_line, divider])


def metric_row(label: str, team_value: Any, peer_value: Any, team_fmt=fmt_num, peer_fmt=fmt_num) -> list[str]:
    return [label, team_fmt(team_value), peer_fmt(peer_value)]


def build_comparison_table(cohort_rows: pd.DataFrame, team_meta: dict[str, dict[str, Any]], comparison_ids: list[str]) -> str:
    if cohort_rows.empty or not comparison_ids:
        return "_No comparison teams available._"
    subset = cohort_rows[cohort_rows["team_id"].astype(str).isin(comparison_ids)].copy()
    subset = subset.sort_values(["rank_in_cohort_final", "team_id"], ascending=[True, True]).head(20)
    rows = []
    for _, row in subset.iterrows():
        meta = team_meta.get(str(row["team_id"]), {})
        rows.append(
            [
                fmt_int(row.get("rank_in_cohort_final")),
                meta.get("team_name") or str(row["team_id"]),
                meta.get("club_name") or "",
                f"{meta.get('age_group') or row.get('age_group')} {meta.get('gender') or row.get('gender')}",
                fmt_num(row.get("powerscore_adj")),
                fmt_num(row.get("power_score_true")),
            ]
        )
    return markdown_table(["Rank", "Team", "Club", "Cohort", "Base", "Published"], rows)


def build_strongest_opponents_table(schedule: ScheduleMetrics) -> str:
    if not schedule.strongest_opponents:
        return "_No ranked opponents found in the active snapshot._"
    rows = []
    for opp in schedule.strongest_opponents:
        rows.append(
            [
                fmt_int(opp.get("rank_in_cohort_final")),
                opp.get("team_name") or opp["team_id"],
                opp.get("club_name") or "",
                f"{opp.get('age_group') or '-'} {opp.get('gender') or '-'}",
                opp.get("state_code") or "-",
                fmt_num(opp.get("power_score_true")),
            ]
        )
    return markdown_table(["Rank", "Team", "Club", "Cohort", "State", "Power"], rows)


def build_impact_games_table(explain_df: pd.DataFrame, team_meta: dict[str, dict[str, Any]]) -> str:
    if explain_df.empty:
        return "_No explainability rows available._"
    top = explain_df.copy()
    top["abs_contribution"] = top["rating_contribution"].abs()
    top = top.sort_values(["abs_contribution", "game_date"], ascending=[False, False]).head(8)
    rows = []
    for _, row in top.iterrows():
        opp_id = str(row["opp_id"])
        meta = team_meta.get(opp_id, {})
        score = f"{fmt_int(row['gf'])}-{fmt_int(row['ga'])}"
        rows.append(
            [
                pd.to_datetime(row["game_date"]).strftime("%Y-%m-%d"),
                meta.get("team_name") or opp_id,
                score,
                fmt_num(row.get("expected_outcome")),
                fmt_num(row.get("actual_outcome")),
                fmt_num(row.get("rating_contribution"), 4),
                "Yes" if bool(row.get("is_cross_age")) else "No",
            ]
        )
    return markdown_table(["Date", "Opponent", "Score", "Expected", "Actual", "Contribution", "Cross-Age"], rows)


def build_report(
    baseline_label: str,
    summary_rows: list[dict[str, Any]],
    team_sections: list[str],
) -> str:
    summary_table = markdown_table(
        [
            "Rank",
            "Team",
            "Cohort",
            "Base Rank",
            "ML Lift",
            "Top100",
            "Avg Opp Power",
            "Cross-Age",
            "Repeat",
            "Driver",
        ],
        [
            [
                fmt_int(row["published_rank"]),
                row["team_name"],
                row["cohort"],
                fmt_int(row["base_rank"]),
                fmt_num(row["ml_lift"]),
                fmt_int(row["top100_count"]),
                fmt_num(row["avg_opp_power_true"]),
                fmt_pct(row["cross_age_share"]),
                fmt_pct(row["repeat_share"]),
                row["primary_driver"],
            ]
            for row in summary_rows
        ],
    )
    return "\n\n".join(
        [
            f"# Overranked Male Team Audit\n\nBaseline snapshot: {baseline_label}\n\n"
            "This is a read-only investigation. U10-U12 audits ignore league and tier entirely; "
            "U13+ cohorts include league context only as secondary evidence.",
            "## Executive Summary\n" + summary_table,
            *team_sections,
            "Change candidates deferred pending confirmed causes.",
        ]
    )


async def run_audit(args: argparse.Namespace) -> tuple[Path, Path]:
    client = get_supabase()
    cfg = GlickoConfig()
    resolver = MergeResolver(client)
    resolver.load_merge_map()

    target_ids = [resolver.resolve(team_id) for team_id in args.team_ids]
    published_rows = batch_fetch_rankings_rows(client, target_ids, PUBLISHED_COLS)
    missing = [team_id for team_id in target_ids if team_id not in published_rows]
    if missing:
        raise RuntimeError(f"Teams not found in rankings_full: {', '.join(missing)}")

    last_calc_values = [published_rows[team_id].get("last_calculated") for team_id in target_ids if published_rows[team_id].get("last_calculated")]
    if last_calc_values:
        baseline_ts = pd.to_datetime(max(last_calc_values), utc=True)
    else:
        baseline_ts = pd.Timestamp("2026-04-07", tz="UTC")
    baseline_day = baseline_ts.tz_localize(None).normalize() if baseline_ts.tzinfo is not None else baseline_ts.normalize()
    baseline_label = baseline_day.strftime("%Y-%m-%d")

    report_path = Path(args.report_path) if args.report_path else Path(f"reports/overranked-male-teams-{baseline_label}.md")
    csv_path = Path(args.csv_path) if args.csv_path else Path(f"reports/overranked-male-teams-{baseline_label}.csv")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"Fetching games through {baseline_label}...")
    games_df = await fetch_games_for_rankings(
        client,
        lookback_days=args.lookback_days,
        today=baseline_day,
        merge_resolver=resolver,
    )
    if games_df.empty:
        raise RuntimeError("No games returned for the ranking window.")
    games_df["team_id"] = games_df["team_id"].astype(str)
    games_df["opp_id"] = games_df["opp_id"].astype(str)

    target_meta = batch_fetch_team_meta(client, target_ids)
    cohort_keys = sorted({(published_rows[team_id]["age_group"], published_rows[team_id]["gender"]) for team_id in target_ids})

    cohort_rows_map: dict[tuple[str, str], pd.DataFrame] = {}
    comparison_ids_map: dict[str, list[str]] = {}
    comparison_union: set[str] = set(target_ids)

    for cohort_key in cohort_keys:
        cohort_rows = fetch_all_cohort_rows(client, cohort_key[0], cohort_key[1])
        cohort_rows_map[cohort_key] = cohort_rows
        cohort_target_ids = [team_id for team_id in target_ids if (published_rows[team_id]["age_group"], published_rows[team_id]["gender"]) == cohort_key]
        for team_id in cohort_target_ids:
            comparison_ids = build_comparison_ids(cohort_rows, team_id, nearby=5)
            comparison_ids_map[team_id] = comparison_ids
            comparison_union.update(comparison_ids)

    comparison_meta = batch_fetch_team_meta(client, list(comparison_union))
    all_meta = {**comparison_meta, **target_meta}

    replay_map: dict[str, dict[str, Any]] = {}
    explainability_map: dict[str, pd.DataFrame] = {}
    schedule_metrics_map: dict[str, ScheduleMetrics] = {}
    peer_metrics_map: dict[str, dict[str, float | None]] = {}

    for cohort_key, cohort_rows in cohort_rows_map.items():
        cohort_target_ids = [team_id for team_id in target_ids if (published_rows[team_id]["age_group"], published_rows[team_id]["gender"]) == cohort_key]
        cohort_compare_ids = sorted({comp_id for team_id in cohort_target_ids for comp_id in comparison_ids_map.get(team_id, [])})
        cohort_audit_ids = sorted(set(cohort_target_ids) | set(cohort_compare_ids))
        team_games = build_team_windows(games_df, cohort_audit_ids, cfg, baseline_day)

        opponent_ids = sorted({str(opp_id) for team_id in cohort_audit_ids for opp_id in team_games[team_id]["opp_id"].astype(str).tolist()}) if cohort_audit_ids else []
        opponent_rankings = batch_fetch_rankings_rows(
            client,
            opponent_ids,
            "team_id,age_group,gender,state_code,status,power_score_true,rank_in_cohort_final,glicko_rating,glicko_rd,glicko_volatility",
        )
        opponent_meta = batch_fetch_team_meta(client, opponent_ids)
        all_meta.update(opponent_meta)

        team_state_map = {
            team_id: (all_meta.get(team_id, {}) or {}).get("state_code") or (published_rows.get(team_id, {}) or {}).get("state_code")
            for team_id in set(cohort_audit_ids) | set(opponent_ids)
        }
        team_ratings = {
            str(row["team_id"]): (
                safe_float(row.get("glicko_rating")) or cfg.INITIAL_MU,
                safe_float(row.get("glicko_rd")) or cfg.INITIAL_SIGMA,
                safe_float(row.get("glicko_volatility")) or cfg.INITIAL_VOLATILITY,
            )
            for _, row in cohort_rows.iterrows()
        }
        global_rating_map = {
            team_id: safe_float(row.get("glicko_rating")) or cfg.INITIAL_MU
            for team_id, row in opponent_rankings.items()
        }

        cohort_age = normalize_age(cohort_key[0]) or 0
        tier_league_map = None
        if cohort_age >= 13:
            tier_league_map = {
                team_id: meta.get("league")
                for team_id, meta in {**all_meta, **opponent_meta}.items()
                if meta.get("league")
            }

        scf_data = compute_scf(
            games_df[games_df["team_id"].isin(cohort_audit_ids)].copy(),
            team_state_map=team_state_map,
            team_ratings={team_id: team_ratings.get(team_id, (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY)) for team_id in cohort_audit_ids},
            cfg=cfg,
            team_games=team_games,
            tier_league_map=tier_league_map,
        )
        replay_map.update(scf_data)

        explain_df = compute_game_explainability(
            games_df[games_df["team_id"].isin(cohort_audit_ids)].copy(),
            team_ratings={team_id: team_ratings.get(team_id, (cfg.INITIAL_MU, cfg.INITIAL_SIGMA, cfg.INITIAL_VOLATILITY)) for team_id in cohort_audit_ids},
            cfg=cfg,
            today=baseline_day,
            team_games=team_games,
            global_rating_map=global_rating_map,
        )
        explain_df = attach_cross_age_flags(explain_df, team_games)

        for team_id in cohort_audit_ids:
            schedule_metrics_map[team_id] = compute_schedule_metrics(
                team_id,
                team_games.get(team_id, pd.DataFrame()),
                opponent_rankings,
                {**all_meta, **opponent_meta},
                team_state_map,
            )
            explainability_map[team_id] = (
                explain_df[explain_df["team_id"].astype(str) == team_id].copy() if not explain_df.empty else pd.DataFrame()
            )

        for team_id in cohort_target_ids:
            peer_metrics = [schedule_metrics_map[cid] for cid in comparison_ids_map.get(team_id, []) if cid in schedule_metrics_map and cid != team_id]
            peer_metrics_map[team_id] = peer_metric_medians(peer_metrics)

    summary_rows: list[dict[str, Any]] = []
    team_sections: list[str] = []

    for cohort_key, cohort_rows in cohort_rows_map.items():
        base_rank_map = compute_base_rank_map(cohort_rows)
        cohort_target_ids = [team_id for team_id in target_ids if (published_rows[team_id]["age_group"], published_rows[team_id]["gender"]) == cohort_key]
        for team_id in cohort_target_ids:
            team_row = published_rows[team_id]
            meta = all_meta.get(team_id, {})
            schedule = schedule_metrics_map[team_id]
            classification = classify_team(
                team_row=team_row,
                base_rank=base_rank_map.get(team_id),
                schedule=schedule,
                peer_medians=peer_metrics_map.get(team_id, {}),
                scf_row=replay_map.get(team_id, {}),
                explain_df=explainability_map.get(team_id, pd.DataFrame()),
            )
            ml_lift = (safe_float(team_row.get("power_score_true")) or 0.0) - (safe_float(team_row.get("powerscore_adj")) or 0.0)
            summary_rows.append(
                {
                    "team_id": team_id,
                    "team_name": meta.get("team_name") or team_id,
                    "club_name": meta.get("club_name") or "",
                    "cohort": f"{team_row.get('age_group')} {team_row.get('gender')}",
                    "published_rank": safe_float(team_row.get("rank_in_cohort_final")),
                    "base_rank": base_rank_map.get(team_id),
                    "ml_lift": ml_lift,
                    "top20_count": schedule.top20_count,
                    "top100_count": schedule.top100_count,
                    "top500_count": schedule.top500_count,
                    "avg_opp_rank": schedule.avg_opp_rank,
                    "avg_opp_power_true": schedule.avg_opp_power_true,
                    "cross_age_games": schedule.cross_age_games,
                    "cross_age_share": schedule.cross_age_share,
                    "repeat_opponents_3plus": schedule.repeat_opponents_3plus,
                    "repeat_share": schedule.repeat_share,
                    "primary_driver": classification.primary_driver,
                    "why_high": classification.why_high,
                    "scf": safe_float(replay_map.get(team_id, {}).get("scf")),
                    "is_isolated": bool(replay_map.get(team_id, {}).get("is_isolated")),
                    "bridge_games": schedule.bridge_games,
                    "unique_opp_states": schedule.unique_opp_states,
                }
            )

            peer = peer_metrics_map.get(team_id, {})
            decomp_table = markdown_table(
                ["Metric", "Value"],
                [
                    ["Glicko rating", fmt_num(team_row.get("glicko_rating"))],
                    ["Glicko RD", fmt_num(team_row.get("glicko_rd"))],
                    ["powerscore_adj", fmt_num(team_row.get("powerscore_adj"))],
                    ["powerscore_ml", fmt_num(team_row.get("powerscore_ml"))],
                    ["power_score_true", fmt_num(team_row.get("power_score_true"))],
                    ["ML lift (true - adj)", fmt_num(ml_lift)],
                ],
            )
            schedule_table = markdown_table(
                ["Metric", "Team", "Peer Median"],
                [
                    metric_row("Window games", schedule.window_games, None, fmt_int, fmt_int),
                    metric_row("Top-100 opponents", schedule.top100_count, peer.get("top100_count"), fmt_int, fmt_int),
                    metric_row("Top-500 opponents", schedule.top500_count, peer.get("top500_count"), fmt_int, fmt_int),
                    metric_row("Avg opponent power", schedule.avg_opp_power_true, peer.get("avg_opp_power_true")),
                    metric_row("Avg opponent rank", schedule.avg_opp_rank, peer.get("avg_opp_rank")),
                    metric_row("Bridge games", schedule.bridge_games, peer.get("bridge_games"), fmt_int, fmt_int),
                    metric_row("Unique opponent states", schedule.unique_opp_states, peer.get("unique_opp_states"), fmt_int, fmt_int),
                    metric_row("Cross-age share", schedule.cross_age_share, peer.get("cross_age_share"), fmt_pct, fmt_pct),
                    metric_row("Repeat-opponent share", schedule.repeat_share, peer.get("repeat_share"), fmt_pct, fmt_pct),
                ],
            )
            connectivity_table = markdown_table(
                ["Metric", "Value"],
                [
                    ["SCF", fmt_num(replay_map.get(team_id, {}).get("scf"))],
                    ["Is isolated", "Yes" if replay_map.get(team_id, {}).get("is_isolated") else "No"],
                    ["Replay bridge games", fmt_int(replay_map.get(team_id, {}).get("bridge_games"))],
                    ["Replay unique states", fmt_int(replay_map.get(team_id, {}).get("unique_states"))],
                ],
            )
            team_sections.append(
                "\n\n".join(
                    [
                        f"## {meta.get('team_name') or team_id}\n"
                        f"- Team ID: `{team_id}`\n"
                        f"- Club: {meta.get('club_name') or '-'}\n"
                        f"- Cohort: {team_row.get('age_group')} {team_row.get('gender')}\n"
                        f"- Published rank: {fmt_int(team_row.get('rank_in_cohort_final'))}\n"
                        f"- Base rank by powerscore_adj: {fmt_int(base_rank_map.get(team_id))}\n"
                        f"- Primary driver: {classification.primary_driver}\n"
                        f"- Plain-English conclusion: {classification.why_high}\n"
                        f"- Evidence notes: {', '.join(classification.evidence_notes)}",
                        "### Published Decomposition\n" + decomp_table,
                        "### Schedule Evidence\n" + schedule_table,
                        "### Connectivity Replay\n" + connectivity_table,
                        "### Comparison Set\n" + build_comparison_table(cohort_rows, all_meta, comparison_ids_map.get(team_id, [])),
                        "### Strongest Opponents Faced\n" + build_strongest_opponents_table(schedule),
                        "### Highest-Impact Games\n" + build_impact_games_table(explainability_map.get(team_id, pd.DataFrame()), all_meta),
                    ]
                )
            )

    summary_rows = sorted(summary_rows, key=lambda row: (row["published_rank"] or math.inf, row["team_name"]))
    report_text = build_report(baseline_label, summary_rows, team_sections)
    pd.DataFrame(summary_rows).to_csv(csv_path, index=False)
    report_path.write_text(report_text, encoding="utf-8")
    return report_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only audit helper for overranked male teams")
    parser.add_argument("team_ids", nargs="+", help="One or more team UUIDs to audit")
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--report-path")
    parser.add_argument("--csv-path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report_path, csv_path = asyncio.run(run_audit(args))
    except Exception as exc:
        console.print(f"[red]Audit failed:[/red] {exc}")
        return 1
    console.print(f"[green]Wrote report:[/green] {report_path}")
    console.print(f"[green]Wrote csv:[/green] {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
