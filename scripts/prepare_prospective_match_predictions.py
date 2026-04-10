"""
Prepare prospective match-prediction fixtures from upcoming-event artifacts.

This script ingests a JSONL file from scrape_upcoming_gotsport_events.py,
deduplicates it to one row per fixture, resolves provider team IDs to
PitchRank master team IDs, optionally freezes the offline point-in-time model,
and stores the result in prospective_match_predictions.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.process_match_prediction_shadow import (  # noqa: E402
    _apply_optional_calibration,
    _build_shadow_payload,
    _derive_shadow_model_version,
)
from scripts.predictor_python import Game as PredictorGame  # noqa: E402
from src.predictions.point_in_time_calibration import PointInTimeProbabilityCalibrator  # noqa: E402
from src.predictions.point_in_time_match_model import (  # noqa: E402
    PointInTimeMatchModel,
    build_point_in_time_matchup_row,
)
from src.utils.merge_resolver import MergeResolver  # noqa: E402
from supabase import Client, create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OPTIONAL_RANKINGS_FULL_FIELDS = (
    "team_id, age_group, gender, rank_in_cohort_final, power_score_final, glicko_rating, glicko_rd, "
    "glicko_volatility, sos_norm, off_norm, def_norm, wins, losses, draws, games_played, "
    "same_age_games, same_age_game_share, same_age_unique_opponents, same_age_top100_opp_count, "
    "same_age_top500_opp_count, same_age_avg_opp_power_adj, repeat_opponent_share, "
    "positive_ml_evidence_scale, publication_cap_rank, publication_cap_score"
)
BASE_RANKINGS_FULL_FIELDS = (
    "team_id, age_group, gender, rank_in_cohort_final, power_score_final, glicko_rating, glicko_rd, "
    "glicko_volatility, sos_norm, off_norm, def_norm, wins, losses, draws, games_played"
)


@dataclass
class FixtureRecord:
    fixture_key: str
    provider_code: str
    source_system: str
    source_artifact_path: Optional[str]
    source_event_id: Optional[str]
    source_match_key: Optional[str]
    game_date: str
    competition: str
    division_name: str
    venue: str
    home_provider_team_id: str
    away_provider_team_id: str
    home_team_name: str
    away_team_name: str
    fixture_payload: Dict[str, Any]


@dataclass
class TeamResolution:
    team_id_master: Optional[str]
    resolution_method: Optional[str]


def _supabase_client() -> Client:
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY")
    return create_client(supabase_url, supabase_key)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _sanitize_key_part(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize_text(value)).strip("-") or "unknown"


def _safe_json_loads(line: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_event_id_from_row(row: Dict[str, Any]) -> Optional[str]:
    match_id = str(row.get("match_id") or "").strip()
    if match_id:
        match = re.match(r"(\d+)_", match_id)
        if match:
            return match.group(1)

    source_url = str(row.get("source_url") or "").strip()
    match = re.search(r"/events/(\d+)", source_url)
    return match.group(1) if match else None


def _group_key_for_row(row: Dict[str, Any]) -> Tuple[str, ...]:
    team_marker_a = str(row.get("team_id_source") or row.get("team_id") or row.get("team_name") or "")
    team_marker_b = str(row.get("opponent_id_source") or row.get("opponent_id") or row.get("opponent_name") or "")
    team_pair = tuple(sorted([_normalize_text(team_marker_a), _normalize_text(team_marker_b)]))
    return (
        _normalize_text(row.get("provider") or "gotsport"),
        str(row.get("game_date") or ""),
        _normalize_text(row.get("competition") or row.get("event_name") or ""),
        _normalize_text(row.get("division_name") or ""),
        _normalize_text(row.get("venue") or ""),
        *team_pair,
    )


def _canonical_fixture_key(fixture: FixtureRecord) -> str:
    parts = [
        fixture.provider_code,
        fixture.source_event_id or "eventless",
        fixture.game_date,
        fixture.home_provider_team_id or fixture.home_team_name,
        fixture.away_provider_team_id or fixture.away_team_name,
        fixture.venue or "",
        fixture.division_name or "",
    ]
    return "|".join(_sanitize_key_part(part) for part in parts)


def load_fixtures_from_jsonl(fixtures_file: Path, source_artifact_path: Optional[str]) -> List[FixtureRecord]:
    grouped_rows: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    for raw_line in fixtures_file.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        row = _safe_json_loads(raw_line)
        if row is None:
            continue
        grouped_rows.setdefault(_group_key_for_row(row), []).append(row)

    fixtures: List[FixtureRecord] = []
    for rows in grouped_rows.values():
        home_row = next((row for row in rows if str(row.get("home_away") or "").upper() == "H"), None)
        away_row = next((row for row in rows if str(row.get("home_away") or "").upper() == "A"), None)
        base_row = home_row or rows[0]

        if home_row:
            home_provider_team_id = str(home_row.get("team_id_source") or home_row.get("team_id") or "")
            away_provider_team_id = str(home_row.get("opponent_id_source") or home_row.get("opponent_id") or "")
            home_team_name = str(home_row.get("team_name") or "")
            away_team_name = str(home_row.get("opponent_name") or "")
            source_match_key = str(home_row.get("match_id") or "")
        else:
            home_provider_team_id = str(base_row.get("opponent_id_source") or base_row.get("opponent_id") or "")
            away_provider_team_id = str(base_row.get("team_id_source") or base_row.get("team_id") or "")
            home_team_name = str(base_row.get("opponent_name") or "")
            away_team_name = str(base_row.get("team_name") or "")
            source_match_key = str(base_row.get("match_id") or "")

        fixture = FixtureRecord(
            fixture_key="",
            provider_code=str(base_row.get("provider") or "gotsport"),
            source_system="gotsport_event_schedule",
            source_artifact_path=source_artifact_path,
            source_event_id=_extract_event_id_from_row(base_row),
            source_match_key=source_match_key or None,
            game_date=str(base_row.get("game_date") or ""),
            competition=str(base_row.get("competition") or base_row.get("event_name") or ""),
            division_name=str(base_row.get("division_name") or ""),
            venue=str(base_row.get("venue") or ""),
            home_provider_team_id=home_provider_team_id,
            away_provider_team_id=away_provider_team_id,
            home_team_name=home_team_name,
            away_team_name=away_team_name,
            fixture_payload={
                "home_row": home_row,
                "away_row": away_row,
                "rows": rows,
            },
        )
        fixture.fixture_key = _canonical_fixture_key(fixture)
        fixtures.append(fixture)

    fixtures.sort(key=lambda fixture: (fixture.game_date, fixture.competition, fixture.home_team_name, fixture.away_team_name))
    return fixtures


def _chunked(values: Iterable[str], size: int) -> Iterable[List[str]]:
    batch: List[str] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _is_missing_optional_prediction_column(error: Exception) -> bool:
    message = str(error).lower()
    return (
        ("column" in message or "schema cache" in message or "could not find" in message)
        and (
            "same_age_" in message
            or "positive_ml_evidence_scale" in message
            or "publication_cap_" in message
        )
    )


def _is_missing_review_status_column(error: Exception) -> bool:
    message = str(error).lower()
    return ("column" in message or "schema cache" in message or "could not find" in message) and "review_status" in message


def _is_missing_table(error: Exception, table_name: str) -> bool:
    message = str(error).lower()
    return ("could not find the table" in message or "schema cache" in message) and table_name.lower() in message


def _to_python(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_python(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_python(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _normalize_gender_code(raw_gender: Any) -> str:
    normalized = str(raw_gender or "").strip().lower()
    if normalized in {"female", "f", "g", "girls", "girl"}:
        return "F"
    if normalized in {"male", "m", "b", "boys", "boy"}:
        return "M"
    return "M"


def _normalize_age_value(raw_age: Any) -> Optional[int]:
    if raw_age is None:
        return None
    text = str(raw_age).strip().lower()
    if not text:
        return None
    text = text.replace("u", "")
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _normalize_age_group_label(raw_age: Any) -> str:
    age_value = _normalize_age_value(raw_age)
    return str(age_value) if age_value is not None else ""


def _build_actual_outcome(home_score: Optional[int], away_score: Optional[int]) -> Optional[str]:
    if home_score is None or away_score is None:
        return None
    if home_score > away_score:
        return "team_a"
    if away_score > home_score:
        return "team_b"
    return "draw"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fetch_provider_id(supabase: Client, provider_code: str) -> Optional[str]:
    response = supabase.table("providers").select("id").eq("code", provider_code).maybe_single().execute()
    data = response.data or {}
    return str(data.get("id") or "") or None


def _fetch_existing_rows(
    supabase: Client,
    fixture_keys: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    keys = [str(value) for value in fixture_keys if value]
    if not keys:
        return {}

    rows: Dict[str, Dict[str, Any]] = {}
    select_fields = (
        "fixture_key, heuristic_prediction_status, heuristic_model_version, heuristic_prediction, "
        "heuristic_predicted_at, offline_prediction_status, offline_model_version, offline_prediction, "
        "offline_predicted_at, actual_game_id, actual_home_score, actual_away_score, actual_outcome, "
        "actual_recorded_at, evaluation_status, evaluation_notes"
    )
    for batch in _chunked(keys, 100):
        response = (
            supabase.table("prospective_match_predictions")
            .select(select_fields)
            .in_("fixture_key", batch)
            .execute()
        )
        for row in response.data or []:
            fixture_key = str(row.get("fixture_key") or "")
            if fixture_key:
                rows[fixture_key] = row
    return rows


def _fetch_alias_rows(
    supabase: Client,
    provider_id: str,
    provider_team_ids: Iterable[str],
) -> List[Dict[str, Any]]:
    ids = [str(value) for value in provider_team_ids if value]
    if not ids:
        return []

    rows: List[Dict[str, Any]] = []
    select_fields = "provider_team_id, team_id_master, match_method, review_status"
    for batch in _chunked(ids, 100):
        query = (
            supabase.table("team_alias_map")
            .select(select_fields)
            .eq("provider_id", provider_id)
            .in_("provider_team_id", batch)
        )
        try:
            response = query.execute()
        except Exception as error:
            if _is_missing_review_status_column(error):
                response = (
                    supabase.table("team_alias_map")
                    .select("provider_team_id, team_id_master, match_method")
                    .eq("provider_id", provider_id)
                    .in_("provider_team_id", batch)
                    .execute()
                )
            else:
                raise
        rows.extend(response.data or [])
    return rows


def _resolve_provider_team_ids(
    supabase: Client,
    provider_id: str,
    provider_team_ids: Iterable[str],
    merge_resolver: MergeResolver,
) -> Dict[str, TeamResolution]:
    ids = sorted({str(value).strip() for value in provider_team_ids if str(value or "").strip()})
    if not ids:
        return {}

    resolutions: Dict[str, TeamResolution] = {}
    alias_rows = _fetch_alias_rows(supabase, provider_id, ids)
    alias_by_provider_id: Dict[str, Dict[str, Any]] = {}
    for row in alias_rows:
        provider_team_id = str(row.get("provider_team_id") or "").strip()
        if not provider_team_id:
            continue
        current = alias_by_provider_id.get(provider_team_id)
        current_review = str((current or {}).get("review_status") or "").lower()
        candidate_review = str(row.get("review_status") or "").lower()
        if current is None or candidate_review == "approved" or (current_review != "approved" and not current_review):
            alias_by_provider_id[provider_team_id] = row

    for provider_team_id, row in alias_by_provider_id.items():
        canonical_id = merge_resolver.resolve(str(row.get("team_id_master") or "")) or None
        method = str(row.get("match_method") or "alias").strip() or "alias"
        review_status = str(row.get("review_status") or "").strip().lower()
        if review_status == "approved":
            method = f"alias_approved:{method}"
        elif review_status:
            method = f"alias_{review_status}:{method}"
        else:
            method = f"alias:{method}"
        resolutions[provider_team_id] = TeamResolution(team_id_master=canonical_id, resolution_method=method)

    unresolved_ids = [provider_team_id for provider_team_id in ids if provider_team_id not in resolutions]
    for batch in _chunked(unresolved_ids, 100):
        response = (
            supabase.table("teams")
            .select("team_id_master, provider_team_id")
            .eq("provider_id", provider_id)
            .in_("provider_team_id", batch)
            .execute()
        )
        for row in response.data or []:
            provider_team_id = str(row.get("provider_team_id") or "").strip()
            canonical_id = merge_resolver.resolve(str(row.get("team_id_master") or "")) or None
            if provider_team_id and provider_team_id not in resolutions:
                resolutions[provider_team_id] = TeamResolution(
                    team_id_master=canonical_id,
                    resolution_method="teams_provider_id",
                )

    for provider_team_id in ids:
        resolutions.setdefault(provider_team_id, TeamResolution(team_id_master=None, resolution_method=None))
    return resolutions


def _fetch_recent_games(
    supabase: Client,
    team_ids: Iterable[str],
    lookback_days: int,
) -> List[PredictorGame]:
    ids = sorted({str(team_id) for team_id in team_ids if team_id})
    if not ids:
        return []

    cutoff_date = (datetime.now(timezone.utc).date() - timedelta(days=lookback_days)).isoformat()
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    select_fields = "id, game_date, home_team_master_id, away_team_master_id, home_score, away_score, is_excluded"

    for batch in _chunked(ids, 100):
        for column_name in ("home_team_master_id", "away_team_master_id"):
            response = (
                supabase.table("games")
                .select(select_fields)
                .gte("game_date", cutoff_date)
                .eq("is_excluded", False)
                .in_(column_name, batch)
                .execute()
            )
            for row in response.data or []:
                game_id = str(row.get("id") or "")
                if not game_id:
                    continue
                if row.get("home_score") is None or row.get("away_score") is None:
                    continue
                rows_by_id[game_id] = row

    games = [
        PredictorGame(
            id=str(row.get("id") or ""),
            home_team_master_id=row.get("home_team_master_id"),
            away_team_master_id=row.get("away_team_master_id"),
            home_score=int(row["home_score"]) if row.get("home_score") is not None else None,
            away_score=int(row["away_score"]) if row.get("away_score") is not None else None,
            game_date=str(row.get("game_date") or ""),
        )
        for row in rows_by_id.values()
    ]
    games.sort(key=lambda game: game.game_date, reverse=True)
    return games


def _fetch_rankings_full_rows(
    supabase: Client,
    team_ids: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    ids = sorted({str(team_id) for team_id in team_ids if team_id})
    if not ids:
        return {}

    rows: Dict[str, Dict[str, Any]] = {}

    def _attempt(selector: str, batch: List[str]) -> List[Dict[str, Any]]:
        response = (
            supabase.table("rankings_full")
            .select(selector)
            .in_("team_id", batch)
            .execute()
        )
        return list(response.data or [])

    for batch in _chunked(ids, 100):
        try:
            batch_rows = _attempt(OPTIONAL_RANKINGS_FULL_FIELDS, batch)
        except Exception as error:
            if _is_missing_optional_prediction_column(error):
                batch_rows = _attempt(BASE_RANKINGS_FULL_FIELDS, batch)
            else:
                raise
        for row in batch_rows:
            team_id = str(row.get("team_id") or "")
            if team_id:
                rows[team_id] = row
    return rows


def _fetch_team_contexts(
    supabase: Client,
    team_ids: Iterable[str],
) -> Dict[str, Dict[str, Any]]:
    ids = sorted({str(team_id) for team_id in team_ids if team_id})
    if not ids:
        return {}

    team_rows: Dict[str, Dict[str, Any]] = {}
    predictive_rows: Dict[str, Dict[str, Any]] = {}
    rankings_rows = _fetch_rankings_full_rows(supabase, ids)

    for batch in _chunked(ids, 100):
        team_response = (
            supabase.table("teams")
            .select("team_id_master, team_name, club_name, state, state_code, age_group, gender, last_scraped_at")
            .in_("team_id_master", batch)
            .execute()
        )
        for row in team_response.data or []:
            team_id = str(row.get("team_id_master") or "")
            if team_id:
                team_rows[team_id] = row

        predictive_response = (
            supabase.table("team_predictive_view")
            .select("team_id_master, exp_margin, exp_win_rate, exp_goals_for, exp_goals_against")
            .in_("team_id_master", batch)
        )
        try:
            predictive_result = predictive_response.execute()
        except Exception as error:
            if _is_missing_table(error, "team_predictive_view"):
                predictive_result = type("PredictiveResult", (), {"data": []})()
            else:
                raise
        for row in predictive_result.data or []:
            team_id = str(row.get("team_id_master") or "")
            if team_id:
                predictive_rows[team_id] = row

    contexts: Dict[str, Dict[str, Any]] = {}
    for team_id in ids:
        team_row = team_rows.get(team_id)
        if team_row is None:
            continue
        rankings_row = rankings_rows.get(team_id, {})
        predictive_row = predictive_rows.get(team_id, {})

        wins = rankings_row.get("wins") or 0
        losses = rankings_row.get("losses") or 0
        draws = rankings_row.get("draws") or 0
        games_played = rankings_row.get("games_played") or 0
        win_percentage = None
        if games_played:
            win_percentage = ((float(wins) + float(draws) * 0.5) / float(games_played)) * 100.0

        contexts[team_id] = {
            "team_id_master": team_id,
            "team_name": team_row.get("team_name"),
            "club_name": team_row.get("club_name"),
            "state": team_row.get("state") or team_row.get("state_code"),
            "age": _normalize_age_value(rankings_row.get("age_group") or team_row.get("age_group")),
            "gender": _normalize_gender_code(rankings_row.get("gender") or team_row.get("gender")),
            "rank_in_cohort_final": rankings_row.get("rank_in_cohort_final"),
            "power_score_final": rankings_row.get("power_score_final"),
            "glicko_rating": rankings_row.get("glicko_rating"),
            "glicko_rd": rankings_row.get("glicko_rd"),
            "glicko_volatility": rankings_row.get("glicko_volatility"),
            "sos_norm": rankings_row.get("sos_norm"),
            "sos_norm_state": rankings_row.get("sos_norm"),
            "offense_norm": rankings_row.get("off_norm"),
            "defense_norm": rankings_row.get("def_norm"),
            "same_age_games": rankings_row.get("same_age_games"),
            "same_age_game_share": rankings_row.get("same_age_game_share"),
            "same_age_unique_opponents": rankings_row.get("same_age_unique_opponents"),
            "same_age_top100_opp_count": rankings_row.get("same_age_top100_opp_count"),
            "same_age_top500_opp_count": rankings_row.get("same_age_top500_opp_count"),
            "same_age_avg_opp_power_adj": rankings_row.get("same_age_avg_opp_power_adj"),
            "repeat_opponent_share": rankings_row.get("repeat_opponent_share"),
            "positive_ml_evidence_scale": rankings_row.get("positive_ml_evidence_scale"),
            "publication_cap_rank": rankings_row.get("publication_cap_rank"),
            "publication_cap_score": rankings_row.get("publication_cap_score"),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "games_played": games_played,
            "last_scraped_at": team_row.get("last_scraped_at"),
            "win_percentage": win_percentage,
            "exp_margin": predictive_row.get("exp_margin"),
            "exp_win_rate": predictive_row.get("exp_win_rate"),
            "exp_goals_for": predictive_row.get("exp_goals_for"),
            "exp_goals_against": predictive_row.get("exp_goals_against"),
        }
    return contexts


def _build_snapshot_payload(team_context: Dict[str, Any], snapshot_date: str) -> Dict[str, Any]:
    return {
        "snapshot_date": snapshot_date,
        "team_id": str(team_context.get("team_id_master") or ""),
        "team_name": team_context.get("team_name"),
        "club_name": team_context.get("club_name"),
        "age_group": _normalize_age_group_label(team_context.get("age")),
        "gender": "Female" if _normalize_gender_code(team_context.get("gender")) == "F" else "Male",
        "status": "Active",
        "rank_in_cohort_final": team_context.get("rank_in_cohort_final"),
        "power_score_final": team_context.get("power_score_final"),
        "sos_norm": team_context.get("sos_norm"),
        "offense_norm": team_context.get("offense_norm"),
        "defense_norm": team_context.get("defense_norm"),
        "glicko_rating": team_context.get("glicko_rating"),
        "glicko_rd": team_context.get("glicko_rd"),
        "glicko_volatility": team_context.get("glicko_volatility"),
        "wins": team_context.get("wins"),
        "losses": team_context.get("losses"),
        "draws": team_context.get("draws"),
        "games_played": team_context.get("games_played"),
        "win_percentage": team_context.get("win_percentage"),
        "same_age_games": team_context.get("same_age_games"),
        "same_age_game_share": team_context.get("same_age_game_share"),
        "same_age_unique_opponents": team_context.get("same_age_unique_opponents"),
        "same_age_top100_opp_count": team_context.get("same_age_top100_opp_count"),
        "same_age_top500_opp_count": team_context.get("same_age_top500_opp_count"),
        "same_age_avg_opp_power_adj": team_context.get("same_age_avg_opp_power_adj"),
        "repeat_opponent_share": team_context.get("repeat_opponent_share"),
        "positive_ml_evidence_scale": team_context.get("positive_ml_evidence_scale"),
        "publication_cap_rank": team_context.get("publication_cap_rank"),
        "publication_cap_score": team_context.get("publication_cap_score"),
        "exp_margin": team_context.get("exp_margin"),
        "exp_win_rate": team_context.get("exp_win_rate"),
        "exp_goals_for": team_context.get("exp_goals_for"),
        "exp_goals_against": team_context.get("exp_goals_against"),
    }


def _build_snapshot_index(
    team_contexts: Dict[str, Dict[str, Any]],
    snapshot_date: str,
) -> Dict[str, List[Dict[str, Any]]]:
    snapshot_ts = pd.Timestamp(snapshot_date)
    snapshot_index: Dict[str, List[Dict[str, Any]]] = {}
    for team_id, team_context in team_contexts.items():
        snapshot_index[team_id] = [
            {
                "team_id": team_id,
                "snapshot_date": snapshot_date,
                "snapshot_ts": snapshot_ts,
                "power_score_final": team_context.get("power_score_final"),
                "age_group": _normalize_age_group_label(team_context.get("age")),
            }
        ]
    return snapshot_index


def _build_offline_prediction(
    fixture: FixtureRecord,
    *,
    home_team_id: str,
    away_team_id: str,
    team_contexts: Dict[str, Dict[str, Any]],
    recent_games: List[PredictorGame],
    snapshot_index: Dict[str, List[Dict[str, Any]]],
    model: PointInTimeMatchModel,
    calibrator: Optional[PointInTimeProbabilityCalibrator],
    model_version: str,
) -> Dict[str, Any]:
    if home_team_id not in team_contexts:
        raise ValueError(f"Missing team context for home team {home_team_id}")
    if away_team_id not in team_contexts:
        raise ValueError(f"Missing team context for away team {away_team_id}")

    game_date = fixture.game_date or datetime.now(timezone.utc).date().isoformat()
    home_snapshot = _build_snapshot_payload(team_contexts[home_team_id], game_date)
    away_snapshot = _build_snapshot_payload(team_contexts[away_team_id], game_date)
    matchup_frame = pd.DataFrame(
        [
            build_point_in_time_matchup_row(
                team_a_id=home_team_id,
                team_b_id=away_team_id,
                team_a_snapshot=home_snapshot,
                team_b_snapshot=away_snapshot,
                all_games=recent_games,
                game_date=game_date,
                snapshot_index=snapshot_index,
                team_names={
                    home_team_id: team_contexts[home_team_id].get("team_name"),
                    away_team_id: team_contexts[away_team_id].get("team_name"),
                },
                game_id=f"prospective:{fixture.fixture_key}",
                example_orientation="prospective",
            )
        ]
    )
    prediction_frame = model.predict_frame(matchup_frame)
    prediction_frame = _apply_optional_calibration(prediction_frame, model, calibrator)
    prediction_row = prediction_frame.iloc[0]
    return _build_shadow_payload(
        prediction_row,
        model_version=model_version,
        calibrated=calibrator is not None,
    )


def _upsert_rows(
    supabase: Client,
    rows: List[Dict[str, Any]],
) -> None:
    for batch in _chunked(rows, 100):
        supabase.table("prospective_match_predictions").upsert(batch, on_conflict="fixture_key").execute()


def prepare_prospective_match_predictions(
    *,
    fixtures_file: Path,
    source_artifact_path: Optional[str],
    limit: Optional[int],
    lookback_days: int,
    model_artifact: Optional[Path],
    calibration_artifact: Optional[Path],
    offline_model_version: Optional[str],
    force_offline_refresh: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    fixtures = load_fixtures_from_jsonl(fixtures_file, source_artifact_path or str(fixtures_file))
    if limit is not None:
        fixtures = fixtures[:limit]

    supabase = _supabase_client()
    merge_resolver = MergeResolver(supabase)
    merge_resolver.load_merge_map()

    try:
        existing_rows = _fetch_existing_rows(supabase, [fixture.fixture_key for fixture in fixtures])
    except Exception as error:
        if dry_run and _is_missing_table(error, "prospective_match_predictions"):
            logger.warning("prospective_match_predictions table not found; continuing dry-run without existing rows")
            existing_rows = {}
        else:
            raise RuntimeError(
                "prospective_match_predictions table is missing. Apply the new Supabase migration before running this script."
            ) from error

    provider_ids_by_code: Dict[str, Optional[str]] = {}
    for provider_code in sorted({fixture.provider_code for fixture in fixtures}):
        provider_ids_by_code[provider_code] = _fetch_provider_id(supabase, provider_code)

    resolution_index: Dict[Tuple[str, str], TeamResolution] = {}
    for provider_code, provider_id in provider_ids_by_code.items():
        provider_team_ids = {
            fixture.home_provider_team_id
            for fixture in fixtures
            if fixture.provider_code == provider_code and fixture.home_provider_team_id
        }
        provider_team_ids.update(
            fixture.away_provider_team_id
            for fixture in fixtures
            if fixture.provider_code == provider_code and fixture.away_provider_team_id
        )
        if provider_id:
            resolutions = _resolve_provider_team_ids(supabase, provider_id, provider_team_ids, merge_resolver)
        else:
            resolutions = {provider_team_id: TeamResolution(None, None) for provider_team_id in provider_team_ids}
        for provider_team_id, resolution in resolutions.items():
            resolution_index[(provider_code, provider_team_id)] = resolution

    resolved_team_ids = sorted(
        {
            resolution.team_id_master
            for resolution in resolution_index.values()
            if resolution.team_id_master
        }
    )
    recent_games = _fetch_recent_games(supabase, resolved_team_ids, lookback_days)
    involved_team_ids = set(resolved_team_ids)
    for game in recent_games:
        if game.home_team_master_id:
            involved_team_ids.add(str(game.home_team_master_id))
        if game.away_team_master_id:
            involved_team_ids.add(str(game.away_team_master_id))

    team_contexts = _fetch_team_contexts(supabase, involved_team_ids)
    snapshot_index = _build_snapshot_index(team_contexts, datetime.now(timezone.utc).date().isoformat())

    model = None
    calibrator = None
    resolved_model_version = None
    if model_artifact:
        model = PointInTimeMatchModel.load(str(model_artifact))
        calibrator = (
            PointInTimeProbabilityCalibrator.load(str(calibration_artifact))
            if calibration_artifact
            else None
        )
        resolved_model_version = _derive_shadow_model_version(
            model_artifact,
            offline_model_version,
            calibration_artifact,
        )

    now_iso = _now_iso()
    rows_to_upsert: List[Dict[str, Any]] = []
    summary = {
        "fixtures_seen": len(fixtures),
        "resolved": 0,
        "partial": 0,
        "unresolved": 0,
        "offline_completed": 0,
        "offline_errored": 0,
        "offline_skipped": 0,
        "rows_to_upsert": 0,
        "fixtures_file": str(fixtures_file),
        "model_artifact": str(model_artifact) if model_artifact else None,
        "calibration_artifact": str(calibration_artifact) if calibration_artifact else None,
    }

    for fixture in fixtures:
        home_resolution = resolution_index.get((fixture.provider_code, fixture.home_provider_team_id), TeamResolution(None, None))
        away_resolution = resolution_index.get((fixture.provider_code, fixture.away_provider_team_id), TeamResolution(None, None))

        if home_resolution.team_id_master and away_resolution.team_id_master:
            resolution_status = "resolved"
            summary["resolved"] += 1
        elif home_resolution.team_id_master or away_resolution.team_id_master:
            resolution_status = "partial"
            summary["partial"] += 1
        else:
            resolution_status = "unresolved"
            summary["unresolved"] += 1

        existing_row = existing_rows.get(fixture.fixture_key, {})

        row_payload: Dict[str, Any] = {
            "fixture_key": fixture.fixture_key,
            "provider_code": fixture.provider_code,
            "source_system": fixture.source_system,
            "source_artifact_path": fixture.source_artifact_path,
            "source_event_id": fixture.source_event_id,
            "source_match_key": fixture.source_match_key,
            "game_date": fixture.game_date,
            "competition": fixture.competition or None,
            "division_name": fixture.division_name or None,
            "venue": fixture.venue or None,
            "home_provider_team_id": fixture.home_provider_team_id,
            "away_provider_team_id": fixture.away_provider_team_id,
            "home_team_name": fixture.home_team_name,
            "away_team_name": fixture.away_team_name,
            "home_team_master_id": home_resolution.team_id_master,
            "away_team_master_id": away_resolution.team_id_master,
            "home_resolution_method": home_resolution.resolution_method,
            "away_resolution_method": away_resolution.resolution_method,
            "resolution_status": resolution_status,
            "fixture_payload": _to_python(fixture.fixture_payload),
            "heuristic_prediction_status": existing_row.get("heuristic_prediction_status") or "pending",
            "heuristic_model_version": existing_row.get("heuristic_model_version"),
            "heuristic_prediction": existing_row.get("heuristic_prediction"),
            "heuristic_predicted_at": existing_row.get("heuristic_predicted_at"),
            "offline_prediction_status": existing_row.get("offline_prediction_status") or "pending",
            "offline_model_version": existing_row.get("offline_model_version"),
            "offline_prediction": existing_row.get("offline_prediction"),
            "offline_predicted_at": existing_row.get("offline_predicted_at"),
            "actual_game_id": existing_row.get("actual_game_id"),
            "actual_home_score": existing_row.get("actual_home_score"),
            "actual_away_score": existing_row.get("actual_away_score"),
            "actual_outcome": existing_row.get("actual_outcome"),
            "actual_recorded_at": existing_row.get("actual_recorded_at"),
            "evaluation_status": existing_row.get("evaluation_status")
            or ("pending_result" if resolution_status == "resolved" else "pending_resolution"),
            "evaluation_notes": existing_row.get("evaluation_notes") or {},
        }

        should_refresh_offline = bool(model is not None and resolution_status == "resolved")
        if row_payload["offline_prediction_status"] == "completed" and not force_offline_refresh:
            should_refresh_offline = False

        if should_refresh_offline and model and resolved_model_version:
            try:
                payload = _build_offline_prediction(
                    fixture,
                    home_team_id=str(home_resolution.team_id_master),
                    away_team_id=str(away_resolution.team_id_master),
                    team_contexts=team_contexts,
                    recent_games=recent_games,
                    snapshot_index=snapshot_index,
                    model=model,
                    calibrator=calibrator,
                    model_version=resolved_model_version,
                )
                row_payload["offline_prediction_status"] = "completed"
                row_payload["offline_model_version"] = resolved_model_version
                row_payload["offline_prediction"] = payload
                row_payload["offline_predicted_at"] = now_iso
                summary["offline_completed"] += 1
            except Exception as error:
                logger.exception("Failed to build offline prediction for %s", fixture.fixture_key)
                row_payload["offline_prediction_status"] = "error"
                row_payload["offline_model_version"] = resolved_model_version
                row_payload["offline_prediction"] = {
                    "modelVersion": resolved_model_version,
                    "error": {
                        "type": error.__class__.__name__,
                        "message": str(error),
                    },
                }
                row_payload["offline_predicted_at"] = now_iso
                summary["offline_errored"] += 1
        else:
            summary["offline_skipped"] += 1

        rows_to_upsert.append(row_payload)

    summary["rows_to_upsert"] = len(rows_to_upsert)
    if not dry_run and rows_to_upsert:
        try:
            _upsert_rows(supabase, rows_to_upsert)
        except Exception as error:
            if _is_missing_table(error, "prospective_match_predictions"):
                raise RuntimeError(
                    "prospective_match_predictions table is missing. Apply the new Supabase migration before running this script."
                ) from error
            raise

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare prospective match-prediction fixtures from upcoming-event JSONL")
    parser.add_argument("--fixtures-file", required=True, help="Path to upcoming-event JSONL artifact")
    parser.add_argument(
        "--source-artifact-path",
        default=None,
        help="Optional source artifact path recorded on prospective rows",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of fixtures to ingest")
    parser.add_argument("--lookback-days", type=int, default=365, help="Historical window for recent games")
    parser.add_argument(
        "--model-artifact",
        default=None,
        help="Optional point_in_time_match_model.pkl path to freeze offline predictions",
    )
    parser.add_argument(
        "--calibration-artifact",
        default=None,
        help="Optional point_in_time_model_calibration.pkl path",
    )
    parser.add_argument(
        "--offline-model-version",
        default=None,
        help="Optional explicit offline model version label",
    )
    parser.add_argument(
        "--force-offline-refresh",
        action="store_true",
        help="Recompute offline predictions even when rows already have completed offline payloads",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build everything but skip database writes")
    parser.add_argument("--summary-path", default=None, help="Optional path to write JSON summary")
    args = parser.parse_args()

    fixtures_file = Path(args.fixtures_file)
    if not fixtures_file.exists():
        raise FileNotFoundError(f"Fixtures file not found: {fixtures_file}")

    model_artifact = Path(args.model_artifact) if args.model_artifact else None
    if model_artifact and not model_artifact.exists():
        raise FileNotFoundError(f"Model artifact not found: {model_artifact}")

    calibration_artifact = Path(args.calibration_artifact) if args.calibration_artifact else None
    if calibration_artifact and not calibration_artifact.exists():
        raise FileNotFoundError(f"Calibration artifact not found: {calibration_artifact}")

    summary = prepare_prospective_match_predictions(
        fixtures_file=fixtures_file,
        source_artifact_path=args.source_artifact_path,
        limit=args.limit,
        lookback_days=args.lookback_days,
        model_artifact=model_artifact,
        calibration_artifact=calibration_artifact,
        offline_model_version=args.offline_model_version,
        force_offline_refresh=args.force_offline_refresh,
        dry_run=args.dry_run,
    )
    if args.summary_path:
        summary_path = Path(args.summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
