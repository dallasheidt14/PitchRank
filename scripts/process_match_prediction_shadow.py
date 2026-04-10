"""
Process pending /compare shadow-log rows with the offline point-in-time model.

This script is intentionally fail-open: each row is handled independently and
errors are written back to the shadow payload without interrupting the batch.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from dotenv import load_dotenv

env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.predictor_python import Game as PredictorGame  # noqa: E402
from src.predictions.point_in_time_calibration import PointInTimeProbabilityCalibrator  # noqa: E402
from src.predictions.point_in_time_match_model import (  # noqa: E402
    PointInTimeMatchModel,
    build_point_in_time_matchup_row,
)
from supabase import Client, create_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _supabase_client() -> Client:
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY")
    return create_client(supabase_url, supabase_key)


def _normalize_gender(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"female", "f", "g", "girls", "girl"}:
        return "Female"
    return "Male"


def _normalize_age_group(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    try:
        return str(int(value))
    except Exception:
        return str(value)


def _normalize_team_snapshot(team_payload: Dict[str, Any], snapshot_date: str) -> Dict[str, Any]:
    return {
        "snapshot_date": snapshot_date,
        "team_id": str(team_payload.get("team_id_master") or ""),
        "team_name": team_payload.get("team_name"),
        "club_name": team_payload.get("club_name"),
        "age_group": _normalize_age_group(team_payload.get("age")),
        "gender": _normalize_gender(team_payload.get("gender")),
        "status": "Active",
        "rank_in_cohort_final": team_payload.get("rank_in_cohort_final"),
        "power_score_final": team_payload.get("power_score_final"),
        "sos_norm": team_payload.get("sos_norm"),
        "offense_norm": team_payload.get("offense_norm"),
        "defense_norm": team_payload.get("defense_norm"),
        "glicko_rating": team_payload.get("glicko_rating"),
        "glicko_rd": team_payload.get("glicko_rd"),
        "glicko_volatility": team_payload.get("glicko_volatility"),
        "wins": team_payload.get("wins"),
        "losses": team_payload.get("losses"),
        "draws": team_payload.get("draws"),
        "games_played": team_payload.get("games_played"),
        "win_percentage": team_payload.get("win_percentage"),
        "same_age_games": team_payload.get("same_age_games"),
        "same_age_game_share": team_payload.get("same_age_game_share"),
        "same_age_unique_opponents": team_payload.get("same_age_unique_opponents"),
        "same_age_top100_opp_count": team_payload.get("same_age_top100_opp_count"),
        "same_age_top500_opp_count": team_payload.get("same_age_top500_opp_count"),
        "same_age_avg_opp_power_adj": team_payload.get("same_age_avg_opp_power_adj"),
        "repeat_opponent_share": team_payload.get("repeat_opponent_share"),
        "positive_ml_evidence_scale": team_payload.get("positive_ml_evidence_scale"),
        "publication_cap_rank": team_payload.get("publication_cap_rank"),
        "publication_cap_score": team_payload.get("publication_cap_score"),
        "exp_margin": team_payload.get("exp_margin"),
        "exp_win_rate": team_payload.get("exp_win_rate"),
        "exp_goals_for": team_payload.get("exp_goals_for"),
        "exp_goals_against": team_payload.get("exp_goals_against"),
    }


def _safe_request_context(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _fetch_shadow_rows(supabase: Client, status: str, limit: int) -> List[Dict[str, Any]]:
    response = (
        supabase.table("match_prediction_shadow_log")
        .select("id, created_at, team_a_id, team_b_id, team_a_input, team_b_input, request_context")
        .eq("shadow_status", status)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return list(response.data or [])


def _fetch_games_by_ids(supabase: Client, game_ids: Iterable[str]) -> List[PredictorGame]:
    ids = [str(game_id) for game_id in game_ids if game_id]
    if not ids:
        return []

    rows: List[Dict[str, Any]] = []
    batch_size = 100
    for index in range(0, len(ids), batch_size):
        batch = ids[index : index + batch_size]
        response = (
            supabase.table("games")
            .select("id, game_date, home_team_master_id, away_team_master_id, home_score, away_score")
            .in_("id", batch)
            .execute()
        )
        rows.extend(response.data or [])

    return [
        PredictorGame(
            id=str(row.get("id") or ""),
            home_team_master_id=row.get("home_team_master_id"),
            away_team_master_id=row.get("away_team_master_id"),
            home_score=int(row["home_score"]) if row.get("home_score") is not None else None,
            away_score=int(row["away_score"]) if row.get("away_score") is not None else None,
            game_date=str(row.get("game_date") or ""),
        )
        for row in rows
        if row.get("id")
    ]


def _fetch_snapshot_index(
    supabase: Client,
    team_ids: Iterable[str],
    snapshot_date: str,
) -> Dict[str, List[Dict[str, Any]]]:
    ids = sorted({str(team_id) for team_id in team_ids if team_id})
    if not ids:
        return {}

    rankings_rows: List[Dict[str, Any]] = []
    batch_size = 100
    for index in range(0, len(ids), batch_size):
        batch = ids[index : index + batch_size]
        response = (
            supabase.table("rankings_full")
            .select("team_id, power_score_final, age_group")
            .in_("team_id", batch)
            .execute()
        )
        rankings_rows.extend(response.data or [])

    snapshot_ts = pd.Timestamp(snapshot_date)
    snapshot_index: Dict[str, List[Dict[str, Any]]] = {}
    for row in rankings_rows:
        team_id = str(row.get("team_id") or "")
        if not team_id:
            continue
        snapshot_index[team_id] = [
            {
                "team_id": team_id,
                "snapshot_date": snapshot_date,
                "snapshot_ts": snapshot_ts,
                "power_score_final": row.get("power_score_final"),
                "age_group": row.get("age_group"),
            }
        ]
    return snapshot_index


def _build_matchup_frame(
    row: Dict[str, Any],
    games: List[PredictorGame],
    snapshot_index: Dict[str, List[Dict[str, Any]]],
) -> pd.DataFrame:
    created_at = str(row.get("created_at") or "")
    snapshot_date = created_at.split("T")[0] if "T" in created_at else created_at[:10]
    snapshot_date = snapshot_date or pd.Timestamp.utcnow().strftime("%Y-%m-%d")

    team_a_input = row.get("team_a_input") or {}
    team_b_input = row.get("team_b_input") or {}
    team_a_snapshot = _normalize_team_snapshot(team_a_input, snapshot_date)
    team_b_snapshot = _normalize_team_snapshot(team_b_input, snapshot_date)
    team_a_id = str(team_a_input.get("team_id_master") or row.get("team_a_id") or "")
    team_b_id = str(team_b_input.get("team_id_master") or row.get("team_b_id") or "")
    team_names = {
        team_a_id: team_a_input.get("team_name"),
        team_b_id: team_b_input.get("team_name"),
    }

    feature_row = build_point_in_time_matchup_row(
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        team_a_snapshot=team_a_snapshot,
        team_b_snapshot=team_b_snapshot,
        all_games=games,
        game_date=snapshot_date,
        snapshot_index=snapshot_index,
        team_names=team_names,
        game_id=f"shadow:{row['id']}",
        example_orientation="shadow",
    )
    return pd.DataFrame([feature_row])


def _apply_optional_calibration(
    frame: pd.DataFrame,
    model: PointInTimeMatchModel,
    calibrator: Optional[PointInTimeProbabilityCalibrator],
) -> pd.DataFrame:
    if calibrator is None:
        return frame
    return calibrator.transform_frame(frame, prediction_postprocessor=model.relabel_evaluation_frame)


def _to_python(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _to_python(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_to_python(item) for item in value]
    if isinstance(value, bool):
        return value
    if value is None:
        return None
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


def _build_shadow_payload(
    prediction_row: pd.Series,
    *,
    model_version: str,
    calibrated: bool,
) -> Dict[str, Any]:
    predicted_winner = str(prediction_row.get("predicted_outcome") or "draw")
    return {
        "modelVersion": model_version,
        "calibrated": calibrated,
        "prediction": {
            "predictedWinner": predicted_winner,
            "winProbabilityA": float(prediction_row["prob_team_a_win"]),
            "drawProbability": float(prediction_row["prob_draw"]),
            "winProbabilityB": float(prediction_row["prob_team_b_win"]),
            "expectedScore": {
                "teamA": int(round(float(prediction_row["predicted_score_a"]))),
                "teamB": int(round(float(prediction_row["predicted_score_b"]))),
            },
            "expectedMargin": float(prediction_row["predicted_margin"]),
            "probabilityStrategy": str(prediction_row.get("probability_strategy") or ""),
            "blowoutProbability3Plus": float(prediction_row.get("blowout_3plus_probability") or 0.0),
            "blowoutProbability5Plus": float(prediction_row.get("blowout_5plus_probability") or 0.0),
            "predictedBlowout3Plus": bool(int(prediction_row.get("predicted_blowout_3plus") or 0)),
            "predictedBlowout5Plus": bool(int(prediction_row.get("predicted_blowout_5plus") or 0)),
        },
        "diagnostics": {
            "stalemateSignal": float(prediction_row.get("stalemate_signal") or 0.0),
            "projectedTotalGoals": float(prediction_row.get("projected_total_goals") or 0.0),
            "expectedGoalsA": float(prediction_row.get("expected_goals_a") or 0.0),
            "expectedGoalsB": float(prediction_row.get("expected_goals_b") or 0.0),
            "poissonProbabilities": {
                "teamA": float(prediction_row.get("poisson_prob_team_a_win") or 0.0),
                "draw": float(prediction_row.get("poisson_prob_draw") or 0.0),
                "teamB": float(prediction_row.get("poisson_prob_team_b_win") or 0.0),
            },
            "drawModelProbability": float(prediction_row.get("draw_model_probability") or 0.0),
        },
        "rawRow": _to_python(prediction_row.to_dict()),
    }


def _update_shadow_row(
    supabase: Client,
    row_id: str,
    *,
    shadow_status: str,
    shadow_model_version: str,
    shadow_prediction: Dict[str, Any],
) -> None:
    supabase.table("match_prediction_shadow_log").update(
        {
            "shadow_status": shadow_status,
            "shadow_model_version": shadow_model_version,
            "shadow_prediction": shadow_prediction,
        }
    ).eq("id", row_id).execute()


def _derive_shadow_model_version(
    model_artifact: Path,
    shadow_model_version: Optional[str],
    calibration_artifact: Optional[Path],
) -> str:
    if shadow_model_version:
        return shadow_model_version
    base = model_artifact.parent.name or model_artifact.stem
    if calibration_artifact:
        return f"{base}:calibrated"
    return base


def process_shadow_rows(
    *,
    supabase: Client,
    model: PointInTimeMatchModel,
    model_artifact: Path,
    shadow_status: str,
    limit: int,
    shadow_model_version: Optional[str] = None,
    calibration_artifact: Optional[Path] = None,
) -> Dict[str, Any]:
    rows = _fetch_shadow_rows(supabase, shadow_status, limit)
    calibrator = (
        PointInTimeProbabilityCalibrator.load(str(calibration_artifact)) if calibration_artifact else None
    )
    model_version = _derive_shadow_model_version(model_artifact, shadow_model_version, calibration_artifact)

    summary = {
        "requested_status": shadow_status,
        "requested_limit": limit,
        "model_artifact": str(model_artifact),
        "calibration_artifact": str(calibration_artifact) if calibration_artifact else None,
        "shadow_model_version": model_version,
        "fetched_rows": len(rows),
        "processed": 0,
        "completed": 0,
        "errored": 0,
        "row_ids": [],
    }

    for row in rows:
        row_id = str(row["id"])
        summary["processed"] += 1
        summary["row_ids"].append(row_id)
        try:
            request_context = _safe_request_context(row.get("request_context"))
            games = _fetch_games_by_ids(supabase, request_context.get("relevantGameIds") or [])
            involved_team_ids = {
                team_id
                for game in games
                for team_id in (game.home_team_master_id, game.away_team_master_id)
                if team_id
            }
            involved_team_ids.update(
                [
                    str((row.get("team_a_input") or {}).get("team_id_master") or row.get("team_a_id") or ""),
                    str((row.get("team_b_input") or {}).get("team_id_master") or row.get("team_b_id") or ""),
                ]
            )
            snapshot_date = (str(row.get("created_at") or "").split("T")[0]) or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
            snapshot_index = _fetch_snapshot_index(supabase, involved_team_ids, snapshot_date)
            matchup_frame = _build_matchup_frame(row, games, snapshot_index)
            prediction_frame = model.predict_frame(matchup_frame)
            prediction_frame = _apply_optional_calibration(prediction_frame, model, calibrator)
            prediction_row = prediction_frame.iloc[0]
            payload = _build_shadow_payload(
                prediction_row,
                model_version=model_version,
                calibrated=calibrator is not None,
            )
            _update_shadow_row(
                supabase,
                row_id,
                shadow_status="completed",
                shadow_model_version=model_version,
                shadow_prediction=payload,
            )
            summary["completed"] += 1
        except Exception as error:
            logger.exception("Failed to process shadow row %s", row_id)
            _update_shadow_row(
                supabase,
                row_id,
                shadow_status="error",
                shadow_model_version=model_version,
                shadow_prediction={
                    "modelVersion": model_version,
                    "error": {
                        "type": error.__class__.__name__,
                        "message": str(error),
                    },
                },
            )
            summary["errored"] += 1

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Process pending match prediction shadow-log rows")
    parser.add_argument("--model-artifact", required=True, help="Path to point_in_time_match_model.pkl")
    parser.add_argument(
        "--calibration-artifact",
        default=None,
        help="Optional path to point_in_time_model_calibration.pkl",
    )
    parser.add_argument(
        "--shadow-status",
        default="pending",
        help="Shadow status to pull from match_prediction_shadow_log",
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of rows to process")
    parser.add_argument(
        "--shadow-model-version",
        default=None,
        help="Version label stored on processed rows",
    )
    parser.add_argument(
        "--summary-path",
        default=None,
        help="Optional path to write a JSON summary",
    )
    args = parser.parse_args()

    model_artifact = Path(args.model_artifact)
    if not model_artifact.exists():
        raise FileNotFoundError(f"Model artifact not found: {model_artifact}")

    calibration_artifact = Path(args.calibration_artifact) if args.calibration_artifact else None
    if calibration_artifact and not calibration_artifact.exists():
        raise FileNotFoundError(f"Calibration artifact not found: {calibration_artifact}")

    supabase = _supabase_client()
    model = PointInTimeMatchModel.load(str(model_artifact))
    summary = process_shadow_rows(
        supabase=supabase,
        model=model,
        model_artifact=model_artifact,
        shadow_status=args.shadow_status,
        limit=args.limit,
        shadow_model_version=args.shadow_model_version,
        calibration_artifact=calibration_artifact,
    )

    if args.summary_path:
        summary_path = Path(args.summary_path)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
