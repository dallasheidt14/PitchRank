"""Integrated Rankings Calculator (v53e + ML Layer)"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from src.etl.glicko_config import GlickoConfig
from src.etl.glicko_engine import compute_rankings_v2
from src.etl.v53e import V53EConfig, compute_rankings
from src.rankings.data_adapter import batch_fetch_rows, fetch_games_for_rankings
from src.rankings.layer13_predictive_adjustment import Layer13Config, apply_predictive_adjustment
from src.rankings.prediction_feature_history import save_prediction_feature_snapshot
from src.rankings.ranking_history import calculate_rank_changes, get_prior_cohort_ranks, save_ranking_snapshot

if TYPE_CHECKING:
    from src.profiling.timer import TimingReport


@dataclass
class RankingContext:
    """Shared context for multi-pass ranking computation.

    Groups team metadata, cross-age state, engine control, and instrumentation
    parameters that were previously passed as individual arguments to
    ``compute_rankings_with_ml``.
    """

    # Team metadata
    team_state_map: Optional[Dict[str, str]] = None
    tier_league_map: Optional[Dict[str, str]] = None
    # Cross-age / two-pass state
    global_strength_map: Optional[Dict] = None
    pre_sos_state: Optional[Dict] = None
    merge_version: Optional[str] = None
    initial_ratings: Optional[Dict] = None
    # Engine selection & control
    use_glicko: bool = True
    force_rebuild: bool = False
    save_snapshot: bool = True
    persist_game_residuals: bool = True
    persist_game_explainability: bool = True
    # Instrumentation
    timing_report: Optional[Any] = None
    pass_label: Optional[str] = None


logger = logging.getLogger(__name__)


def _section(timing_report: Optional["TimingReport"], name: str, **metadata):
    """Return a timing section context manager, or a no-op if profiling is off."""
    if timing_report is not None:
        return timing_report.section(name, **metadata)
    return nullcontext()


def _normalize_snapshot_date(today: Optional[pd.Timestamp]) -> Optional[date]:
    if today is None:
        return None

    timestamp = pd.Timestamp(today)
    return timestamp.date()


async def _save_prediction_feature_snapshot_safe(
    supabase_client, rankings_df: pd.DataFrame, snapshot_date: Optional[date] = None
) -> None:
    """
    Persist benchmark-only predictor snapshots without blocking rankings publication.
    """
    try:
        await save_prediction_feature_snapshot(
            supabase_client=supabase_client,
            rankings_df=rankings_df,
            snapshot_date=snapshot_date,
        )
    except Exception as error:
        logger.warning("Skipping prediction feature snapshot save after write failure: %s", error)


async def _persist_game_explainability(supabase_client, game_explainability: pd.DataFrame) -> Tuple[int, int]:
    """
    Persist per-game explainability rows using a batch RPC.

    The explainability breakdown is additive metadata derived from final
    converged ratings. Persistence failures should not block rankings
    publication, so this helper mirrors the retry and partial-failure behavior
    used for ML residual persistence.
    """
    if game_explainability.empty:
        return (0, 0)

    persist_df = game_explainability.copy().dropna(subset=["id", "team_id", "opp_id"])
    if persist_df.empty:
        logger.warning("No explainability rows had game UUID + team/opponent IDs; skipping persistence")
        return (0, 0)

    before_dedup = len(persist_df)
    persist_df = persist_df.drop_duplicates(subset=["team_id", "id"], keep="last")
    deduped_rows = before_dedup - len(persist_df)
    if deduped_rows > 0:
        logger.warning(
            "Dropped %s duplicate explainability row(s) on (team_id, game_uuid) before batch upsert",
            deduped_rows,
        )

    batch_size = 500
    max_retries = 3
    retry_delay = 2
    total_upserted = 0
    failed_count = 0
    failed_batches = []

    for i in range(0, len(persist_df), batch_size):
        batch = persist_df.iloc[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(persist_df) + batch_size - 1) // batch_size

        if batch_num > 1:
            await asyncio.sleep(0.1)

        batch_data = []
        for row in batch.itertuples(index=False):
            game_date = pd.Timestamp(row.game_date) if pd.notna(row.game_date) else None
            batch_data.append(
                {
                    "game_uuid": str(row.id),
                    "game_id": str(row.game_id) if pd.notna(row.game_id) else str(row.id),
                    "team_id": str(row.team_id),
                    "opp_id": str(row.opp_id),
                    "game_date": game_date.date().isoformat() if game_date is not None else None,
                    "gf": int(row.gf),
                    "ga": int(row.ga),
                    "team_mu": float(row.team_mu),
                    "team_sigma": float(row.team_sigma),
                    "opp_mu": float(row.opp_mu),
                    "opp_sigma": float(row.opp_sigma),
                    "expected_outcome": float(row.expected_outcome),
                    "actual_outcome": float(row.actual_outcome),
                    "outcome_surprise": float(row.outcome_surprise),
                    "g_factor": float(row.g_factor),
                    "recency_weight": float(row.recency_weight),
                    "rating_contribution": float(row.rating_contribution),
                    "off_residual": float(row.off_residual),
                    "def_residual": float(row.def_residual),
                }
            )

        batch_retry_delay = retry_delay
        batch_saved = False
        for attempt in range(max_retries):
            try:
                result = supabase_client.rpc(
                    "batch_upsert_game_explainability",
                    {"rows": batch_data},
                ).execute()

                if result.data is not None:
                    total_upserted += result.data
                else:
                    total_upserted += len(batch_data)

                batch_saved = True
                break
            except Exception as error:
                error_msg = str(error)
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Retriable explainability error on batch {batch_num}/{total_batches}, "
                        f"attempt {attempt + 1}/{max_retries}. "
                        f"Retrying in {batch_retry_delay}s... Error: {error_msg[:100]}"
                    )
                    await asyncio.sleep(batch_retry_delay)
                    batch_retry_delay *= 2
                else:
                    logger.warning(
                        f"Explainability batch {batch_num}/{total_batches} failed after "
                        f"{max_retries} attempts: {error_msg[:100]}"
                    )
                    failed_batches.append((batch_num, batch_data))
                    break

        if not batch_saved:
            failed_count += len(batch_data)

        if batch_num % 10 == 0:
            logger.info(f"  Explainability progress: {total_upserted:,} / {len(persist_df):,} rows upserted...")

    if failed_batches:
        logger.info(f"Retrying {len(failed_batches)} failed explainability batch(es)...")
        for batch_num, batch_data in failed_batches:
            batch_retry_delay = retry_delay
            for attempt in range(max_retries):
                try:
                    result = supabase_client.rpc(
                        "batch_upsert_game_explainability",
                        {"rows": batch_data},
                    ).execute()

                    if result.data is not None:
                        total_upserted += result.data
                    else:
                        total_upserted += len(batch_data)

                    failed_count -= len(batch_data)
                    logger.info(f"Explainability batch {batch_num} saved on retry")
                    break
                except Exception as error:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(batch_retry_delay)
                        batch_retry_delay *= 2
                    else:
                        logger.error(f"Explainability batch {batch_num} failed after all retries: {str(error)[:100]}")

    if failed_count > 0 and total_upserted == 0:
        logger.error(
            f"Explainability persistence failed: 0/{len(persist_df):,} rows upserted, {failed_count:,} failed"
        )
    elif failed_count > 0:
        logger.warning(
            f"Explainability persistence partial: {total_upserted:,} upserted, "
            f"{failed_count:,} failed out of {len(persist_df):,}"
        )
    else:
        logger.info(f"✅ Successfully upserted {total_upserted:,} game explainability rows")

    return (total_upserted, failed_count)


def _safe_int(value: Any) -> int:
    try:
        if pd.isna(value):
            return 0
    except TypeError:
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_age_number(value: Any) -> int | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except (TypeError, ValueError):
        return None


def _unit_interval(value: Any, lower: float, upper: float, *, default: float = 0.0) -> float:
    numeric = _safe_float(value)
    if numeric is None:
        return float(np.clip(default, 0.0, 1.0))
    if upper <= lower:
        return 1.0 if numeric >= upper else 0.0
    return float(np.clip((numeric - lower) / (upper - lower), 0.0, 1.0))


def _effective_fetch_lookback_days(lookback_days: int, *, use_glicko: bool) -> int:
    effective = max(int(lookback_days), 0)
    if not use_glicko:
        return effective
    cfg = GlickoConfig()
    return max(effective, int(getattr(cfg, "WINDOW_DAYS", effective))) + max(
        int(getattr(cfg, "WINDOW_GRACE_DAYS", 0)), 0
    )


def _same_age_evidence_policy(age_num: int) -> dict[str, float | int]:
    """Uniform evidence policy for ML authority and publication caps.

    The same standard is applied to every age group. The age argument is kept
    in the signature so the policy can be tuned again later without changing
    the call sites.
    """
    return {
        "cap_rank": 400,
        "soft_cap_rank": 250,
        "regional_thin_cap_rank": 800,
        "regional_thin_escalated_cap_rank": 1800,
        "one_top100_thin_cap_rank": 800,
        "one_top100_thin_escalated_cap_rank": 1800,
        "mid_thin_cap_rank": 1000,
        "weak_quality_results_cap_rank": 1500,
        "zero_top100_weak_results_cap_rank": 1500,
        "zero_top100_weak_results_escalated_cap_rank": 1800,
        "thin_schedule_cap_rank": 1500,
        "quality_result_void_cap_rank": 1500,
        "severe_cap_rank": 2000,
        "cap_band_min_width": 0.005,
        "cap_band_max_width": 0.020,
        "cap_band_step_per_team": 0.0005,
        "min_top500": 5,
        "min_avg_opp_power": 0.68,
        "severe_min_avg_opp_power": 0.55,
        "regional_thin_max_top500": 4,
        "regional_thin_min_top500_non_loss": 4,
        "regional_thin_max_avg_opp_power": 0.60,
        "mid_thin_max_top500": 1,
        "mid_thin_max_top1000_non_loss": 3,
        "mid_thin_max_avg_opp_power": 0.56,
        "one_top100_thin_max_top500": 3,
        "one_top100_thin_max_top500_non_loss": 2,
        "one_top100_thin_max_avg_opp_power": 0.58,
        "weak_quality_results_max_top100_non_loss": 0,
        "weak_quality_results_min_top500": 5,
        "weak_quality_results_max_top500_non_loss": 1,
        "weak_quality_results_max_top1000_non_loss": 4,
        "weak_quality_results_max_avg_opp_power": 0.63,
        "zero_top100_weak_results_min_unique_opponents": 12,
        "zero_top100_weak_results_max_top500": 3,
        "zero_top100_weak_results_severe_max_top500": 1,
        "zero_top100_weak_results_max_top500_non_loss": 1,
        "zero_top100_weak_results_max_top1000_non_loss": 1,
        "zero_top100_weak_results_max_avg_opp_power": 0.54,
        "zero_top100_weak_results_severe_max_avg_opp_power": 0.53,
        "thin_schedule_max_top500": 2,
        "thin_schedule_max_avg_opp_power": 0.50,
        "quality_result_void_max_top500": 3,
        "quality_result_void_max_avg_opp_power": 0.60,
        "quality_result_void_severe_max_avg_opp_power": 0.52,
        "thin_quality_results_min_unique_opponents": 18,
        "thin_quality_results_max_top100": 1,
        "thin_quality_results_max_top500": 5,
        "thin_quality_results_max_top500_non_loss": 1,
        "thin_quality_results_max_top1000_non_loss": 2,
        "thin_quality_results_max_avg_opp_power": 0.65,
        "thin_quality_results_min_repeat_share": 0.30,
        "thin_quality_results_publish_penalty_bonus": 0.018,
        "thin_quality_results_raw_shrink_bonus": 0.012,
        "local_loop_max_top500": 1,
        "local_loop_max_avg_opp_power": 0.52,
        "local_loop_repeat_share": 0.60,
        "local_loop_max_states": 1,
        "local_loop_max_scf": 0.40,
        "isolation_override_max_scf": 0.50,
        "isolation_override_max_states": 2,
        "isolation_override_repeat_share": 0.45,
        "max_repeat_share": 0.40,
        "full_release_min_top100": 3,
        "full_release_combo_top100": 2,
        "full_release_combo_top500": 5,
        "full_release_authority": 0.84,
        "soft_release_authority": 0.62,
        "thin_top100_min_top500": 5,
        "thin_top100_min_avg_opp_power": 0.60,
        "connectivity_min_unique_states": 3,
        "connectivity_repeat_share": 0.45,
        "partial_ml_scale": 0.25,
        "play_up_partial_ml_scale": 0.50,
        "play_up_min_game_share": 0.40,
        "play_up_min_top500_non_loss": 2,
        "play_up_min_top1000_non_loss": 4,
        "play_up_min_avg_opp_power": 0.58,
        "play_up_bonus_per_top500_non_loss": 0.015,
        "play_up_bonus_per_top1000_non_loss": 0.005,
        "play_up_bonus_max": 0.060,
        "quality_bridge_min_top500": 3,
        "quality_bridge_min_avg_opp_power": 0.57,
        "quality_bridge_min_quality_opp_power": 0.60,
        "quality_bridge_alt_min_quality_opp_power": 0.585,
        "quality_bridge_min_unique_opponents": 15,
        "quality_bridge_min_recent_games": 12,
        "quality_bridge_min_raw_power": 0.72,
        "quality_bridge_alt_min_unique_opponents": 18,
        "quality_bridge_alt_min_recent_games": 18,
        "quality_bridge_alt_min_same_age_games": 30,
        "quality_bridge_max_repeat_share": 0.60,
        "quality_bridge_alt_max_repeat_share": 0.55,
        "quality_bridge_results_min_top500_non_loss": 2,
        "quality_bridge_results_min_top1000_non_loss": 5,
        "quality_bridge_results_min_avg_opp_power": 0.58,
        "quality_bridge_results_min_quality_opp_power": 0.575,
        "quality_bridge_results_min_unique_opponents": 20,
        "quality_bridge_results_min_recent_games": 18,
        "quality_bridge_results_min_same_age_games": 30,
        "quality_bridge_results_max_repeat_share": 0.45,
        "quality_bridge_results_min_scf": 0.45,
        "freshness_recent_games_soft": 6,
        "freshness_recent_games_full": 12,
        "freshness_days_since_soft": 21,
        "freshness_days_since_stale": 90,
        "freshness_authority_floor": 0.55,
        "freshness_recent_games_min_for_uncap": 6,
        "freshness_hard_recent_games_cap": 5,
        "freshness_stale_days_cap": 75,
        "freshness_stale_recent_games_max": 6,
        "thin_recent_ml_scale_max": 0.50,
        "stale_recent_ml_scale_max": 0.35,
        "quality_sheet_relief_max": 0.10,
        "strong_broad_relief_max": 0.14,
        "strong_broad_quality_avg_min": 0.64,
        "strong_broad_alt_min_top100": 4,
        "strong_broad_alt_min_top500": 8,
        "strong_broad_alt_min_top500_non_loss": 4,
        "strong_broad_alt_min_top1000_non_loss": 6,
        "strong_broad_alt_min_unique_opponents": 20,
        "strong_broad_alt_min_recent_games": 8,
        "strong_broad_alt_max_repeat_share": 0.33,
        "strong_broad_alt_min_quality_avg_opp_power": 0.61,
        "strong_broad_alt_min_quality_support": 0.48,
        "strong_broad_exposure_min_top100": 4,
        "strong_broad_exposure_min_top500": 7,
        "strong_broad_exposure_min_top500_non_loss": 2,
        "strong_broad_exposure_min_top1000_non_loss": 6,
        "strong_broad_exposure_min_unique_opponents": 20,
        "strong_broad_exposure_min_unique_states": 5,
        "strong_broad_exposure_min_recent_games": 8,
        "strong_broad_exposure_min_avg_opp_power": 0.57,
        "strong_broad_exposure_min_quality_support": 0.45,
        "strong_broad_exposure_max_repeat_share": 0.30,
        "strong_broad_field_penalty_floor": 0.72,
        "strong_broad_authority_floor": 0.40,
        "repetitive_quality_relief_min_top100": 4,
        "repetitive_quality_relief_min_top500_non_loss": 6,
        "repetitive_quality_relief_min_top1000_non_loss": 8,
        "repetitive_quality_relief_min_unique_opponents": 20,
        "repetitive_quality_relief_min_recent_games": 12,
        "repetitive_quality_relief_min_quality_avg_opp_power": 0.64,
        "repetitive_quality_relief_min_scf": 0.65,
        "repetitive_quality_relief_min_bridge_games": 3.0,
        "repetitive_quality_relief_max_repeat_share": 0.62,
        "elite_repetitive_release_min_top100_non_loss": 2,
        "elite_repetitive_release_min_top500_non_loss": 10,
        "elite_repetitive_release_min_top1000_non_loss": 12,
        "elite_repetitive_release_min_recent_games": 20,
        "elite_repetitive_release_min_quality_support": 0.70,
        "elite_repetitive_release_ml_scale_floor": 0.75,
        "elite_repetitive_release_connectivity_penalty_multiplier": 0.35,
        "publish_field_penalty_max": 0.035,
        "publish_freshness_penalty_max": 0.025,
        "publish_connectivity_penalty_max": 0.010,
        "publish_weak_field_penalty_max": 0.020,
        "publish_weak_field_max_avg_opp_power": 0.56,
        "raw_shrink_max": 0.035,
        "raw_shrink_max_avg_opp_power": 0.62,
        "raw_shrink_bridge_relief_floor": 0.55,
        "weak_field_connectivity_min_avg_opp_power": 0.50,
        "weak_field_connectivity_max_avg_opp_power": 0.52,
        "weak_field_connectivity_max_unique_states": 2,
        "weak_field_connectivity_max_unique_opponents": 21,
        "weak_field_connectivity_min_top100": 1,
        "weak_field_connectivity_min_top500": 3,
        "weak_field_connectivity_min_top500_non_loss": 2,
        "weak_field_connectivity_publish_penalty_bonus": 0.013,
        "weak_field_connectivity_raw_shrink_bonus": 0.010,
        "weak_field_connectivity_cap_rank": 250,
        "diagnostic_top_rank": 25,
        "diagnostic_max_top500": 4,
        "diagnostic_min_top500_non_loss": 4,
        "diagnostic_max_avg_opp_power": 0.60,
    }


def _score_cutoff_for_rank(cohort_df: pd.DataFrame, score_col: str, target_rank: int) -> float:
    eligible = cohort_df.copy()
    if "status" in eligible.columns:
        eligible = eligible[eligible["status"] == "Active"]
    eligible = eligible[eligible[score_col].notna()].sort_values([score_col, "team_id"], ascending=[False, True])
    if eligible.empty:
        return 0.0
    idx = min(max(target_rank, 1), len(eligible)) - 1
    cutoff = float(eligible.iloc[idx][score_col])
    return max(0.0, cutoff - 1e-6)


def _compute_publication_cap_scores(teams_age: pd.DataFrame, base_scores: pd.Series) -> pd.Series:
    """Translate cap ranks onto the pre-cap final-score scale.

    Publication caps should be derived from the same score domain that drives the
    published ranking, not raw powerscore_adj.
    """
    result = pd.Series(pd.NA, index=teams_age.index, dtype="Float64")
    if "publication_cap_rank" not in teams_age.columns:
        return result

    cap_rank_series = pd.to_numeric(teams_age["publication_cap_rank"], errors="coerce")
    if not cap_rank_series.notna().any():
        return result

    pre_cap_df = teams_age[["team_id"]].copy()
    if "status" in teams_age.columns:
        pre_cap_df["status"] = teams_age["status"]
    pre_cap_df["pre_cap_base"] = pd.to_numeric(base_scores, errors="coerce")

    age_cap_lookup: dict[int, float] = {}

    def _cap_for_rank(val: float) -> float:
        rank = int(val)
        if rank not in age_cap_lookup:
            age_cap_lookup[rank] = _score_cutoff_for_rank(pre_cap_df, "pre_cap_base", rank)
        return age_cap_lookup[rank]

    result.loc[cap_rank_series.notna()] = cap_rank_series.loc[cap_rank_series.notna()].map(_cap_for_rank)
    return result


def _apply_publication_cap_band(base_scores: pd.Series, teams_age: pd.DataFrame) -> pd.Series:
    """Apply publication caps without flattening all capped teams to one score.

    Teams that fail the same-age evidence gate still cannot rise above their
    cohort ceiling, but they keep a compressed version of their relative order
    underneath that ceiling.
    """
    if "publication_cap_score" not in teams_age.columns:
        return base_scores

    adjusted = base_scores.copy()
    cap_scores = pd.to_numeric(teams_age["publication_cap_score"], errors="coerce")
    effective_mask = cap_scores.notna() & (adjusted >= cap_scores)
    if not effective_mask.any():
        return adjusted

    work = teams_age.loc[effective_mask, ["team_id", "age_num", "publication_cap_rank"]].copy()
    work["base_pre_cap"] = pd.to_numeric(adjusted.loc[effective_mask], errors="coerce")
    work["cap_score"] = pd.to_numeric(cap_scores.loc[effective_mask], errors="coerce")
    work = work.dropna(subset=["base_pre_cap", "cap_score"])
    if work.empty:
        return adjusted

    for (_, cap_rank, cap_score), grp in work.groupby(["age_num", "publication_cap_rank", "cap_score"], dropna=False):
        age_num = _safe_int(grp["age_num"].iloc[0])
        policy = _same_age_evidence_policy(age_num)
        group_size = len(grp)
        band_width = max(
            float(policy["cap_band_min_width"]),
            min(
                float(policy["cap_band_max_width"]),
                group_size * float(policy["cap_band_step_per_team"]),
            ),
        )
        upper = max(0.0, float(cap_score) - 1e-6)
        lower = max(0.0, upper - band_width)

        ranked = grp.sort_values(["base_pre_cap", "team_id"], ascending=[False, True])
        if group_size == 1:
            adjusted.loc[ranked.index] = upper
            continue

        compressed = np.linspace(upper, lower, group_size)
        adjusted.loc[ranked.index] = compressed

    return adjusted


def _validate_publication_caps(teams_age: pd.DataFrame, capped_scores: pd.Series) -> None:
    """Fail fast if any capped team still finishes above its cohort ceiling."""
    if "publication_cap_score" not in teams_age.columns:
        return

    cap_scores = pd.to_numeric(teams_age["publication_cap_score"], errors="coerce")
    if cap_scores.isna().all():
        return

    actual_scores = pd.to_numeric(capped_scores, errors="coerce")
    violations = teams_age.loc[
        cap_scores.notna() & actual_scores.notna() & (actual_scores > (cap_scores + 1e-9))
    ].copy()
    if violations.empty:
        return

    violations["actual_score"] = actual_scores.loc[violations.index]
    violations["cap_score"] = cap_scores.loc[violations.index]
    sample = []
    for row in violations.head(5).itertuples(index=False):
        team_name = getattr(row, "team_name", None) or getattr(row, "team_id", "unknown")
        sample.append(
            f"{team_name}({getattr(row, 'team_id', 'unknown')}): "
            f"actual={float(getattr(row, 'actual_score')):.6f} > cap={float(getattr(row, 'cap_score')):.6f}"
        )
    raise ValueError(
        "Publication cap violation after band compression for "
        f"{len(violations)} team(s): {'; '.join(sample)}"
    )


def _collect_top_tier_weak_uncapped(teams_age: pd.DataFrame, base_scores: pd.Series) -> pd.DataFrame:
    """Return top provisional teams that still look weak but were not capped."""
    required_cols = {
        "same_age_top100_opp_count",
        "same_age_top500_opp_count",
        "same_age_top500_non_loss_opp_count",
        "same_age_avg_opp_power_adj",
    }
    if not required_cols.issubset(teams_age.columns):
        return pd.DataFrame()

    work = teams_age.copy()
    work["team_id"] = work["team_id"].astype(str)
    work["base_after_cap"] = pd.to_numeric(base_scores, errors="coerce")
    work = work[work["base_after_cap"].notna()].sort_values(["base_after_cap", "team_id"], ascending=[False, True])
    if work.empty:
        return pd.DataFrame()

    work = work.reset_index(drop=True)
    work["provisional_rank"] = work.index + 1
    age_num = _safe_int(work["age_num"].iloc[0]) if "age_num" in work.columns else 0
    policy = _same_age_evidence_policy(age_num)
    publication_cap_rank = pd.to_numeric(work.get("publication_cap_rank"), errors="coerce")
    top100 = pd.to_numeric(work["same_age_top100_opp_count"], errors="coerce").fillna(0)
    top500 = pd.to_numeric(work["same_age_top500_opp_count"], errors="coerce").fillna(0)
    top500_non_loss = pd.to_numeric(work["same_age_top500_non_loss_opp_count"], errors="coerce").fillna(0)
    avg_opp = pd.to_numeric(work["same_age_avg_opp_power_adj"], errors="coerce")
    if "unique_opp_states" in work.columns:
        unique_states = pd.to_numeric(work["unique_opp_states"], errors="coerce")
    else:
        unique_states = pd.Series(np.nan, index=work.index, dtype=float)

    mask = (
        (work["provisional_rank"] <= int(policy["diagnostic_top_rank"]))
        & publication_cap_rank.isna()
        & (top100 <= 0)
        & (top500 <= int(policy["diagnostic_max_top500"]))
        & (top500_non_loss < int(policy["diagnostic_min_top500_non_loss"]))
        & avg_opp.notna()
        & (
            (avg_opp < float(policy["diagnostic_max_avg_opp_power"]))
            | (unique_states.notna() & (unique_states <= int(policy["isolation_override_max_states"])))
        )
    )
    if not mask.any():
        return pd.DataFrame()

    cols = [
        "team_id",
        "team_name",
        "provisional_rank",
        "base_after_cap",
        "same_age_top100_opp_count",
        "same_age_top500_opp_count",
        "same_age_top500_non_loss_opp_count",
        "same_age_avg_opp_power_adj",
        "repeat_opponent_share",
        "unique_opp_states",
        "scf",
    ]
    existing = [col for col in cols if col in work.columns]
    return work.loc[mask, existing].copy()


def _compute_same_age_evidence_metrics(
    games_used_df: pd.DataFrame,
    teams_df: pd.DataFrame,
    frozen_rank_lookup: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """Build same-age evidence metrics from a broader same-age evidence pool.

    When ``frozen_rank_lookup`` is provided — mapping team_id to its prior published rank and
    the cohort it held in that snapshot (``{"age_group", "gender", "rank"}``) — opponent ranks
    are read from that stable reference instead of the current run's ``powerscore_adj`` ordering,
    so an engine-input change cannot reshuffle the rank-driven gates within the run. A frozen
    rank is applied only when the team's snapshot cohort matches its current cohort, so a team
    that aged up keeps its current-run rank. Opponent power is unaffected (stays on the live
    ``powerscore_adj`` scale); teams absent from the reference keep their current-run rank.
    """
    defaults = pd.DataFrame(
        {
            "team_id": teams_df["team_id"].astype(str),
            "same_age_games": 0,
            "same_age_game_share": 0.0,
            "same_age_unique_opponents": 0,
            "same_age_top100_opp_count": 0,
            "same_age_top100_non_loss_opp_count": 0,
            "same_age_top500_opp_count": 0,
            "same_age_top500_non_loss_opp_count": 0,
            "same_age_top1000_non_loss_opp_count": 0,
            "same_age_avg_opp_power_adj": pd.NA,
            "same_age_quality_opp_power_adj": pd.NA,
            "play_up_games": 0,
            "play_up_game_share": 0.0,
            "play_up_unique_opponents": 0,
            "play_up_top100_opp_count": 0,
            "play_up_top500_opp_count": 0,
            "play_up_top500_non_loss_opp_count": 0,
            "play_up_top1000_non_loss_opp_count": 0,
            "play_up_avg_opp_power_adj": pd.NA,
            "repeat_opponent_share": 0.0,
        }
    )
    if games_used_df.empty or teams_df.empty:
        return defaults

    teams_work = teams_df.copy()
    teams_work["team_id"] = teams_work["team_id"].astype(str)
    teams_work["age"] = teams_work["age"].astype(str)
    teams_work["gender"] = teams_work["gender"].astype(str)

    active = (
        teams_work[teams_work["status"] == "Active"].copy() if "status" in teams_work.columns else teams_work.copy()
    )
    base_rank_lookup: dict[tuple[str, str], dict[str, int]] = {}
    base_power_lookup = dict(zip(teams_work["team_id"], pd.to_numeric(teams_work["powerscore_adj"], errors="coerce")))

    for (age, gender), grp in active.groupby(["age", "gender"]):
        ranked = grp.sort_values(["powerscore_adj", "team_id"], ascending=[False, True]).reset_index(drop=True)
        ranked["base_rank"] = ranked.index + 1
        base_rank_lookup[(str(age), str(gender))] = dict(zip(ranked["team_id"], ranked["base_rank"]))

    if frozen_rank_lookup:
        frozen_used = 0
        rank_total = 0
        for (age, gender), rank_map in base_rank_lookup.items():
            cohort_age = _parse_age_number(age)
            for opp_id in rank_map:
                rank_total += 1
                ref = frozen_rank_lookup.get(opp_id)
                if (
                    ref is not None
                    and cohort_age is not None
                    and _parse_age_number(ref["age_group"]) == cohort_age
                    and str(ref["gender"]).lower() == str(gender).lower()
                ):
                    rank_map[opp_id] = int(ref["rank"])
                    frozen_used += 1
        coverage = (frozen_used / rank_total) if rank_total else 0.0
        logger.info(
            f"🧊 Evidence-gate frozen rank reference: {frozen_used:,}/{rank_total:,} "
            f"ranked teams used prior-snapshot ranks ({coverage * 100:.1f}% coverage)"
        )

    games = games_used_df.copy()
    games["team_id"] = games["team_id"].astype(str)
    games["opp_id"] = games["opp_id"].astype(str)
    games["age"] = games["age"].astype(str)
    games["gender"] = games["gender"].astype(str)
    games["opp_age"] = games["opp_age"].astype(str)
    games["opp_gender"] = games["opp_gender"].astype(str)

    rows: list[dict[str, Any]] = []
    for team_id, tg in games.groupby("team_id"):
        if tg.empty:
            continue
        team_age = str(tg["age"].iloc[0])
        team_gender = str(tg["gender"].iloc[0])
        team_age_num = _parse_age_number(team_age)
        same_age = tg[(tg["opp_age"] == team_age) & (tg["opp_gender"] == team_gender)]
        play_up = tg[
            (tg["opp_gender"] == team_gender)
            & (tg["opp_age"].map(_parse_age_number) == (team_age_num + 1 if team_age_num is not None else None))
        ]
        unique_same_age_opp_ids = same_age["opp_id"].dropna().astype(str).unique().tolist()
        unique_play_up = play_up[["opp_id", "opp_age", "opp_gender"]].dropna(subset=["opp_id"]).copy()
        unique_play_up["opp_id"] = unique_play_up["opp_id"].astype(str)
        unique_play_up = unique_play_up.drop_duplicates(subset=["opp_id", "opp_age", "opp_gender"])
        if {"gf", "ga"}.issubset(same_age.columns):
            non_loss_same_age = same_age[same_age["gf"].fillna(-999) >= same_age["ga"].fillna(999)]
        else:
            non_loss_same_age = same_age.iloc[0:0]
        if {"gf", "ga"}.issubset(play_up.columns):
            non_loss_play_up = play_up[play_up["gf"].fillna(-999) >= play_up["ga"].fillna(999)]
        else:
            non_loss_play_up = play_up.iloc[0:0]
        unique_non_loss_same_age_opp_ids = non_loss_same_age["opp_id"].dropna().astype(str).unique().tolist()
        unique_non_loss_play_up = non_loss_play_up[["opp_id", "opp_age", "opp_gender"]].dropna(subset=["opp_id"]).copy()
        unique_non_loss_play_up["opp_id"] = unique_non_loss_play_up["opp_id"].astype(str)
        unique_non_loss_play_up = unique_non_loss_play_up.drop_duplicates(subset=["opp_id", "opp_age", "opp_gender"])
        cohort_rank_map = base_rank_lookup.get((team_age, team_gender), {})
        opp_ranks = [cohort_rank_map.get(opp_id) for opp_id in unique_same_age_opp_ids if opp_id in cohort_rank_map]
        non_loss_opp_ranks = [
            cohort_rank_map.get(opp_id) for opp_id in unique_non_loss_same_age_opp_ids if opp_id in cohort_rank_map
        ]
        play_up_opp_ranks = [
            base_rank_lookup.get((str(row.opp_age), str(row.opp_gender)), {}).get(str(row.opp_id))
            for row in unique_play_up.itertuples(index=False)
        ]
        play_up_non_loss_opp_ranks = [
            base_rank_lookup.get((str(row.opp_age), str(row.opp_gender)), {}).get(str(row.opp_id))
            for row in unique_non_loss_play_up.itertuples(index=False)
        ]
        opp_powers = [
            base_power_lookup.get(opp_id) for opp_id in unique_same_age_opp_ids if opp_id in base_power_lookup
        ]
        play_up_opp_powers = [
            base_power_lookup.get(str(opp_id))
            for opp_id in unique_play_up["opp_id"].tolist()
            if str(opp_id) in base_power_lookup
        ]
        counts = tg["opp_id"].value_counts()
        repeat_share = float(counts[counts >= 2].sum() / len(tg)) if len(tg) else 0.0
        clean_opp_powers = [float(val) for val in opp_powers if val is not None and not pd.isna(val)]
        clean_play_up_powers = [float(val) for val in play_up_opp_powers if val is not None and not pd.isna(val)]
        non_loss_same_age_set = set(unique_non_loss_same_age_opp_ids)
        quality_weighted_opp_powers: list[tuple[float, float]] = []
        for opp_id in unique_same_age_opp_ids:
            opp_power = base_power_lookup.get(opp_id)
            if opp_power is None or pd.isna(opp_power):
                continue
            opp_rank = cohort_rank_map.get(opp_id)
            non_loss = opp_id in non_loss_same_age_set
            weight = 1.0
            if opp_rank is not None and opp_rank <= 100:
                weight += 0.30
            elif opp_rank is not None and opp_rank <= 500:
                weight += 0.15
            elif opp_rank is not None and opp_rank <= 1000:
                weight += 0.05
            if non_loss:
                weight += 1.00
                if opp_rank is not None and opp_rank <= 500:
                    weight += 0.35
            quality_weighted_opp_powers.append((float(opp_power), weight))
        quality_weight_sum = sum(weight for _, weight in quality_weighted_opp_powers)

        rows.append(
            {
                "team_id": team_id,
                "same_age_games": int(len(same_age)),
                "same_age_game_share": float(len(same_age) / len(tg)) if len(tg) else 0.0,
                "same_age_unique_opponents": int(len(unique_same_age_opp_ids)),
                "same_age_top100_opp_count": int(sum(1 for rank in opp_ranks if rank is not None and rank <= 100)),
                "same_age_top100_non_loss_opp_count": int(
                    sum(1 for rank in non_loss_opp_ranks if rank is not None and rank <= 100)
                ),
                "same_age_top500_opp_count": int(sum(1 for rank in opp_ranks if rank is not None and rank <= 500)),
                "same_age_top500_non_loss_opp_count": int(
                    sum(1 for rank in non_loss_opp_ranks if rank is not None and rank <= 500)
                ),
                "same_age_top1000_non_loss_opp_count": int(
                    sum(1 for rank in non_loss_opp_ranks if rank is not None and rank <= 1000)
                ),
                "same_age_avg_opp_power_adj": (
                    float(sum(clean_opp_powers) / len(clean_opp_powers)) if clean_opp_powers else pd.NA
                ),
                "same_age_quality_opp_power_adj": (
                    float(sum(power * weight for power, weight in quality_weighted_opp_powers) / quality_weight_sum)
                    if quality_weight_sum > 0
                    else pd.NA
                ),
                "play_up_games": int(len(play_up)),
                "play_up_game_share": float(len(play_up) / len(tg)) if len(tg) else 0.0,
                "play_up_unique_opponents": int(len(unique_play_up)),
                "play_up_top100_opp_count": int(
                    sum(1 for rank in play_up_opp_ranks if rank is not None and rank <= 100)
                ),
                "play_up_top500_opp_count": int(
                    sum(1 for rank in play_up_opp_ranks if rank is not None and rank <= 500)
                ),
                "play_up_top500_non_loss_opp_count": int(
                    sum(1 for rank in play_up_non_loss_opp_ranks if rank is not None and rank <= 500)
                ),
                "play_up_top1000_non_loss_opp_count": int(
                    sum(1 for rank in play_up_non_loss_opp_ranks if rank is not None and rank <= 1000)
                ),
                "play_up_avg_opp_power_adj": (
                    float(sum(clean_play_up_powers) / len(clean_play_up_powers)) if clean_play_up_powers else pd.NA
                ),
                "repeat_opponent_share": repeat_share,
            }
        )

    metrics_df = pd.DataFrame(rows)
    if metrics_df.empty:
        return defaults
    merged = defaults.merge(metrics_df, on="team_id", how="left", suffixes=("_default", ""))
    for col in [
        "same_age_games",
        "same_age_game_share",
        "same_age_unique_opponents",
        "same_age_top100_opp_count",
        "same_age_top100_non_loss_opp_count",
        "same_age_top500_opp_count",
        "same_age_top500_non_loss_opp_count",
        "same_age_top1000_non_loss_opp_count",
        "same_age_avg_opp_power_adj",
        "same_age_quality_opp_power_adj",
        "play_up_games",
        "play_up_game_share",
        "play_up_unique_opponents",
        "play_up_top100_opp_count",
        "play_up_top500_opp_count",
        "play_up_top500_non_loss_opp_count",
        "play_up_top1000_non_loss_opp_count",
        "play_up_avg_opp_power_adj",
        "repeat_opponent_share",
    ]:
        default_col = f"{col}_default"
        if default_col in merged.columns:
            merged[col] = merged[col].where(merged[col].notna(), merged[default_col])
            merged.drop(columns=[default_col], inplace=True)
    return merged


def _connectivity_flags(row: pd.Series, policy: dict[str, float | int]) -> tuple[bool, bool, bool]:
    unique_states_raw = row.get("unique_opp_states")
    if unique_states_raw is None:
        unique_states = None
    else:
        unique_states = _safe_float(unique_states_raw)
        unique_states = int(unique_states) if unique_states is not None else None

    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    low_state = unique_states is not None and unique_states < int(policy["connectivity_min_unique_states"])
    repeat_heavy = repeat_share >= float(policy["connectivity_repeat_share"])
    repetitive_quality_relief = _has_proven_repetitive_profile(row, policy)
    severe_connectivity = low_state and repeat_heavy and not repetitive_quality_relief
    return low_state, repeat_heavy, severe_connectivity


def _quality_same_age_avg_opp_power(row: pd.Series) -> float | None:
    quality_avg = _safe_float(row.get("same_age_quality_opp_power_adj"))
    if quality_avg is not None:
        return quality_avg
    return _safe_float(row.get("same_age_avg_opp_power_adj"))


def _has_proven_repetitive_profile(row: pd.Series, policy: dict[str, float | int]) -> bool:
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    recent_games = _safe_int(row.get("games_last_180_days"))
    quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    scf = _safe_float(row.get("scf"))
    bridge_games = _safe_float(row.get("bridge_games"))

    return bool(
        repeat_share >= float(policy["connectivity_repeat_share"])
        and repeat_share <= float(policy["repetitive_quality_relief_max_repeat_share"])
        and top100 >= int(policy["repetitive_quality_relief_min_top100"])
        and top500_non_loss >= int(policy["repetitive_quality_relief_min_top500_non_loss"])
        and top1000_non_loss >= int(policy["repetitive_quality_relief_min_top1000_non_loss"])
        and unique_opponents >= int(policy["repetitive_quality_relief_min_unique_opponents"])
        and recent_games >= int(policy["repetitive_quality_relief_min_recent_games"])
        and quality_avg_opp_power is not None
        and quality_avg_opp_power >= float(policy["repetitive_quality_relief_min_quality_avg_opp_power"])
        and scf is not None
        and scf >= float(policy["repetitive_quality_relief_min_scf"])
        and bridge_games is not None
        and bridge_games >= float(policy["repetitive_quality_relief_min_bridge_games"])
    )


def _has_elite_repetitive_release_profile(row: pd.Series, policy: dict[str, float | int]) -> bool:
    if not _has_proven_repetitive_profile(row, policy):
        return False

    top100_non_loss = _safe_int(row.get("same_age_top100_non_loss_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    recent_games = _safe_int(row.get("games_last_180_days"))
    quality_support = _same_age_quality_support_score(row, policy)

    return bool(
        top100_non_loss >= int(policy["elite_repetitive_release_min_top100_non_loss"])
        and top500_non_loss >= int(policy["elite_repetitive_release_min_top500_non_loss"])
        and top1000_non_loss >= int(policy["elite_repetitive_release_min_top1000_non_loss"])
        and recent_games >= int(policy["elite_repetitive_release_min_recent_games"])
        and quality_support >= float(policy["elite_repetitive_release_min_quality_support"])
    )


def _days_since_last_game(row: pd.Series) -> float | None:
    days_since_last = _safe_float(row.get("days_since_last"))
    if days_since_last is not None:
        return max(days_since_last, 0.0)

    last_game = row.get("last_game")
    if last_game is None or (isinstance(last_game, float) and pd.isna(last_game)):
        return None

    try:
        last_game_ts = pd.Timestamp(last_game)
    except (TypeError, ValueError):
        return None
    if pd.isna(last_game_ts):
        return None
    if last_game_ts.tzinfo is not None:
        last_game_ts = last_game_ts.tz_convert(None)

    as_of = row.get("last_calculated")
    if as_of is None or (isinstance(as_of, float) and pd.isna(as_of)):
        as_of_ts = pd.Timestamp.utcnow().tz_localize(None).normalize()
    else:
        try:
            as_of_ts = pd.Timestamp(as_of)
        except (TypeError, ValueError):
            as_of_ts = pd.Timestamp.utcnow().tz_localize(None).normalize()
        if pd.isna(as_of_ts):
            as_of_ts = pd.Timestamp.utcnow().tz_localize(None).normalize()
        elif as_of_ts.tzinfo is not None:
            as_of_ts = as_of_ts.tz_convert(None)

    return float(max((as_of_ts.normalize() - last_game_ts.normalize()).days, 0))


def _freshness_score(row: pd.Series, policy: dict[str, float | int]) -> float:
    components: list[tuple[float, float]] = []

    recent_games_raw = row.get("games_last_180_days")
    if recent_games_raw is not None:
        recent_games = _safe_float(recent_games_raw)
        if recent_games is not None:
            components.append(
                (
                    0.55,
                    _unit_interval(
                        recent_games,
                        float(policy["freshness_recent_games_soft"]),
                        float(policy["freshness_recent_games_full"]),
                    ),
                )
            )

    days_since_last = _days_since_last_game(row)
    if days_since_last is not None:
        recency = 1.0 - _unit_interval(
            days_since_last,
            float(policy["freshness_days_since_soft"]),
            float(policy["freshness_days_since_stale"]),
            default=0.0,
        )
        components.append((0.45, recency))

    if not components:
        return 1.0

    total_weight = sum(weight for weight, _ in components)
    if total_weight <= 0:
        return 1.0
    return float(np.clip(sum(weight * value for weight, value in components) / total_weight, 0.0, 1.0))


def _freshness_flags(
    row: pd.Series, policy: dict[str, float | int]
) -> tuple[float, int | None, float | None, bool, bool]:
    recent_games_raw = row.get("games_last_180_days")
    recent_games = _safe_int(recent_games_raw) if recent_games_raw is not None else None
    days_since_last = _days_since_last_game(row)
    freshness = _freshness_score(row, policy)
    thin_recent = recent_games is not None and recent_games < int(policy["freshness_recent_games_min_for_uncap"])
    stale_recent = (
        recent_games is not None
        and
        days_since_last is not None
        and days_since_last >= float(policy["freshness_stale_days_cap"])
        and recent_games <= int(policy["freshness_stale_recent_games_max"])
    )
    return freshness, recent_games, days_since_last, thin_recent, stale_recent


def _same_age_quality_support_score(row: pd.Series, policy: dict[str, float | int]) -> float:
    top100_non_loss = _safe_int(row.get("same_age_top100_non_loss_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0

    support = (
        0.40 * _unit_interval(top500_non_loss, 1.0, 5.0)
        + 0.30 * _unit_interval(top1000_non_loss, 2.0, 6.0)
        + 0.20 * _unit_interval(top100_non_loss, 0.0, 2.0)
        + 0.10 * _unit_interval(unique_opponents, 8.0, 24.0)
    )
    repeat_relief = 1.0 - _unit_interval(repeat_share, 0.25, 0.55)
    return float(np.clip(support * (0.90 + 0.10 * repeat_relief), 0.0, 1.0))


def _has_quality_bridge_support(row: pd.Series, policy: dict[str, float | int]) -> bool:
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    quality_opp_power = _quality_same_age_avg_opp_power(row)
    same_age_games = _safe_int(row.get("same_age_games"))
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    recent_games = _safe_int(row.get("games_last_180_days"))
    unique_states = row.get("unique_opp_states")
    unique_states = _safe_int(unique_states) if unique_states is not None else None
    scf = _safe_float(row.get("scf"))
    _, _, severe_connectivity = _connectivity_flags(row, policy)
    raw_strength = max(
        _safe_float(row.get("powerscore_ml")) or 0.0,
        _safe_float(row.get("powerscore_adj")) or 0.0,
    )

    direct_quality_bridge = (
        top100 == 0
        and top500 >= int(policy["quality_bridge_min_top500"])
        and avg_opp_power is not None
        and avg_opp_power >= float(policy["quality_bridge_min_avg_opp_power"])
        and quality_opp_power is not None
        and quality_opp_power >= float(policy["quality_bridge_min_quality_opp_power"])
        and unique_opponents >= int(policy["quality_bridge_min_unique_opponents"])
        and recent_games >= int(policy["quality_bridge_min_recent_games"])
        and raw_strength >= float(policy["quality_bridge_min_raw_power"])
        and repeat_share <= float(policy["quality_bridge_max_repeat_share"])
        and (unique_states is None or unique_states >= 3)
        and (scf is None or scf > 0.55)
    )
    volume_bridge = (
        top100 == 0
        and not severe_connectivity
        and top500 >= int(policy["quality_bridge_min_top500"])
        and avg_opp_power is not None
        and avg_opp_power >= float(policy["quality_bridge_min_avg_opp_power"])
        and quality_opp_power is not None
        and quality_opp_power >= float(policy["quality_bridge_alt_min_quality_opp_power"])
        and unique_opponents >= int(policy["quality_bridge_alt_min_unique_opponents"])
        and same_age_games >= int(policy["quality_bridge_alt_min_same_age_games"])
        and recent_games >= int(policy["quality_bridge_alt_min_recent_games"])
        and raw_strength >= float(policy["quality_bridge_min_raw_power"])
        and repeat_share <= float(policy["quality_bridge_alt_max_repeat_share"])
        and (unique_states is None or unique_states >= 2)
        and (scf is None or scf > 0.50)
    )
    results_volume_bridge = (
        top100 == 0
        and not severe_connectivity
        and top500 >= int(policy["quality_bridge_min_top500"])
        and top500_non_loss >= int(policy["quality_bridge_results_min_top500_non_loss"])
        and top1000_non_loss >= int(policy["quality_bridge_results_min_top1000_non_loss"])
        and avg_opp_power is not None
        and avg_opp_power >= float(policy["quality_bridge_results_min_avg_opp_power"])
        and quality_opp_power is not None
        and quality_opp_power >= float(policy["quality_bridge_results_min_quality_opp_power"])
        and unique_opponents >= int(policy["quality_bridge_results_min_unique_opponents"])
        and same_age_games >= int(policy["quality_bridge_results_min_same_age_games"])
        and recent_games >= int(policy["quality_bridge_results_min_recent_games"])
        and raw_strength >= float(policy["quality_bridge_min_raw_power"])
        and repeat_share <= float(policy["quality_bridge_results_max_repeat_share"])
        and (unique_states is None or unique_states >= 2)
        and (scf is None or scf > float(policy["quality_bridge_results_min_scf"]))
    )
    return bool(direct_quality_bridge or volume_bridge or results_volume_bridge)


def _has_strong_broad_profile(row: pd.Series, policy: dict[str, float | int]) -> bool:
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    recent_games = _safe_int(row.get("games_last_180_days"))
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    quality_support = _same_age_quality_support_score(row, policy)
    unique_states = _safe_int(row.get("unique_opp_states")) if row.get("unique_opp_states") is not None else None
    proven_repetitive_profile = _has_proven_repetitive_profile(row, policy)

    strict_profile = (
        unique_opponents >= 20
        and top100 >= 4
        and top500_non_loss >= 6
        and top1000_non_loss >= 8
        and quality_avg_opp_power is not None
        and quality_avg_opp_power >= float(policy["strong_broad_quality_avg_min"])
    )
    broad_sheet_profile = (
        unique_opponents >= int(policy["strong_broad_alt_min_unique_opponents"])
        and recent_games >= int(policy["strong_broad_alt_min_recent_games"])
        and top100 >= int(policy["strong_broad_alt_min_top100"])
        and top500 >= int(policy["strong_broad_alt_min_top500"])
        and top500_non_loss >= int(policy["strong_broad_alt_min_top500_non_loss"])
        and top1000_non_loss >= int(policy["strong_broad_alt_min_top1000_non_loss"])
        and quality_avg_opp_power is not None
        and quality_avg_opp_power >= float(policy["strong_broad_alt_min_quality_avg_opp_power"])
        and quality_support >= float(policy["strong_broad_alt_min_quality_support"])
        and repeat_share <= float(policy["strong_broad_alt_max_repeat_share"])
    )
    broad_exposure_profile = (
        unique_opponents >= int(policy["strong_broad_exposure_min_unique_opponents"])
        and recent_games >= int(policy["strong_broad_exposure_min_recent_games"])
        and unique_states is not None
        and unique_states >= int(policy["strong_broad_exposure_min_unique_states"])
        and top100 >= int(policy["strong_broad_exposure_min_top100"])
        and top500 >= int(policy["strong_broad_exposure_min_top500"])
        and top500_non_loss >= int(policy["strong_broad_exposure_min_top500_non_loss"])
        and top1000_non_loss >= int(policy["strong_broad_exposure_min_top1000_non_loss"])
        and broad_avg_opp_power is not None
        and broad_avg_opp_power >= float(policy["strong_broad_exposure_min_avg_opp_power"])
        and quality_support >= float(policy["strong_broad_exposure_min_quality_support"])
        and repeat_share <= float(policy["strong_broad_exposure_max_repeat_share"])
    )
    return bool(strict_profile or broad_sheet_profile or broad_exposure_profile or proven_repetitive_profile)


def _has_weak_field_connectivity_overtrust_profile(
    row: pd.Series, policy: dict[str, float | int]
) -> bool:
    broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    unique_states = _safe_int(row.get("unique_opp_states")) if row.get("unique_opp_states") is not None else None
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))

    return bool(
        broad_avg_opp_power is not None
        and broad_avg_opp_power >= float(policy["weak_field_connectivity_min_avg_opp_power"])
        and broad_avg_opp_power < float(policy["weak_field_connectivity_max_avg_opp_power"])
        and unique_states is not None
        and unique_states <= int(policy["weak_field_connectivity_max_unique_states"])
        and unique_opponents is not None
        and unique_opponents <= int(policy["weak_field_connectivity_max_unique_opponents"])
        and top100 >= int(policy["weak_field_connectivity_min_top100"])
        and top500 >= int(policy["weak_field_connectivity_min_top500"])
        and top500_non_loss >= int(policy["weak_field_connectivity_min_top500_non_loss"])
    )


def _has_thin_quality_results_profile(row: pd.Series, policy: dict[str, float | int]) -> bool:
    """Flag thin schedules whose few quality looks are mostly losses.

    These teams can still post strong raw ratings in Glicko, but they have not
    produced enough same-age quality results to justify that raw strength.
    """
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top100_non_loss = _safe_int(row.get("same_age_top100_non_loss_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    avg_opp_power = _effective_same_age_avg_opp_power(row, policy)
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0

    return bool(
        unique_opponents >= int(policy["thin_quality_results_min_unique_opponents"])
        and top100 <= int(policy["thin_quality_results_max_top100"])
        and top100_non_loss == 0
        and top500 <= int(policy["thin_quality_results_max_top500"])
        and top500_non_loss <= int(policy["thin_quality_results_max_top500_non_loss"])
        and top1000_non_loss <= int(policy["thin_quality_results_max_top1000_non_loss"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["thin_quality_results_max_avg_opp_power"])
        and repeat_share >= float(policy["thin_quality_results_min_repeat_share"])
    )


def _effective_same_age_avg_opp_power(row: pd.Series, policy: dict[str, float | int]) -> float | None:
    broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    if broad_avg_opp_power is None:
        return None
    quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    if quality_avg_opp_power is None:
        return broad_avg_opp_power

    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    unique_opponents = _safe_int(row.get("same_age_unique_opponents"))
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    quality_support = _same_age_quality_support_score(row, policy)
    strong_broad_profile = _has_strong_broad_profile(row, policy)

    high_end_exposure = 0.60 * _unit_interval(top100, 1.0, 4.0) + 0.40 * _unit_interval(top500, 5.0, 10.0)
    breadth = _unit_interval(unique_opponents, 10.0, 24.0)
    repeat_relief = 1.0 - _unit_interval(repeat_share, 0.25, 0.55)
    quality_gap = max(0.0, quality_avg_opp_power - broad_avg_opp_power)
    relief_cap = float(policy["quality_sheet_relief_max"])
    if strong_broad_profile:
        relief_cap = max(relief_cap, float(policy["strong_broad_relief_max"]))
    relief = min(quality_gap, relief_cap)
    relief_multiplier = (
        (0.35 + 0.65 * quality_support)
        * (0.40 + 0.60 * high_end_exposure)
        * (0.60 + 0.40 * breadth)
        * (0.70 + 0.30 * repeat_relief)
    )
    if strong_broad_profile:
        relief_multiplier = max(relief_multiplier, 0.78 + 0.22 * quality_support)
    relief *= relief_multiplier
    return float(min(broad_avg_opp_power + relief, 0.75))


def _has_play_up_support(
    play_up_share: float,
    play_up_top500_non_loss: int,
    play_up_top1000_non_loss: int,
    play_up_avg_opp_power: float | None,
    policy: dict[str, float | int],
) -> bool:
    if play_up_avg_opp_power is None:
        return False
    return (
        play_up_share >= float(policy["play_up_min_game_share"])
        and play_up_top500_non_loss >= int(policy["play_up_min_top500_non_loss"])
        and play_up_top1000_non_loss >= int(policy["play_up_min_top1000_non_loss"])
        and play_up_avg_opp_power >= float(policy["play_up_min_avg_opp_power"])
    )


def _same_age_authority_score(row: pd.Series, policy: dict[str, float | int]) -> float:
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top100_non_loss = _safe_int(row.get("same_age_top100_non_loss_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    _avg_opp_power = _effective_same_age_avg_opp_power(row, policy)
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    unique_states = _safe_float(row.get("unique_opp_states"))
    low_state, repeat_heavy, severe_connectivity = _connectivity_flags(row, policy)
    connectivity_constrained = low_state or repeat_heavy
    quality_support = _same_age_quality_support_score(row, policy)
    freshness, recent_games, _, thin_recent, stale_recent = _freshness_flags(row, policy)
    quality_bridge = _has_quality_bridge_support(row, policy)
    strong_broad_profile = _has_strong_broad_profile(row, policy)

    elite_exposure = (
        0.65 * _unit_interval(top100, 0.0, float(policy["full_release_min_top100"]))
        + 0.35 * _unit_interval(top100_non_loss, 0.0, float(policy["full_release_combo_top100"]))
    )
    depth = (
        0.55 * _unit_interval(top500, 2.0, 8.0)
        + 0.45 * _unit_interval(top500_non_loss, 1.0, 5.0)
    )
    quality_results = (
        0.45 * _unit_interval(top100_non_loss, 0.0, 2.0)
        + 0.35 * _unit_interval(top500_non_loss, 1.0, 5.0)
        + 0.20 * _unit_interval(top1000_non_loss, 2.0, 6.0)
    )
    field_strength = _unit_interval(broad_avg_opp_power, float(policy["severe_min_avg_opp_power"]), 0.72)
    quality_field_strength = _unit_interval(
        quality_avg_opp_power, float(policy["quality_bridge_min_avg_opp_power"]), 0.72
    )
    state_breadth = _unit_interval(unique_states, 1.0, 6.0, default=0.5)
    repeat_relief = 1.0 - _unit_interval(repeat_share, 0.20, 0.50)

    authority = 0.34 * elite_exposure + 0.24 * depth + 0.24 * quality_results + 0.18 * field_strength
    authority += 0.08 * quality_support * quality_field_strength * (0.35 + 0.65 * elite_exposure)
    authority *= 0.85 + 0.15 * (0.55 * state_breadth + 0.45 * repeat_relief)

    if not severe_connectivity and quality_bridge:
        authority = max(
            authority,
            float(policy["partial_ml_scale"]) + 0.08 * quality_support + 0.08 * quality_field_strength,
        )
    if strong_broad_profile and not severe_connectivity:
        authority = max(
            authority,
            float(policy["strong_broad_authority_floor"])
            + 0.10 * quality_support
            + 0.08 * quality_field_strength,
        )

    if (
        not severe_connectivity
        and top100 >= int(policy["full_release_combo_top100"])
        and top500 >= int(policy["full_release_combo_top500"])
        and top500_non_loss >= 2
    ):
        combo_floor = (
            0.56
            + 0.04 * field_strength
            + 0.06 * quality_field_strength
            + 0.06 * quality_support
            + 0.04 * _unit_interval(top100_non_loss, 0.0, 2.0)
        )
        authority = max(authority, combo_floor)

    if broad_avg_opp_power is None:
        authority *= 0.35
    elif broad_avg_opp_power < float(policy["min_avg_opp_power"]):
        field_penalty = 0.45 + 0.55 * _unit_interval(
            broad_avg_opp_power,
            float(policy["severe_min_avg_opp_power"]),
            float(policy["min_avg_opp_power"]),
        )
        field_penalty += 0.15 * quality_support * _unit_interval(
            quality_avg_opp_power,
            float(policy["severe_min_avg_opp_power"]),
            float(policy["min_avg_opp_power"]),
        )
        if strong_broad_profile and not severe_connectivity:
            field_penalty = max(field_penalty, float(policy["strong_broad_field_penalty_floor"]))
        field_penalty = min(field_penalty, 1.0)
        authority *= field_penalty

    if top100 == 0 and top500 <= 1 and top500_non_loss == 0:
        authority *= 0.50

    if connectivity_constrained:
        authority *= 0.70
    if severe_connectivity:
        authority *= 0.60

    freshness_floor = float(policy["freshness_authority_floor"])
    authority *= freshness_floor + (1.0 - freshness_floor) * freshness
    if stale_recent:
        authority = min(authority, float(policy["stale_recent_ml_scale_max"]))
    elif thin_recent:
        recent_cap = float(policy["thin_recent_ml_scale_max"])
        if quality_bridge:
            recent_cap = max(recent_cap, float(policy["partial_ml_scale"]))
        authority = min(authority, recent_cap)
    if quality_bridge and not severe_connectivity:
        authority = max(authority, float(policy["partial_ml_scale"]))

    play_up_share = _safe_float(row.get("play_up_game_share")) or 0.0
    play_up_top500_non_loss = _safe_int(row.get("play_up_top500_non_loss_opp_count"))
    play_up_top1000_non_loss = _safe_int(row.get("play_up_top1000_non_loss_opp_count"))
    play_up_avg_opp_power = _safe_float(row.get("play_up_avg_opp_power_adj"))
    if _has_play_up_support(
        play_up_share,
        play_up_top500_non_loss,
        play_up_top1000_non_loss,
        play_up_avg_opp_power,
        policy,
    ):
        play_up_floor = (
            float(policy["play_up_partial_ml_scale"])
            + 0.08
            * _unit_interval(
                play_up_top500_non_loss,
                float(policy["play_up_min_top500_non_loss"]),
                float(policy["play_up_min_top500_non_loss"]) + 2.0,
            )
            + 0.04
            * _unit_interval(
                play_up_avg_opp_power,
                float(policy["play_up_min_avg_opp_power"]),
                0.70,
            )
        )
        authority = max(authority, min(play_up_floor, float(policy["soft_release_authority"])))

    return float(np.clip(authority, 0.0, 1.0))


def _same_age_publish_penalty(row: pd.Series) -> float:
    age_num = _safe_int(row.get("age_num"))
    policy = _same_age_evidence_policy(age_num)
    authority = _same_age_authority_score(row, policy)
    quality_support = _same_age_quality_support_score(row, policy)
    _effective_avg_opp_power = _effective_same_age_avg_opp_power(row, policy)
    broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    freshness, _, _, thin_recent, stale_recent = _freshness_flags(row, policy)
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    low_state, repeat_heavy, severe_connectivity = _connectivity_flags(row, policy)
    strong_broad_profile = _has_strong_broad_profile(row, policy)
    elite_repetitive_release = _has_elite_repetitive_release_profile(row, policy)
    weak_field_connectivity_profile = _has_weak_field_connectivity_overtrust_profile(row, policy)
    thin_quality_results_profile = _has_thin_quality_results_profile(row, policy)
    quality_field_strength = _unit_interval(
        quality_avg_opp_power,
        float(policy["quality_bridge_min_avg_opp_power"]),
        0.72,
    )

    min_avg_opp_power = float(policy["min_avg_opp_power"])
    severe_min_avg_opp_power = float(policy["severe_min_avg_opp_power"])
    if broad_avg_opp_power is None:
        field_shortfall = 1.0
    else:
        field_shortfall = float(
            np.clip(
                (min_avg_opp_power - broad_avg_opp_power) / max(min_avg_opp_power - severe_min_avg_opp_power, 1e-6),
                0.0,
                1.0,
            )
        )
    field_shortfall *= max(0.0, 1.0 - 0.45 * quality_support - 0.40 * quality_field_strength)
    if strong_broad_profile:
        field_shortfall *= 0.45

    freshness_shortfall = 1.0 - freshness
    exposure_pressure = max(_unit_interval(top100, 1.0, 3.0), _unit_interval(top500, 3.0, 8.0))
    repeat_pressure = _unit_interval(repeat_share, 0.20, 0.50)
    authority_gap = 1.0 - authority

    penalty = (
        float(policy["publish_field_penalty_max"])
        * field_shortfall
        * (0.40 + 0.60 * max(authority_gap, exposure_pressure))
    )
    penalty += (
        float(policy["publish_freshness_penalty_max"])
        * freshness_shortfall
        * (0.30 + 0.70 * max(authority, exposure_pressure))
    )
    if broad_avg_opp_power is not None:
        weak_field_shortfall = _unit_interval(
            float(policy["publish_weak_field_max_avg_opp_power"]) - broad_avg_opp_power,
            0.0,
            float(policy["publish_weak_field_max_avg_opp_power"]) - float(policy["severe_min_avg_opp_power"]),
        )
        penalty += (
            float(policy["publish_weak_field_penalty_max"])
            * weak_field_shortfall
            * exposure_pressure
            * max(0.0, 1.0 - 0.75 * quality_support)
            * (0.25 if strong_broad_profile else 1.0)
        )
    if weak_field_connectivity_profile:
        penalty += float(policy["weak_field_connectivity_publish_penalty_bonus"]) * (
            0.40 + 0.60 * exposure_pressure
        )
    if thin_quality_results_profile:
        penalty += float(policy["thin_quality_results_publish_penalty_bonus"]) * (
            0.45 + 0.55 * max(field_shortfall, 1.0 - quality_support)
        )
    if thin_recent:
        penalty += 0.008
    if stale_recent:
        penalty += 0.012
    if low_state or repeat_heavy:
        connectivity_multiplier = 1.0
        if elite_repetitive_release:
            connectivity_multiplier = float(policy["elite_repetitive_release_connectivity_penalty_multiplier"])
        penalty += (
            float(policy["publish_connectivity_penalty_max"])
            * max(repeat_pressure, 0.5 * float(low_state))
            * connectivity_multiplier
        )
    if severe_connectivity:
        penalty += 0.005

    return float(np.clip(penalty, 0.0, 0.08))


def _same_age_raw_shrink(row: pd.Series) -> float:
    age_num = _safe_int(row.get("age_num"))
    policy = _same_age_evidence_policy(age_num)
    broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    if broad_avg_opp_power is None:
        return 0.0

    strong_broad_profile = _has_strong_broad_profile(row, policy)
    if strong_broad_profile:
        return 0.0

    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    quality_support = _same_age_quality_support_score(row, policy)
    quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    quality_field_strength = _unit_interval(
        quality_avg_opp_power,
        float(policy["quality_bridge_min_avg_opp_power"]),
        0.72,
    )
    quality_bridge = _has_quality_bridge_support(row, policy)
    weak_field_connectivity_profile = _has_weak_field_connectivity_overtrust_profile(row, policy)
    thin_quality_results_profile = _has_thin_quality_results_profile(row, policy)

    weak_field_shortfall = _unit_interval(
        float(policy["raw_shrink_max_avg_opp_power"]) - broad_avg_opp_power,
        0.0,
        float(policy["raw_shrink_max_avg_opp_power"]) - float(policy["severe_min_avg_opp_power"]),
    )
    if weak_field_shortfall <= 0.0 and not thin_quality_results_profile:
        return 0.0

    exposure_pressure = (
        0.60 * _unit_interval(top100, 0.0, float(policy["full_release_min_top100"]))
        + 0.40 * _unit_interval(top500, 0.0, 8.0)
    )
    quality_relief = 0.55 * quality_support + 0.25 * quality_field_strength
    if quality_bridge:
        quality_relief = max(quality_relief, float(policy["raw_shrink_bridge_relief_floor"]))

    shrink = (
        float(policy["raw_shrink_max"])
        * weak_field_shortfall
        * (0.25 + 0.75 * exposure_pressure)
        * max(0.0, 1.0 - 0.75 * quality_relief)
    )
    if weak_field_connectivity_profile:
        shrink += float(policy["weak_field_connectivity_raw_shrink_bonus"]) * weak_field_shortfall * (
            0.50 + 0.50 * exposure_pressure
        )
    if thin_quality_results_profile:
        profile_shortfall = max(weak_field_shortfall, 0.30 + 0.40 * max(0.0, 1.0 - quality_support))
        shrink += float(policy["thin_quality_results_raw_shrink_bonus"]) * (
            0.45 + 0.55 * profile_shortfall
        )
    if top100 == 0 and top500 <= 2:
        shrink *= 0.70
    return float(np.clip(shrink, 0.0, float(policy["raw_shrink_max"])))


def _play_up_bonus(row: pd.Series) -> float:
    age_num = _safe_int(row.get("age_num"))
    policy = _same_age_evidence_policy(age_num)
    _, _, severe_connectivity = _connectivity_flags(row, policy)
    authority = _same_age_authority_score(row, policy)
    if not severe_connectivity and authority >= float(policy["full_release_authority"]):
        return 0.0

    play_up_share = _safe_float(row.get("play_up_game_share")) or 0.0
    play_up_top500_non_loss = _safe_int(row.get("play_up_top500_non_loss_opp_count"))
    play_up_top1000_non_loss = _safe_int(row.get("play_up_top1000_non_loss_opp_count"))
    play_up_avg_opp_power = _safe_float(row.get("play_up_avg_opp_power_adj"))
    if not _has_play_up_support(
        play_up_share,
        play_up_top500_non_loss,
        play_up_top1000_non_loss,
        play_up_avg_opp_power,
        policy,
    ):
        return 0.0

    bonus = (
        play_up_top500_non_loss * float(policy["play_up_bonus_per_top500_non_loss"])
        + max(0, play_up_top1000_non_loss - play_up_top500_non_loss)
        * float(policy["play_up_bonus_per_top1000_non_loss"])
    )
    bonus = min(bonus, float(policy["play_up_bonus_max"]))
    if severe_connectivity:
        bonus *= 0.75
    return bonus


def _positive_ml_evidence_scale(row: pd.Series) -> float:
    age_num = _safe_int(row.get("age_num"))
    policy = _same_age_evidence_policy(age_num)
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    low_state, repeat_heavy, severe_connectivity = _connectivity_flags(row, policy)
    connectivity_constrained = low_state or repeat_heavy
    freshness, _, _, thin_recent, stale_recent = _freshness_flags(row, policy)
    play_up_share = _safe_float(row.get("play_up_game_share")) or 0.0
    play_up_top500_non_loss = _safe_int(row.get("play_up_top500_non_loss_opp_count"))
    play_up_top1000_non_loss = _safe_int(row.get("play_up_top1000_non_loss_opp_count"))
    play_up_avg_opp_power = _safe_float(row.get("play_up_avg_opp_power_adj"))
    has_play_up_support = _has_play_up_support(
        play_up_share,
        play_up_top500_non_loss,
        play_up_top1000_non_loss,
        play_up_avg_opp_power,
        policy,
    )
    authority = _same_age_authority_score(row, policy)
    quality_bridge = _has_quality_bridge_support(row, policy)
    elite_repetitive_release = _has_elite_repetitive_release_profile(row, policy)

    if severe_connectivity:
        if has_play_up_support:
            return float(policy["partial_ml_scale"])
        if quality_bridge:
            return min(
                max(authority, float(policy["partial_ml_scale"])),
                float(policy["thin_recent_ml_scale_max"]),
            )
        return 0.0
    if elite_repetitive_release and not severe_connectivity:
        scale = max(authority, float(policy["elite_repetitive_release_ml_scale_floor"]))
    elif has_play_up_support and connectivity_constrained:
        return float(policy["play_up_partial_ml_scale"])
    elif connectivity_constrained and top100 >= 1:
        return float(policy["partial_ml_scale"])
    elif has_play_up_support:
        scale = max(authority, float(policy["play_up_partial_ml_scale"]))
    else:
        scale = authority

    if stale_recent and not has_play_up_support:
        scale = min(scale, float(policy["stale_recent_ml_scale_max"]))
    elif thin_recent and not has_play_up_support and not quality_bridge:
        scale = min(scale, float(policy["thin_recent_ml_scale_max"]))
    return scale


def _publication_cap_rank(row: pd.Series) -> int | None:
    age_num = _safe_int(row.get("age_num"))
    policy = _same_age_evidence_policy(age_num)
    top100 = _safe_int(row.get("same_age_top100_opp_count"))
    top100_non_loss = _safe_int(row.get("same_age_top100_non_loss_opp_count"))
    top500 = _safe_int(row.get("same_age_top500_opp_count"))
    top500_non_loss = _safe_int(row.get("same_age_top500_non_loss_opp_count"))
    top1000_non_loss = _safe_int(row.get("same_age_top1000_non_loss_opp_count"))
    _broad_avg_opp_power = _safe_float(row.get("same_age_avg_opp_power_adj"))
    _quality_avg_opp_power = _quality_same_age_avg_opp_power(row)
    avg_opp_power = _effective_same_age_avg_opp_power(row, policy)
    repeat_share = _safe_float(row.get("repeat_opponent_share")) or 0.0
    low_state, repeat_heavy, severe_connectivity = _connectivity_flags(row, policy)
    connectivity_constrained = low_state or repeat_heavy
    severe_weak_avg = avg_opp_power is None or avg_opp_power < float(policy["severe_min_avg_opp_power"])
    scf = _safe_float(row.get("scf"))
    unique_opponents = (
        _safe_int(row.get("same_age_unique_opponents")) if row.get("same_age_unique_opponents") is not None else None
    )
    unique_states = _safe_int(row.get("unique_opp_states")) if row.get("unique_opp_states") is not None else None
    play_up_share = _safe_float(row.get("play_up_game_share")) or 0.0
    play_up_top500_non_loss = _safe_int(row.get("play_up_top500_non_loss_opp_count"))
    play_up_top1000_non_loss = _safe_int(row.get("play_up_top1000_non_loss_opp_count"))
    play_up_avg_opp_power = _safe_float(row.get("play_up_avg_opp_power_adj"))
    has_play_up_support = _has_play_up_support(
        play_up_share,
        play_up_top500_non_loss,
        play_up_top1000_non_loss,
        play_up_avg_opp_power,
        policy,
    )
    authority = _same_age_authority_score(row, policy)
    quality_bridge = _has_quality_bridge_support(row, policy)
    elite_repetitive_release = _has_elite_repetitive_release_profile(row, policy)
    freshness, recent_games, days_since_last, thin_recent, stale_recent = _freshness_flags(row, policy)

    thin_schedule = (
        top100 == 0
        and top500 <= int(policy["thin_schedule_max_top500"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["thin_schedule_max_avg_opp_power"])
    )
    regional_thin = (
        top100 == 0
        and top500 <= int(policy["regional_thin_max_top500"])
        and top500_non_loss < int(policy["regional_thin_min_top500_non_loss"])
    )
    regional_thin_quality = (
        regional_thin
        and avg_opp_power is not None
        and avg_opp_power < float(policy["regional_thin_max_avg_opp_power"])
    )
    mid_thin_quality = (
        top100 == 0
        and top500 <= int(policy["mid_thin_max_top500"])
        and top1000_non_loss <= int(policy["mid_thin_max_top1000_non_loss"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["mid_thin_max_avg_opp_power"])
    )
    one_top100_thin = (
        top100 == 1
        and top500 <= int(policy["one_top100_thin_max_top500"])
        and top500_non_loss <= int(policy["one_top100_thin_max_top500_non_loss"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["one_top100_thin_max_avg_opp_power"])
    )
    weak_quality_results = (
        top100 == 1
        and top100_non_loss <= int(policy["weak_quality_results_max_top100_non_loss"])
        and top500 >= int(policy["weak_quality_results_min_top500"])
        and top500_non_loss <= int(policy["weak_quality_results_max_top500_non_loss"])
        and top1000_non_loss <= int(policy["weak_quality_results_max_top1000_non_loss"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["weak_quality_results_max_avg_opp_power"])
    )
    zero_top100_weak_results = (
        top100 == 0
        and unique_opponents is not None
        and unique_opponents >= int(policy["zero_top100_weak_results_min_unique_opponents"])
        and top500 <= int(policy["zero_top100_weak_results_max_top500"])
        and top500_non_loss <= int(policy["zero_top100_weak_results_max_top500_non_loss"])
        and top1000_non_loss <= int(policy["zero_top100_weak_results_max_top1000_non_loss"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["zero_top100_weak_results_max_avg_opp_power"])
    )
    zero_top100_weak_results_severe = zero_top100_weak_results and (
        top500 <= int(policy["zero_top100_weak_results_severe_max_top500"])
        or avg_opp_power < float(policy["zero_top100_weak_results_severe_max_avg_opp_power"])
    )
    local_loop_override = (
        top100 == 0
        and top500 <= int(policy["local_loop_max_top500"])
        and avg_opp_power is not None
        and avg_opp_power < float(policy["local_loop_max_avg_opp_power"])
        and (
            repeat_share >= float(policy["local_loop_repeat_share"])
            or (unique_states is not None and unique_states <= int(policy["local_loop_max_states"]))
            or (scf is not None and scf <= float(policy["local_loop_max_scf"]))
        )
    )
    isolation_override = (
        (scf is not None and scf <= float(policy["isolation_override_max_scf"]))
        or (unique_states is not None and unique_states <= int(policy["isolation_override_max_states"]))
        or repeat_share >= float(policy["isolation_override_repeat_share"])
    )
    regional_thin_low_connectivity = regional_thin and isolation_override
    quality_result_void = (
        top100 == 0
        and top500 <= int(policy["quality_result_void_max_top500"])
        and top500_non_loss == 0
        and top1000_non_loss == 0
        and avg_opp_power is not None
        and avg_opp_power < float(policy["quality_result_void_max_avg_opp_power"])
    )
    strong_broad_profile = _has_strong_broad_profile(row, policy)
    weak_field_connectivity_profile = _has_weak_field_connectivity_overtrust_profile(row, policy)
    weak_avg = avg_opp_power is None or avg_opp_power < float(policy["min_avg_opp_power"])
    weak_depth = top500 < int(policy["min_top500"])
    repeat_heavy_for_cap = repeat_share >= float(policy["max_repeat_share"])

    if has_play_up_support and severe_connectivity:
        return int(policy["soft_cap_rank"])
    if has_play_up_support and connectivity_constrained:
        return int(policy["soft_cap_rank"])
    if strong_broad_profile and not severe_connectivity:
        if elite_repetitive_release:
            return None
        if repeat_heavy_for_cap or connectivity_constrained:
            return int(policy["soft_cap_rank"])
        return None
    if local_loop_override:
        return int(policy["severe_cap_rank"])
    if top100 == 0 and top500 == 0 and top500_non_loss == 0 and top1000_non_loss == 0 and severe_weak_avg:
        return int(policy["severe_cap_rank"])
    if quality_bridge:
        return int(policy["cap_rank"])
    if (
        recent_games is not None
        and recent_games <= int(policy["freshness_hard_recent_games_cap"])
        and not has_play_up_support
        and not strong_broad_profile
    ):
        return int(policy["cap_rank"])
    if stale_recent and not has_play_up_support and not strong_broad_profile:
        return int(policy["cap_rank"])
    if quality_result_void:
        if avg_opp_power < float(policy["quality_result_void_severe_max_avg_opp_power"]):
            return int(policy["severe_cap_rank"])
        return int(policy["quality_result_void_cap_rank"])
    if thin_schedule and isolation_override:
        return int(policy["severe_cap_rank"])
    if zero_top100_weak_results_severe:
        return int(policy["zero_top100_weak_results_escalated_cap_rank"])
    if zero_top100_weak_results:
        return int(policy["zero_top100_weak_results_cap_rank"])
    if regional_thin_low_connectivity:
        return int(policy["regional_thin_escalated_cap_rank"])
    if weak_field_connectivity_profile:
        return int(policy["weak_field_connectivity_cap_rank"])
    if not severe_connectivity and authority >= float(policy["full_release_authority"]):
        return None
    if authority >= float(policy["soft_release_authority"]):
        if connectivity_constrained or weak_avg or weak_depth or repeat_heavy_for_cap:
            return int(policy["soft_cap_rank"])
        return None
    if mid_thin_quality and not isolation_override:
        return int(policy["mid_thin_cap_rank"])
    if regional_thin_quality:
        return int(policy["regional_thin_cap_rank"])
    if thin_schedule:
        return int(policy["thin_schedule_cap_rank"])
    if severe_connectivity:
        return int(policy["cap_rank"])

    if one_top100_thin and isolation_override:
        return int(policy["one_top100_thin_escalated_cap_rank"])
    if one_top100_thin:
        return int(policy["one_top100_thin_cap_rank"])
    if weak_quality_results:
        return int(policy["weak_quality_results_cap_rank"])
    thin_top100 = (
        top100 == 1
        and avg_opp_power is not None
        and top500 < int(policy["thin_top100_min_top500"])
        and avg_opp_power < float(policy["thin_top100_min_avg_opp_power"])
    )
    if thin_top100:
        return int(policy["cap_rank"])
    if connectivity_constrained and top100 >= 1:
        return int(policy["soft_cap_rank"])

    if weak_avg or weak_depth or repeat_heavy_for_cap:
        return int(policy["cap_rank"])
    if connectivity_constrained:
        return int(policy["soft_cap_rank"])
    return None


async def _persist_game_residuals(supabase_client, game_residuals: pd.DataFrame) -> Tuple[int, int]:
    """
    Persist per-game ML residuals to the games table using batch RPC.

    Uses a PostgreSQL function for fast batch updates (~100x faster than individual queries).
    Includes retry logic with exponential backoff for network/timeout errors.

    Args:
        supabase_client: Supabase client instance
        game_residuals: DataFrame with columns [game_id, ml_overperformance]

    Returns:
        Tuple of (total_updated, failed_count)
    """
    if game_residuals.empty:
        return (0, 0)

    # Smaller batch size to reduce statement timeout probability
    batch_size = 500
    max_retries = 3
    retry_delay = 2  # seconds (exponential: 2s, 4s, 8s)
    total_updated = 0
    failed_count = 0
    failed_batches = []  # Collect for end-of-run retry

    for i in range(0, len(game_residuals), batch_size):
        batch = game_residuals.iloc[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(game_residuals) + batch_size - 1) // batch_size

        if batch_num > 1:
            await asyncio.sleep(0.1)

        batch_data = [
            {"id": str(gid), "ml_overperformance": float(val)}
            for gid, val in zip(batch["game_id"].values, batch["ml_overperformance"].values)
        ]

        batch_retry_delay = retry_delay
        batch_saved = False

        for attempt in range(max_retries):
            try:
                result = supabase_client.rpc(
                    "batch_update_ml_overperformance",
                    {"updates": batch_data},
                ).execute()

                if result.data is not None:
                    total_updated += result.data
                else:
                    total_updated += len(batch_data)

                batch_saved = True
                break
            except Exception as e:
                error_msg = str(e)
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Retriable error on batch {batch_num}/{total_batches}, "
                        f"attempt {attempt + 1}/{max_retries}. "
                        f"Retrying in {batch_retry_delay}s... Error: {error_msg[:100]}"
                    )
                    await asyncio.sleep(batch_retry_delay)
                    batch_retry_delay *= 2
                else:
                    logger.warning(
                        f"Batch {batch_num}/{total_batches} failed after {max_retries} attempts: {error_msg[:100]}"
                    )
                    failed_batches.append((batch_num, batch_data))
                    break

        if not batch_saved:
            failed_count += len(batch_data)

        if batch_num % 10 == 0:
            logger.info(f"  Progress: {total_updated:,} / {len(game_residuals):,} games updated...")

    # Retry failed batches once more at the end
    if failed_batches:
        logger.info(f"Retrying {len(failed_batches)} failed batch(es)...")
        for batch_num, batch_data in failed_batches:
            batch_retry_delay = retry_delay
            for attempt in range(max_retries):
                try:
                    result = supabase_client.rpc("batch_update_ml_overperformance", {"updates": batch_data}).execute()

                    if result.data is not None:
                        total_updated += result.data
                    else:
                        total_updated += len(batch_data)

                    failed_count -= len(batch_data)
                    logger.info(f"Batch {batch_num} saved on retry")
                    break  # Success
                except Exception as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(batch_retry_delay)
                        batch_retry_delay *= 2
                    else:
                        logger.error(f"Batch {batch_num} failed after all retries: {str(e)[:100]}")

    if failed_count > 0 and total_updated == 0:
        logger.error(
            f"❌ Residual persistence failed: 0/{len(game_residuals):,} games updated, {failed_count:,} failed"
        )
    elif failed_count > 0:
        logger.warning(
            f"⚠️ Residual persistence partial: {total_updated:,} updated, "
            f"{failed_count:,} failed out of {len(game_residuals):,}"
        )
    else:
        logger.info(f"✅ Successfully updated {total_updated:,} games with ML residuals")

    return (total_updated, failed_count)


async def compute_rankings_with_ml(
    supabase_client,
    games_df: Optional[pd.DataFrame] = None,
    today: Optional[pd.Timestamp] = None,
    v53_cfg: Optional[V53EConfig] = None,
    layer13_cfg: Optional[Layer13Config] = None,
    fetch_from_supabase: bool = True,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    ctx: Optional[RankingContext] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Run the selected rankings engine, then apply the Supabase-aware ML adjustment.

    Args:
        supabase_client: Supabase client instance
        games_df: Optional pre-fetched games DataFrame in the shared rankings input shape
        today: Reference date for rankings
        v53_cfg: Legacy v53e configuration (ignored in Glicko mode except for shared downstream steps)
        layer13_cfg: ML layer configuration
        fetch_from_supabase: If True and games_df is None, fetch from Supabase
        lookback_days: Days to look back for rankings
        provider_filter: Optional provider code filter
        ctx: Ranking context with team metadata, cross-age state, and engine control

    Returns:
        {
            "teams": teams_df_with_ml,
            "games_used": games_used_df,
            "game_explainability": explainability_df
        }
    """
    ctx = ctx or RankingContext()
    # Unpack context fields as locals so the body reads naturally
    force_rebuild = ctx.force_rebuild
    save_snapshot = ctx.save_snapshot
    persist_game_residuals = ctx.persist_game_residuals
    persist_game_explainability = ctx.persist_game_explainability
    global_strength_map = ctx.global_strength_map
    merge_version = ctx.merge_version
    team_state_map = ctx.team_state_map
    tier_league_map = ctx.tier_league_map
    timing_report = ctx.timing_report
    pass_label = ctx.pass_label
    pre_sos_state = ctx.pre_sos_state
    use_glicko = ctx.use_glicko
    initial_ratings = ctx.initial_ratings
    snapshot_date = _normalize_snapshot_date(today)

    v53_cfg = v53_cfg or V53EConfig()
    glicko_cfg = GlickoConfig() if use_glicko else None
    fetch_lookback_days = _effective_fetch_lookback_days(lookback_days, use_glicko=use_glicko)

    # 1) Get games data
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            logger.info("🔍 Fetching games from Supabase...")
            with _section(timing_report, "fetch_games"):
                games_df = await fetch_games_for_rankings(
                    supabase_client=supabase_client,
                    lookback_days=fetch_lookback_days,
                    provider_filter=provider_filter,
                    today=today,
                )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")

    if games_df.empty:
        logger.warning("⚠️  No games found - returning empty results")
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame(),
            "game_explainability": pd.DataFrame(),
        }

    logger.info(f"📊 Computing rankings for {len(games_df):,} game perspectives...")

    # 2) Check cache before running v53e rankings engine
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Generate hash key from game IDs + full config fingerprint
    # Changing any tuning param (engine, Glicko config, ML config, tier multipliers) invalidates cache
    game_ids = games_df["game_id"].astype(str).tolist() if "game_id" in games_df.columns else []
    hash_input = "".join(sorted(game_ids)) + str(lookback_days) + (provider_filter or "")
    if merge_version and merge_version != "no_merges":
        hash_input += f"_merge_{merge_version}"

    # Config fingerprint: serialize actual engine + ML + tier config
    import json as _json

    from src.rankings.constants import (
        LEAGUE_MULTIPLIER_FEMALE as _LMF,
    )
    from src.rankings.constants import (
        LEAGUE_MULTIPLIER_MALE as _LMM,
    )
    from src.rankings.constants import (
        NEGATIVE_ML_FLOOR as _NMF,
    )
    from src.rankings.constants import (
        SOS_ML_THRESHOLD_HIGH as _SMH,
    )
    from src.rankings.constants import (
        SOS_ML_THRESHOLD_LOW as _SML,
    )
    from src.rankings.constants import (
        UNAFFILIATED_MULTIPLIER_FEMALE as _UMF,
    )
    from src.rankings.constants import (
        UNAFFILIATED_MULTIPLIER_MALE as _UMM,
    )

    _ecfg = glicko_cfg or v53_cfg
    _ml = layer13_cfg or Layer13Config(lookback_days=_ecfg.WINDOW_DAYS if hasattr(_ecfg, "WINDOW_DAYS") else 365)
    _cfg_dict = {
        "cache_schema": 3,
        "engine": "glicko" if use_glicko else "v53e",
        "min_games": _ecfg.MIN_GAMES_PROVISIONAL,
        "window": getattr(_ecfg, "WINDOW_DAYS", 365),
        "window_grace": getattr(_ecfg, "WINDOW_GRACE_DAYS", 0),
        "scf": getattr(_ecfg, "SCF_ENABLED", True),
        "scf_po": getattr(_ecfg, "SCF_PUBLISH_ONLY", None),
        "scf_lf": getattr(_ecfg, "SCF_LEAGUE_FLOOR", None),
        "scf_lc": getattr(_ecfg, "SCF_LEAGUE_CONCENTRATION_THRESHOLD", None),
        "tier_ctr": getattr(_ecfg, "TIER_MULT_CENTERED", None),
        "ml_a": _ml.alpha,
        "ml_nm": _ml.norm_mode,
        "ml_mg": _ml.min_team_games_for_residual,
        "ml_rd": _ml.recency_decay_lambda,
        "ml_rc": getattr(_ml, "residual_clip_goals", 6),
        "nmf": _NMF,
        "sml": _SML,
        "smh": _SMH,
        "tm": sorted(_LMM.items()),
        "tf": sorted(_LMF.items()),
        "um": _UMM,
        "uf": _UMF,
        "sos_adj": getattr(_ecfg, "SOS_ADJ_ENABLED", False),
        "sos_adj_wt": getattr(_ecfg, "SOS_ADJ_WEAK_THRESHOLD", None),
        "sos_adj_st": getattr(_ecfg, "SOS_ADJ_STRONG_THRESHOLD", None),
        "sos_adj_wm": getattr(_ecfg, "SOS_ADJ_WEAK_MAX", None),
        "sos_adj_sm": getattr(_ecfg, "SOS_ADJ_STRONG_MAX", None),
    }
    _cfg_fp = hashlib.md5(_json.dumps(_cfg_dict, sort_keys=True, default=str).encode()).hexdigest()[:12]
    hash_input += f"_cfg_{_cfg_fp}"

    cache_key = hashlib.md5(hash_input.encode()).hexdigest()
    cache_file_teams = cache_dir / f"rankings_{cache_key}_teams.parquet"
    cache_file_games = cache_dir / f"rankings_{cache_key}_games.parquet"
    cache_file_explain = cache_dir / f"rankings_{cache_key}_game_explainability.parquet"

    # Try to load from cache (both teams and games_used)
    base = None
    if not force_rebuild and cache_file_teams.exists():
        try:
            cached_teams = pd.read_parquet(cache_file_teams)
            if not cached_teams.empty:
                # Cache hit - load teams plus any auxiliary DataFrames.
                cached_games_used = pd.DataFrame()
                cached_game_explainability = pd.DataFrame()
                if cache_file_games.exists():
                    try:
                        cached_games_used = pd.read_parquet(cache_file_games)
                    except Exception as error:
                        # A partial hit (cached ratings + freshly fetched ML inputs)
                        # would mix two game universes, so a failed games_used load
                        # invalidates the entire cached set
                        logger.warning("games_used cache load failed; rebuilding rankings: %s", error)
                        raise
                if use_glicko:
                    if cache_file_explain.exists():
                        try:
                            cached_game_explainability = pd.read_parquet(cache_file_explain)
                        except Exception as error:
                            logger.warning("Game explainability cache load failed; rebuilding rankings: %s", error)
                            raise
                    else:
                        raise FileNotFoundError("Missing game explainability cache for Glicko run")
                base = {
                    "teams": cached_teams,
                    "games_used": cached_games_used,
                    "game_explainability": cached_game_explainability,
                }
        except Exception:
            # Cache load failed - continue with computation
            pass

    # 2) Run rankings engine (if not cached)
    if base is None:
        if use_glicko:
            logger.info(f"🔁 Rebuilding Glicko-2 rankings from raw data... (force_rebuild={force_rebuild})")
            with _section(timing_report, "glicko2_computation"):
                base = compute_rankings_v2(
                    games_df=games_df,
                    today=today,
                    cfg=glicko_cfg or GlickoConfig(),
                    global_rating_map=global_strength_map,
                    team_state_map=team_state_map,
                    pass_label=pass_label,
                    initial_ratings=initial_ratings,
                    tier_league_map=tier_league_map,
                )
            logger.info(f"✅ Glicko-2 engine completed: {len(base['teams']):,} teams ranked")
        else:
            logger.info(f"🔁 Rebuilding v53e rankings from raw data... (force_rebuild={force_rebuild})")
            with _section(timing_report, "v53e_computation"):
                base = compute_rankings(
                    games_df=games_df,
                    today=today,
                    cfg=v53_cfg,
                    global_strength_map=global_strength_map,
                    team_state_map=team_state_map,
                    pass_label=pass_label,
                    pre_sos_state=pre_sos_state,
                    tier_league_map=tier_league_map,
                )
            logger.info(f"✅ v53e engine completed: {len(base['teams']):,} teams ranked")

        # Save to cache (both teams and games_used DataFrames)
        try:
            if not base["teams"].empty:
                base["teams"].to_parquet(cache_file_teams, index=False)
                logger.debug(f"💾 Cached teams to {cache_file_teams}")
            games_used_to_cache = base.get("games_used")
            if games_used_to_cache is not None and not getattr(games_used_to_cache, "empty", True):
                games_used_to_cache.to_parquet(cache_file_games, index=False)
                logger.debug(f"💾 Cached games_used to {cache_file_games}")
            explainability_to_cache = base.get("game_explainability")
            if explainability_to_cache is not None and not getattr(explainability_to_cache, "empty", True):
                explainability_to_cache.to_parquet(cache_file_explain, index=False)
                logger.debug(f"💾 Cached game explainability to {cache_file_explain}")
        except Exception:
            # Cache save failed - continue without caching
            pass
    else:
        logger.info("💾 Using cached v53e rankings")

    teams_base = base["teams"]
    games_used = base.get("games_used")
    game_explainability = base.get("game_explainability")
    _pre_sos_state = base.get("pre_sos_state")

    if teams_base.empty:
        return {
            "teams": teams_base,
            "games_used": games_used if not getattr(games_used, "empty", True) else pd.DataFrame(),
            "game_explainability": (
                game_explainability if not getattr(game_explainability, "empty", True) else pd.DataFrame()
            ),
        }

    # Log PowerScore summary before ML layer
    if not teams_base.empty and "powerscore_adj" in teams_base.columns:
        ps_stats = teams_base["powerscore_adj"]
        logger.info(
            f"📊 Pre-ML PowerScore: min={ps_stats.min():.3f}, max={ps_stats.max():.3f}, "
            f"mean={ps_stats.mean():.3f}, n={len(teams_base)}"
        )

    # 3) Apply ML predictive adjustment
    logger.info("🤖 Applying ML predictive adjustment layer...")
    logger.debug(
        f"games_df: {len(games_df)} rows, has_id={'id' in games_df.columns}, "
        f"has_home_master={'home_team_master_id' in games_df.columns}"
    )

    ml_cfg = layer13_cfg or Layer13Config(
        lookback_days=v53_cfg.WINDOW_DAYS,
        alpha=0.08,  # Tuned via weight simulator grid search: 0.08 optimal (quality 14→19/23)
        norm_mode="zscore",
        min_team_games_for_residual=12,
        recency_decay_lambda=0.06,  # Short-term form focus; tune later after stability verified
        table_name="games",
        provider_filter=provider_filter,
    )

    with _section(timing_report, "ml_layer_13"):
        teams_with_ml, game_residuals = await apply_predictive_adjustment(
            supabase_client=supabase_client,
            teams_df=teams_base,
            games_used_df=base.get("games_used", games_df),  # Use Glicko-2 filtered games
            cfg=ml_cfg,
            return_game_residuals=True,  # Request per-game residuals
        )
    logger.info(f"✅ ML adjustment completed: {len(teams_with_ml):,} teams processed")

    # Persist game residuals to database (skip during Pass 1 — Pass 2 values overwrite)
    skip_persist = pass_label == "Pass1"
    with _section(timing_report, "persist_game_residuals"):
        if not persist_game_residuals:
            logger.info("Skipping residual persistence (disabled for this run)")
        elif skip_persist:
            logger.info("⏭️  Skipping residual persistence (Pass 1 — will persist in Pass 2)")
        elif not game_residuals.empty:
            logger.info(f"💾 Persisting {len(game_residuals):,} game residuals to database...")
            updated, failed = await _persist_game_residuals(supabase_client, game_residuals)
            if failed > 0:
                logger.warning(f"⚠️ Game residuals: {updated:,} persisted, {failed:,} failed")
            elif updated == 0:
                logger.warning("⚠️ Game residuals: 0 records persisted despite non-empty input")
            else:
                logger.info(f"✅ Game residuals persisted: {updated:,} records")
        else:
            logger.warning("⚠️ No game residuals to persist — check extraction logs above")
            logger.warning("   Common causes: missing columns (id, home_team_master_id), empty feats, or filter issues")

    with _section(timing_report, "persist_game_explainability"):
        if not persist_game_explainability:
            logger.info("Skipping explainability persistence (disabled for this run)")
        elif skip_persist:
            logger.info("Skipping explainability persistence (Pass 1 - will persist in Pass 2)")
        elif getattr(game_explainability, "empty", True):
            logger.info("No game explainability rows to persist for this cohort")
        else:
            logger.info("Persisting %s game explainability rows to database...", len(game_explainability))
            updated, failed = await _persist_game_explainability(supabase_client, game_explainability)
            if failed > 0:
                logger.warning("Game explainability: %s persisted, %s failed", f"{updated:,}", f"{failed:,}")
            elif updated == 0:
                logger.warning("Game explainability: 0 records persisted despite non-empty input")
            else:
                logger.info("Game explainability persisted: %s records", f"{updated:,}")

    # Log PowerScore summary after ML layer
    if not teams_with_ml.empty and "powerscore_ml" in teams_with_ml.columns:
        ps_ml = teams_with_ml["powerscore_ml"]
        logger.info(f"📊 Post-ML PowerScore: min={ps_ml.min():.3f}, max={ps_ml.max():.3f}, mean={ps_ml.mean():.3f}")

        # Per-cohort detail at DEBUG
        if "powerscore_adj" in teams_with_ml.columns:
            ps_max_before_ml = teams_with_ml.groupby(["age", "gender"])["powerscore_adj"].max().round(3)
            ps_max_after_ml = teams_with_ml.groupby(["age", "gender"])["powerscore_ml"].max().round(3)
            for age, gender in ps_max_before_ml.index:
                before = ps_max_before_ml[(age, gender)]
                after = ps_max_after_ml.get((age, gender), 0)
                logger.debug(f"  {age} {gender}: pre-ML={before:.3f}, post-ML={after:.3f}, diff={after - before:+.3f}")

    # Rank-change columns are populated later in compute_all_cohorts; init here so
    # solo callers of this function still see the columns on the returned DataFrame.
    for column in [
        "rank_change_7d",
        "rank_change_30d",
        "rank_change_state_7d",
        "rank_change_state_30d",
    ]:
        if column not in teams_with_ml.columns:
            teams_with_ml[column] = None

    # Save current rankings as a snapshot for future rank change calculations
    # (Skip if save_snapshot=False, e.g., when called from compute_all_cohorts)
    if save_snapshot and not teams_with_ml.empty:
        logger.info("💾 Saving ranking snapshot for future comparisons...")
        with _section(timing_report, "save_ranking_snapshot"):
            await save_ranking_snapshot(
                supabase_client=supabase_client,
                rankings_df=teams_with_ml,
                snapshot_date=snapshot_date,
            )
        with _section(timing_report, "save_prediction_feature_snapshot"):
            await _save_prediction_feature_snapshot_safe(
                supabase_client=supabase_client,
                rankings_df=teams_with_ml,
                snapshot_date=snapshot_date,
            )

    return {
        "teams": teams_with_ml,
        "games_used": games_used if not getattr(games_used, "empty", True) else pd.DataFrame(),
        "game_explainability": (
            game_explainability if not getattr(game_explainability, "empty", True) else pd.DataFrame()
        ),
        "pre_sos_state": _pre_sos_state,
    }


async def compute_rankings_v53e_only(
    supabase_client,
    games_df: Optional[pd.DataFrame] = None,
    today: Optional[pd.Timestamp] = None,
    v53_cfg: Optional[V53EConfig] = None,
    fetch_from_supabase: bool = True,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    force_rebuild: bool = False,
    team_state_map: Optional[Dict[str, str]] = None,  # For SCF regional bubble detection
    tier_league_map: Optional[Dict[str, str]] = None,  # For tier-based SOS discounting
    merge_resolver=None,  # Optional MergeResolver for team merge resolution
    timing_report: Optional["TimingReport"] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Run v53e rankings engine only (without ML layer).

    Useful for comparison or when ML is disabled.
    Note: team_state_map is optional - if not provided, SCF will be disabled.
    """
    v53_cfg = v53_cfg or V53EConfig()

    # Get games data
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            logger.info("🔍 Fetching games from Supabase...")
            with _section(timing_report, "fetch_games"):
                games_df = await fetch_games_for_rankings(
                    supabase_client=supabase_client,
                    lookback_days=lookback_days,
                    provider_filter=provider_filter,
                    today=today,
                    merge_resolver=merge_resolver,
                )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")

    if games_df.empty:
        logger.warning("⚠️  No games found - returning empty results")
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame(),
            "game_explainability": pd.DataFrame(),
        }

    logger.info(f"📊 Computing v53e rankings for {len(games_df):,} game perspectives...")

    # Run v53e rankings engine
    logger.info("⚙️  Running v53e rankings engine...")
    with _section(timing_report, "v53e_computation"):
        result = compute_rankings(
            games_df=games_df,
            today=today,
            cfg=v53_cfg,
            team_state_map=team_state_map,  # For SCF regional bubble detection
            tier_league_map=tier_league_map,  # For tier-based SOS discounting
        )
    logger.info(f"✅ v53e engine completed: {len(result['teams']):,} teams ranked")

    return {
        **result,
        "game_explainability": result.get("game_explainability", pd.DataFrame()),
    }


async def compute_all_cohorts(
    supabase_client,
    games_df: Optional[pd.DataFrame] = None,
    today: Optional[pd.Timestamp] = None,
    v53_cfg: Optional[V53EConfig] = None,
    layer13_cfg: Optional[Layer13Config] = None,
    fetch_from_supabase: bool = True,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    force_rebuild: bool = False,
    merge_resolver=None,  # Optional MergeResolver for team merge resolution
    timing_report: Optional["TimingReport"] = None,
    use_glicko: bool = True,  # True = Glicko-2 engine, False = legacy v53e engine
    persist_game_residuals: bool = True,
    persist_game_explainability: bool = True,
    calculate_rank_changes_enabled: bool = True,
    save_snapshot: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Compute rankings for all cohorts using two-pass architecture.

    Pass 1: Run each cohort to get initial cohort strength values
    Pass 2: Re-run with a global strength map for accurate cross-age opponent lookups

    In Glicko mode, Pass 2 reuses cohort `mu` values for cross-age opponent ratings.
    Legacy v53e uses `abs_strength` for its cross-age SOS path.

    Args:
        merge_resolver: Optional MergeResolver instance for resolving merged teams
        use_glicko: If True, use Glicko-2 engine; if False, use legacy v53e engine
    """
    # Default config if not provided
    v53_cfg = v53_cfg or V53EConfig()

    # Get merge version for cache invalidation
    merge_version = merge_resolver.version if merge_resolver else None

    # Get games data if not provided
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            fetch_lookback_days = _effective_fetch_lookback_days(lookback_days, use_glicko=use_glicko)
            with _section(timing_report, "fetch_games"):
                games_df = await fetch_games_for_rankings(
                    supabase_client=supabase_client,
                    lookback_days=fetch_lookback_days,
                    provider_filter=provider_filter,
                    today=today,
                    merge_resolver=merge_resolver,  # Apply merge resolution
                )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")

    if games_df.empty:
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame(),
            "game_explainability": pd.DataFrame(),
        }

    # ========== FETCH TEAM STATE METADATA FOR SCF ==========
    # Fetch state_code for all teams to enable Schedule Connectivity Factor (SCF)
    # which detects and dampens regional bubbles (e.g., Idaho teams only playing each other)
    team_ids = set()
    team_ids.update(games_df["team_id"].dropna().astype(str).tolist())
    team_ids.update(games_df["opp_id"].dropna().astype(str).tolist())

    team_state_map = {}
    tier_league_map: Dict[str, str] = {}
    with _section(timing_report, "team_metadata"):
        if team_ids:
            logger.info(f"🗺️  Fetching state+league metadata for {len(team_ids):,} teams (for SCF + tier multiplier)...")
            rows = batch_fetch_rows(
                supabase_client,
                "teams",
                "team_id_master, state_code, league",
                "team_id_master",
                list(team_ids),
            )
            for row in rows:
                team_id = str(row.get("team_id_master", ""))
                if not team_id:
                    continue
                state_code = row.get("state_code", "UNKNOWN")
                team_state_map[team_id] = state_code if state_code else "UNKNOWN"
                league = row.get("league")
                if league:
                    tier_league_map[team_id] = league

            state_counts: Dict[str, int] = {}
            for state in team_state_map.values():
                state_counts[state] = state_counts.get(state, 0) + 1
            top_states = sorted(state_counts.items(), key=lambda x: -x[1])[:5]
            logger.info(f"✅ Fetched state_code for {len(team_state_map):,} teams. Top states: {dict(top_states)}")
            league_counts: Dict[str, int] = {}
            for lg in tier_league_map.values():
                league_counts[lg] = league_counts.get(lg, 0) + 1
            top_league_distribution = dict(sorted(league_counts.items(), key=lambda x: -x[1])[:5])
            logger.info(
                f"✅ Fetched league for {len(tier_league_map):,} teams. Distribution: {top_league_distribution}"
            )
        else:
            logger.warning("⚠️ No team IDs found for metadata fetch - SCF and tier multiplier will be disabled")

    # ========== AGE-BUCKET VALIDATION ==========
    # Reject/quarantine ages outside PitchRank's supported range (U10–U19).
    # Ages outside this range are data quality issues (u0, u3–u7) or
    # unsupported age groups (u9, u19–u21). Based on production data:
    #   u0: 3 teams, u3–u7: 54 teams, u8–u9: 2,373 teams, u20–u21: 39 teams
    VALID_AGE_MIN = 10
    VALID_AGE_MAX = 19
    games_df["_age_num"] = pd.to_numeric(games_df["age"], errors="coerce")
    invalid_age_mask = (
        games_df["_age_num"].isna() | (games_df["_age_num"] < VALID_AGE_MIN) | (games_df["_age_num"] > VALID_AGE_MAX)
    )
    if invalid_age_mask.any():
        invalid_games = games_df.loc[invalid_age_mask]
        invalid_age_counts = invalid_games["age"].value_counts().to_dict()
        logger.warning(
            f"🚫 Quarantining {invalid_age_mask.sum():,} game rows with ages "
            f"outside {VALID_AGE_MIN}–{VALID_AGE_MAX}: {invalid_age_counts}"
        )
        for bad_age, count in sorted(invalid_age_counts.items(), key=lambda x: -x[1]):
            sample = invalid_games[invalid_games["age"] == bad_age].head(3)
            for _, row in sample.iterrows():
                logger.warning(
                    f"   Age {bad_age}: team={str(row.get('team_id', ''))[:12]}... "
                    f"opp={str(row.get('opp_id', ''))[:12]}... "
                    f"date={row.get('game_date', 'N/A')}, "
                    f"provider={row.get('provider', 'N/A')}"
                )
        games_df = games_df.loc[~invalid_age_mask].copy()
        logger.info(f"✅ After age validation: {len(games_df):,} game rows remain")
    games_df.drop(columns=["_age_num"], inplace=True, errors="ignore")

    if games_df.empty:
        logger.error("❌ No valid games remain after age validation")
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame(),
            "game_explainability": pd.DataFrame(),
        }

    # Group by (age, gender) cohorts
    cohorts = list(games_df.groupby(["age", "gender"]))
    logger.info(f"🔄 Two-pass cross-age strength flow: processing {len(cohorts)} cohorts")

    # ========== PASS 1: Get initial strengths from all cohorts ==========
    logger.info("📊 Pass 1: Computing initial strengths for all cohorts...")
    pass1_tasks = []
    for (age, gender), cohort_games in cohorts:
        task = compute_rankings_with_ml(
            supabase_client=supabase_client,
            games_df=cohort_games,
            today=today,
            v53_cfg=v53_cfg,
            layer13_cfg=layer13_cfg,
            fetch_from_supabase=False,
            lookback_days=lookback_days,
            provider_filter=provider_filter,
            ctx=RankingContext(
                force_rebuild=force_rebuild,
                save_snapshot=False,
                global_strength_map=None,
                merge_version=merge_version,
                team_state_map=team_state_map,
                tier_league_map=tier_league_map,
                pass_label="Pass1",
                use_glicko=use_glicko,
                persist_game_residuals=persist_game_residuals,
                persist_game_explainability=persist_game_explainability,
            ),
        )
        pass1_tasks.append(task)

    with _section(timing_report, "pass1_all_cohorts"):
        pass1_results = await asyncio.gather(*pass1_tasks)

    # Build the Pass 2 global strength map.
    # Glicko-2 uses `mu` for cross-age opponent lookups; legacy v53e uses `abs_strength`.
    strength_col = "mu" if use_glicko else "abs_strength"
    global_strength_map = {}
    pass1_pre_sos_states = {}
    pass1_glicko_ratings = {}  # Cache converged ratings per cohort for warm-start
    for i, result in enumerate(pass1_results):
        if not result["teams"].empty:
            teams_df = result["teams"]
            if strength_col in teams_df.columns:
                strength_dict = dict(
                    zip(
                        teams_df["team_id"].astype(str),
                        teams_df[strength_col].astype(float),
                    )
                )
                global_strength_map.update(strength_dict)
            # Cache converged Glicko-2 ratings for warm-starting Pass 2
            if use_glicko and all(c in teams_df.columns for c in ("mu", "sigma", "volatility")):
                pass1_glicko_ratings[i] = dict(
                    zip(
                        teams_df["team_id"].astype(str),
                        zip(teams_df["mu"], teams_df["sigma"], teams_df["volatility"]),
                    )
                )
        # Cache pre-SOS state keyed by cohort index (v53e only; Glicko-2 has none)
        if not use_glicko and result.get("pre_sos_state"):
            pass1_pre_sos_states[i] = result["pre_sos_state"]

    logger.info(
        f"🌍 Built global strength map with {len(global_strength_map):,} teams "
        f"(source={strength_col}), cached {len(pass1_pre_sos_states)} legacy pre-SOS states"
    )

    # ========== PASS 2: Re-run with global strength map ==========
    # Legacy v53e reuses cached pre-SOS state from Pass 1 to skip layers 1-5.
    # Glicko-2 warm-starts from Pass 1 converged ratings.
    skip_note = " (skipping layers 1-5)" if not use_glicko else " (warm-start from Pass 1)"
    logger.info(f"📊 Pass 2: Re-running cohorts with global strength map{skip_note}...")
    pass2_tasks = []
    for i, ((age, gender), cohort_games) in enumerate(cohorts):
        task = compute_rankings_with_ml(
            supabase_client=supabase_client,
            games_df=cohort_games,
            today=today,
            v53_cfg=v53_cfg,
            layer13_cfg=layer13_cfg,
            fetch_from_supabase=False,
            lookback_days=lookback_days,
            provider_filter=provider_filter,
            ctx=RankingContext(
                force_rebuild=True,
                save_snapshot=False,
                global_strength_map=global_strength_map,
                merge_version=merge_version,
                team_state_map=team_state_map,
                tier_league_map=tier_league_map,
                pass_label="Pass2",
                pre_sos_state=None if use_glicko else pass1_pre_sos_states.get(i),
                use_glicko=use_glicko,
                initial_ratings=pass1_glicko_ratings.get(i) if use_glicko else None,
                persist_game_residuals=persist_game_residuals,
                persist_game_explainability=persist_game_explainability,
            ),
        )
        pass2_tasks.append(task)

    with _section(timing_report, "pass2_all_cohorts"):
        pass2_results = await asyncio.gather(*pass2_tasks)

    # Merge results from Pass 2
    with _section(timing_report, "merge_and_filter"):
        all_teams = []
        all_games_used = []
        all_game_explainability = []

        for result in pass2_results:
            if not result["teams"].empty:
                all_teams.append(result["teams"])
            if not result.get("games_used", pd.DataFrame()).empty:
                all_games_used.append(result["games_used"])
            if not result.get("game_explainability", pd.DataFrame()).empty:
                all_game_explainability.append(result["game_explainability"])

        # Combine results
        teams_combined = pd.concat(all_teams, ignore_index=True) if all_teams else pd.DataFrame()
        games_used_combined = pd.concat(all_games_used, ignore_index=True) if all_games_used else pd.DataFrame()
        game_explainability_combined = (
            pd.concat(all_game_explainability, ignore_index=True) if all_game_explainability else pd.DataFrame()
        )

    # ========== Deduplicate cross-cohort teams ==========
    # Play-up teams appear in multiple (age, gender) cohorts. Keep the row
    # from the team's primary cohort (most games_played).
    if not teams_combined.empty and teams_combined["team_id"].duplicated().any():
        before_count = len(teams_combined)
        sort_col = "games_played" if "games_played" in teams_combined.columns else "power_score_final"
        teams_combined = (
            teams_combined.sort_values(sort_col, ascending=False, na_position="last")
            .drop_duplicates(subset=["team_id"], keep="first")
            .reset_index(drop=True)
        )
        dedup_count = before_count - len(teams_combined)
        logger.info(f"🔀 Deduplicated {dedup_count} cross-cohort team entries (kept primary cohort by {sort_col})")

    # ========== Filter deprecated teams ==========
    # Remove any deprecated teams that slipped through game-level merge resolution.
    # Check BOTH the merge resolver (team_merge_map) AND the teams.is_deprecated field
    # to catch teams that are deprecated but not yet merged.
    if not teams_combined.empty:
        deprecated_ids = set()

        # Source 1: merge resolver (teams in team_merge_map)
        if merge_resolver is not None and merge_resolver.has_merges:
            deprecated_ids.update(merge_resolver.get_deprecated_teams())

        # Source 2: teams.is_deprecated field (canonical source of truth)
        ranked_team_ids = teams_combined["team_id"].astype(str).unique().tolist()
        batch_size = 100
        for i in range(0, len(ranked_team_ids), batch_size):
            batch = ranked_team_ids[i : i + batch_size]
            try:
                result = (
                    supabase_client.table("teams")
                    .select("team_id_master")
                    .in_("team_id_master", batch)
                    .eq("is_deprecated", True)
                    .execute()
                )
                if result.data:
                    deprecated_ids.update(str(row["team_id_master"]) for row in result.data)
            except Exception as e:
                logger.warning(f"⚠️ Failed to check is_deprecated for batch {i}: {str(e)[:100]}")
                continue

        if deprecated_ids:
            before_count = len(teams_combined)
            teams_combined = teams_combined[~teams_combined["team_id"].astype(str).isin(deprecated_ids)].copy()
            filtered_count = before_count - len(teams_combined)
            if filtered_count > 0:
                logger.info(f"🚫 Filtered {filtered_count} deprecated teams from ranking output")

    # ========== PASS 3: National/State SOS Normalization ==========
    # After all cohorts are combined, compute national and state-level SOS rankings
    if not teams_combined.empty and "sos" in teams_combined.columns:
        logger.info("📊 Pass 3: Computing national/state SOS normalization...")

        # Create sos_raw from the post-shrinkage SOS value
        teams_combined["sos_raw"] = teams_combined["sos"].astype(float)

        # Reuse team_state_map from SCF fetch (line ~520) instead of re-querying Supabase
        if team_state_map:
            teams_combined["state_code"] = teams_combined["team_id"].astype(str).map(team_state_map).fillna("UNKNOWN")
            mapped_count = (teams_combined["state_code"] != "UNKNOWN").sum()
            logger.info(f"✅ Mapped state_code for {mapped_count:,} teams (reused SCF metadata)")
        else:
            teams_combined["state_code"] = "UNKNOWN"
            logger.warning("⚠️ No state metadata available - using 'UNKNOWN' for all teams")

        # Initialize new SOS columns
        teams_combined["sos_norm_national"] = 0.0
        teams_combined["sos_norm_state"] = 0.0
        # Use nullable Int64 type for ranks to support NULL values for ineligible teams
        teams_combined["sos_rank_national"] = pd.array([pd.NA] * len(teams_combined), dtype="Int64")
        teams_combined["sos_rank_state"] = pd.array([pd.NA] * len(teams_combined), dtype="Int64")

        # SOS rank eligibility is derived from Active status (which uses MIN_GAMES_PROVISIONAL)
        # so the ranking gate and SOS gate can never drift apart.
        if "status" in teams_combined.columns:
            sos_rank_eligible = teams_combined["status"] == "Active"
        else:
            logger.warning("⚠️ 'status' column not found - all teams will be eligible for SOS ranking")
            sos_rank_eligible = pd.Series([True] * len(teams_combined), index=teams_combined.index)

        # Compute national and state SOS rankings per cohort (age, gender)
        for (age, gender), cohort_df in teams_combined.groupby(["age", "gender"]):
            cohort_idx = cohort_df.index

            # National normalization: percentile rank across all states in this cohort
            # rank(pct=True) gives values from 0 to 1
            # NOTE: ALL teams get sos_norm values (for PowerScore), regardless of games played
            teams_combined.loc[cohort_idx, "sos_norm_national"] = (
                cohort_df["sos_raw"].rank(method="average", pct=True).fillna(0.5)
            )

            # National rank: only for Active teams
            # This prevents teams with few games from appearing as #1 SOS nationally
            eligible_mask = sos_rank_eligible.loc[cohort_idx]
            eligible_idx = cohort_df[eligible_mask].index
            if len(eligible_idx) > 0:
                eligible_sos_values = teams_combined.loc[eligible_idx, "sos_raw"]
                ranks = eligible_sos_values.rank(method="min", ascending=False).astype("Int64")
                teams_combined.loc[eligible_idx, "sos_rank_national"] = ranks

            # State-level normalization and ranking within this cohort
            for state, state_df in cohort_df.groupby("state_code"):
                state_idx = state_df.index

                # State normalization: percentile rank within state (ALL teams)
                teams_combined.loc[state_idx, "sos_norm_state"] = (
                    state_df["sos_raw"].rank(method="average", pct=True).fillna(0.5)
                )

                # State rank: only for eligible teams within state
                state_eligible_mask = sos_rank_eligible.loc[state_idx]
                state_eligible_idx = state_df[state_eligible_mask].index
                if len(state_eligible_idx) > 0:
                    state_eligible_sos = teams_combined.loc[state_eligible_idx, "sos_raw"]
                    state_ranks = state_eligible_sos.rank(method="min", ascending=False).astype("Int64")
                    teams_combined.loc[state_eligible_idx, "sos_rank_state"] = state_ranks

        # Log SOS normalization results
        excluded_count = (~sos_rank_eligible).sum()
        len(teams_combined)
        ranked_national = teams_combined["sos_rank_national"].notna().sum()
        logger.info(
            f"✅ National/State SOS normalization complete: "
            f"sos_norm_national range="
            f"[{teams_combined['sos_norm_national'].min():.3f}, "
            f"{teams_combined['sos_norm_national'].max():.3f}], "
            f"SOS ranking: {ranked_national:,} Active teams eligible, "
            f"{excluded_count:,} non-Active teams excluded"
        )

        # Sample state distribution for diagnostics
        state_counts = teams_combined["state_code"].value_counts()
        top_states = state_counts.head(5).to_dict()
        logger.info(f"📍 Top states by team count: {top_states}")

    # Ensure age_num exists after metadata merge (fallback safety check)
    if "age_num" not in teams_combined.columns and "age" in teams_combined.columns:
        try:
            # Convert age to numeric, coercing errors to NaN
            age_numeric = pd.to_numeric(teams_combined["age"], errors="coerce")
            teams_combined["age_num"] = age_numeric.fillna(0).astype(int)

            # Log any teams with invalid ages
            invalid_count = age_numeric.isna().sum()
            if invalid_count > 0:
                logger.warning(f"⚠️ {invalid_count} teams had invalid age values, defaulting to 0")

            logger.info("✅ Recreated age_num from age column after metadata merge")
        except Exception as e:
            logger.error(f"❌ Failed to create age_num column: {e}")
            teams_combined["age_num"] = 0  # Default to 0, will get no anchor scaling

    # ========== Same-Age Evidence Metrics ==========
    if not teams_combined.empty:
        frozen_rank_lookup = None
        if use_glicko and GlickoConfig().EVIDENCE_GATE_FROZEN_REF:
            if "status" in teams_combined.columns:
                ranked_team_ids = (
                    teams_combined.loc[teams_combined["status"] == "Active", "team_id"].astype(str).tolist()
                )
            else:
                ranked_team_ids = teams_combined["team_id"].astype(str).tolist()
            # Prior published rank + the cohort the team held in that snapshot, so a team that
            # aged up since only matches its prior cohort and is skipped (falls back to its
            # current-run rank). days_ago=7 = the prior weekly snapshot; reference_date honors
            # the run's `today` so replay/backfill freezes against the replayed week.
            frozen_rank_lookup = await get_prior_cohort_ranks(
                supabase_client, ranked_team_ids, days_ago=7, reference_date=_normalize_snapshot_date(today)
            )
        evidence_df = _compute_same_age_evidence_metrics(games_df, teams_combined, frozen_rank_lookup)
        teams_combined = teams_combined.merge(evidence_df, on="team_id", how="left")

        for col in [
            "same_age_games",
            "same_age_game_share",
            "same_age_unique_opponents",
            "same_age_top100_opp_count",
            "same_age_top100_non_loss_opp_count",
            "same_age_top500_opp_count",
            "same_age_top500_non_loss_opp_count",
            "same_age_top1000_non_loss_opp_count",
            "play_up_games",
            "play_up_game_share",
            "play_up_unique_opponents",
            "play_up_top100_opp_count",
            "play_up_top500_opp_count",
            "play_up_top500_non_loss_opp_count",
            "play_up_top1000_non_loss_opp_count",
            "repeat_opponent_share",
        ]:
            if col in teams_combined.columns:
                teams_combined[col] = pd.to_numeric(teams_combined[col], errors="coerce").fillna(0.0)
        if "same_age_avg_opp_power_adj" in teams_combined.columns:
            teams_combined["same_age_avg_opp_power_adj"] = pd.to_numeric(
                teams_combined["same_age_avg_opp_power_adj"], errors="coerce"
            )
        if "play_up_avg_opp_power_adj" in teams_combined.columns:
            teams_combined["play_up_avg_opp_power_adj"] = pd.to_numeric(
                teams_combined["play_up_avg_opp_power_adj"], errors="coerce"
            )

        teams_combined["positive_ml_evidence_scale"] = teams_combined.apply(_positive_ml_evidence_scale, axis=1)
        teams_combined["publication_cap_rank"] = teams_combined.apply(_publication_cap_rank, axis=1)
        teams_combined["play_up_bonus"] = teams_combined.apply(_play_up_bonus, axis=1)
        teams_combined["publication_cap_score"] = pd.NA

        ps_ml_series = pd.to_numeric(teams_combined.get("powerscore_ml"), errors="coerce")
        ps_adj_series = pd.to_numeric(teams_combined.get("powerscore_adj"), errors="coerce")
        ml_blocked = ((teams_combined["positive_ml_evidence_scale"] <= 0.0) & (ps_ml_series > ps_adj_series)).sum()
        capped = pd.to_numeric(teams_combined["publication_cap_rank"], errors="coerce").notna().sum()
        logger.info(
            f"🧱 Same-age evidence gates prepared: ml_blocked={int(ml_blocked)}, publication_capped={int(capped)}"
        )

    # ========== National SOS Metrics (for display only) ==========
    # NOTE: PowerScore uses cohort-level sos_norm from v53e.compute_rankings().
    # National/state SOS metrics (sos_norm_national, sos_rank_national, etc.) are
    # computed here for display and diagnostic purposes only - they do NOT affect rankings.
    # This preserves the principle that teams are ranked within their cohort (age/gender).

    # The following block is intentionally disabled to keep PowerScore cohort-based.
    # If you want to enable national SOS in PowerScore, uncomment this block.
    """
    # ========== DISABLED: Recompute PowerScore with National SOS ==========
    if not teams_combined.empty and 'sos_norm_national' in teams_combined.columns:
        logger.info("🔄 Recomputing PowerScore with national SOS normalization...")

        cfg = v53_cfg or V53EConfig()

        teams_combined["powerscore_core"] = (
            cfg.OFF_WEIGHT * teams_combined["off_norm"]
            + cfg.DEF_WEIGHT * teams_combined["def_norm"]
            + cfg.SOS_WEIGHT * teams_combined["sos_norm_national"]
            + teams_combined["perf_centered"] * cfg.PERF_BLEND_WEIGHT
        )

        teams_combined["powerscore_adj"] = (
            teams_combined["powerscore_core"] * teams_combined["provisional_mult"]
        )

        anchor_ref = teams_combined.groupby("gender")["anchor"].transform("max")
        anchor_ref = anchor_ref.replace(0, 1.0).fillna(1.0)

        teams_combined["powerscore_adj"] = (
            teams_combined["powerscore_adj"] * teams_combined["anchor"] / anchor_ref
        ).clip(0.0, 1.0)

        if 'powerscore_ml' in teams_combined.columns and 'ml_norm' in teams_combined.columns:
            ml_alpha = layer13_cfg.alpha if layer13_cfg else 0.08
            teams_combined["powerscore_ml"] = (
                teams_combined["powerscore_adj"] + ml_alpha * teams_combined["ml_norm"]
            ).clip(0.0, 1.0)

            teams_combined["powerscore_ml"] = (
                teams_combined["powerscore_ml"] * teams_combined["anchor"] / anchor_ref
            ).clip(0.0, 1.0)

        powerscore_max = teams_combined.groupby(["age", "gender"])["powerscore_adj"].max().round(3)
        logger.info("  PowerScore max (per age/gender) after national SOS recalculation:")
        for (age, gender), ps_max in powerscore_max.items():
            logger.info(f"    {age} {gender}: max_powerscore_adj={ps_max:.3f}")
    """

    # Diagnostic: Log distribution stats for sos_norm and powerscore_adj per cohort
    if save_snapshot and not teams_combined.empty:
        logger.info("📊 Distribution diagnostics per age/gender cohort:")
        for (age, gender), cohort_df in teams_combined.groupby(["age", "gender"]):
            if "sos_norm" in cohort_df.columns:
                sos_stats = cohort_df["sos_norm"]
                logger.info(
                    f"    {age} {gender}: sos_norm min={sos_stats.min():.3f}, "
                    f"max={sos_stats.max():.3f}, mean={sos_stats.mean():.3f}"
                )
            if "powerscore_adj" in cohort_df.columns:
                ps_stats = cohort_df["powerscore_adj"]
                logger.info(
                    f"    {age} {gender}: powerscore_adj min={ps_stats.min():.3f}, "
                    f"max={ps_stats.max():.3f}, mean={ps_stats.mean():.3f}"
                )

    # ---- Final age-anchor scaling for PowerScore ----
    if not teams_combined.empty:
        from src.rankings.constants import AGE_TO_ANCHOR, SOS_ML_THRESHOLD_HIGH, SOS_ML_THRESHOLD_LOW
        from src.rankings.shared import sos_ml_blend

        if "age_num" not in teams_combined.columns:
            logger.warning("⚠️ compute_all_cohorts: 'age_num' column missing; skipping anchor scaling")
        else:
            # age_num is already integer from data adapter
            age_nums = teams_combined["age_num"]

            # Log age distribution
            logger.info("📊 Applying anchor scaling by age. Age distribution: %s", age_nums.value_counts().to_dict())

            # Initialize output columns
            if "power_score_final" not in teams_combined.columns:
                teams_combined["power_score_final"] = None
            if "power_score_true" not in teams_combined.columns:
                teams_combined["power_score_true"] = None

            # Process each age group separately
            for age, anchor_val in AGE_TO_ANCHOR.items():
                mask = age_nums == age
                if not mask.any():
                    continue

                teams_age = teams_combined.loc[mask].copy()

                # =================================================================
                # SOS-CONDITIONED ML SCALING
                # =================================================================
                # Rule: powerscore_adj is ALWAYS the baseline (truth).
                # ML can only adjust if schedule is strong enough.
                # ml_scale = 0 when sos_norm < 0.45, scales to 1 when sos_norm >= 0.60
                # =================================================================

                # Step 1: Get baseline (powerscore_adj is REQUIRED)
                if "powerscore_adj" not in teams_age.columns or not teams_age["powerscore_adj"].notna().any():
                    logger.warning(f"⚠️  Age {age}: powerscore_adj not available, skipping")
                    continue

                ps_adj = teams_age["powerscore_adj"].clip(0.0, 1.0)

                # Step 2: Calculate ML delta (if ML available)
                has_ml = "powerscore_ml" in teams_age.columns and teams_age["powerscore_ml"].notna().any()
                has_sos = "sos_norm" in teams_age.columns and teams_age["sos_norm"].notna().any()

                if has_ml and has_sos:
                    # Vectorized form of sos_ml_blend() (shared.py) for Series performance
                    ps_ml = teams_age["powerscore_ml"].clip(0.0, 1.0)
                    ml_delta = ps_ml - ps_adj

                    # Step 3: Scale ML authority by schedule strength
                    # Weak schedule (sos_norm < 0.45) → ML has no authority for positive corrections
                    # Strong schedule (sos_norm >= 0.60) → ML has full authority
                    sos_norm = teams_age["sos_norm"].fillna(0.5)
                    ml_scale = (
                        (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)
                    ).clip(0.0, 1.0)

                    # Negative ML corrections always apply at full authority.
                    # Positive corrections (inflation) are still fully gated by SOS.
                    positive_ml_evidence_scale = pd.to_numeric(
                        teams_age.get("positive_ml_evidence_scale", 1.0), errors="coerce"
                    ).fillna(1.0)
                    ml_scale_effective = np.where(ml_delta >= 0, ml_scale * positive_ml_evidence_scale, 1.0)

                    # Step 4: Final score = baseline + SOS-scaled ML adjustment
                    base = (ps_adj + ml_delta * ml_scale_effective).clip(0.0, 1.0)

                    # Log statistics for monitoring
                    avg_ml_scale = ml_scale.mean()
                    ml_adjusted_count = (ml_scale > 0).sum()
                    evidence_gated_count = ((ml_delta > 0) & (positive_ml_evidence_scale < 1.0)).sum()
                    logger.info(
                        f"  📊 Age {age}: ML scaling applied - avg_scale={avg_ml_scale:.3f}, "
                        f"teams_with_ml_authority={ml_adjusted_count}/{len(teams_age)}, "
                        f"evidence_gated_positive_ml={int(evidence_gated_count)}"
                    )
                else:
                    # No ML or no SOS available - use baseline directly
                    base = ps_adj
                    if not has_ml:
                        logger.info(f"  📊 Age {age}: No ML data, using powerscore_adj directly")
                    elif not has_sos:
                        logger.info(f"  📊 Age {age}: No SOS data, using powerscore_adj directly")

                raw_shrink = teams_age.apply(_same_age_raw_shrink, axis=1)
                if (raw_shrink > 0).any():
                    base = (base - raw_shrink).clip(0.0, 1.0)
                    logger.info(
                        f"  📊 Age {age}: weak-field raw shrink applied to "
                        f"{int((raw_shrink > 0).sum())} team(s), "
                        f"avg_shrink={float(raw_shrink[raw_shrink > 0].mean()):.4f}, "
                        f"max_shrink={float(raw_shrink.max()):.4f}"
                    )

                if "play_up_bonus" in teams_age.columns:
                    play_up_bonus = pd.to_numeric(teams_age["play_up_bonus"], errors="coerce").fillna(0.0)
                    if (play_up_bonus > 0).any():
                        base = (base + play_up_bonus).clip(0.0, 1.0)
                        logger.info(
                            f"  ðŸ“Š Age {age}: play-up evidence bonus applied to "
                            f"{int((play_up_bonus > 0).sum())} team(s), "
                            f"avg_bonus={float(play_up_bonus[play_up_bonus > 0].mean()):.4f}, "
                            f"max_bonus={float(play_up_bonus.max()):.4f}"
                        )

                publish_penalty = teams_age.apply(_same_age_publish_penalty, axis=1)
                if (publish_penalty > 0).any():
                    base = (base - publish_penalty).clip(0.0, 1.0)
                    logger.info(
                        f"  📊 Age {age}: same-age skepticism penalty applied to "
                        f"{int((publish_penalty > 0).sum())} team(s), "
                        f"avg_penalty={float(publish_penalty[publish_penalty > 0].mean()):.4f}, "
                        f"max_penalty={float(publish_penalty.max()):.4f}"
                    )

                if "publication_cap_rank" in teams_age.columns:
                    teams_age["publication_cap_score"] = _compute_publication_cap_scores(teams_age, base)
                    if pd.to_numeric(teams_age["publication_cap_score"], errors="coerce").notna().any():
                        teams_combined.loc[teams_age.index, "publication_cap_score"] = teams_age[
                            "publication_cap_score"
                        ]

                # Hard publication cap for weak same-age evidence.
                if "publication_cap_score" in teams_age.columns:
                    cap_scores = pd.to_numeric(teams_age["publication_cap_score"], errors="coerce")
                    cap_mask = cap_scores.notna()
                    if cap_mask.any():
                        base = _apply_publication_cap_band(base, teams_age)
                        _validate_publication_caps(teams_age, base)
                        logger.info(
                            f"  📊 Age {age}: publication cap band applied to "
                            f"{int(cap_mask.sum())} team(s) on weak same-age evidence"
                        )
                        top_tier_weak = _collect_top_tier_weak_uncapped(teams_age, base)
                        if not top_tier_weak.empty:
                            detail_parts = []
                            for row in top_tier_weak.itertuples(index=False):
                                team_name = getattr(row, "team_name", None)
                                label = team_name if isinstance(team_name, str) and team_name else row.team_id
                                detail_parts.append(
                                    f"{label}({row.team_id})"
                                    f" rank={int(row.provisional_rank)}"
                                    f" top500={int(_safe_int(row.same_age_top500_opp_count))}"
                                    f" avg_opp={float(row.same_age_avg_opp_power_adj):.3f}"
                                )
                            details = "; ".join(detail_parts)
                            logger.warning(
                                "⚠️ Age %s: weak same-age teams remain uncapped in the top tier: %s",
                                age,
                                details,
                            )

                # Scale by anchor and clip to [0, anchor_val]
                ps_scaled = (base * anchor_val).clip(0.0, anchor_val)

                logger.info(
                    "📊 Age %s: anchor %.3f, base max %.4f -> scaled max %.4f",
                    age,
                    anchor_val,
                    base.max(),
                    ps_scaled.max(),
                )

                # Save unanchored competitive score (single source of truth)
                teams_combined.loc[ps_scaled.index, "power_score_true"] = base

                # Apply anchor (sole application point)
                teams_combined.loc[ps_scaled.index, "power_score_final"] = ps_scaled

            # Check for teams that didn't get anchor scaling (ages outside 10-19 range)
            if "power_score_final" in teams_combined.columns:
                unscaled_mask = teams_combined["power_score_final"].isna()
                unscaled_count = unscaled_mask.sum()
                if unscaled_count > 0:
                    logger.warning(f"⚠️ {unscaled_count} teams didn't match any anchor age - applying fallback scaling")
                    # For teams outside age range, use median anchor (0.70) and apply scaling
                    # Also apply SOS-conditioned ML scaling (same thresholds as main loop)
                    fallback_anchor = 0.70

                    for idx in teams_combined[unscaled_mask].index:
                        row = teams_combined.loc[idx]

                        # powerscore_adj is REQUIRED - skip if not available
                        if "powerscore_adj" not in teams_combined.columns or pd.isna(row.get("powerscore_adj")):
                            logger.warning(f"⚠️ Team {idx}: powerscore_adj not available, skipping fallback")
                            continue

                        ps_adj = float(row["powerscore_adj"])

                        # Apply SOS-conditioned ML scaling (same logic as main loop)
                        has_ml = "powerscore_ml" in teams_combined.columns and pd.notna(row.get("powerscore_ml"))
                        has_sos = "sos_norm" in teams_combined.columns and pd.notna(row.get("sos_norm"))

                        if has_ml and has_sos:
                            base_score = sos_ml_blend(ps_adj, float(row["powerscore_ml"]), float(row["sos_norm"]))
                        else:
                            base_score = ps_adj

                        base_score = max(0.0, min(1.0, base_score))
                        teams_combined.loc[idx, "power_score_true"] = base_score
                        teams_combined.loc[idx, "power_score_final"] = min(
                            base_score * fallback_anchor, fallback_anchor
                        )

                # Verify all teams have anchor-scaled power_score_final
                still_null = teams_combined["power_score_final"].isna().sum()
                if still_null > 0:
                    logger.error(f"❌ {still_null} teams still have NULL power_score_final after anchor scaling!")

            # Ensure power_score_true is numeric (initialized as None → object dtype)
            if "power_score_true" in teams_combined.columns:
                teams_combined["power_score_true"] = pd.to_numeric(teams_combined["power_score_true"], errors="coerce")

            # === MANDATORY: power_score_true bounds check ===
            if "power_score_true" in teams_combined.columns:
                pst = teams_combined["power_score_true"].dropna()
                if len(pst) > 0:
                    if pst.min() < 0 or pst.max() > 1.0:
                        violations = ((pst < 0) | (pst > 1.0)).sum()
                        logger.error(
                            f"❌ power_score_true out of [0,1] bounds: {violations} violations, "
                            f"min={pst.min():.6f}, max={pst.max():.6f}"
                        )
                    else:
                        logger.info(f"✅ power_score_true bounds: [{pst.min():.4f}, {pst.max():.4f}]")

            # === MANDATORY: Anchor integrity validation ===
            if "power_score_true" in teams_combined.columns:
                logger.info("🔒 Anchor integrity validation:")
                for age_val in sorted(AGE_TO_ANCHOR.keys()):
                    mask = teams_combined["age_num"] == age_val
                    if not mask.any():
                        continue
                    subset = teams_combined.loc[mask]
                    anchor_val = AGE_TO_ANCHOR[age_val]
                    expected = (subset["power_score_true"] * anchor_val).clip(0.0, anchor_val)
                    actual = subset["power_score_final"]
                    max_diff = (expected - actual).abs().max()
                    if max_diff >= 0.001:
                        raise ValueError(
                            f"❌ ANCHOR INTEGRITY FAILURE: Age {age_val}, max diff={max_diff:.6f}. "
                            f"power_score_final must equal power_score_true * anchor."
                        )
                    logger.info(f"  Age {age_val}: anchor={anchor_val}, max_diff={max_diff:.6f} ✅")

            # === MANDATORY: Monotonicity guarantee ===
            # Within a single cohort (same age/gender), all teams share the same anchor.
            # Multiplying all scores by the same constant preserves order — but floating-point
            # precision at the clip boundary (base near 1.0) can create micro-inversions.
            # Fix: recompute power_score_final directly from power_score_true * anchor to
            # guarantee identical ordering, eliminating any accumulated float drift from
            # the intermediate computation path.
            if "power_score_true" in teams_combined.columns and "gender" in teams_combined.columns:
                logger.info("🔒 Monotonicity enforcement (recompute power_score_final from power_score_true):")
                for (age_val, gender), grp in teams_combined.groupby(["age_num", "gender"]):
                    if len(grp) < 2:
                        continue
                    anchor_val = AGE_TO_ANCHOR.get(int(age_val), 0.70)
                    pst = grp["power_score_true"].fillna(0.0)
                    psf_recomputed = (pst * anchor_val).clip(0.0, anchor_val)
                    # Overwrite power_score_final to guarantee monotonicity
                    teams_combined.loc[grp.index, "power_score_final"] = psf_recomputed
                    logger.info(f"  {age_val} {gender}: {len(grp)} teams, monotonicity enforced ✅")

            # === PUBLISHED RANK: canonical ordering by power_score_true DESC, team_id ASC ===
            # power_score_true is unanchored, so within an (age, gender) cohort it produces
            # the same ordering as power_score_final (anchor is a constant multiplier).
            # team_id ASC is the deterministic tie-break (matches UI sort behavior).
            #
            # NOTE: The SQL views remap age 18 → 19 (U19 encompasses 2007+2008 birth years).
            # The calculator ranks by raw age_num (before remap), so U18 and U19 are ranked
            # as separate cohorts here. The view layer merges them for display.
            if "power_score_true" in teams_combined.columns:
                teams_combined["rank_in_cohort_final"] = pd.array([pd.NA] * len(teams_combined), dtype="Int64")
                active_mask = teams_combined["status"] == "Active"
                if active_mask.any():
                    for (age_val, gender), grp in teams_combined[active_mask].groupby(["age_num", "gender"]):
                        ranked = grp.sort_values(
                            ["power_score_true", "team_id"],
                            ascending=[False, True],
                        )
                        ranks = pd.Series(
                            range(1, len(ranked) + 1),
                            index=ranked.index,
                            dtype="Int64",
                        )
                        teams_combined.loc[ranks.index, "rank_in_cohort_final"] = ranks
                    logger.info(f"  Published rank_in_cohort_final computed for {active_mask.sum()} Active teams")

                # Compute rank-change deltas inside the rank_in_cohort_final guard so both
                # sides of the diff resolve to the published final rank, not rank_in_cohort_ml.
                if calculate_rank_changes_enabled:
                    logger.info("📊 Calculating rank changes from historical data...")
                    with _section(timing_report, "rank_changes"):
                        teams_combined = await calculate_rank_changes(
                            supabase_client=supabase_client,
                            current_rankings_df=teams_combined,
                            reference_date=_normalize_snapshot_date(today),
                        )

            # === Anchor integrity sample (top 3 per age group) ===
            if "power_score_true" in teams_combined.columns:
                logger.info("📊 Anchor integrity sample (top 3 per age):")
                for age_val in [10, 12, 14, 16, 19]:
                    mask = (teams_combined["age_num"] == age_val) & teams_combined["power_score_true"].notna()
                    if not mask.any():
                        continue
                    sample = teams_combined.loc[mask].nlargest(3, "power_score_true")
                    anchor_val = AGE_TO_ANCHOR.get(age_val, 0.70)
                    for _, row in sample.iterrows():
                        logger.info(
                            f"  Age {age_val}: power_score_true={row['power_score_true']:.4f}, "
                            f"power_score_final={row['power_score_final']:.4f}, "
                            f"anchor={anchor_val:.3f}, "
                            f"expected_final={row['power_score_true'] * anchor_val:.4f}"
                        )

    # 🔒 Ensure PowerScore is fully clipped to [0, 1] after all operations
    if not teams_combined.empty:
        cols_to_clip = ["powerscore_core", "powerscore_adj", "powerscore_ml", "power_score_final"]
        for col in cols_to_clip:
            if col in teams_combined.columns:
                before_min = teams_combined[col].min()
                before_max = teams_combined[col].max()
                teams_combined[col] = teams_combined[col].clip(0.0, 1.0)
                after_min = teams_combined[col].min()
                after_max = teams_combined[col].max()
                if before_min < 0.0 or before_max > 1.0:
                    logger.info(
                        f"  🔒 Clipped {col}: [{before_min:.4f}, {before_max:.4f}] → [{after_min:.4f}, {after_max:.4f}]"
                    )

    # Save one combined snapshot for all cohorts
    if save_snapshot and not teams_combined.empty:
        logger.info("💾 Saving combined ranking snapshot for all cohorts...")
        await save_ranking_snapshot(
            supabase_client=supabase_client,
            rankings_df=teams_combined,
            snapshot_date=_normalize_snapshot_date(today),
        )
        await _save_prediction_feature_snapshot_safe(
            supabase_client=supabase_client,
            rankings_df=teams_combined,
            snapshot_date=_normalize_snapshot_date(today),
        )

    logger.info(f"✅ Two-pass rankings flow complete: {len(teams_combined):,} teams ranked")

    return {
        "teams": teams_combined,
        "games_used": games_used_combined,
        "game_explainability": game_explainability_combined,
    }
