"""
Point-in-time predictor feature snapshots.

This module persists the feature subset consumed by match prediction so
offline backtests and future model training can evaluate matches using the
same pre-match information that was available at ranking time.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date
from typing import Optional

import pandas as pd

from src.rankings.predictive_priors import LEAGUE_AVG_TOTAL_GOALS, ensure_predictive_priors

logger = logging.getLogger(__name__)
OPTIONAL_PREDICTION_EVIDENCE_COLUMNS = {
    "same_age_games",
    "same_age_game_share",
    "same_age_unique_opponents",
    "same_age_top100_opp_count",
    "same_age_top500_opp_count",
    "same_age_avg_opp_power_adj",
    "repeat_opponent_share",
    "positive_ml_evidence_scale",
    "publication_cap_rank",
    "publication_cap_score",
}


def _safe_int(value) -> Optional[int]:
    try:
        if pd.isna(value) or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value) -> Optional[float]:
    try:
        if pd.isna(value) or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_gender(raw_gender) -> Optional[str]:
    if pd.isna(raw_gender):
        return None

    value = str(raw_gender).strip().lower()
    if value in {"male", "m", "b", "boys", "boy"}:
        return "Male"
    if value in {"female", "f", "g", "girls", "girl"}:
        return "Female"
    if value in {"", "none", "null", "nan"}:
        return None
    return str(raw_gender).strip()


def _derive_age_group(age_value, age_group_value) -> Optional[str]:
    if pd.notna(age_group_value) and str(age_group_value).strip():
        return str(age_group_value).strip().lower()

    if pd.isna(age_value) or str(age_value).strip() == "":
        return None

    try:
        return f"u{int(float(age_value))}"
    except (TypeError, ValueError):
        return None


def _compute_expected_goals(
    offense_norm: Optional[float], defense_norm: Optional[float], exp_margin: Optional[float]
) -> tuple[Optional[float], Optional[float]]:
    if offense_norm is None or defense_norm is None or exp_margin is None:
        return None, None

    expected_total_goals = LEAGUE_AVG_TOTAL_GOALS * ((offense_norm + defense_norm) / 2.0)
    exp_goals_for = expected_total_goals / (1.0 + math.exp(-exp_margin))
    exp_goals_against = expected_total_goals - exp_goals_for
    return exp_goals_for, exp_goals_against


def _strip_optional_prediction_columns(records: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in record.items() if key not in OPTIONAL_PREDICTION_EVIDENCE_COLUMNS}
        for record in records
    ]


def _should_retry_without_optional_prediction_columns(error: Exception) -> bool:
    message = str(error).lower()
    return (
        (
            "column" in message
            or "schema cache" in message
            or "could not find" in message
            or "does not exist" in message
        )
        and (
            "same_age_" in message
            or "positive_ml_evidence_scale" in message
            or "publication_cap_" in message
        )
    )


def build_prediction_feature_snapshot_records(
    rankings_df: pd.DataFrame, snapshot_date: Optional[date] = None
) -> list[dict]:
    """
    Build serializable records for prediction_feature_history.

    The input DataFrame is expected to be the post-ranking calculator output
    (e.g. teams_with_ml / teams_combined), not raw rankings_full rows.
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    if rankings_df.empty:
        return []

    df = ensure_predictive_priors(rankings_df)

    if "games_played" not in df.columns and "gp" in df.columns:
        df["games_played"] = df["gp"]

    if "offense_norm" not in df.columns and "off_norm" in df.columns:
        df["offense_norm"] = df["off_norm"]
    if "defense_norm" not in df.columns and "def_norm" in df.columns:
        df["defense_norm"] = df["def_norm"]

    if "glicko_rating" not in df.columns and "mu" in df.columns:
        df["glicko_rating"] = df["mu"]
    if "glicko_rd" not in df.columns and "sigma" in df.columns:
        df["glicko_rd"] = df["sigma"]
    if "glicko_volatility" not in df.columns and "volatility" in df.columns:
        df["glicko_volatility"] = df["volatility"]

    records: list[dict] = []
    snapshot_date_str = snapshot_date.isoformat()

    for _, row in df.iterrows():
        team_id = row.get("team_id")
        if pd.isna(team_id) or not str(team_id).strip():
            continue

        wins = _safe_int(row.get("wins")) or 0
        losses = _safe_int(row.get("losses")) or 0
        draws = _safe_int(row.get("draws")) or 0
        games_played = _safe_int(row.get("games_played")) or 0

        win_percentage = (
            ((wins + (0.5 * draws)) / games_played) * 100.0
            if games_played > 0
            else _safe_float(row.get("win_percentage"))
        )

        offense_norm = _safe_float(row.get("offense_norm"))
        defense_norm = _safe_float(row.get("defense_norm"))
        exp_margin = _safe_float(row.get("exp_margin"))
        exp_goals_for = _safe_float(row.get("exp_goals_for"))
        exp_goals_against = _safe_float(row.get("exp_goals_against"))

        if exp_goals_for is None or exp_goals_against is None:
            derived_gf, derived_ga = _compute_expected_goals(offense_norm, defense_norm, exp_margin)
            exp_goals_for = exp_goals_for if exp_goals_for is not None else derived_gf
            exp_goals_against = exp_goals_against if exp_goals_against is not None else derived_ga

        record = {
            "snapshot_date": snapshot_date_str,
            "team_id": str(team_id),
            "age_group": _derive_age_group(row.get("age"), row.get("age_group")),
            "gender": _normalize_gender(row.get("gender")),
            "state_code": str(row.get("state_code")).strip() if pd.notna(row.get("state_code")) else None,
            "status": str(row.get("status")).strip() if pd.notna(row.get("status")) else None,
            "rank_in_cohort_final": _safe_int(row.get("rank_in_cohort_final")),
            "power_score_final": _safe_float(row.get("power_score_final")),
            "sos_norm": _safe_float(row.get("sos_norm")),
            "offense_norm": offense_norm,
            "defense_norm": defense_norm,
            "glicko_rating": _safe_float(row.get("glicko_rating")),
            "glicko_rd": _safe_float(row.get("glicko_rd")),
            "glicko_volatility": _safe_float(row.get("glicko_volatility")),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "games_played": games_played,
            "win_percentage": win_percentage,
            "exp_margin": exp_margin,
            "exp_win_rate": _safe_float(row.get("exp_win_rate")),
            "exp_goals_for": exp_goals_for,
            "exp_goals_against": exp_goals_against,
            "same_age_games": _safe_int(row.get("same_age_games")),
            "same_age_game_share": _safe_float(row.get("same_age_game_share")),
            "same_age_unique_opponents": _safe_int(row.get("same_age_unique_opponents")),
            "same_age_top100_opp_count": _safe_int(row.get("same_age_top100_opp_count")),
            "same_age_top500_opp_count": _safe_int(row.get("same_age_top500_opp_count")),
            "same_age_avg_opp_power_adj": _safe_float(row.get("same_age_avg_opp_power_adj")),
            "repeat_opponent_share": _safe_float(row.get("repeat_opponent_share")),
            "positive_ml_evidence_scale": _safe_float(row.get("positive_ml_evidence_scale")),
            "publication_cap_rank": _safe_int(row.get("publication_cap_rank")),
            "publication_cap_score": _safe_float(row.get("publication_cap_score")),
            "last_calculated": row.get("last_calculated").isoformat()
            if isinstance(row.get("last_calculated"), pd.Timestamp) and pd.notna(row.get("last_calculated"))
            else None,
        }
        records.append(record)

    return records


async def save_prediction_feature_snapshot(
    supabase_client, rankings_df: pd.DataFrame, snapshot_date: Optional[date] = None
) -> int:
    """
    Persist point-in-time predictor inputs for future backtests.
    """
    records = build_prediction_feature_snapshot_records(rankings_df, snapshot_date=snapshot_date)
    if not records:
        logger.warning("No prediction feature snapshot records to save")
        return 0

    total_records = len(records)
    batch_size = 1000
    max_retries = 4
    saved_count = 0

    logger.info("Saving %s prediction feature snapshots...", f"{total_records:,}")

    for index in range(0, total_records, batch_size):
        batch = records[index : index + batch_size]
        batch_num = (index // batch_size) + 1
        total_batches = (total_records + batch_size - 1) // batch_size
        stripped_optional_columns = False

        for attempt in range(max_retries + 1):
            try:
                response = (
                    supabase_client.table("prediction_feature_history")
                    .upsert(batch, on_conflict="team_id,snapshot_date")
                    .execute()
                )
                batch_saved = len(response.data) if response.data else len(batch)
                saved_count += batch_saved
                if total_batches > 1:
                    label = f" (retry {attempt})" if attempt > 0 else ""
                    logger.info(
                        "  Batch %s/%s%s: saved %s predictor snapshots",
                        batch_num,
                        total_batches,
                        label,
                        f"{batch_saved:,}",
                    )
                break
            except Exception as error:
                if _should_retry_without_optional_prediction_columns(error) and not stripped_optional_columns:
                    logger.warning(
                        "prediction_feature_history is missing optional evidence columns. "
                        "Retrying batch %s/%s without them.",
                        batch_num,
                        total_batches,
                    )
                    batch = _strip_optional_prediction_columns(batch)
                    stripped_optional_columns = True
                    continue

                if attempt < max_retries:
                    wait_seconds = 2 ** (attempt + 1)
                    logger.warning(
                        "Prediction feature snapshot batch %s/%s failed on attempt %s. Retrying in %ss: %s",
                        batch_num,
                        total_batches,
                        attempt + 1,
                        wait_seconds,
                        error,
                    )
                    time.sleep(wait_seconds)
                    continue

                logger.error(
                    "Prediction feature snapshot batch %s/%s failed after %s attempts: %s",
                    batch_num,
                    total_batches,
                    max_retries + 1,
                    error,
                )
                raise

    logger.info("Saved %s/%s prediction feature snapshots", f"{saved_count:,}", f"{total_records:,}")
    return saved_count
