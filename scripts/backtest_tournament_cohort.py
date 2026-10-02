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
3. the operator-verified tournament format on the optimized grouping
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass, replace
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
from src.tournaments.backtest_rating_fallback import (  # noqa: E402
    MISSING_HISTORY_FALLBACK_POLICY,
    build_average_rating_estimate,
    needs_rating_fallback,
)
from src.tournaments.compare_predictor_bridge import (  # noqa: E402
    PREDICTOR_CALIBRATION_AVAILABLE_DATE,
    PREDICTOR_CALIBRATION_SOURCE_COMMIT,
    canonical_predictor_sha256,
    run_compare_prediction_batch,
    validate_predictor_cutoff,
)
from src.tournaments.modelled_comparison import (  # noqa: E402
    compare_modelled_arrangements,
    project_matchup_pairs,
    summarize_modelled_matchups,
)
from src.tournaments.schedule_simulator import (  # noqa: E402
    captured_division_schedule_template,
    explicit_division_schedule_template,
    prediction_expected_margin,
    simulate_tournament_schedule,
)
from src.tournaments.seeding_optimizer import (  # noqa: E402
    DIVISION_POLICY_RANKED_BANDS,
    POOL_POLICY_BALANCED_STRENGTH,
    DivisionAssignment,
    DivisionSpec,
    FlightAssignment,
    MatchupCost,
    SeedableTeam,
    normalize_age_group,
    normalize_gender_label,
    normalize_tournament_age_group,
    optimize_tournament_format,
)
from src.utils.merge_resolver import MergeResolver  # noqa: E402

TEAM_META_COLS = "team_id_master,team_name,club_name,state_code,provider_team_id,provider_id,is_deprecated"
PREDICTOR_SOURCE_PYTHON = "python"
PREDICTOR_SOURCE_COMPARE = "compare"
PREDICTOR_SOURCE_POINT_IN_TIME = "point_in_time"
DEFAULT_TOURNAMENT_POINT_IN_TIME_STRATEGY = "poisson_draw_gate"
UNCHANGED_MARGIN_MAX_ABSOLUTE_ERROR = 1.0
UNCHANGED_BLOWOUT_RATE_MAX_ABSOLUTE_ERROR = 0.10
UNCHANGED_FIXTURE_MIN_COVERAGE = 0.95
BLOWOUT_4PLUS_COST_WEIGHT = 2.75


@dataclass(frozen=True)
class TournamentMatchPrediction:
    predicted_winner: str
    expected_score: dict[str, int]
    expected_margin: float
    win_probability_a: float | None = None
    draw_probability: float | None = None
    win_probability_b: float | None = None
    blowout_3plus_probability: float | None = None
    blowout_4plus_probability: float | None = None
    blowout_5plus_probability: float | None = None
    probability_strategy: str | None = None
    source: str = PREDICTOR_SOURCE_PYTHON


def _get_supabase():
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    )
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY")
    return create_client(supabase_url, supabase_key)


def _expand_merged_team_ids(resolver: MergeResolver, team_ids: list[str]) -> list[str]:
    """Include deprecated aliases whose immutable game rows belong to these teams."""

    canonical_ids = {str(resolver.resolve(team_id) or team_id) for team_id in team_ids}
    aliases = {
        str(team_id)
        for team_id in resolver.get_deprecated_teams()
        if str(resolver.resolve(team_id) or team_id) in canonical_ids
    }
    return sorted(canonical_ids | aliases)


def _canonicalize_historical_games(
    resolver: MergeResolver,
    games: list[PredictorGame],
) -> list[PredictorGame]:
    """Resolve immutable game-side IDs and omit merge-created self games."""

    canonical: list[PredictorGame] = []
    for game in games:
        home_id = str(resolver.resolve(game.home_team_master_id) or "")
        away_id = str(resolver.resolve(game.away_team_master_id) or "")
        if not home_id or not away_id or home_id == away_id:
            continue
        canonical.append(
            PredictorGame(
                id=game.id,
                home_team_master_id=home_id,
                away_team_master_id=away_id,
                home_score=game.home_score,
                away_score=game.away_score,
                game_date=game.game_date,
                created_at=game.created_at,
            )
        )
    return canonical


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


def _reviewed_actual_games(
    payload: dict[str, Any],
    division_names: set[str],
) -> list[dict[str, Any]] | None:
    """Return reviewed games when supplied; ``None`` means the key was absent."""

    if "actual_games_override" not in payload:
        return None
    return _normalize_actual_games_override(payload.get("actual_games_override"), division_names)


def _pair_count(team_count: int) -> int:
    return max(0, int(team_count) * max(0, int(team_count) - 1) // 2)


def _captured_fixture_count(
    division_payload: dict[str, Any],
    actual_game_counts: dict[str, int],
    *,
    fallback_division_name: str,
) -> int | None:
    """Keep structural fixture coverage separate from the scored-game baseline."""

    captured = division_payload.get("captured_fixture_count")
    if captured is not None:
        return int(captured)
    actual_name = _actual_division_name(division_payload, fallback_division_name)
    return actual_game_counts.get(actual_name)


def _actual_division_name(division_payload: dict[str, Any], fallback_name: str) -> str:
    if "actual_division_name" in division_payload:
        return str(division_payload.get("actual_division_name") or "")
    return str(fallback_name)


def _schedule_template_from_payload(
    division_payload: dict[str, Any],
    division_spec: DivisionSpec,
    actual_game_counts: dict[str, int],
):
    captured = division_payload.get("captured_schedule")
    if captured:
        return captured_division_schedule_template(
            division_name=division_spec.name,
            actual_division_name=_actual_division_name(division_payload, division_spec.name),
            pool_sizes=division_spec.pool_sizes,
            fixture_slots=captured.get("fixture_slots") or (),
            tiebreak_order=captured.get("tiebreak_order") or (),
            tiebreak_source_urls=captured.get("tiebreak_source_urls") or (),
            scoring_policy=str(captured.get("scoring_policy") or ""),
            three_team_head_to_head=bool(captured.get("three_team_head_to_head", False)),
        )
    return explicit_division_schedule_template(
        division_name=division_spec.name,
        actual_division_name=_actual_division_name(division_payload, division_spec.name),
        pool_sizes=division_spec.pool_sizes,
        format_code=division_spec.advancement,
        actual_game_count=_captured_fixture_count(
            division_payload,
            actual_game_counts,
            fallback_division_name=division_spec.name,
        ),
    )


def _fetch_rows_by_ids(client, table: str, columns: str, id_column: str, ids: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        if not batch:
            continue
        rows.extend((client.table(table).select(columns).in_(id_column, batch).execute().data) or [])
    return rows


def _fetch_recent_games_for_teams(
    client,
    team_ids: list[str],
    *,
    as_of_date: str,
    lookback_days: int = 365,
    sub_batch_size: int = 10,
    page_size: int = 1000,
) -> list[PredictorGame]:
    if not team_ids:
        return []

    prediction_ts = pd.Timestamp(as_of_date).normalize()
    cutoff_date = (prediction_ts - pd.Timedelta(days=max(0, lookback_days))).strftime("%Y-%m-%d")
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
                .select(
                    "id,home_team_master_id,away_team_master_id,home_score,away_score,game_date,created_at"
                )
                .gte("game_date", cutoff_date)
                .lt("game_date", prediction_ts.strftime("%Y-%m-%d"))
                .lt("created_at", f"{prediction_ts.strftime('%Y-%m-%d')}T00:00:00+00:00")
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
                        created_at=str(game_row.get("created_at") or ""),
                    )
                )

            if len(rows) < page_size:
                break
            offset += page_size

    return games


def _historical_ranking_row(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Adapt a frozen prediction snapshot to the entrant rating contract."""

    return {
        "team_id": str(snapshot["team_id"]),
        "age_group": snapshot.get("age_group"),
        "gender": snapshot.get("gender"),
        "status": snapshot.get("status"),
        "games_played": snapshot.get("games_played"),
        "power_score_final": snapshot.get("power_score_final"),
        "prediction_power_score": snapshot.get("prediction_power_score"),
        "power_score_scale_version": snapshot.get("power_score_scale_version"),
        "sos_norm": snapshot.get("sos_norm"),
        "off_norm": snapshot.get("offense_norm"),
        "def_norm": snapshot.get("defense_norm"),
        "glicko_rating": snapshot.get("glicko_rating"),
        "glicko_rd": snapshot.get("glicko_rd"),
        "glicko_volatility": snapshot.get("glicko_volatility"),
        "rank_in_cohort_final": snapshot.get("rank_in_cohort_final"),
        "wins": snapshot.get("wins"),
        "losses": snapshot.get("losses"),
        "draws": snapshot.get("draws"),
        "win_percentage": snapshot.get("win_percentage"),
        "exp_margin": snapshot.get("exp_margin"),
        "exp_win_rate": snapshot.get("exp_win_rate"),
        "exp_goals_for": snapshot.get("exp_goals_for"),
        "exp_goals_against": snapshot.get("exp_goals_against"),
        "same_age_games": snapshot.get("same_age_games"),
        "same_age_game_share": snapshot.get("same_age_game_share"),
        "same_age_unique_opponents": snapshot.get("same_age_unique_opponents"),
        "same_age_top100_opp_count": snapshot.get("same_age_top100_opp_count"),
        "same_age_top500_opp_count": snapshot.get("same_age_top500_opp_count"),
        "same_age_avg_opp_power_adj": snapshot.get("same_age_avg_opp_power_adj"),
        "repeat_opponent_share": snapshot.get("repeat_opponent_share"),
        "positive_ml_evidence_scale": snapshot.get("positive_ml_evidence_scale"),
        "publication_cap_rank": snapshot.get("publication_cap_rank"),
        "publication_cap_score": snapshot.get("publication_cap_score"),
    }


def _verify_snapshot_provenance(snapshot: dict[str, Any], *, prediction_date: str, team_name: str) -> None:
    created_at = snapshot.get("created_at")
    if not created_at:
        raise ValueError(
            f"Historical snapshot for '{team_name}' has no created_at provenance and cannot prove availability"
        )
    created_ts = pd.Timestamp(created_at)
    if pd.isna(created_ts):
        raise ValueError(
            f"Historical snapshot for '{team_name}' has invalid created_at provenance and cannot prove availability"
        )
    if created_ts.tzinfo is not None:
        created_ts = created_ts.tz_convert("UTC").tz_localize(None)
    if created_ts >= pd.Timestamp(prediction_date):
        raise ValueError(
            f"Historical snapshot for '{team_name}' was created after the event cutoff; "
            "it is a reconstructed input, not contemporaneous evidence"
        )
    last_calculated = snapshot.get("last_calculated")
    if last_calculated:
        calculated_ts = pd.Timestamp(last_calculated)
        if pd.isna(calculated_ts):
            raise ValueError(
                f"Historical snapshot for '{team_name}' has invalid last_calculated provenance"
            )
        if calculated_ts.tzinfo is not None:
            calculated_ts = calculated_ts.tz_convert("UTC").tz_localize(None)
        if calculated_ts >= pd.Timestamp(prediction_date):
            raise ValueError(
                f"Historical snapshot for '{team_name}' was recalculated after the event cutoff; "
                "it is a reconstructed input, not contemporaneous evidence"
            )


def _filter_snapshot_index_for_cutoff(
    snapshot_index: dict[str, list[dict[str, Any]]],
    prediction_date: str,
) -> dict[str, list[dict[str, Any]]]:
    """Keep only snapshots proven available before the event cutoff.

    The matchup model also consults snapshots for common opponents. Those
    rows need the same strict date and ``created_at`` provenance policy as
    entrant rows; otherwise a same-day or later-backfilled opponent rating
    can leak into a claimed point-in-time comparison.
    """

    filtered: dict[str, list[dict[str, Any]]] = {}
    for team_id, entries in snapshot_index.items():
        eligible: list[dict[str, Any]] = []
        for entry in entries:
            if _snapshot_as_of_date([entry], prediction_date) is None:
                continue
            try:
                _verify_snapshot_provenance(
                    entry,
                    prediction_date=prediction_date,
                    team_name=str(team_id),
                )
            except (TypeError, ValueError):
                continue
            eligible.append(entry)
        if eligible:
            filtered[str(team_id)] = eligible
    return filtered


def _canonicalize_snapshot_index(
    resolver: MergeResolver,
    snapshot_index: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Index immutable snapshot rows under their current canonical team ID."""

    canonical: dict[str, list[dict[str, Any]]] = {}
    for source_id, entries in snapshot_index.items():
        canonical_id = str(resolver.resolve(source_id) or source_id)
        for entry in entries:
            canonical.setdefault(canonical_id, []).append(
                {
                    **entry,
                    "snapshot_source_team_id": str(entry.get("team_id") or source_id),
                    "team_id": canonical_id,
                }
            )
    for canonical_id, entries in canonical.items():
        entries.sort(
            key=lambda entry: (
                pd.Timestamp(entry["snapshot_ts"]),
                str(entry.get("snapshot_source_team_id") or "") == canonical_id,
                str(entry.get("snapshot_source_team_id") or ""),
                str(entry.get("created_at") or ""),
            )
        )
    return canonical


def _verify_model_training_provenance(
    model_training_metadata: dict[str, Any],
    *,
    prediction_date: str,
) -> str:
    """Require proof that model fitting and selection used only earlier games."""

    data_end_date = model_training_metadata.get("model_data_end_date")
    if not data_end_date:
        raise ValueError(
            "Point-in-time model artifact has no model_data_end_date provenance; "
            "retrain it with the current training pipeline"
        )
    normalized_end = pd.Timestamp(data_end_date).normalize()
    if normalized_end >= pd.Timestamp(prediction_date).normalize():
        raise ValueError(
            f"Point-in-time model used data through {normalized_end.strftime('%Y-%m-%d')}, "
            f"which is not before the event cutoff {prediction_date}"
        )
    return normalized_end.strftime("%Y-%m-%d")


def _freeze_historical_inputs(
    entrant_rows: list[dict[str, Any]],
    snapshots_by_source_id: dict[str, dict[str, Any]],
    *,
    prediction_date: str,
    history_start_date: str,
    predictor_source: str,
    model_artifact: Path | None,
    model_training_metadata: dict[str, Any] | None,
    resolved_probability_strategy: str | None,
    recent_games: list[PredictorGame] | None = None,
    related_snapshot_index: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    def freeze_value(value: Any) -> Any:
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        try:
            if value is not None and pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        item = getattr(value, "item", None)
        if callable(item):
            value = item()
        try:
            json.dumps(value)
        except TypeError:
            return str(value)
        return value

    teams = []
    for entrant in sorted(entrant_rows, key=lambda row: str(row["entrant_id"])):
        source_id = str(entrant["ranking_source_team_id"])
        snapshot = snapshots_by_source_id[source_id]
        teams.append(
            {
                "entrant_id": str(entrant["entrant_id"]),
                "canonical_team_id": str(entrant["canonical_team_id"]),
                "ranking_source_team_id": source_id,
                "snapshot_date": str(snapshot["snapshot_date"]),
                "snapshot_source_team_id": str(
                    snapshot.get("snapshot_source_team_id") or snapshot.get("team_id") or source_id
                ),
                "snapshot_created_at": str(snapshot["created_at"]),
                "snapshot_last_calculated": str(snapshot.get("last_calculated") or ""),
                "availability_verified": True,
                "source_age_group": str(entrant["source_age_group"]),
                "source_gender": str(entrant["source_gender"]),
                "event_age_group": str(entrant["age_group"]),
                "event_gender": str(entrant["gender"]),
                "rating_fallback": str(entrant.get("rating_fallback") or ""),
                "rating_basis": str(entrant.get("rating_basis") or "historical_snapshot"),
                "average_source_count": int(entrant.get("average_source_count") or 0),
                "average_source_entrant_ids": list(
                    entrant.get("average_source_entrant_ids") or ()
                ),
                "average_source_team_ids": list(
                    entrant.get("average_source_team_ids") or ()
                ),
                "power_score": float(entrant["power_score"]),
                "rank_in_cohort": entrant.get("rank_in_cohort"),
                "games_played": int(entrant.get("games_played") or 0),
                "sos_norm": entrant.get("sos_norm"),
                "off_norm": entrant.get("off_norm"),
                "def_norm": entrant.get("def_norm"),
                "glicko_rating": entrant.get("glicko_rating"),
                "glicko_rd": entrant.get("glicko_rd"),
                "glicko_volatility": entrant.get("glicko_volatility"),
                "wins": int(entrant.get("wins") or 0),
                "losses": int(entrant.get("losses") or 0),
                "draws": int(entrant.get("draws") or 0),
                "win_percentage": entrant.get("win_percentage"),
                "exp_margin": entrant.get("exp_margin"),
                "exp_win_rate": entrant.get("exp_win_rate"),
                "exp_goals_for": entrant.get("exp_goals_for"),
                "exp_goals_against": entrant.get("exp_goals_against"),
                "same_age_games": entrant.get("same_age_games"),
                "same_age_game_share": entrant.get("same_age_game_share"),
                "same_age_unique_opponents": entrant.get("same_age_unique_opponents"),
                "same_age_top100_opp_count": entrant.get("same_age_top100_opp_count"),
                "same_age_top500_opp_count": entrant.get("same_age_top500_opp_count"),
                "same_age_avg_opp_power_adj": entrant.get("same_age_avg_opp_power_adj"),
                "repeat_opponent_share": entrant.get("repeat_opponent_share"),
                "positive_ml_evidence_scale": entrant.get("positive_ml_evidence_scale"),
                "publication_cap_rank": entrant.get("publication_cap_rank"),
                "publication_cap_score": entrant.get("publication_cap_score"),
            }
        )

    artifact_sha256 = None
    if model_artifact is not None:
        artifact_sha256 = hashlib.sha256(model_artifact.read_bytes()).hexdigest()
    frozen_games = [
        {
            "id": str(game.id),
            "home_team_master_id": game.home_team_master_id,
            "away_team_master_id": game.away_team_master_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "game_date": str(game.game_date),
            "created_at": str(game.created_at or ""),
        }
        for game in sorted(recent_games or [], key=lambda item: (str(item.game_date), str(item.id)))
    ]
    frozen_related_snapshots: list[dict[str, Any]] = []
    for team_id in sorted(related_snapshot_index or {}):
        for snapshot in related_snapshot_index[team_id]:
            frozen_related_snapshots.append(
                {
                    str(key): freeze_value(value)
                    for key, value in sorted(snapshot.items())
                    if key != "snapshot_ts"
                }
            )
    frozen_related_snapshots.sort(
        key=lambda row: (
            str(row.get("team_id") or ""),
            str(row.get("snapshot_date") or ""),
            str(row.get("created_at") or ""),
        )
    )
    payload: dict[str, Any] = {
        "source": "prediction_feature_history",
        "availability_policy": "snapshot_created_before_event_cutoff",
        "data_cutoff_exclusive": prediction_date,
        "history_start_date": history_start_date,
        "team_count": len(teams),
        "teams": teams,
        "model_artifact": str(model_artifact) if model_artifact is not None else None,
        "model_artifact_sha256": artifact_sha256,
        "predictor_source": predictor_source,
        "predictor_sha256": (
            canonical_predictor_sha256()
            if predictor_source == PREDICTOR_SOURCE_COMPARE
            else None
        ),
        "model_training_metadata": model_training_metadata or {},
        "resolved_probability_strategy": resolved_probability_strategy,
        "recent_games": frozen_games,
        "related_snapshots": frozen_related_snapshots,
    }
    if predictor_source == PREDICTOR_SOURCE_COMPARE:
        payload.update(
            {
                "calibration_available_date": PREDICTOR_CALIBRATION_AVAILABLE_DATE,
                "calibration_source_commit": PREDICTOR_CALIBRATION_SOURCE_COMMIT,
            }
        )
    digest_source = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload["input_digest_sha256"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return payload


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
        prediction_power_score=(
            float(row["prediction_power_score"])
            if row.get("prediction_power_score") is not None
            else None
        ),
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
    event_age_group = normalize_tournament_age_group(str(entrant.get("event_age_group") or cohort_age_group))
    event_gender = normalize_gender_label(str(entrant.get("event_gender") or cohort_gender))

    if notes is not None and canonical_team_id != ranking_source_team_id:
        notes.append(
            f"{event_team_name}: using ranking surrogate {ranking_source_team_id} "
            f"for canonical team {canonical_team_id}"
        )
    if notes is not None and source_age_group != event_age_group:
        notes.append(
            f"{event_team_name}: playing up from {source_age_group} into {event_age_group} for this tournament cohort"
        )

    return {
        "entrant_id": str(entrant["entrant_id"]),
        "canonical_team_id": canonical_team_id,
        "ranking_source_team_id": ranking_source_team_id,
        "event_team_name": event_team_name,
        "provider_team_id": str(entrant.get("provider_team_id") or ""),
        "actual_division_key": str(entrant.get("actual_division_key") or entrant["actual_division_name"]),
        "actual_division_name": str(entrant["actual_division_name"]),
        "actual_pool_key": str(entrant.get("actual_pool_key") or ""),
        "actual_pool_name": str(entrant.get("actual_pool_name") or ""),
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
        "rating_fallback": str(entrant.get("rating_fallback") or ""),
        "rating_basis": str(entrant.get("rating_basis") or "historical_snapshot"),
        "games_played": int(ranking_row.get("games_played") or 0),
        "power_score": float(power_score),
        "prediction_power_score": ranking_row.get("prediction_power_score"),
        "power_score_scale_version": ranking_row.get("power_score_scale_version"),
        "rank_in_cohort": ranking_row.get("rank_in_cohort_final"),
        "sos_norm": ranking_row.get("sos_norm"),
        "off_norm": ranking_row.get("off_norm"),
        "def_norm": ranking_row.get("def_norm"),
        "glicko_rating": ranking_row.get("glicko_rating"),
        "glicko_rd": ranking_row.get("glicko_rd"),
        "glicko_volatility": ranking_row.get("glicko_volatility"),
        "wins": int(ranking_row.get("wins") or 0),
        "losses": int(ranking_row.get("losses") or 0),
        "draws": int(ranking_row.get("draws") or 0),
        "win_percentage": ranking_row.get("win_percentage"),
        "exp_margin": ranking_row.get("exp_margin"),
        "exp_win_rate": ranking_row.get("exp_win_rate"),
        "exp_goals_for": ranking_row.get("exp_goals_for"),
        "exp_goals_against": ranking_row.get("exp_goals_against"),
        "same_age_games": ranking_row.get("same_age_games"),
        "same_age_game_share": ranking_row.get("same_age_game_share"),
        "same_age_unique_opponents": ranking_row.get("same_age_unique_opponents"),
        "same_age_top100_opp_count": ranking_row.get("same_age_top100_opp_count"),
        "same_age_top500_opp_count": ranking_row.get("same_age_top500_opp_count"),
        "same_age_avg_opp_power_adj": ranking_row.get("same_age_avg_opp_power_adj"),
        "repeat_opponent_share": ranking_row.get("repeat_opponent_share"),
        "positive_ml_evidence_scale": ranking_row.get("positive_ml_evidence_scale"),
        "publication_cap_rank": ranking_row.get("publication_cap_rank"),
        "publication_cap_score": ranking_row.get("publication_cap_score"),
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
        if snapshot_ts < target_ts:
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

    snapshot_ts = pd.Timestamp(prediction_date).normalize() - pd.Timedelta(days=1)
    snapshot_date = snapshot_ts.strftime("%Y-%m-%d")
    wins = entrant_row.get("wins")
    losses = entrant_row.get("losses")
    draws = entrant_row.get("draws")
    win_percentage = entrant_row.get("win_percentage")
    exp_margin = entrant_row.get("exp_margin")
    exp_win_rate = entrant_row.get("exp_win_rate")
    exp_goals_for = entrant_row.get("exp_goals_for")
    exp_goals_against = entrant_row.get("exp_goals_against")
    is_average_estimate = int(entrant_row.get("average_source_count") or 0) > 0

    def supplied_or_derived(value: Any, derived: float | int) -> Any:
        if value is not None:
            return value
        return None if is_average_estimate else derived

    return {
        "snapshot_date": snapshot_date,
        "snapshot_ts": snapshot_ts,
        "created_at": snapshot_date,
        "last_calculated": snapshot_date,
        "snapshot_source_team_id": str(entrant_row["ranking_source_team_id"]),
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
        "wins": supplied_or_derived(wins, win_guess),
        "losses": supplied_or_derived(losses, loss_guess),
        "draws": supplied_or_derived(draws, draw_guess),
        "games_played": games_played,
        "win_percentage": supplied_or_derived(
            win_percentage,
            (float(win_guess) / games_played * 100.0) if games_played else 0.0,
        ),
        "exp_margin": supplied_or_derived(
            exp_margin,
            float((power_score - 0.5) * 2.2),
        ),
        "exp_win_rate": supplied_or_derived(
            exp_win_rate,
            float(min(max(0.20 + power_score * 0.60, 0.05), 0.95)),
        ),
        "exp_goals_for": supplied_or_derived(
            exp_goals_for,
            float(min(max(1.10 + (offense_norm - 0.5) * 1.8, 0.35), 4.25)),
        ),
        "exp_goals_against": supplied_or_derived(
            exp_goals_against,
            float(min(max(1.10 - (defense_norm - 0.5) * 1.5, 0.35), 4.25)),
        ),
        "same_age_games": entrant_row.get("same_age_games"),
        "same_age_game_share": entrant_row.get("same_age_game_share"),
        "same_age_unique_opponents": entrant_row.get("same_age_unique_opponents"),
        "same_age_top100_opp_count": entrant_row.get("same_age_top100_opp_count"),
        "same_age_top500_opp_count": entrant_row.get("same_age_top500_opp_count"),
        "same_age_avg_opp_power_adj": entrant_row.get("same_age_avg_opp_power_adj"),
        "repeat_opponent_share": entrant_row.get("repeat_opponent_share"),
        "positive_ml_evidence_scale": entrant_row.get("positive_ml_evidence_scale"),
        "publication_cap_rank": entrant_row.get("publication_cap_rank"),
        "publication_cap_score": entrant_row.get("publication_cap_score"),
        "is_average_estimate": True,
        "average_source_count": int(entrant_row.get("average_source_count") or 0),
        "average_source_entrant_ids": list(entrant_row.get("average_source_entrant_ids") or ()),
        "average_source_team_ids": list(entrant_row.get("average_source_team_ids") or ()),
    }


def _resolve_prediction_snapshot(
    entrant_row: dict[str, Any],
    snapshot_entries: list[dict[str, Any]] | None,
    prediction_date: str,
    *,
    allow_fallbacks: bool = False,
) -> tuple[dict[str, Any], str]:
    as_of_snapshot = _snapshot_as_of_date(snapshot_entries, prediction_date)
    if as_of_snapshot is not None:
        return as_of_snapshot, "as_of"
    if allow_fallbacks and snapshot_entries:
        return snapshot_entries[0], "future_snapshot_fallback"
    if allow_fallbacks:
        return _synthesize_snapshot_from_entrant_row(entrant_row, prediction_date), "synthetic_snapshot_fallback"
    raise ValueError(
        f"No prediction_feature_history snapshot exists before {prediction_date} for "
        f"'{entrant_row.get('event_team_name') or entrant_row.get('ranking_source_team_id')}' "
        f"(ranking_source_team_id={entrant_row.get('ranking_source_team_id')})"
    )


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

    def optional_probability(column: str) -> float | None:
        value = row.get(column)
        if value is None or pd.isna(value):
            return None
        return float(value)

    return TournamentMatchPrediction(
        predicted_winner=predicted_winner,
        expected_score=expected_score,
        expected_margin=expected_margin,
        win_probability_a=optional_probability("prob_team_a_win"),
        draw_probability=optional_probability("prob_draw"),
        win_probability_b=optional_probability("prob_team_b_win"),
        blowout_3plus_probability=optional_probability("blowout_3plus_probability"),
        blowout_4plus_probability=optional_probability("blowout_4plus_probability"),
        blowout_5plus_probability=optional_probability("blowout_5plus_probability"),
        probability_strategy=str(row.get("probability_strategy") or ""),
        source=source,
    )


def _validate_optional_probability(value: float | None, *, name: str) -> float | None:
    if value is None:
        return None
    probability = float(value)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError(f"{name} must be a finite probability between 0 and 1; got {value!r}")
    return probability


def _point_in_time_matchup_cost(prediction: TournamentMatchPrediction) -> MatchupCost:
    # ``expected_margin`` is the continuous, holdout-calibrated value that is
    # also reported to the operator.  The integer score is presentation-only;
    # using it as a floor here would optimize a different objective from the
    # one shown in the Backtest result.
    projected_margin = abs(prediction_expected_margin(prediction))
    win_probability_a = _validate_optional_probability(
        prediction.win_probability_a, name="win_probability_a"
    ) or 0.0
    win_probability_b = _validate_optional_probability(
        prediction.win_probability_b, name="win_probability_b"
    ) or 0.0
    draw_probability = _validate_optional_probability(prediction.draw_probability, name="draw_probability") or 0.0
    probability_gap = abs(win_probability_a - win_probability_b)
    competitive_probability = (
        _sigmoid((1.05 - projected_margin) / 0.35) * 0.45
        + _sigmoid((0.12 - probability_gap) / 0.08) * 0.25
        + draw_probability * 0.30
    )
    if prediction.predicted_winner == "draw":
        competitive_probability = max(competitive_probability, 0.88)

    supplied_blowout_3plus = _validate_optional_probability(
        prediction.blowout_3plus_probability, name="blowout_3plus_probability"
    )
    supplied_blowout_4plus = _validate_optional_probability(
        prediction.blowout_4plus_probability, name="blowout_4plus_probability"
    )
    supplied_blowout_5plus = _validate_optional_probability(
        prediction.blowout_5plus_probability, name="blowout_5plus_probability"
    )
    blowout_3plus_probability = (
        supplied_blowout_3plus
        if supplied_blowout_3plus is not None
        else _sigmoid((projected_margin - 2.6) / 0.45)
    )
    blowout_5plus_probability = (
        supplied_blowout_5plus
        if supplied_blowout_5plus is not None
        else _sigmoid((projected_margin - 4.5) / 0.40)
    )
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
        blowout_4plus_probability=supplied_blowout_4plus,
    )


def _apply_backtest_projection_calibration(
    prediction: TournamentMatchPrediction,
    calibration: dict[str, Any] | None,
) -> TournamentMatchPrediction:
    """Apply a model artifact's frozen pre-event holdout calibration."""

    calibration = calibration or {}
    raw_margin_scale = calibration.get("margin_absolute_scale", 1.0)
    if raw_margin_scale is None:
        raw_margin_scale = 1.0
    try:
        margin_scale = float(raw_margin_scale)
    except (TypeError, ValueError):
        margin_scale = 1.0
    if not math.isfinite(margin_scale) or margin_scale <= 0:
        raise ValueError("Backtest margin calibration scale must be finite and positive")
    raw_probability_scales = calibration.get("blowout_probability_scales") or {}

    def scaled_probability(value: float | None, threshold: int) -> float | None:
        if value is None:
            return None
        raw_scale = raw_probability_scales.get(str(threshold), 1.0)
        if raw_scale is None:
            raw_scale = 1.0
        try:
            scale = float(raw_scale)
        except (TypeError, ValueError):
            scale = 1.0
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(
                f"Backtest {threshold}+ blowout calibration scale must be finite and positive"
            )
        return min(1.0, max(0.0, float(value) * scale))

    unscaled_margin = prediction_expected_margin(prediction)
    expected_margin = math.copysign(abs(unscaled_margin) * margin_scale, unscaled_margin)
    return replace(
        prediction,
        expected_margin=expected_margin,
        blowout_3plus_probability=scaled_probability(
            prediction.blowout_3plus_probability, 3
        ),
        blowout_4plus_probability=scaled_probability(
            prediction.blowout_4plus_probability, 4
        ),
        blowout_5plus_probability=scaled_probability(
            prediction.blowout_5plus_probability, 5
        ),
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
    fitted = str(model.probability_strategy).strip().lower()
    if requested == fitted:
        return None
    raise ValueError(
        f"Point-in-time model was fitted for probability strategy '{fitted or 'unknown'}'; "
        f"this Backtest requires '{requested}'"
    )


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


def _matchup_cost_from_prediction(prediction: Any) -> MatchupCost:
    signed_margin = abs(float(prediction.expected_margin))
    distribution_margin = getattr(prediction, "expected_absolute_goal_difference", None)
    projected_margin = signed_margin if distribution_margin is None else float(distribution_margin)
    if not math.isfinite(projected_margin) or projected_margin < 0:
        raise ValueError(
            "expected_absolute_goal_difference must be finite and non-negative; "
            f"got {distribution_margin!r}"
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
    blowout_4plus_probability = _validate_optional_probability(
        getattr(prediction, "blowout_4plus_probability", None),
        name="blowout_4plus_probability",
    )
    return MatchupCost(
        projected_margin=projected_margin,
        competitive_probability=competitive_probability,
        blowout_3plus_probability=blowout_3plus_probability,
        blowout_5plus_probability=blowout_5plus_probability,
        total_cost=(
            projected_margin
            + (1.0 - competitive_probability)
            + (2.0 * blowout_3plus_probability)
            + (BLOWOUT_4PLUS_COST_WEIGHT * (blowout_4plus_probability or 0.0))
            + (3.5 * blowout_5plus_probability)
        ),
        blowout_4plus_probability=blowout_4plus_probability,
    )


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
                "source_age_group": row["source_age_group"],
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
        cache_key = (team_a.team_id, team_b.team_id)
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

        canonical_a, canonical_b = sorted((team_a, team_b), key=lambda team: team.team_id)
        prediction = predict_fn(canonical_a, canonical_b)
        result = _matchup_cost_from_prediction(prediction)
        cost_cache[cache_key] = result
        return result

    return predict_fn, matchup_cost_fn


def _build_compare_prediction_and_cost_functions(
    entrant_rows: list[dict[str, Any]],
    all_games: list[PredictorGame],
):
    teams_by_entrant_id: dict[str, dict[str, Any]] = {}
    for row in entrant_rows:
        source_age = int(normalize_age_group(row["source_age_group"]).removeprefix("u"))
        source_gender = normalize_gender_label(row["source_gender"])
        teams_by_entrant_id[str(row["entrant_id"])] = {
            "team_id_master": str(row["ranking_source_team_id"]),
            "team_name": str(row["event_team_name"]),
            "club_name": row.get("club_name"),
            "league": None,
            "distinction": None,
            "state": row.get("state_code"),
            "age": source_age,
            "gender": "F" if source_gender == "Female" else "M",
            "rank_in_cohort_final": row.get("rank_in_cohort"),
            "power_score_final": row.get("power_score"),
            "glicko_rating": row.get("glicko_rating"),
            "glicko_rd": row.get("glicko_rd"),
            "glicko_volatility": row.get("glicko_volatility"),
            "sos_norm": row.get("sos_norm"),
            "offense_norm": row.get("off_norm"),
            "defense_norm": row.get("def_norm"),
            "wins": int(row.get("wins") or 0),
            "losses": int(row.get("losses") or 0),
            "draws": int(row.get("draws") or 0),
            "games_played": int(row.get("games_played") or 0),
            "last_scraped_at": None,
            "win_percentage": row.get("win_percentage"),
            "exp_margin": row.get("exp_margin"),
            "exp_win_rate": row.get("exp_win_rate"),
            "exp_goals_for": row.get("exp_goals_for"),
            "exp_goals_against": row.get("exp_goals_against"),
            "same_age_games": row.get("same_age_games"),
            "same_age_game_share": row.get("same_age_game_share"),
            "same_age_unique_opponents": row.get("same_age_unique_opponents"),
            "same_age_top100_opp_count": row.get("same_age_top100_opp_count"),
            "same_age_top500_opp_count": row.get("same_age_top500_opp_count"),
            "same_age_avg_opp_power_adj": row.get("same_age_avg_opp_power_adj"),
            "repeat_opponent_share": row.get("repeat_opponent_share"),
            "positive_ml_evidence_scale": row.get("positive_ml_evidence_scale"),
            "publication_cap_rank": row.get("publication_cap_rank"),
            "publication_cap_score": row.get("publication_cap_score"),
        }
    game_payload = [
        {
            "id": str(game.id),
            "home_team_master_id": game.home_team_master_id,
            "away_team_master_id": game.away_team_master_id,
            "home_score": game.home_score,
            "away_score": game.away_score,
            "game_date": str(game.game_date),
            "created_at": str(game.created_at or ""),
        }
        for game in all_games
    ]
    predictions = run_compare_prediction_batch(teams_by_entrant_id, game_payload)
    cost_cache: dict[tuple[str, str], MatchupCost] = {}

    def predict_fn(team_a: SeedableTeam, team_b: SeedableTeam):
        try:
            return predictions[(team_a.team_id, team_b.team_id)]
        except KeyError as exc:
            raise ValueError(
                f"Canonical Compare predictor has no matchup for {team_a.team_id} vs {team_b.team_id}"
            ) from exc

    def matchup_cost_fn(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = cost_cache.get(cache_key)
        if cached is None:
            cached = _matchup_cost_from_prediction(predictions[cache_key])
            cost_cache[cache_key] = cached
        return cached

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
    snapshot_index = _filter_snapshot_index_for_cutoff(snapshot_index, prediction_date)
    model = PointInTimeMatchModel.load(str(model_artifact))
    _override_point_in_time_probability_strategy(model, probability_strategy_override)
    projection_calibration = dict(
        getattr(model, "backtest_projection_calibration", {})
        or (getattr(model, "training_metadata", {}) or {}).get(
            "backtest_projection_calibration", {}
        )
    )
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
        cache_key = (team_a.team_id, team_b.team_id)
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
            raise ValueError(
                f"Missing point-in-time snapshot for {team_a_row['event_team_name']} as of {prediction_date}"
            )  # noqa: E501
        if team_b_snapshot is None:
            raise ValueError(
                f"Missing point-in-time snapshot for {team_b_row['event_team_name']} as of {prediction_date}"
            )  # noqa: E501

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
        prediction = _apply_backtest_projection_calibration(
            prediction,
            projection_calibration,
        )
        prediction_cache[cache_key] = prediction
        return prediction

    def predict_fn(team_a: SeedableTeam, team_b: SeedableTeam) -> TournamentMatchPrediction:
        return _predict(team_a, team_b)

    def matchup_cost_fn(team_a: SeedableTeam, team_b: SeedableTeam) -> MatchupCost:
        cache_key = tuple(sorted((team_a.team_id, team_b.team_id)))
        cached = cost_cache.get(cache_key)
        if cached is not None:
            return cached
        canonical_a, canonical_b = sorted((team_a, team_b), key=lambda team: team.team_id)
        prediction = _predict(canonical_a, canonical_b)
        result = _point_in_time_matchup_cost(prediction)
        cost_cache[cache_key] = result
        return result

    return predict_fn, matchup_cost_fn, model


def _parse_positive_slot_count(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer; got {value!r}")
    if isinstance(value, int):
        count = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        count = int(value.strip())
    else:
        raise ValueError(f"{label} must be a positive integer; got {value!r}")
    if count <= 0:
        raise ValueError(f"{label} must be a positive integer; got {value!r}")
    return count


def _parse_division_name(value: Any, *, index: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Division at index {index} needs a non-empty string name")
    return value.strip()


def _build_division_specs(payload: dict[str, Any]) -> list[DivisionSpec]:
    divisions: list[DivisionSpec] = []
    for index, division in enumerate(payload.get("divisions") or []):
        name = _parse_division_name(division.get("name"), index=index)
        team_count = _parse_positive_slot_count(
            division["team_count"],
            label=f"Division '{name}' team_count",
        )
        pool_sizes = tuple(
            _parse_positive_slot_count(size, label=f"Division '{name}' pool size")
            for size in (division.get("pool_sizes") or [team_count])
        )
        divisions.append(
            DivisionSpec(
                name=name,
                team_count=team_count,
                pool_sizes=pool_sizes,
                advancement=str(division["advancement"]) if division.get("advancement") else None,
                pool_names=tuple(str(name) for name in (division.get("pool_names") or ())),
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
            "total_goal_differential": 0,
            "average_goal_differential": 0.0,
            "median_goal_differential": 0.0,
            "close_game_rate": 0.0,
            "blowout_3plus_rate": 0.0,
            "blowout_4plus_count": 0,
            "blowout_4plus_rate": 0.0,
            "blowout_5plus_rate": 0.0,
            "draw_rate": 0.0,
        }
    return {
        "actual_game_count": len(margins),
        "total_goal_differential": sum(margins),
        "average_goal_differential": float(sum(margins) / len(margins)),
        "median_goal_differential": float(
            sorted(margins)[len(margins) // 2]
            if len(margins) % 2
            else (sorted(margins)[len(margins) // 2 - 1] + sorted(margins)[len(margins) // 2]) / 2
        ),  # noqa: E501
        "close_game_rate": float(sum(1 for margin in margins if margin <= 1) / len(margins)),
        "blowout_3plus_rate": float(sum(1 for margin in margins if margin >= 3) / len(margins)),
        "blowout_4plus_count": sum(1 for margin in margins if margin >= 4),
        "blowout_4plus_rate": float(sum(1 for margin in margins if margin >= 4) / len(margins)),
        "blowout_5plus_rate": float(sum(1 for margin in margins if margin >= 5) / len(margins)),
        "draw_rate": float(sum(1 for margin in margins if margin == 0) / len(margins)),
    }


def _summarize_actual_games_by_division(game_rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    by_division: dict[str, list[dict[str, Any]]] = {}
    for row in game_rows:
        by_division.setdefault(str(row["division_name"]), []).append(row)
    return {division_name: _summarize_actual_games(rows) for division_name, rows in by_division.items()}


def _project_original_pool_arrangement(
    entrant_rows: list[dict[str, Any]],
    teams: list[SeedableTeam],
    matchup_cost_fn,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    teams_by_id = {team.team_id: team for team in teams}
    pools: dict[tuple[str, ...], list[SeedableTeam]] = {}
    issues: list[str] = []
    for entrant in entrant_rows:
        division_name = str(entrant.get("actual_division_name") or "").strip()
        pool_key = str(entrant.get("actual_pool_key") or "").strip()
        pool_name = str(entrant.get("actual_pool_name") or "").strip()
        entrant_id = str(entrant["entrant_id"])
        if pool_key:
            identity = ("captured", pool_key)
        elif pool_name:
            identity = ("legacy", division_name, pool_name)
        else:
            issues.append(f"Entrant {entrant_id} is missing its captured original pool")
            continue
        pools.setdefault(identity, []).append(teams_by_id[entrant_id])
    if issues:
        return None, tuple(issues)
    pairs = [
        (pool_teams[left], pool_teams[right])
        for pool_teams in pools.values()
        for left in range(len(pool_teams))
        for right in range(left + 1, len(pool_teams))
    ]
    return (
        summarize_modelled_matchups(
            project_matchup_pairs(pairs, matchup_cost_fn),
            projection_basis="captured_original_intra_pool_pairings",
        ),
        (),
    )


def _project_optimized_pool_arrangement(
    optimization_result,
    matchup_cost_fn,
) -> dict[str, Any]:
    pairs = [
        (pool.teams[left], pool.teams[right])
        for division in optimization_result.divisions
        for pool in division.pools
        for left in range(len(pool.teams))
        for right in range(left + 1, len(pool.teams))
    ]
    projection = summarize_modelled_matchups(
        project_matchup_pairs(pairs, matchup_cost_fn),
        projection_basis="optimized_intra_pool_pairings",
    )
    if not math.isclose(
        float(projection["total_model_cost"]),
        float(optimization_result.total_cost),
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise RuntimeError("Optimizer total cost disagrees with its reported intra-pool matchup set")
    return projection


def _captured_original_assignments(
    entrant_rows: list[dict[str, Any]],
    teams: list[SeedableTeam],
    divisions: list[DivisionSpec],
) -> tuple[DivisionAssignment, ...]:
    """Rebuild the captured division and pool placement for an unchanged replay."""

    teams_by_id = {team.team_id: team for team in teams}
    assignments: list[DivisionAssignment] = []
    for division in divisions:
        division_rows = [
            row for row in entrant_rows if str(row.get("actual_division_key") or "") == division.name
        ]
        pools: dict[str, list[SeedableTeam]] = {}
        pool_labels: dict[str, str] = {}
        for row in division_rows:
            pool_key = str(row.get("actual_pool_key") or "").strip()
            if not pool_key:
                raise ValueError(
                    f"Entrant {row.get('entrant_id')} is missing its captured original pool"
                )
            pool_labels.setdefault(pool_key, str(row.get("actual_pool_name") or pool_key))
            pools.setdefault(pool_key, []).append(teams_by_id[str(row["entrant_id"])])
        pool_teams = tuple(tuple(items) for items in pools.values())
        if tuple(len(items) for items in pool_teams) != division.pool_sizes:
            raise ValueError(
                f"Division '{division.name}' captured pool membership does not match its pool capacities"
            )
        flights = tuple(
            FlightAssignment(
                name=pool_labels[pool_key],
                teams=tuple(items),
                total_pair_cost=0.0,
                average_pair_cost=0.0,
                average_projected_margin=0.0,
                competitive_probability=0.0,
                blowout_3plus_probability=0.0,
                blowout_5plus_probability=0.0,
            )
            for pool_key, items in pools.items()
        )
        captured_teams = tuple(team for items in pool_teams for team in items)
        if len(captured_teams) != division.team_count:
            raise ValueError(
                f"Division '{division.name}' captured {len(captured_teams)} teams; "
                f"expected {division.team_count}"
            )
        assignments.append(
            DivisionAssignment(
                name=division.name,
                teams=captured_teams,
                total_pair_cost=0.0,
                average_pair_cost=0.0,
                average_projected_margin=0.0,
                competitive_probability=0.0,
                blowout_3plus_probability=0.0,
                blowout_5plus_probability=0.0,
                pool_sizes=division.pool_sizes,
                advancement=division.advancement,
                pools=flights,
            )
        )
    return tuple(assignments)


def _schedule_projection(simulation, *, projection_basis: str) -> dict[str, Any]:
    margins = [
        match.expected_goal_differential
        for division in simulation.divisions
        for match in division.matches
    ]
    blowout_4plus_probabilities = [
        match.blowout_4plus_probability
        for division in simulation.divisions
        for match in division.matches
        if match.blowout_4plus_probability is not None
    ]
    return {
        "projection_basis": projection_basis,
        "projected_matchup_count": len(margins),
        "average_goal_differential": (
            float(sum(margins) / len(margins)) if margins else None
        ),
        "median_goal_differential": (
            float(pd.Series(margins).median()) if margins else None
        ),
        "close_game_probability": simulation.close_game_rate if margins else None,
        "blowout_3plus_probability": simulation.blowout_3plus_rate if margins else None,
        "blowout_4plus_probability": (
            sum(blowout_4plus_probabilities) / len(blowout_4plus_probabilities)
            if margins and len(blowout_4plus_probabilities) == len(margins)
            else None
        ),
        "blowout_5plus_probability": simulation.blowout_5plus_rate if margins else None,
    }


def _validate_unchanged_fixture_projection(
    actual_summary: dict[str, Any],
    original_projection: dict[str, Any],
) -> dict[str, Any]:
    """Gate sales comparisons on the model's replay of the unchanged tournament."""

    actual_count = int(actual_summary.get("actual_game_count") or 0)
    projected_count = int(original_projection.get("projected_matchup_count") or 0)
    coverage = min(actual_count, projected_count) / max(actual_count, projected_count, 1)
    actual_margin = actual_summary.get("average_goal_differential")
    projected_margin = original_projection.get("average_goal_differential")
    actual_blowout = actual_summary.get("blowout_4plus_rate")
    projected_blowout = original_projection.get("blowout_4plus_probability")
    margin_error = (
        abs(float(actual_margin) - float(projected_margin))
        if actual_count and actual_margin is not None and projected_margin is not None
        else None
    )
    blowout_error = (
        abs(float(actual_blowout) - float(projected_blowout))
        if actual_count and actual_blowout is not None and projected_blowout is not None
        else None
    )
    blockers = []
    if actual_count == 0:
        blockers.append("No scored captured fixtures are available for calibration")
    if coverage < UNCHANGED_FIXTURE_MIN_COVERAGE:
        blockers.append(
            f"Unchanged replay covers {coverage:.1%} of the captured scored fixture count"
        )
    if margin_error is None or margin_error > UNCHANGED_MARGIN_MAX_ABSOLUTE_ERROR:
        blockers.append("Unchanged average-margin prediction is outside the accepted tolerance")
    if blowout_error is None or blowout_error > UNCHANGED_BLOWOUT_RATE_MAX_ABSOLUTE_ERROR:
        blockers.append("Unchanged 4+ blowout-rate prediction is outside the accepted tolerance")
    return {
        "status": "passed" if not blockers else "failed",
        "basis": "same_model_replay_of_captured_original_fixture_graph",
        "actual_scored_game_count": actual_count,
        "unchanged_projected_game_count": projected_count,
        "fixture_count_coverage": coverage,
        "average_goal_margin_absolute_error": margin_error,
        "blowout_4plus_rate_absolute_error": blowout_error,
        "thresholds": {
            "minimum_fixture_count_coverage": UNCHANGED_FIXTURE_MIN_COVERAGE,
            "maximum_average_goal_margin_absolute_error": UNCHANGED_MARGIN_MAX_ABSOLUTE_ERROR,
            "maximum_blowout_4plus_rate_absolute_error": UNCHANGED_BLOWOUT_RATE_MAX_ABSOLUTE_ERROR,
        },
        "blockers": blockers,
    }


def _build_division_recommendations(
    entrant_rows: list[dict[str, Any]],
    optimized_divisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    division_order = {division["name"]: index for index, division in enumerate(optimized_divisions, start=1)}
    display_by_key = {
        str(division["name"]): _actual_division_name(division, str(division["name"]))
        for division in optimized_divisions
    }
    recommended_by_entrant: dict[str, str] = {}
    recommended_pool_by_entrant: dict[str, str] = {}
    for division in optimized_divisions:
        for team in division["teams"]:
            recommended_by_entrant[str(team["team_id"])] = str(division["name"])
        for pool in division.get("pools") or ():
            for team in pool.get("teams") or ():
                recommended_pool_by_entrant[str(team["team_id"])] = str(pool.get("name") or "")

    recommendations: list[dict[str, Any]] = []
    for entrant in entrant_rows:
        actual_division = str(entrant["actual_division_name"])
        actual_division_key = str(entrant.get("actual_division_key") or actual_division)
        recommended_division_key = recommended_by_entrant[str(entrant["entrant_id"])]
        recommended_division = display_by_key[recommended_division_key]
        actual_rank = division_order.get(actual_division_key, 0)
        recommended_rank = division_order.get(recommended_division_key, 0)
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
                "entrant_id": entrant["entrant_id"],
                "actual_division_key": actual_division_key,
                "actual_division": actual_division,
                "recommended_division_key": recommended_division_key,
                "recommended_division": recommended_division,
                "actual_pool": str(entrant.get("actual_pool_name") or ""),
                "recommended_pool": recommended_pool_by_entrant.get(str(entrant["entrant_id"]), ""),
                "move": move,
                "power_score": entrant["power_score"],
                "ranking_source_team_id": entrant["ranking_source_team_id"],
                "rating_fallback": entrant.get("rating_fallback", ""),
                "rating_basis": entrant.get("rating_basis", "historical_snapshot"),
                "canonical_team_id": entrant["canonical_team_id"],
                "ranking_status": entrant["ranking_status"],
            }
        )

    recommendations.sort(
        key=lambda row: (row["move"] == "stay", row["recommended_division"], -(row["power_score"] or 0.0))
    )  # noqa: E501
    return recommendations


def _verify_merge_map_version(*, actual: str, expected: str) -> None:
    expected = str(expected or "").strip()
    if expected and str(actual) != expected:
        raise RuntimeError(
            "Team merge information changed after Backtest readiness was checked "
            f"(expected {expected}, loaded {actual}); refresh the intake before running"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest one completed tournament cohort against an optimized reseeding"
    )  # noqa: E501
    parser.add_argument("--input", required=True, help="Path to cohort backtest request JSON")
    parser.add_argument(
        "--output-dir",
        default="reports/tournament_cohort_backtest",
        help="Directory for JSON/CSV outputs",
    )
    parser.add_argument(
        "--predictor-source",
        default=PREDICTOR_SOURCE_COMPARE,
        choices=[PREDICTOR_SOURCE_COMPARE, PREDICTOR_SOURCE_PYTHON, PREDICTOR_SOURCE_POINT_IN_TIME],
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
    parser.add_argument(
        "--expected-merge-map-version",
        default="",
        help="Fail if the subprocess reads a different team merge-map version",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    event_name = str(payload["event_name"])
    age_group = normalize_tournament_age_group(str(payload["age_group"]))
    gender = normalize_gender_label(str(payload["gender"]))
    divisions = _build_division_specs(payload)
    entrants_payload = payload.get("entrants") or []
    if not entrants_payload:
        raise ValueError("Input needs a non-empty entrants list")

    client = _get_supabase()
    merge_resolver = MergeResolver(client)
    merge_resolver.load_merge_map()
    if merge_resolver.version == "error":
        raise RuntimeError("Team merge information could not be loaded for the historical backtest")
    _verify_merge_map_version(
        actual=merge_resolver.version,
        expected=args.expected_merge_map_version,
    )
    normalized_entrants = []
    for entrant in entrants_payload:
        if needs_rating_fallback(entrant):
            normalized_entrants.append(
                {**entrant, "canonical_team_id": str(entrant["canonical_team_id"]),
                 "ranking_source_team_id": ""}
            )
            continue
        canonical = str(
            merge_resolver.resolve(str(entrant["canonical_team_id"]))
            or entrant["canonical_team_id"]
        )
        ranking_source = str(
            merge_resolver.resolve(str(entrant.get("ranking_source_team_id") or canonical))
            or entrant.get("ranking_source_team_id")
            or canonical
        )
        normalized_entrants.append(
            {**entrant, "canonical_team_id": canonical, "ranking_source_team_id": ranking_source}
        )
    entrants_payload = normalized_entrants
    print("PHASE: loading-actual-games", flush=True)
    canonical_team_ids = sorted(
        {str(entrant["canonical_team_id"]) for entrant in entrants_payload
         if not needs_rating_fallback(entrant)}
    )
    ranking_source_ids = sorted(
        {str(entrant.get("ranking_source_team_id") or entrant["canonical_team_id"])
         for entrant in entrants_payload if not needs_rating_fallback(entrant)}
    )

    team_rows = _fetch_rows_by_ids(client, "teams", TEAM_META_COLS, "team_id_master", canonical_team_ids)
    team_by_id = {str(row["team_id_master"]): row for row in team_rows}
    division_names = {
        _actual_division_name(division, str(division["name"]))
        for division in payload["divisions"]
    }
    actual_games = _reviewed_actual_games(payload, division_names)
    if actual_games is None:
        actual_games = (
            client.table("games")
            .select("id,division_name,game_date,home_team_master_id,away_team_master_id,home_score,away_score")
            .eq("event_name", event_name)
            .in_(
                "division_name",
                sorted(division_names),
            )  # noqa: E501
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
    snapshot_lookback_days = max(0, max(args.history_lookback_days, args.snapshot_buffer_days))
    snapshot_start = (
        pd.Timestamp(prediction_date).normalize() - pd.Timedelta(days=snapshot_lookback_days)
    ).strftime("%Y-%m-%d")
    snapshot_end = pd.Timestamp(prediction_date).normalize().strftime("%Y-%m-%d")
    print("PHASE: fetching-entrant-snapshots", flush=True)
    snapshot_query_ids = _expand_merged_team_ids(merge_resolver, ranking_source_ids)
    entrant_snapshots_df = asyncio.run(
        fetch_prediction_feature_snapshots(
            client,
            snapshot_query_ids,
            snapshot_start,
            snapshot_end,
            availability_cutoff=prediction_date,
            strict=True,
        )
    )
    entrant_snapshot_index = build_snapshot_index(entrant_snapshots_df)
    entrant_snapshot_index = _canonicalize_snapshot_index(
        merge_resolver,
        _filter_snapshot_index_for_cutoff(
            entrant_snapshot_index,
            prediction_date,
        ),
    )
    resolved_snapshots_by_source_id: dict[str, dict[str, Any]] = {}
    entrant_rows_by_id: dict[str, dict[str, Any]] = {}
    fallback_entrants: list[dict[str, Any]] = []
    notes: list[str] = []
    for entrant in entrants_payload:
        if needs_rating_fallback(entrant):
            fallback_entrants.append(entrant)
            continue
        canonical_team_id = str(entrant["canonical_team_id"])
        ranking_source_team_id = str(entrant["ranking_source_team_id"])
        provisional = {
            "event_team_name": entrant.get("event_team_name"),
            "ranking_source_team_id": ranking_source_team_id,
        }
        snapshot_entries = entrant_snapshot_index.get(ranking_source_team_id)
        if not snapshot_entries:
            fallback_entrants.append(
                {
                    **entrant,
                    "rating_fallback": MISSING_HISTORY_FALLBACK_POLICY,
                }
            )
            continue
        resolved_snapshot, _resolution_mode = _resolve_prediction_snapshot(
            provisional,
            snapshot_entries,
            prediction_date,
        )
        _verify_snapshot_provenance(
            resolved_snapshot,
            prediction_date=prediction_date,
            team_name=str(entrant.get("event_team_name") or ranking_source_team_id),
        )
        resolved_snapshots_by_source_id[ranking_source_team_id] = resolved_snapshot
        entrant_row = _build_entrant_row(
            entrant,
            team_by_id.get(canonical_team_id),
            _historical_ranking_row(resolved_snapshot),
            cohort_age_group=age_group,
            cohort_gender=gender,
            notes=notes,
        )
        entrant_rows_by_id[str(entrant["entrant_id"])] = entrant_row

    rated_rows = list(entrant_rows_by_id.values())
    for entrant in fallback_entrants:
        estimate, basis = build_average_rating_estimate(entrant, rated_rows)
        ranking_source_team_id = str(estimate["ranking_source_team_id"])
        fallback_entrant = {
            **entrant,
            **estimate,
            "ranking_source_team_id": ranking_source_team_id,
            "rating_basis": basis,
        }
        resolved_snapshot = _synthesize_snapshot_from_entrant_row(
            {
                **fallback_entrant,
                "source_age_group": age_group,
                "source_gender": gender,
                "age_group": age_group,
                "gender": gender,
                "ranking_status": "Estimated",
            },
            prediction_date,
        )
        resolved_snapshots_by_source_id[ranking_source_team_id] = resolved_snapshot
        entrant_row = _build_entrant_row(
            fallback_entrant,
            team_by_id.get(str(entrant["canonical_team_id"])),
            _historical_ranking_row(resolved_snapshot),
            cohort_age_group=age_group,
            cohort_gender=gender,
            notes=notes,
        )
        entrant_rows_by_id[str(entrant["entrant_id"])] = {
            **entrant_row,
            "average_source_count": int(estimate["average_source_count"]),
            "average_source_entrant_ids": list(estimate["average_source_entrant_ids"]),
            "average_source_team_ids": list(estimate["average_source_team_ids"]),
        }

    entrant_rows = [entrant_rows_by_id[str(entrant["entrant_id"])] for entrant in entrants_payload]
    seedable_teams: list[SeedableTeam] = []
    for index, entrant_row in enumerate(entrant_rows):
        seedable_teams.append(
            SeedableTeam(
                team_id=entrant_row["entrant_id"],
                team_name=entrant_row["event_team_name"],
                age_group=entrant_row["age_group"],
                gender=entrant_row["gender"],
                power_score=entrant_row["power_score"],
                rank_in_cohort=float(entrant_row["rank_in_cohort"])
                if entrant_row["rank_in_cohort"] is not None
                else None,
                club_name=entrant_row["club_name"],
                state_code=entrant_row["state_code"],
                games_played=entrant_row["games_played"],
            )
        )
        print(f"PROGRESS: entrant-snapshots {index + 1}/{len(entrants_payload)}", flush=True)

    print("PHASE: fetching-recent-games", flush=True)
    historical_game_team_ids = _expand_merged_team_ids(merge_resolver, ranking_source_ids)
    recent_games = _fetch_recent_games_for_teams(
        client,
        historical_game_team_ids,
        as_of_date=prediction_date,
        lookback_days=args.history_lookback_days,
    )
    recent_games = _canonicalize_historical_games(merge_resolver, recent_games)
    predictor_details: dict[str, Any] = {
        "source": args.predictor_source,
        "prediction_date": prediction_date,
        "history_lookback_days": args.history_lookback_days,
    }
    model_artifact_for_manifest: Path | None = None
    model_training_metadata: dict[str, Any] = {}
    resolved_probability_strategy: str | None = None
    related_snapshot_index: dict[str, list[dict[str, Any]]] = {}
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
        model_artifact_for_manifest = artifact_candidate

        related_team_ids = sorted(
            {str(game.home_team_master_id) for game in recent_games if game.home_team_master_id}
            | {str(game.away_team_master_id) for game in recent_games if game.away_team_master_id}
            | set(ranking_source_ids)
        )
        print("PHASE: fetching-snapshots", flush=True)
        related_snapshot_query_ids = _expand_merged_team_ids(merge_resolver, related_team_ids)
        snapshots_df = asyncio.run(
            fetch_prediction_feature_snapshots(
                client,
                related_snapshot_query_ids,
                snapshot_start,
                snapshot_end,
                availability_cutoff=prediction_date,
                strict=True,
            )
        )
        if snapshots_df.empty:
            raise ValueError(
                f"No point-in-time snapshots found for predictor date {prediction_date} and {len(related_team_ids)} teams"  # noqa: E501
            )
        snapshot_index = _canonicalize_snapshot_index(
            merge_resolver,
            _filter_snapshot_index_for_cutoff(
                build_snapshot_index(snapshots_df),
                prediction_date,
            ),
        )
        if not snapshot_index:
            raise ValueError(
                f"No point-in-time snapshots with pre-event provenance found for predictor date "
                f"{prediction_date} and {len(related_team_ids)} teams"
            )
        related_snapshot_index = snapshot_index
        snapshot_resolution_counts = {"as_of": len(entrant_rows)}
        predict_fn, matchup_cost_fn, point_in_time_model = _build_point_in_time_prediction_and_cost_functions(
            entrant_rows,
            recent_games,
            prediction_date=prediction_date,
            snapshot_index=snapshot_index,
            resolved_snapshots_by_source_id=resolved_snapshots_by_source_id,
            model_artifact=artifact_candidate,
            probability_strategy_override=probability_strategy_override,
        )
        model_training_metadata = dict(point_in_time_model.training_metadata or {})
        resolved_probability_strategy = point_in_time_model.probability_strategy
        model_data_end_date = _verify_model_training_provenance(
            model_training_metadata,
            prediction_date=prediction_date,
        )
        predictor_details.update(
            {
                "artifact_path": str(artifact_candidate),
                "snapshot_start": snapshot_start,
                "snapshot_end": snapshot_end,
                "snapshot_team_count": len(snapshot_index),
                "snapshot_row_count": int(len(snapshots_df)),
                "snapshot_resolution_counts": snapshot_resolution_counts,
                "probability_strategy": point_in_time_model.probability_strategy,
                "probability_strategy_override": probability_strategy_override,
                "probability_strategy_default": DEFAULT_TOURNAMENT_POINT_IN_TIME_STRATEGY,
                "selection_objective": point_in_time_model.selection_objective,
                "model_data_end_date": model_data_end_date,
                "backtest_projection_calibration": dict(
                    getattr(point_in_time_model, "backtest_projection_calibration", {})
                    or model_training_metadata.get("backtest_projection_calibration", {})
                ),
            }
        )
        matchup_proxy = f"point_in_time_match_model:{point_in_time_model.probability_strategy}"
    elif args.predictor_source == PREDICTOR_SOURCE_COMPARE:
        validate_predictor_cutoff(prediction_date)
        predictor_details.update(
            {
                "predictor_sha256": canonical_predictor_sha256(),
                "calibration_available_date": PREDICTOR_CALIBRATION_AVAILABLE_DATE,
                "calibration_source_commit": PREDICTOR_CALIBRATION_SOURCE_COMMIT,
            }
        )
        predict_fn, matchup_cost_fn = _build_compare_prediction_and_cost_functions(entrant_rows, recent_games)
        matchup_proxy = "canonical_compare_match_predictor_v4"
    else:
        predict_fn, matchup_cost_fn = _build_python_prediction_and_cost_functions(entrant_rows, recent_games)
        matchup_proxy = "legacy_python_match_predictor_v1"

    historical_inputs = _freeze_historical_inputs(
        entrant_rows,
        resolved_snapshots_by_source_id,
        prediction_date=prediction_date,
        history_start_date=snapshot_start,
        predictor_source=args.predictor_source,
        model_artifact=model_artifact_for_manifest,
        model_training_metadata=model_training_metadata,
        resolved_probability_strategy=resolved_probability_strategy,
        recent_games=recent_games,
        related_snapshot_index=related_snapshot_index,
    )

    print("PHASE: running-optimizer", flush=True)
    optimization_result = optimize_tournament_format(
        seedable_teams,
        divisions,
        matchup_cost_fn=matchup_cost_fn,
        matchup_proxy=matchup_proxy,
        pool_assignment_policy=POOL_POLICY_BALANCED_STRENGTH,
        division_assignment_policy=DIVISION_POLICY_RANKED_BANDS,
    )

    actual_game_counts = {
        str(division_name): int(summary["actual_game_count"])
        for division_name, summary in actual_summary["divisions"].items()
    }
    templates = {
        division_spec.name: _schedule_template_from_payload(
            division_payload,
            division_spec,
            actual_game_counts,
        )
        for division_spec, division_payload in zip(divisions, payload["divisions"], strict=False)
    }
    simulated_tournament = simulate_tournament_schedule(
        optimization_result.divisions,
        templates,
        predict_fn,
    )
    captured_original_assignments = _captured_original_assignments(
        entrant_rows,
        seedable_teams,
        divisions,
    )
    original_simulated_tournament = simulate_tournament_schedule(
        captured_original_assignments,
        templates,
        predict_fn,
    )
    original_schedule_projection = _schedule_projection(
        original_simulated_tournament,
        projection_basis="captured_original_fixture_graph",
    )
    proposed_schedule_projection = _schedule_projection(
        simulated_tournament,
        projection_basis="matchbalance_reseeded_fixture_graph",
    )
    model_validation = _validate_unchanged_fixture_projection(
        actual_summary,
        original_schedule_projection,
    )
    original_model_projection, comparison_issues = _project_original_pool_arrangement(
        entrant_rows,
        seedable_teams,
        matchup_cost_fn,
    )
    proposed_model_projection = _project_optimized_pool_arrangement(
        optimization_result,
        matchup_cost_fn,
    )
    if original_model_projection is None:
        seeding_comparison = {
            "status": "unavailable",
            "reason": "; ".join(comparison_issues),
            "comparison_basis": "same_model_original_vs_proposed_matchups",
        }
    else:
        seeding_comparison = compare_modelled_arrangements(
            original_model_projection,
            proposed_model_projection,
        )

    optimized_payload = optimization_result.to_dict()
    for optimized_division, source_division in zip(
        optimized_payload["divisions"],
        payload["divisions"],
        strict=True,
    ):
        optimized_division["actual_division_name"] = _actual_division_name(
            source_division,
            str(source_division["name"]),
        )
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
        "assignment_policy": "ranked_division_bands_balanced_pools",
        "historical_inputs": historical_inputs,
        "notes": sorted(set(notes)),
        "actual_results": actual_summary,
        "original_model_projection": original_model_projection,
        "original_schedule_projection": original_schedule_projection,
        "original_simulated_schedule": original_simulated_tournament.to_dict(),
        "optimized_projection": optimized_payload,
        "proposed_model_projection": proposed_model_projection,
        "proposed_schedule_projection": proposed_schedule_projection,
        "model_validation": model_validation,
        "seeding_comparison": seeding_comparison,
        "comparison_issues": list(comparison_issues),
        "comparison_to_actual": None,
        "entrants": entrant_rows,
        "division_recommendations": recommendations,
    }

    output_dir = Path(args.output_dir)
    print("PHASE: writing-summary", flush=True)
    _write_json(output_dir / "summary.json", output_payload)
    _write_json(output_dir / "historical_inputs.json", historical_inputs)
    _write_json(output_dir / "division_recommendations.json", recommendations)
    _write_csv(output_dir / "division_recommendations.csv", recommendations)

    print(f"Saved tournament cohort backtest to {output_dir}")
    proposed_average = proposed_model_projection.get("average_goal_differential")
    proposed_average_label = "unavailable" if proposed_average is None else f"{float(proposed_average):.2f}"
    print(
        f"{age_group} {gender}: actual avg GD={actual_summary['average_goal_differential']:.2f}, "
        f"proposed modeled avg GD={proposed_average_label}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
