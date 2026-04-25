#!/usr/bin/env python3
"""Beta tournament seeding optimizer.

Input is a tournament request JSON with one or more age/gender cohorts, a
user-provided tournament format, and the entered teams. The optimizer resolves
teams against the active rankings table, then plugs them into the requested
structure to reduce likely lopsided games.
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import sys
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from supabase import create_client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv(Path(__file__).parent.parent / ".env.local")
load_dotenv(Path(__file__).parent.parent / ".env")
if not os.getenv("SUPABASE_KEY") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_KEY"] = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

from scripts.predictor_python import Game as PredictorGame  # noqa: E402
from scripts.predictor_python import TeamRanking, predict_match  # noqa: E402
from src.rankings.data_adapter import batch_fetch_rows  # noqa: E402
from src.tournaments.seeding_optimizer import (  # noqa: E402
    DivisionSpec,
    MatchupCost,
    TournamentOptimizationResult,
    build_seedable_teams,
    normalize_age_group,
    normalize_gender_label,
    normalize_team_text,
    optimize_tournament_format,
)

COHORT_SELECT_COLS = ",".join(
    [
        "team_id",
        "age_group",
        "gender",
        "state_code",
        "status",
        "games_played",
        "power_score_true",
        "power_score_final",
        "sos_norm",
        "off_norm",
        "def_norm",
        "glicko_rating",
        "glicko_rd",
        "glicko_volatility",
        "rank_in_cohort_final",
    ]
)
TEAM_META_COLS = "team_id_master,team_name,club_name,state_code"


def _get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv(
        "SUPABASE_KEY"
    )
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


def _validate_supported_age_group(age_group: str) -> str:
    normalized = normalize_age_group(age_group)
    age_number = int(normalized.removeprefix("u"))
    if age_number < 10 or age_number > 19:
        raise ValueError(
            f"Unsupported age group '{age_group}'. Tournament seeding beta currently supports u10 through u19 only."
        )
    return normalized


def _fetch_active_cohort_rows(client, age_group: str, gender: str) -> list[dict[str, Any]]:
    all_rows: list[dict[str, Any]] = []
    page_size = 1000
    offset = 0
    normalized_age = _validate_supported_age_group(age_group)
    canonical_gender = normalize_gender_label(gender)

    while True:
        result = (
            client.table("rankings_full")
            .select(COHORT_SELECT_COLS)
            .eq("age_group", normalized_age)
            .eq("gender", canonical_gender)
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
        return []

    ranking_df = pd.DataFrame(all_rows)
    team_ids = sorted(ranking_df["team_id"].dropna().astype(str).unique().tolist())
    meta_rows = batch_fetch_rows(client, "teams", TEAM_META_COLS, "team_id_master", team_ids)
    meta_df = (
        pd.DataFrame(meta_rows)
        .rename(columns={"team_id_master": "team_id"})
        .drop_duplicates(subset=["team_id"], keep="first")
        if meta_rows
        else pd.DataFrame(columns=["team_id", "team_name", "club_name", "state_code"])
    )

    merged = ranking_df.merge(meta_df, on="team_id", how="left", suffixes=("", "_meta"))
    merged["power_score"] = pd.to_numeric(merged["power_score_true"], errors="coerce").fillna(
        pd.to_numeric(merged["power_score_final"], errors="coerce")
    )
    merged["rank_in_cohort"] = pd.to_numeric(merged["rank_in_cohort_final"], errors="coerce")
    merged["team_id"] = merged["team_id"].astype(str)
    merged["search_name"] = merged["team_name"].fillna("").astype(str)
    merged["display_name"] = (
        merged["club_name"].fillna("").astype(str).str.strip() + " " + merged["team_name"].fillna("").astype(str).str.strip()  # noqa: E501
    ).str.strip()
    merged["normalized_names"] = merged.apply(
        lambda row: {
            value
            for value in {
                normalize_team_text(row.get("search_name", "")),
                normalize_team_text(row.get("display_name", "")),
            }
            if value
        },
        axis=1,
    )
    return merged.to_dict(orient="records")


def _request_label(team_request: str | dict[str, Any]) -> str:
    if isinstance(team_request, str):
        return team_request
    team_name = str(team_request.get("team_name") or "").strip()
    club_name = str(team_request.get("club_name") or "").strip()
    return " ".join(part for part in [club_name, team_name] if part).strip() or str(team_request.get("team_id") or "")


def _resolve_team_request(team_request: str | dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    request_payload = {"team_name": team_request} if isinstance(team_request, str) else dict(team_request)
    request_team_id = str(request_payload.get("team_id") or "").strip()
    request_state = str(request_payload.get("state_code") or "").strip().upper()

    if request_team_id:
        for candidate in candidates:
            if str(candidate.get("team_id")) == request_team_id:
                return candidate
        raise ValueError(f"Requested team_id '{request_team_id}' was not found in the active cohort rankings")

    requested_label = _request_label(request_payload)
    normalized_label = normalize_team_text(requested_label)
    if not normalized_label:
        raise ValueError("Each requested team needs either team_id or team_name")

    exact_matches = [
        candidate
        for candidate in candidates
        if normalized_label in candidate.get("normalized_names", set())
    ]
    if request_state:
        exact_matches = [
            candidate for candidate in exact_matches if str(candidate.get("state_code") or "").upper() == request_state
        ] or exact_matches

    if len(exact_matches) == 1:
        return exact_matches[0]

    if len(exact_matches) > 1:
        match_labels = ", ".join(str(candidate.get("display_name") or candidate.get("search_name")) for candidate in exact_matches[:5])  # noqa: E501
        raise ValueError(
            f"Ambiguous team match for '{requested_label}'. "
            f"Multiple active teams matched this request: {match_labels}"
        )

    display_to_candidate = {
        str(candidate.get("display_name") or candidate.get("search_name") or candidate.get("team_id")): candidate
        for candidate in candidates
    }
    close_matches = difflib.get_close_matches(
        requested_label,
        list(display_to_candidate.keys()),
        n=5,
        cutoff=0.55,
    )
    suggestion_text = ", ".join(close_matches) if close_matches else "no close matches found"
    raise ValueError(f"Could not resolve '{requested_label}'. Suggestions: {suggestion_text}")


def _resolve_seedable_teams(cohort_request: dict[str, Any], candidates: list[dict[str, Any]]):
    requested_teams = cohort_request.get("teams") or []
    resolved_rows = []
    seen_team_ids: set[str] = set()

    for team_request in requested_teams:
        candidate = _resolve_team_request(team_request, candidates)
        team_id = str(candidate["team_id"])
        if team_id in seen_team_ids:
            continue
        seen_team_ids.add(team_id)
        resolved_rows.append(
            {
                "team_id": team_id,
                "team_name": candidate.get("search_name") or candidate.get("display_name") or team_id,
                "club_name": candidate.get("club_name"),
                "state_code": candidate.get("state_code"),
                "age_group": candidate.get("age_group") or cohort_request.get("age_group"),
                "gender": candidate.get("gender") or cohort_request.get("gender"),
                "power_score": candidate.get("power_score"),
                "rank_in_cohort": candidate.get("rank_in_cohort"),
                "games_played": candidate.get("games_played"),
            }
        )

    return build_seedable_teams(resolved_rows), resolved_rows


def _build_predictor_team_ranking(row: dict[str, Any]) -> TeamRanking:
    games_played = row.get("games_played", 0)
    try:
        games_played = int(games_played) if games_played is not None and not pd.isna(games_played) else 0
    except (TypeError, ValueError):
        games_played = 0

    age_group = normalize_age_group(row.get("age_group") or "")
    age = int(age_group.removeprefix("u"))

    return TeamRanking(
        team_id_master=str(row["team_id"]),
        power_score_final=float(row.get("power_score", row.get("power_score_final") or 0.5) or 0.5),
        sos_norm=float(row.get("sos_norm") or 0.5),
        offense_norm=float(row.get("offense_norm") or row.get("off_norm") or 0.5),
        defense_norm=float(row.get("defense_norm") or row.get("def_norm") or 0.5),
        age=age,
        games_played=games_played,
        team_name=str(row.get("team_name") or row.get("search_name") or row.get("display_name") or row["team_id"]),
        glicko_rating=float(row["glicko_rating"]) if row.get("glicko_rating") is not None else None,
        glicko_rd=float(row["glicko_rd"]) if row.get("glicko_rd") is not None else None,
        glicko_volatility=float(row["glicko_volatility"]) if row.get("glicko_volatility") is not None else None,
    )


def _fetch_recent_games_for_teams(
    client,
    team_ids: list[str],
    *,
    lookback_days: int = 365,
    sub_batch_size: int = 10,
    page_size: int = 1000,
) -> list[PredictorGame]:
    if not team_ids:
        return []

    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    seen_game_ids: set[str] = set()
    games: list[PredictorGame] = []

    for start in range(0, len(team_ids), sub_batch_size):
        sub_batch = team_ids[start : start + sub_batch_size]
        or_filters: list[str] = []
        for team_id in sub_batch:
            or_filters.append(f"home_team_master_id.eq.{team_id}")
            or_filters.append(f"away_team_master_id.eq.{team_id}")

        offset = 0
        while True:
            response = (
                client.table("games")
                .select("id,home_team_master_id,away_team_master_id,home_score,away_score,game_date")
                .gte("game_date", cutoff_date)
                .not_.is_("home_score", "null")
                .not_.is_("away_score", "null")
                .eq("is_excluded", False)
                .or_(",".join(or_filters))
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = response.data or []
            if not rows:
                break

            for game_row in rows:
                game_id = str(game_row["id"])
                if game_id in seen_game_ids:
                    continue
                seen_game_ids.add(game_id)
                games.append(
                    PredictorGame(
                        id=game_id,
                        home_team_master_id=(
                            str(game_row["home_team_master_id"]) if game_row.get("home_team_master_id") else None
                        ),
                        away_team_master_id=(
                            str(game_row["away_team_master_id"]) if game_row.get("away_team_master_id") else None
                        ),
                        home_score=game_row.get("home_score"),
                        away_score=game_row.get("away_score"),
                        game_date=str(game_row["game_date"]),
                    )
                )

            if len(rows) < page_size:
                break
            offset += page_size

    return games


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _projected_matchup_costs_from_result(
    result: TournamentOptimizationResult,
    matchup_cost_fn,
) -> list[MatchupCost]:
    projected_costs: list[MatchupCost] = []
    for division in result.divisions:
        for pool in division.pools:
            projected_costs.extend(matchup_cost_fn(team_a, team_b) for team_a, team_b in combinations(pool.teams, 2))
    return projected_costs


def _summarize_projected_result(
    result: TournamentOptimizationResult,
    matchup_cost_fn,
) -> dict[str, float | int | str]:
    projected_costs = _projected_matchup_costs_from_result(result, matchup_cost_fn)
    if not projected_costs:
        return {
            "projection_basis": "all_intra_pool_pairings",
            "projected_matchup_count": 0,
            "average_goal_differential": 0.0,
            "median_goal_differential": 0.0,
            "close_game_probability": 1.0,
            "blowout_3plus_probability": 0.0,
            "blowout_5plus_probability": 0.0,
        }

    margins = [float(cost.projected_margin) for cost in projected_costs]
    return {
        "projection_basis": "all_intra_pool_pairings",
        "projected_matchup_count": len(projected_costs),
        "average_goal_differential": float(sum(margins) / len(margins)),
        "median_goal_differential": float(median(margins)),
        "close_game_probability": float(
            sum(float(cost.competitive_probability) for cost in projected_costs) / len(projected_costs)
        ),
        "blowout_3plus_probability": float(
            sum(float(cost.blowout_3plus_probability) for cost in projected_costs) / len(projected_costs)
        ),
        "blowout_5plus_probability": float(
            sum(float(cost.blowout_5plus_probability) for cost in projected_costs) / len(projected_costs)
        ),
    }


def _fetch_actual_event_games(
    client,
    event_name: str,
    team_ids: list[str],
    *,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    if not event_name or not team_ids:
        return []

    all_rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = (
            client.table("games")
            .select(
                "id,game_date,event_name,division_name,home_team_master_id,away_team_master_id,home_score,away_score"
            )
            .eq("event_name", event_name)
            .eq("is_excluded", False)
            .not_.is_("home_score", "null")
            .not_.is_("away_score", "null")
            .in_("home_team_master_id", team_ids)
            .in_("away_team_master_id", team_ids)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = response.data or []
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def _summarize_actual_games(game_rows: list[dict[str, Any]]) -> dict[str, float | int]:
    margins: list[int] = []
    for row in game_rows:
        home_score = row.get("home_score")
        away_score = row.get("away_score")
        if home_score is None or away_score is None:
            continue
        margins.append(abs(int(home_score) - int(away_score)))

    if not margins:
        return {
            "actual_game_count": 0,
            "average_goal_differential": 0.0,
            "median_goal_differential": 0.0,
            "close_game_rate": 0.0,
            "blowout_3plus_rate": 0.0,
            "blowout_5plus_rate": 0.0,
            "draw_rate": 0.0,
        }

    return {
        "actual_game_count": len(margins),
        "average_goal_differential": float(sum(margins) / len(margins)),
        "median_goal_differential": float(median(margins)),
        "close_game_rate": float(sum(1 for margin in margins if margin <= 1) / len(margins)),
        "blowout_3plus_rate": float(sum(1 for margin in margins if margin >= 3) / len(margins)),
        "blowout_5plus_rate": float(sum(1 for margin in margins if margin >= 5) / len(margins)),
        "draw_rate": float(sum(1 for margin in margins if margin == 0) / len(margins)),
    }


def _build_projection_vs_actual_comparison(
    projected_summary: dict[str, float | int | str],
    actual_summary: dict[str, float | int],
) -> dict[str, float | int] | None:
    actual_game_count = int(actual_summary.get("actual_game_count") or 0)
    projected_matchup_count = int(projected_summary.get("projected_matchup_count") or 0)
    if actual_game_count <= 0 or projected_matchup_count <= 0:
        return None

    projected_average = float(projected_summary["average_goal_differential"])
    actual_average = float(actual_summary["average_goal_differential"])
    projected_median = float(projected_summary["median_goal_differential"])
    actual_median = float(actual_summary["median_goal_differential"])

    return {
        "average_goal_differential_improvement": float(actual_average - projected_average),
        "median_goal_differential_improvement": float(actual_median - projected_median),
        "close_game_rate_delta": float(projected_summary["close_game_probability"]) - float(actual_summary["close_game_rate"]),  # noqa: E501
        "blowout_3plus_rate_improvement": float(actual_summary["blowout_3plus_rate"])
        - float(projected_summary["blowout_3plus_probability"]),
        "blowout_5plus_rate_improvement": float(actual_summary["blowout_5plus_rate"])
        - float(projected_summary["blowout_5plus_probability"]),
    }


def _build_predictor_matchup_cost_fn(
    resolved_rows: list[dict[str, Any]],
    all_games: list[PredictorGame],
):
    rankings_by_team_id = {
        str(row["team_id"]): _build_predictor_team_ranking(row)
        for row in resolved_rows
    }
    matchup_cache: dict[tuple[str, str], MatchupCost] = {}
    predictor_name = "python_match_predictor_v1"

    def predictor_matchup_cost(team_a, team_b) -> MatchupCost:
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = matchup_cache.get(cache_key)
        if cached is not None:
            return cached

        prediction = predict_match(
            rankings_by_team_id[team_a.team_id],
            rankings_by_team_id[team_b.team_id],
            all_games,
        )
        projected_margin = max(
            abs(float(prediction.expected_margin)),
            abs(int(prediction.expected_score["teamA"]) - int(prediction.expected_score["teamB"])),
        )
        probability_gap = abs(float(prediction.win_probability_a) - float(prediction.win_probability_b))
        competitive_probability = (
            _sigmoid((1.15 - projected_margin) / 0.45) * 0.7
            + _sigmoid((0.10 - probability_gap) / 0.08) * 0.3
        )
        if prediction.predicted_winner == "draw":
            competitive_probability = max(competitive_probability, 0.85)

        blowout_3plus_probability = _sigmoid((projected_margin - 2.6) / 0.45)
        blowout_5plus_probability = _sigmoid((projected_margin - 4.5) / 0.40)
        total_cost = (
            projected_margin
            + (1.0 - competitive_probability)
            + (2.0 * blowout_3plus_probability)
            + (3.5 * blowout_5plus_probability)
        )
        result = MatchupCost(
            projected_margin=projected_margin,
            competitive_probability=competitive_probability,
            blowout_3plus_probability=blowout_3plus_probability,
            blowout_5plus_probability=blowout_5plus_probability,
            total_cost=total_cost,
        )
        matchup_cache[cache_key] = result
        return result

    return predictor_matchup_cost, predictor_name


def _derive_pool_sizes(division: dict[str, Any]) -> tuple[int, ...]:
    if division.get("pool_sizes"):
        return tuple(int(size) for size in division["pool_sizes"])
    pool_count = division.get("pool_count")
    team_count = int(division["team_count"])
    if pool_count in (None, "", 0):
        return (team_count,)
    pool_count = int(pool_count)
    if pool_count <= 0:
        raise ValueError(f"Invalid pool_count {pool_count} for division '{division.get('name')}'")
    if team_count % pool_count != 0:
        raise ValueError(
            f"Division '{division.get('name')}' has team_count={team_count} and pool_count={pool_count}. "
            "Provide explicit pool_sizes when pools are uneven."
        )
    teams_per_pool = team_count // pool_count
    return tuple(teams_per_pool for _ in range(pool_count))


def _build_division_specs(cohort_request: dict[str, Any]) -> list[DivisionSpec]:
    format_payload = cohort_request.get("format") or {}
    divisions_payload = format_payload.get("divisions") or cohort_request.get("divisions") or []
    divisions = []
    for division in divisions_payload:
        divisions.append(
            DivisionSpec(
                name=str(division["name"]),
                team_count=int(division["team_count"]),
                pool_sizes=_derive_pool_sizes(division),
                advancement=str(division["advancement"]) if division.get("advancement") else None,
            )
        )
    if not divisions:
        raise ValueError("Each cohort needs a format.divisions list")
    return divisions


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize tournament seeding to reduce likely lopsided games")
    parser.add_argument("--input", required=True, help="Path to tournament request JSON")
    parser.add_argument(
        "--output-dir",
        default="reports/tournament_seeding_beta",
        help="Directory for JSON reports",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    request_payload = json.loads(input_path.read_text(encoding="utf-8"))
    cohorts = request_payload.get("cohorts") or []
    if not cohorts:
        raise ValueError("Tournament request JSON needs a non-empty cohorts array")

    client = _get_supabase()
    output_dir = Path(args.output_dir)
    results = []

    for cohort_request in cohorts:
        age_group = str(cohort_request["age_group"])
        gender = str(cohort_request["gender"])
        normalized_age_group = _validate_supported_age_group(age_group)
        candidates = _fetch_active_cohort_rows(client, age_group=age_group, gender=gender)
        if not candidates:
            raise ValueError(f"No active rankings found for cohort {age_group} {gender}")

        divisions = _build_division_specs(cohort_request)
        seedable_teams, resolved_rows = _resolve_seedable_teams(cohort_request, candidates)
        recent_games = _fetch_recent_games_for_teams(client, [team.team_id for team in seedable_teams])
        matchup_cost_fn, matchup_proxy = _build_predictor_matchup_cost_fn(resolved_rows, recent_games)
        optimization_result = optimize_tournament_format(
            seedable_teams,
            divisions,
            matchup_cost_fn=matchup_cost_fn,
            matchup_proxy=matchup_proxy,
        )
        projected_summary = _summarize_projected_result(optimization_result, matchup_cost_fn)
        actual_event_name = str(
            cohort_request.get("actual_event_name") or request_payload.get("actual_event_name") or ""
        ).strip()
        actual_summary = None
        comparison = None
        if actual_event_name:
            actual_games = _fetch_actual_event_games(client, actual_event_name, [team.team_id for team in seedable_teams])  # noqa: E501
            actual_summary = {
                "event_name": actual_event_name,
                **_summarize_actual_games(actual_games),
            }
            comparison = _build_projection_vs_actual_comparison(projected_summary, actual_summary)

        results.append(
            {
                "age_group": normalized_age_group,
                "gender": normalize_gender_label(gender),
                "team_count": len(seedable_teams),
                "historical_games_used": len(recent_games),
                "projection": projected_summary,
                "actual_results": actual_summary,
                "comparison_to_actual": comparison,
                "format": {
                    "divisions": [
                        {
                            "name": division.name,
                            "team_count": division.team_count,
                            "pool_sizes": list(division.pool_sizes),
                            "advancement": division.advancement,
                        }
                        for division in divisions
                    ]
                },
                **optimization_result.to_dict(),
            }
        )

    summary = {
        "event_name": request_payload.get("event_name"),
        "event_date": request_payload.get("event_date"),
        "cohorts": results,
    }
    _write_json(output_dir / "summary.json", summary)

    for cohort in results:
        cohort_slug = f"{cohort['age_group']}_{cohort['gender'].lower()}"
        _write_json(output_dir / f"{cohort_slug}.json", cohort)

    print(f"Saved tournament seeding beta report to {output_dir}")
    for cohort in results:
        print(
            f"{cohort['age_group']} {cohort['gender']}: "
            f"{cohort['team_count']} teams across {len(cohort['divisions'])} divisions "
            f"(cost={cohort['total_cost']:.2f})"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
