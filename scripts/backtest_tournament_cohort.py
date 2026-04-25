#!/usr/bin/env python3
"""Backtest one completed tournament cohort against an optimized reseeding.

Input is intentionally explicit. A completed tournament cohort already has
known entrants and a known division structure, so this script accepts:

- actual event name
- one cohort (age_group + gender)
- explicit division sizes / pool sizes
- explicit entrant rows with canonical team IDs

That lets us replay:
1. the actual completed tournament results
2. an optimized regrouping / reseeding of the same entrants
3. the exact inferred tournament format on the optimized grouping
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from supabase import create_client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

load_dotenv(Path(__file__).parent.parent / ".env.local")
load_dotenv(Path(__file__).parent.parent / ".env")
if not os.getenv("SUPABASE_KEY") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
    os.environ["SUPABASE_KEY"] = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

from scripts.backtest_predictor import (  # noqa: E402
    build_snapshot_index,
    fetch_prediction_feature_snapshots,
)
from scripts.predictor_python import Game as PredictorGame  # noqa: E402
from scripts.predictor_python import TeamRanking, predict_match  # noqa: E402
from src.predictions.point_in_time_match_model import (  # noqa: E402
    PointInTimeMatchModel,
    build_point_in_time_matchup_row,
)
from src.tournaments.schedule_simulator import (  # noqa: E402
    infer_division_schedule_template,
    simulate_tournament_schedule,
)
from src.tournaments.seeding_optimizer import (  # noqa: E402
    DivisionSpec,
    MatchupCost,
    SeedableTeam,
    normalize_age_group,
    normalize_gender_label,
    optimize_tournament_format,
)

TEAM_META_COLS = "team_id_master,team_name,club_name,state_code,provider_team_id,provider_id,is_deprecated"
RANKING_COLS = ",".join(
    [
        "team_id",
        "age_group",
        "gender",
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

PREDICTOR_SOURCE_PYTHON = "python"
PREDICTOR_SOURCE_POINT_IN_TIME = "point_in_time"
DEFAULT_TOURNAMENT_POINT_IN_TIME_STRATEGY = "poisson_draw_gate"


@dataclass(frozen=True)
class TournamentMatchPrediction:
    predicted_winner: str
    expected_score: dict[str, int]
    expected_margin: float
    win_probability_a: float | None = None
    draw_probability: float | None = None
    win_probability_b: float | None = None
    blowout_3plus_probability: float | None = None
    blowout_5plus_probability: float | None = None
    probability_strategy: str | None = None
    source: str = PREDICTOR_SOURCE_PYTHON


def _get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv(
        "SUPABASE_KEY"
    )
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _normalize_actual_games_override(
    actual_games_override: list[dict[str, Any]] | None,
    expected_division_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in actual_games_override or []:
        division_name = str(row.get("division_name") or "")
        if expected_division_names and division_name not in expected_division_names:
            continue
        home_score = row.get("home_score")
        away_score = row.get("away_score")
        if home_score is None or away_score is None:
            continue
        normalized_rows.append(
            {
                "id": str(row.get("id") or ""),
                "division_name": division_name,
                "game_date": str(row.get("game_date") or ""),
                "home_team_master_id": str(row.get("home_team_master_id") or ""),
                "away_team_master_id": str(row.get("away_team_master_id") or ""),
                "home_score": int(home_score),
                "away_score": int(away_score),
            }
        )
    return normalized_rows


def _pair_count(team_count: int) -> int:
    return max(0, int(team_count) * max(0, int(team_count) - 1) // 2)


def _fetch_rows_by_ids(client, table: str, columns: str, id_column: str, ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(ids), 200):
        batch = ids[start : start + 200]
        if not batch:
            continue
        rows.extend((client.table(table).select(columns).in_(id_column, batch).execute().data) or [])
    return rows


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


def _build_predictor_team_ranking(row: dict[str, Any]) -> TeamRanking:
    games_played = row.get("games_played", 0)
    try:
        games_played = int(games_played) if games_played is not None else 0
    except (TypeError, ValueError):
        games_played = 0

    age_group = normalize_age_group(row.get("source_age_group") or row.get("age_group") or "")
    age = int(age_group.removeprefix("u"))

    return TeamRanking(
        team_id_master=str(row["team_id"]),
        power_score_final=float(row.get("power_score", row.get("power_score_final") or 0.5) or 0.5),
        sos_norm=float(row.get("sos_norm") or 0.5),
        offense_norm=float(row.get("off_norm") or 0.5),
        defense_norm=float(row.get("def_norm") or 0.5),
        age=age,
        games_played=games_played,
        team_name=str(row.get("team_name") or row["team_id"]),
        glicko_rating=float(row["glicko_rating"]) if row.get("glicko_rating") is not None else None,
        glicko_rd=float(row["glicko_rd"]) if row.get("glicko_rd") is not None else None,
        glicko_volatility=float(row["glicko_volatility"]) if row.get("glicko_volatility") is not None else None,
    )


def _build_entrant_row(
    entrant: dict[str, Any],
    team_row: dict[str, Any] | None,
    ranking_row: dict[str, Any],
    *,
    cohort_age_group: str,
    cohort_gender: str,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    canonical_team_id = str(entrant["canonical_team_id"])
    ranking_source_team_id = str(entrant.get("ranking_source_team_id") or canonical_team_id)
    event_team_name = str(entrant["event_team_name"])

    power_score = ranking_row.get("power_score_true")
    if power_score is None:
        power_score = ranking_row.get("power_score_final")
    if power_score is None:
        raise ValueError(f"No power score found for entrant '{event_team_name}'")

    source_age_group = normalize_age_group(str(ranking_row.get("age_group") or cohort_age_group))
    source_gender = normalize_gender_label(str(ranking_row.get("gender") or cohort_gender))
    event_age_group = normalize_age_group(str(entrant.get("event_age_group") or cohort_age_group))
    event_gender = normalize_gender_label(str(entrant.get("event_gender") or cohort_gender))

    if notes is not None and canonical_team_id != ranking_source_team_id:
        notes.append(
            f"{event_team_name}: using ranking surrogate {ranking_source_team_id} "
            f"for canonical team {canonical_team_id}"
        )
    if notes is not None and source_age_group != event_age_group:
        notes.append(
            f"{event_team_name}: playing up from {source_age_group} into {event_age_group} "
            "for this tournament cohort"
        )

    return {
        "entrant_id": str(entrant["entrant_id"]),
        "canonical_team_id": canonical_team_id,
        "ranking_source_team_id": ranking_source_team_id,
        "event_team_name": event_team_name,
        "provider_team_id": str(entrant.get("provider_team_id") or ""),
        "actual_division_name": str(entrant["actual_division_name"]),
        "canonical_team_name": (team_row or {}).get("team_name") or event_team_name,
        "club_name": (team_row or {}).get("club_name"),
        "state_code": (team_row or {}).get("state_code"),
        "canonical_is_deprecated": bool((team_row or {}).get("is_deprecated")),
        # Tournament bracket membership defines cohort placement; source age/gender
        # remains available separately for rating/snapshot lookups.
        "age_group": event_age_group,
        "gender": event_gender,
        "source_age_group": source_age_group,
        "source_gender": source_gender,
        "ranking_status": str(ranking_row.get("status") or ""),
        "games_played": int(ranking_row.get("games_played") or 0),
        "power_score": float(power_score),
        "rank_in_cohort": ranking_row.get("rank_in_cohort_final"),
        "sos_norm": ranking_row.get("sos_norm"),
        "off_norm": ranking_row.get("off_norm"),
        "def_norm": ranking_row.get("def_norm"),
        "glicko_rating": ranking_row.get("glicko_rating"),
        "glicko_rd": ranking_row.get("glicko_rd"),
        "glicko_volatility": ranking_row.get("glicko_volatility"),
    }


def _round_half_up(value: Any) -> int:
    try:
        numeric_value = float(value)
    except Exception:
        return 0
    if math.isnan(numeric_value) or math.isinf(numeric_value):
        return 0
    return max(0, int(math.floor(numeric_value + 0.5)))


def _winner_consistent_expected_score(
    predicted_winner: str,
    expected_goals_a: float,
    expected_goals_b: float,
) -> dict[str, int]:
    score_a = _round_half_up(expected_goals_a)
    score_b = _round_half_up(expected_goals_b)

    if predicted_winner == "team_a" and score_a <= score_b:
        score_a = score_b + 1
    elif predicted_winner == "team_b" and score_b <= score_a:
        score_b = score_a + 1
    elif predicted_winner == "draw" and score_a != score_b:
        tied_score = _round_half_up((float(expected_goals_a) + float(expected_goals_b)) / 2.0)
        score_a = tied_score
        score_b = tied_score

    return {
        "teamA": score_a,
        "teamB": score_b,
    }


def _normalize_predicted_outcome(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"team_a", "team_a_win", "a", "home"}:
        return "team_a"
    if normalized in {"team_b", "team_b_win", "b", "away"}:
        return "team_b"
    return "draw"


def _snapshot_as_of_date(snapshot_entries: list[dict[str, Any]] | None, target_date: str) -> dict[str, Any] | None:
    if not snapshot_entries:
        return None

    target_ts = pd.Timestamp(target_date).normalize()
    candidate: dict[str, Any] | None = None
    for entry in snapshot_entries:
        snapshot_ts = entry.get("snapshot_ts")
        if snapshot_ts is None or pd.isna(snapshot_ts):
            snapshot_date = entry.get("snapshot_date")
            if not snapshot_date:
                continue
            try:
                snapshot_ts = pd.Timestamp(snapshot_date).normalize()
            except Exception:
                continue
        if snapshot_ts <= target_ts:
            candidate = entry
            continue
        break
    return candidate


def _synthesize_snapshot_from_entrant_row(entrant_row: dict[str, Any], prediction_date: str) -> dict[str, Any]:
    games_played = max(0, int(entrant_row.get("games_played") or 0))
    draw_guess = min(games_played, max(0, int(round(games_played * 0.12))))
    remaining_games = max(0, games_played - draw_guess)
    power_score = float(entrant_row.get("power_score") or 0.5)
    win_share = min(max(power_score, 0.15), 0.85)
    win_guess = min(remaining_games, max(0, int(round(remaining_games * win_share))))
    loss_guess = max(0, remaining_games - win_guess)
    offense_norm = float(entrant_row.get("off_norm") or 0.5)
    defense_norm = float(entrant_row.get("def_norm") or 0.5)

    return {
        "snapshot_date": prediction_date,
        "snapshot_ts": pd.Timestamp(prediction_date).normalize(),
        "team_id": str(entrant_row["ranking_source_team_id"]),
        "age_group": str(entrant_row.get("source_age_group") or entrant_row.get("age_group") or ""),
        "gender": str(entrant_row.get("source_gender") or entrant_row.get("gender") or ""),
        "status": str(entrant_row.get("ranking_status") or "Active"),
        "rank_in_cohort_final": entrant_row.get("rank_in_cohort"),
        "power_score_final": power_score,
        "sos_norm": float(entrant_row.get("sos_norm") or 0.5),
        "offense_norm": offense_norm,
        "defense_norm": defense_norm,
        "glicko_rating": entrant_row.get("glicko_rating"),
        "glicko_rd": entrant_row.get("glicko_rd"),
        "glicko_volatility": entrant_row.get("glicko_volatility"),
        "wins": win_guess,
        "losses": loss_guess,
        "draws": draw_guess,
        "games_played": games_played,
        "win_percentage": (float(win_guess) / games_played) if games_played else 0.0,
        "exp_margin": float((power_score - 0.5) * 2.2),
        "exp_win_rate": float(min(max(0.20 + power_score * 0.60, 0.05), 0.95)),
        "exp_goals_for": float(min(max(1.10 + (offense_norm - 0.5) * 1.8, 0.35), 4.25)),
        "exp_goals_against": float(min(max(1.10 - (defense_norm - 0.5) * 1.5, 0.35), 4.25)),
    }


def _resolve_prediction_snapshot(
    entrant_row: dict[str, Any],
    snapshot_entries: list[dict[str, Any]] | None,
    prediction_date: str,
) -> tuple[dict[str, Any], str]:
    as_of_snapshot = _snapshot_as_of_date(snapshot_entries, prediction_date)
    if as_of_snapshot is not None:
        return as_of_snapshot, "as_of"
    if snapshot_entries:
        return snapshot_entries[0], "future_snapshot_fallback"
    return _synthesize_snapshot_from_entrant_row(entrant_row, prediction_date), "synthetic_snapshot_fallback"


def _point_in_time_prediction_from_row(
    row: pd.Series,
    *,
    source: str,
) -> TournamentMatchPrediction:
    predicted_winner = _normalize_predicted_outcome(row.get("predicted_outcome"))
    expected_goals_a = float(row.get("expected_goals_a", row.get("predicted_score_a", 0.0)) or 0.0)
    expected_goals_b = float(row.get("expected_goals_b", row.get("predicted_score_b", 0.0)) or 0.0)
    expected_score = _winner_consistent_expected_score(predicted_winner, expected_goals_a, expected_goals_b)
    expected_margin = float(row.get("predicted_margin", expected_goals_a - expected_goals_b) or 0.0)

    return TournamentMatchPrediction(
        predicted_winner=predicted_winner,
        expected_score=expected_score,
        expected_margin=expected_margin,
        win_probability_a=float(row.get("prob_team_a_win", 0.0) or 0.0),
        draw_probability=float(row.get("prob_draw", 0.0) or 0.0),
        win_probability_b=float(row.get("prob_team_b_win", 0.0) or 0.0),
        blowout_3plus_probability=float(row.get("blowout_3plus_probability", 0.0) or 0.0),
        blowout_5plus_probability=float(row.get("blowout_5plus_probability", 0.0) or 0.0),
        probability_strategy=str(row.get("probability_strategy") or ""),
        source=source,
    )


def _point_in_time_matchup_cost(prediction: TournamentMatchPrediction) -> MatchupCost:
    projected_margin = max(
        abs(float(prediction.expected_margin)),
        abs(int(prediction.expected_score["teamA"]) - int(prediction.expected_score["teamB"])),
    )
    win_probability_a = float(prediction.win_probability_a or 0.0)
    win_probability_b = float(prediction.win_probability_b or 0.0)
    draw_probability = float(prediction.draw_probability or 0.0)
    probability_gap = abs(win_probability_a - win_probability_b)
    competitive_probability = (
        _sigmoid((1.05 - projected_margin) / 0.35) * 0.45
        + _sigmoid((0.12 - probability_gap) / 0.08) * 0.25
        + draw_probability * 0.30
    )
    if prediction.predicted_winner == "draw":
        competitive_probability = max(competitive_probability, 0.88)

    blowout_3plus_probability = float(prediction.blowout_3plus_probability or _sigmoid((projected_margin - 2.6) / 0.45))
    blowout_5plus_probability = float(prediction.blowout_5plus_probability or _sigmoid((projected_margin - 4.5) / 0.40))
    total_cost = (
        projected_margin
        + (1.0 - competitive_probability)
        + (2.0 * blowout_3plus_probability)
        + (3.5 * blowout_5plus_probability)
    )
    return MatchupCost(
        projected_margin=projected_margin,
        competitive_probability=competitive_probability,
        blowout_3plus_probability=blowout_3plus_probability,
        blowout_5plus_probability=blowout_5plus_probability,
        total_cost=total_cost,
    )


def _override_point_in_time_probability_strategy(
    model: PointInTimeMatchModel,
    probability_strategy: str | None,
) -> str | None:
    if not probability_strategy:
        return None
    requested = str(probability_strategy).strip().lower()
    if not requested:
        return None
    if requested == str(model.probability_strategy).strip().lower():
        return None

    model.requested_probability_strategy = requested
    model.probability_strategy = requested
    # Loaded artifacts only persist the selected policy. When we override the
    # probability engine for tournament replay, fall back to the model's
    # built-in conservative draw policy instead of reusing a policy fit for a
    # different strategy.
    model.draw_decision_policy = {
        "default": model._default_draw_decision_policy(),
        "by_age": {},
    }
    return requested


def _resolve_point_in_time_probability_strategy_override(
    cli_override: str | None,
    payload_override: str | None = None,
) -> str:
    for candidate in (cli_override, payload_override):
        normalized = str(candidate or "").strip().lower()
        if normalized:
            return normalized
    return DEFAULT_TOURNAMENT_POINT_IN_TIME_STRATEGY


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _build_python_prediction_and_cost_functions(
    entrant_rows: list[dict[str, Any]],
    all_games: list[PredictorGame],
):
    rankings_by_entrant_id = {
        str(row["entrant_id"]): _build_predictor_team_ranking(
            {
                "team_id": row["ranking_source_team_id"],
                "team_name": row["event_team_name"],
                "power_score": row["power_score"],
                "age_group": row["age_group"],
                "games_played": row["games_played"],
                "sos_norm": row["sos_norm"],
                "off_norm": row["off_norm"],
                "def_norm": row["def_norm"],
                "glicko_rating": row["glicko_rating"],
                "glicko_rd": row["glicko_rd"],
                "glicko_volatility": row["glicko_volatility"],
            }
        )
        for row in entrant_rows
    }
    prediction_cache: dict[tuple[str, str], Any] = {}
    cost_cache: dict[tuple[str, str], MatchupCost] = {}

    def predict_fn(team_a: SeedableTeam, team_b: SeedableTeam):
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = prediction_cache.get(cache_key)
        if cached is not None:
            return cached

        prediction = predict_match(
            rankings_by_entrant_id[team_a.team_id],
            rankings_by_entrant_id[team_b.team_id],
            all_games,
        )
        prediction_cache[cache_key] = prediction
        return prediction

    def matchup_cost_fn(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = cost_cache.get(cache_key)
        if cached is not None:
            return cached

        prediction = predict_fn(team_a, team_b)
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
        cost_cache[cache_key] = result
        return result

    return predict_fn, matchup_cost_fn


def _build_point_in_time_prediction_and_cost_functions(
    entrant_rows: list[dict[str, Any]],
    all_games: list[PredictorGame],
    *,
    prediction_date: str,
    snapshot_index: dict[str, list[dict[str, Any]]],
    resolved_snapshots_by_source_id: dict[str, dict[str, Any]] | None = None,
    model_artifact: Path,
    probability_strategy_override: str | None = None,
):
    model = PointInTimeMatchModel.load(str(model_artifact))
    _override_point_in_time_probability_strategy(model, probability_strategy_override)
    entrant_by_id = {str(row["entrant_id"]): row for row in entrant_rows}
    team_names = {
        str(row["ranking_source_team_id"]): str(row["event_team_name"])
        for row in entrant_rows
        if row.get("ranking_source_team_id")
    }
    if resolved_snapshots_by_source_id is None:
        resolved_snapshots_by_source_id = {}
        for entrant_row in entrant_rows:
            source_id = str(entrant_row["ranking_source_team_id"])
            resolved_snapshot, _ = _resolve_prediction_snapshot(
                entrant_row,
                snapshot_index.get(source_id),
                prediction_date,
            )
            resolved_snapshots_by_source_id[source_id] = resolved_snapshot
    prior_games = tuple(game for game in all_games if str(game.game_date) < prediction_date)
    prediction_cache: dict[tuple[str, str], TournamentMatchPrediction] = {}
    cost_cache: dict[tuple[str, str], MatchupCost] = {}

    def _predict(team_a: SeedableTeam, team_b: SeedableTeam) -> TournamentMatchPrediction:
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = prediction_cache.get(cache_key)
        if cached is not None:
            return cached

        team_a_row = entrant_by_id[team_a.team_id]
        team_b_row = entrant_by_id[team_b.team_id]
        team_a_source_id = str(team_a_row["ranking_source_team_id"])
        team_b_source_id = str(team_b_row["ranking_source_team_id"])
        team_a_snapshot = resolved_snapshots_by_source_id.get(team_a_source_id)
        team_b_snapshot = resolved_snapshots_by_source_id.get(team_b_source_id)
        if team_a_snapshot is None:
            raise ValueError(f"Missing point-in-time snapshot for {team_a_row['event_team_name']} as of {prediction_date}")  # noqa: E501
        if team_b_snapshot is None:
            raise ValueError(f"Missing point-in-time snapshot for {team_b_row['event_team_name']} as of {prediction_date}")  # noqa: E501

        matchup_frame = pd.DataFrame(
            [
                build_point_in_time_matchup_row(
                    team_a_id=team_a_source_id,
                    team_b_id=team_b_source_id,
                    team_a_snapshot=team_a_snapshot,
                    team_b_snapshot=team_b_snapshot,
                    all_games=list(prior_games),
                    game_date=prediction_date,
                    snapshot_index=snapshot_index,
                    team_names={
                        team_a_source_id: team_names.get(team_a_source_id) or team_a.team_name,
                        team_b_source_id: team_names.get(team_b_source_id) or team_b.team_name,
                    },
                    game_id=f"tournament:{team_a.team_id}:{team_b.team_id}:{prediction_date}",
                    example_orientation="tournament_backtest",
                )
            ]
        )
        prediction_frame = model.relabel_evaluation_frame(model.predict_frame(matchup_frame))
        prediction_row = prediction_frame.iloc[0]
        prediction = _point_in_time_prediction_from_row(
            prediction_row,
            source=f"{PREDICTOR_SOURCE_POINT_IN_TIME}:{model_artifact.stem}",
        )
        prediction_cache[cache_key] = prediction
        cost_cache[cache_key] = _point_in_time_matchup_cost(prediction)
        return prediction

    def predict_fn(team_a: SeedableTeam, team_b: SeedableTeam) -> TournamentMatchPrediction:
        return _predict(team_a, team_b)

    def matchup_cost_fn(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = cost_cache.get(cache_key)
        if cached is not None:
            return cached
        _predict(team_a, team_b)
        return cost_cache[cache_key]

    return predict_fn, matchup_cost_fn, model


def _build_division_specs(payload: dict[str, Any]) -> list[DivisionSpec]:
    divisions: list[DivisionSpec] = []
    for division in payload.get("divisions") or []:
        pool_sizes = tuple(int(size) for size in division.get("pool_sizes") or [int(division["team_count"])])
        divisions.append(
            DivisionSpec(
                name=str(division["name"]),
                team_count=int(division["team_count"]),
                pool_sizes=pool_sizes,
                advancement=str(division["advancement"]) if division.get("advancement") else None,
            )
        )
    if not divisions:
        raise ValueError("Input needs a non-empty divisions list")
    return divisions


def _summarize_actual_games(game_rows: list[dict[str, Any]]) -> dict[str, float | int]:
    margins = [abs(int(row["home_score"]) - int(row["away_score"])) for row in game_rows]
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
        "median_goal_differential": float(sorted(margins)[len(margins) // 2] if len(margins) % 2 else (sorted(margins)[len(margins) // 2 - 1] + sorted(margins)[len(margins) // 2]) / 2),  # noqa: E501
        "close_game_rate": float(sum(1 for margin in margins if margin <= 1) / len(margins)),
        "blowout_3plus_rate": float(sum(1 for margin in margins if margin >= 3) / len(margins)),
        "blowout_5plus_rate": float(sum(1 for margin in margins if margin >= 5) / len(margins)),
        "draw_rate": float(sum(1 for margin in margins if margin == 0) / len(margins)),
    }


def _summarize_actual_games_by_division(game_rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    by_division: dict[str, list[dict[str, Any]]] = {}
    for row in game_rows:
        by_division.setdefault(str(row["division_name"]), []).append(row)
    return {division_name: _summarize_actual_games(rows) for division_name, rows in by_division.items()}


def _build_division_recommendations(
    entrant_rows: list[dict[str, Any]],
    optimized_divisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    division_order = {division["name"]: index for index, division in enumerate(optimized_divisions, start=1)}
    recommended_by_entrant: dict[str, str] = {}
    for division in optimized_divisions:
        for team in division["teams"]:
            recommended_by_entrant[str(team["team_id"])] = str(division["name"])

    recommendations: list[dict[str, Any]] = []
    for entrant in entrant_rows:
        actual_division = str(entrant["actual_division_name"])
        recommended_division = recommended_by_entrant[str(entrant["entrant_id"])]
        actual_rank = division_order.get(actual_division, 0)
        recommended_rank = division_order.get(recommended_division, 0)
        if recommended_rank < actual_rank:
            move = "move_up"
        elif recommended_rank > actual_rank:
            move = "move_down"
        else:
            move = "stay"
        recommendations.append(
            {
                "event_team_name": entrant["event_team_name"],
                "canonical_team_name": entrant["canonical_team_name"],
                "club_name": entrant["club_name"],
                "provider_team_id": entrant.get("provider_team_id"),
                "actual_division": actual_division,
                "recommended_division": recommended_division,
                "move": move,
                "power_score": entrant["power_score"],
                "ranking_source_team_id": entrant["ranking_source_team_id"],
                "canonical_team_id": entrant["canonical_team_id"],
                "ranking_status": entrant["ranking_status"],
            }
        )

    recommendations.sort(key=lambda row: (row["move"] == "stay", row["recommended_division"], -(row["power_score"] or 0.0)))  # noqa: E501
    return recommendations


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest one completed tournament cohort against an optimized reseeding")  # noqa: E501
    parser.add_argument("--input", required=True, help="Path to cohort backtest request JSON")
    parser.add_argument(
        "--output-dir",
        default="reports/tournament_cohort_backtest",
        help="Directory for JSON/CSV outputs",
    )
    parser.add_argument(
        "--predictor-source",
        default=PREDICTOR_SOURCE_PYTHON,
        choices=[PREDICTOR_SOURCE_PYTHON, PREDICTOR_SOURCE_POINT_IN_TIME],
        help="Prediction engine for simulated tournament games and matchup costs",
    )
    parser.add_argument(
        "--point-in-time-model-artifact",
        default=None,
        help="Path to a trained point-in-time model artifact (.pkl) when using --predictor-source point_in_time",
    )
    parser.add_argument(
        "--point-in-time-probability-strategy",
        choices=["hybrid", "poisson_primary", "poisson_draw_gate"],
        default=None,
        help=(
            "Probability engine for point-in-time tournament replay. Defaults to "
            f"{DEFAULT_TOURNAMENT_POINT_IN_TIME_STRATEGY}. Uses the model's default "
            "conservative draw policy for overrides."
        ),
    )
    parser.add_argument(
        "--history-lookback-days",
        type=int,
        default=365,
        help="Historical game window to use when building matchup context",
    )
    parser.add_argument(
        "--snapshot-buffer-days",
        type=int,
        default=30,
        help="Extra days to include before the tournament start when fetching point-in-time snapshots",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    event_name = str(payload["event_name"])
    age_group = normalize_age_group(str(payload["age_group"]))
    gender = normalize_gender_label(str(payload["gender"]))
    divisions = _build_division_specs(payload)
    entrants_payload = payload.get("entrants") or []
    if not entrants_payload:
        raise ValueError("Input needs a non-empty entrants list")

    client = _get_supabase()
    canonical_team_ids = sorted({str(entrant["canonical_team_id"]) for entrant in entrants_payload})
    ranking_source_ids = sorted(
        {
            str(entrant.get("ranking_source_team_id") or entrant["canonical_team_id"])
            for entrant in entrants_payload
        }
    )

    team_rows = _fetch_rows_by_ids(client, "teams", TEAM_META_COLS, "team_id_master", canonical_team_ids)
    ranking_rows = _fetch_rows_by_ids(client, "rankings_full", RANKING_COLS, "team_id", ranking_source_ids)
    team_by_id = {str(row["team_id_master"]): row for row in team_rows}
    ranking_by_id = {str(row["team_id"]): row for row in ranking_rows}

    entrant_rows: list[dict[str, Any]] = []
    seedable_teams: list[SeedableTeam] = []
    notes: list[str] = []
    for entrant in entrants_payload:
        canonical_team_id = str(entrant["canonical_team_id"])
        ranking_source_team_id = str(entrant.get("ranking_source_team_id") or canonical_team_id)
        team_row = team_by_id.get(canonical_team_id)
        ranking_row = ranking_by_id.get(ranking_source_team_id)

        if ranking_row is None:
            raise ValueError(
                f"No rankings_full row found for entrant '{entrant.get('event_team_name')}' "
                f"(ranking_source_team_id={ranking_source_team_id})"
            )

        entrant_row = _build_entrant_row(
            entrant,
            team_row,
            ranking_row,
            cohort_age_group=age_group,
            cohort_gender=gender,
            notes=notes,
        )
        entrant_rows.append(entrant_row)
        seedable_teams.append(
            SeedableTeam(
                team_id=entrant_row["entrant_id"],
                team_name=entrant_row["event_team_name"],
                age_group=entrant_row["age_group"],
                gender=entrant_row["gender"],
                power_score=entrant_row["power_score"],
                rank_in_cohort=float(entrant_row["rank_in_cohort"]) if entrant_row["rank_in_cohort"] is not None else None,  # noqa: E501
                club_name=entrant_row["club_name"],
                state_code=entrant_row["state_code"],
                games_played=entrant_row["games_played"],
            )
        )

    actual_games = (
        _normalize_actual_games_override(
            payload.get("actual_games_override"),
            {
                str(division.get("actual_division_name") or division["name"])
                for division in payload["divisions"]
            },
        )
    )
    if not actual_games:
        actual_games = (
            client.table("games")
            .select("id,division_name,game_date,home_team_master_id,away_team_master_id,home_score,away_score")
            .eq("event_name", event_name)
            .in_("division_name", [str(division.get("actual_division_name") or division["name"]) for division in payload["divisions"]])  # noqa: E501
            .eq("is_excluded", False)
            .not_.is_("home_score", "null")
            .not_.is_("away_score", "null")
            .range(0, 1000)
            .execute()
            .data
            or []
        )
    if not actual_games and not payload.get("prediction_date"):
        raise ValueError("No completed games found for the requested cohort, and no prediction_date was provided")

    actual_summary = {
        "event_name": event_name,
        **_summarize_actual_games(actual_games),
        "divisions": _summarize_actual_games_by_division(actual_games),
    }

    prediction_date = str(payload.get("prediction_date") or min(str(row["game_date"]) for row in actual_games))
    recent_games = _fetch_recent_games_for_teams(client, ranking_source_ids, lookback_days=args.history_lookback_days)

    predictor_details: dict[str, Any] = {
        "source": args.predictor_source,
        "prediction_date": prediction_date,
        "history_lookback_days": args.history_lookback_days,
    }
    if args.predictor_source == PREDICTOR_SOURCE_POINT_IN_TIME:
        probability_strategy_override = _resolve_point_in_time_probability_strategy_override(
            args.point_in_time_probability_strategy,
            payload.get("point_in_time_probability_strategy"),
        )
        artifact_option = args.point_in_time_model_artifact or str(payload.get("point_in_time_model_artifact") or "")
        if not artifact_option:
            raise ValueError("Point-in-time predictor selected but no model artifact path was provided")
        artifact_candidate = Path(artifact_option)
        if not artifact_candidate.exists():
            raise FileNotFoundError(f"Point-in-time model artifact not found: {artifact_candidate}")

        related_team_ids = sorted(
            {
                str(game.home_team_master_id)
                for game in recent_games
                if game.home_team_master_id
            }
            | {
                str(game.away_team_master_id)
                for game in recent_games
                if game.away_team_master_id
            }
            | set(ranking_source_ids)
        )
        snapshot_lookback_days = max(0, max(args.history_lookback_days, args.snapshot_buffer_days))
        snapshot_start = (
            pd.Timestamp(prediction_date).normalize() - pd.Timedelta(days=snapshot_lookback_days)
        ).strftime("%Y-%m-%d")
        snapshot_end = pd.Timestamp(prediction_date).normalize().strftime("%Y-%m-%d")
        snapshots_df = asyncio.run(
            fetch_prediction_feature_snapshots(
                client,
                related_team_ids,
                snapshot_start,
                snapshot_end,
            )
        )
        if snapshots_df.empty:
            raise ValueError(
                f"No point-in-time snapshots found for predictor date {prediction_date} and {len(related_team_ids)} teams"  # noqa: E501
            )
        snapshot_index = build_snapshot_index(snapshots_df)
        resolved_snapshots_by_source_id: dict[str, dict[str, Any]] = {}
        snapshot_resolution_counts = {"as_of": 0, "future_snapshot_fallback": 0, "synthetic_snapshot_fallback": 0}
        for entrant_row in entrant_rows:
            source_id = str(entrant_row["ranking_source_team_id"])
            resolved_snapshot, resolution_mode = _resolve_prediction_snapshot(
                entrant_row,
                snapshot_index.get(source_id),
                prediction_date,
            )
            resolved_snapshots_by_source_id[source_id] = resolved_snapshot
            snapshot_resolution_counts[resolution_mode] += 1
            if resolution_mode == "future_snapshot_fallback":
                notes.append(
                    f"{entrant_row['event_team_name']}: no as-of point-in-time snapshot on {prediction_date}; "
                    f"using earliest later snapshot from {resolved_snapshot.get('snapshot_date')}"
                )
            elif resolution_mode == "synthetic_snapshot_fallback":
                notes.append(
                    f"{entrant_row['event_team_name']}: no point-in-time snapshots found; using synthesized "
                    f"snapshot from current ranking inputs"
                )
        predict_fn, matchup_cost_fn, point_in_time_model = _build_point_in_time_prediction_and_cost_functions(
            entrant_rows,
            recent_games,
            prediction_date=prediction_date,
            snapshot_index=snapshot_index,
            resolved_snapshots_by_source_id=resolved_snapshots_by_source_id,
            model_artifact=artifact_candidate,
            probability_strategy_override=probability_strategy_override,
        )
        predictor_details.update(
            {
                "artifact_path": str(artifact_candidate),
                "snapshot_start": snapshot_start,
                "snapshot_end": snapshot_end,
                "snapshot_team_count": len(related_team_ids),
                "snapshot_row_count": int(len(snapshots_df)),
                "snapshot_resolution_counts": snapshot_resolution_counts,
                "probability_strategy": point_in_time_model.probability_strategy,
                "probability_strategy_override": probability_strategy_override,
                "probability_strategy_default": DEFAULT_TOURNAMENT_POINT_IN_TIME_STRATEGY,
                "selection_objective": point_in_time_model.selection_objective,
            }
        )
        matchup_proxy = f"point_in_time_match_model:{point_in_time_model.probability_strategy}"
    else:
        predict_fn, matchup_cost_fn = _build_python_prediction_and_cost_functions(entrant_rows, recent_games)
        matchup_proxy = "python_match_predictor_v1"

    optimization_result = optimize_tournament_format(
        seedable_teams,
        divisions,
        matchup_cost_fn=matchup_cost_fn,
        matchup_proxy=matchup_proxy,
    )

    actual_game_counts = {
        str(division_name): int(summary["actual_game_count"])
        for division_name, summary in actual_summary["divisions"].items()
    }
    templates = {
        division_spec.name: infer_division_schedule_template(
            division_name=division_spec.name,
            actual_division_name=str(division_payload.get("actual_division_name") or division_spec.name),
            pool_sizes=division_spec.pool_sizes,
            actual_game_count=actual_game_counts.get(str(division_payload.get("actual_division_name") or division_spec.name)),  # noqa: E501
        )
        for division_spec, division_payload in zip(divisions, payload["divisions"], strict=False)
    }
    simulated_tournament = simulate_tournament_schedule(
        optimization_result.divisions,
        templates,
        predict_fn,
    )

    comparison = {
        "average_goal_differential_improvement": float(
            actual_summary["average_goal_differential"] - simulated_tournament.average_goal_differential
        ),
        "median_goal_differential_improvement": float(
            actual_summary["median_goal_differential"] - simulated_tournament.median_goal_differential
        ),
        "close_game_rate_delta": float(simulated_tournament.close_game_rate - actual_summary["close_game_rate"]),
        "blowout_3plus_rate_improvement": float(
            actual_summary["blowout_3plus_rate"] - simulated_tournament.blowout_3plus_rate
        ),
        "blowout_5plus_rate_improvement": float(
            actual_summary["blowout_5plus_rate"] - simulated_tournament.blowout_5plus_rate
        ),
    }

    optimized_payload = optimization_result.to_dict()
    optimized_payload["simulated_schedule"] = simulated_tournament.to_dict()
    optimized_payload["schedule_templates"] = {name: template.to_dict() for name, template in templates.items()}

    recommendations = _build_division_recommendations(entrant_rows, optimized_payload["divisions"])
    output_payload = {
        "event_name": event_name,
        "cohort": {"age_group": age_group, "gender": gender},
        "entrant_count": len(entrant_rows),
        "unique_canonical_team_count": len(canonical_team_ids),
        "historical_games_used_for_prediction": len(recent_games),
        "predictor": predictor_details,
        "notes": sorted(set(notes)),
        "actual_results": actual_summary,
        "optimized_projection": optimized_payload,
        "comparison_to_actual": comparison,
        "entrants": entrant_rows,
        "division_recommendations": recommendations,
    }

    output_dir = Path(args.output_dir)
    _write_json(output_dir / "summary.json", output_payload)
    _write_json(output_dir / "division_recommendations.json", recommendations)
    _write_csv(output_dir / "division_recommendations.csv", recommendations)

    print(f"Saved tournament cohort backtest to {output_dir}")
    print(
        f"{age_group} {gender}: actual avg GD={actual_summary['average_goal_differential']:.2f}, "
        f"optimized simulated avg GD={simulated_tournament.average_goal_differential:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
