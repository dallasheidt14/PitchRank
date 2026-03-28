"""Integrated Rankings Calculator (v53e + ML Layer)"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Tuple

import pandas as pd

from src.etl.v53e import V53EConfig, compute_rankings
from src.rankings.data_adapter import fetch_games_for_rankings
from src.rankings.layer13_predictive_adjustment import Layer13Config, apply_predictive_adjustment
from src.rankings.ranking_history import calculate_rank_changes, save_ranking_snapshot

if TYPE_CHECKING:
    from src.profiling.timer import TimingReport

logger = logging.getLogger(__name__)


def _section(timing_report: Optional["TimingReport"], name: str, **metadata):
    """Return a timing section context manager, or a no-op if profiling is off."""
    if timing_report is not None:
        return timing_report.section(name, **metadata)
    return nullcontext()


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
            {"id": str(row["game_id"]), "ml_overperformance": float(row["ml_overperformance"])}
            for _, row in batch.iterrows()
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
            f"⚠️ Residual persistence partial: {total_updated:,} updated, {failed_count:,} failed out of {len(game_residuals):,}"
        )
    else:
        logger.info(f"✅ Successfully updated {total_updated:,} games with ML residuals")

    return (total_updated, failed_count)


async def compute_rankings_with_ml(
    supabase_client,
    games_df: Optional[pd.DataFrame] = None,  # Optional: pass games directly
    today: Optional[pd.Timestamp] = None,
    v53_cfg: Optional[V53EConfig] = None,
    layer13_cfg: Optional[Layer13Config] = None,
    fetch_from_supabase: bool = True,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
    force_rebuild: bool = False,
    save_snapshot: bool = True,  # Set to False when called from compute_all_cohorts
    global_strength_map: Optional[Dict] = None,  # For cross-age SOS lookups
    merge_version: Optional[str] = None,  # For cache invalidation when merges change
    team_state_map: Optional[Dict[str, str]] = None,  # For SCF regional bubble detection
    timing_report: Optional["TimingReport"] = None,
    pass_label: Optional[str] = None,  # "Pass1" or "Pass2" for log disambiguation
    pre_sos_state: Optional[Dict] = None,  # Cached state from Pass 1 for two-pass optimization
) -> Dict[str, pd.DataFrame]:
    """
    Runs your deterministic v53E engine, then applies the Supabase-aware ML adjustment.

    Args:
        supabase_client: Supabase client instance
        games_df: Optional pre-fetched games DataFrame (in v53e format)
        today: Reference date for rankings
        v53_cfg: v53e configuration
        layer13_cfg: ML layer configuration
        fetch_from_supabase: If True and games_df is None, fetch from Supabase
        lookback_days: Days to look back for rankings
        provider_filter: Optional provider code filter
        merge_version: Version hash from MergeResolver for cache invalidation
        team_state_map: Optional dict of team_id -> state_code for SCF calculation

    Returns:
        {
            "teams": teams_df_with_ml,
            "games_used": games_used_df
        }
    """
    v53_cfg = v53_cfg or V53EConfig()

    # 1) Get games data
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            logger.info("🔍 Fetching games from Supabase...")
            with _section(timing_report, "fetch_games"):
                games_df = await fetch_games_for_rankings(
                    supabase_client=supabase_client,
                    lookback_days=lookback_days,
                    provider_filter=provider_filter,
                    today=today,
                )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")

    if games_df.empty:
        logger.warning("⚠️  No games found - returning empty results")
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame()}

    logger.info(f"📊 Computing rankings for {len(games_df):,} game perspectives...")

    # 2) Check cache before running v53e rankings engine
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Generate hash key from ALL game IDs (not just first 1000 - that caused stale cache issues)
    # Include merge_version to invalidate cache when team merges change
    game_ids = games_df["game_id"].astype(str).tolist() if "game_id" in games_df.columns else []
    hash_input = "".join(sorted(game_ids)) + str(lookback_days) + (provider_filter or "")
    # Only include merge_version when merges actually exist (not "no_merges")
    # This ensures cache key stays identical when no merges are configured
    if merge_version and merge_version != "no_merges":
        hash_input += f"_merge_{merge_version}"
    cache_key = hashlib.md5(hash_input.encode()).hexdigest()  # MD5 for cache key only (not security)
    cache_file_teams = cache_dir / f"rankings_{cache_key}_teams.parquet"
    cache_file_games = cache_dir / f"rankings_{cache_key}_games.parquet"

    # Try to load from cache (both teams and games_used)
    base = None
    if not force_rebuild and cache_file_teams.exists():
        try:
            cached_teams = pd.read_parquet(cache_file_teams)
            if not cached_teams.empty:
                # Cache hit - load both teams and games_used, skip v53e entirely
                cached_games_used = pd.DataFrame()
                if cache_file_games.exists():
                    try:
                        cached_games_used = pd.read_parquet(cache_file_games)
                    except Exception:
                        pass  # games_used cache failed, use empty
                base = {"teams": cached_teams, "games_used": cached_games_used}
        except Exception:
            # Cache load failed - continue with computation
            pass

    # 2) Run v53e rankings engine (if not cached)
    if base is None:
        logger.info(f"🔁 Rebuilding v53e rankings from raw data... (force_rebuild={force_rebuild})")
        with _section(timing_report, "v53e_computation"):
            base = compute_rankings(
                games_df=games_df,
                today=today,
                cfg=v53_cfg,
                global_strength_map=global_strength_map,
                team_state_map=team_state_map,  # For SCF regional bubble detection
                pass_label=pass_label,
                pre_sos_state=pre_sos_state,
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
        except Exception:
            # Cache save failed - continue without caching
            pass
    else:
        logger.info("💾 Using cached v53e rankings")

    teams_base = base["teams"]
    games_used = base.get("games_used")
    _pre_sos_state = base.get("pre_sos_state")

    if teams_base.empty:
        return {
            "teams": teams_base,
            "games_used": games_used if not getattr(games_used, "empty", True) else pd.DataFrame(),
        }

    # Log PowerScore summary before ML layer
    if not teams_base.empty and "powerscore_adj" in teams_base.columns:
        ps_stats = teams_base["powerscore_adj"]
        logger.info(
            f"📊 Pre-ML PowerScore: min={ps_stats.min():.3f}, max={ps_stats.max():.3f}, mean={ps_stats.mean():.3f}, n={len(teams_base)}"
        )

    # 3) Apply ML predictive adjustment
    logger.info("🤖 Applying ML predictive adjustment layer...")
    logger.debug(
        f"games_df: {len(games_df)} rows, has_id={'id' in games_df.columns}, has_home_master={'home_team_master_id' in games_df.columns}"
    )

    ml_cfg = layer13_cfg or Layer13Config(
        lookback_days=v53_cfg.WINDOW_DAYS,
        alpha=0.08,  # Tuned via weight simulator grid search: 0.08 optimal (quality 14→19/23)
        norm_mode="zscore",
        min_team_games_for_residual=6,
        recency_decay_lambda=0.06,  # Short-term form focus; tune later after stability verified
        table_name="games",
        provider_filter=provider_filter,
    )

    with _section(timing_report, "ml_layer_13"):
        teams_with_ml, game_residuals = await apply_predictive_adjustment(
            supabase_client=supabase_client,
            teams_df=teams_base,
            games_used_df=games_df,  # Use original games with full columns (id, home_team_master_id)
            cfg=ml_cfg,
            return_game_residuals=True,  # Request per-game residuals
        )
    logger.info(f"✅ ML adjustment completed: {len(teams_with_ml):,} teams processed")

    # Persist game residuals to database
    with _section(timing_report, "persist_game_residuals"):
        if not game_residuals.empty:
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

    # Calculate rank changes using historical snapshots (7d and 30d)
    logger.info("📊 Calculating rank changes from historical data...")
    with _section(timing_report, "rank_changes"):
        teams_with_ml = await calculate_rank_changes(supabase_client=supabase_client, current_rankings_df=teams_with_ml)

    # Save current rankings as a snapshot for future rank change calculations
    # (Skip if save_snapshot=False, e.g., when called from compute_all_cohorts)
    if save_snapshot and not teams_with_ml.empty:
        logger.info("💾 Saving ranking snapshot for future comparisons...")
        with _section(timing_report, "save_ranking_snapshot"):
            await save_ranking_snapshot(supabase_client=supabase_client, rankings_df=teams_with_ml)

    return {
        "teams": teams_with_ml,
        "games_used": games_used if not getattr(games_used, "empty", True) else pd.DataFrame(),
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
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame()}

    logger.info(f"📊 Computing v53e rankings for {len(games_df):,} game perspectives...")

    # Run v53e rankings engine
    logger.info("⚙️  Running v53e rankings engine...")
    with _section(timing_report, "v53e_computation"):
        result = compute_rankings(
            games_df=games_df,
            today=today,
            cfg=v53_cfg,
            team_state_map=team_state_map,  # For SCF regional bubble detection
        )
    logger.info(f"✅ v53e engine completed: {len(result['teams']):,} teams ranked")

    return result


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
) -> Dict[str, pd.DataFrame]:
    """
    Compute rankings for all cohorts using two-pass architecture.

    Pass 1: Run each cohort to get initial abs_strength values
    Pass 2: Re-run with global_strength_map for accurate cross-age SOS

    This ensures cross-age opponents get their real strength instead of 0.35.

    Args:
        merge_resolver: Optional MergeResolver instance for resolving merged teams
    """
    # Default config if not provided
    v53_cfg = v53_cfg or V53EConfig()

    # Get merge version for cache invalidation
    merge_version = merge_resolver.version if merge_resolver else None

    # Get games data if not provided
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            with _section(timing_report, "fetch_games"):
                games_df = await fetch_games_for_rankings(
                    supabase_client=supabase_client,
                    lookback_days=lookback_days,
                    provider_filter=provider_filter,
                    today=today,
                    merge_resolver=merge_resolver,  # Apply merge resolution
                )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")

    if games_df.empty:
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame()}

    # ========== FETCH TEAM STATE METADATA FOR SCF ==========
    # Fetch state_code for all teams to enable Schedule Connectivity Factor (SCF)
    # which detects and dampens regional bubbles (e.g., Idaho teams only playing each other)
    team_ids = set()
    team_ids.update(games_df["team_id"].dropna().astype(str).tolist())
    team_ids.update(games_df["opp_id"].dropna().astype(str).tolist())

    team_state_map = {}
    with _section(timing_report, "team_state_map"):
        if team_ids:
            logger.info(f"🗺️  Fetching state metadata for {len(team_ids):,} teams (for SCF)...")
            team_ids_list = list(team_ids)
            batch_size = 100

            def _fetch_state_batch_sync(batch):
                try:
                    result = (
                        supabase_client.table("teams")
                        .select("team_id_master, state_code")
                        .in_("team_id_master", batch)
                        .execute()
                    )
                    return result.data or []
                except Exception as e:
                    logger.warning(f"⚠️ Failed to fetch state metadata batch: {str(e)[:100]}")
                    return []

            batches = [
                team_ids_list[i : i + batch_size]
                for i in range(0, len(team_ids_list), batch_size)
            ]
            # Run batches concurrently in groups of 5 via thread pool
            for group_start in range(0, len(batches), 5):
                group = batches[group_start : group_start + 5]
                results = await asyncio.gather(
                    *[asyncio.to_thread(_fetch_state_batch_sync, b) for b in group]
                )
                for rows in results:
                    for row in rows:
                        team_id = str(row.get("team_id_master", ""))
                        state_code = row.get("state_code", "UNKNOWN")
                        if team_id:
                            team_state_map[team_id] = state_code if state_code else "UNKNOWN"

            # Count states for logging
            state_counts = {}
            for state in team_state_map.values():
                state_counts[state] = state_counts.get(state, 0) + 1
            top_states = sorted(state_counts.items(), key=lambda x: -x[1])[:5]
            logger.info(f"✅ Fetched state_code for {len(team_state_map):,} teams. Top states: {dict(top_states)}")
        else:
            logger.warning("⚠️ No team IDs found for state metadata fetch - SCF will be disabled")

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
            f"🚫 Quarantining {invalid_age_mask.sum():,} game rows with ages outside {VALID_AGE_MIN}–{VALID_AGE_MAX}: {invalid_age_counts}"
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
        return {"teams": pd.DataFrame(), "games_used": pd.DataFrame()}

    # Group by (age, gender) cohorts
    cohorts = list(games_df.groupby(["age", "gender"]))
    logger.info(f"🔄 Two-pass SOS: Processing {len(cohorts)} cohorts")

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
            force_rebuild=force_rebuild,
            save_snapshot=False,
            global_strength_map=None,  # No global map yet
            merge_version=merge_version,  # For cache invalidation
            team_state_map=team_state_map,  # For SCF regional bubble detection
            pass_label="Pass1",
        )
        pass1_tasks.append(task)

    with _section(timing_report, "pass1_all_cohorts"):
        pass1_results = await asyncio.gather(*pass1_tasks)

    # Build global strength map and collect pre-SOS state from Pass 1
    global_strength_map = {}
    pass1_pre_sos_states = {}
    for i, result in enumerate(pass1_results):
        if not result["teams"].empty:
            teams_df = result["teams"]
            if "abs_strength" in teams_df.columns:
                strength_dict = dict(zip(
                    teams_df["team_id"].astype(str),
                    teams_df["abs_strength"].astype(float),
                ))
                global_strength_map.update(strength_dict)
        # Cache pre-SOS state keyed by cohort index
        if result.get("pre_sos_state"):
            pass1_pre_sos_states[i] = result["pre_sos_state"]

    logger.info(
        f"🌍 Built global strength map with {len(global_strength_map):,} teams, "
        f"cached {len(pass1_pre_sos_states)} pre-SOS states"
    )

    # ========== PASS 2: Re-run with global strength map ==========
    # Uses cached pre-SOS state from Pass 1 to skip layers 1-5 (~50% speedup)
    logger.info("📊 Pass 2: Re-computing SOS with global strength map (skipping layers 1-5)...")
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
            force_rebuild=True,  # Force rebuild to use new global map
            save_snapshot=False,
            global_strength_map=global_strength_map,  # Now with cross-age strengths
            merge_version=merge_version,  # For cache invalidation
            team_state_map=team_state_map,  # For SCF regional bubble detection
            pass_label="Pass2",
            pre_sos_state=pass1_pre_sos_states.get(i),  # Skip layers 1-5
        )
        pass2_tasks.append(task)

    with _section(timing_report, "pass2_all_cohorts"):
        pass2_results = await asyncio.gather(*pass2_tasks)

    # Merge results from Pass 2
    with _section(timing_report, "merge_and_filter"):
        all_teams = []
        all_games_used = []

        for result in pass2_results:
            if not result["teams"].empty:
                all_teams.append(result["teams"])
            if not result.get("games_used", pd.DataFrame()).empty:
                all_games_used.append(result["games_used"])

        # Combine results
        teams_combined = pd.concat(all_teams, ignore_index=True) if all_teams else pd.DataFrame()
        games_used_combined = pd.concat(all_games_used, ignore_index=True) if all_games_used else pd.DataFrame()

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
        total_count = len(teams_combined)
        ranked_national = teams_combined["sos_rank_national"].notna().sum()
        logger.info(
            f"✅ National/State SOS normalization complete: "
            f"sos_norm_national range=[{teams_combined['sos_norm_national'].min():.3f}, {teams_combined['sos_norm_national'].max():.3f}], "
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
    if not teams_combined.empty:
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
                    # Weak schedule (sos_norm < 0.45) → ML has no authority
                    # Strong schedule (sos_norm >= 0.60) → ML has full authority
                    sos_norm = teams_age["sos_norm"].fillna(0.5)
                    ml_scale = (
                        (sos_norm - SOS_ML_THRESHOLD_LOW) / (SOS_ML_THRESHOLD_HIGH - SOS_ML_THRESHOLD_LOW)
                    ).clip(0.0, 1.0)

                    # Step 4: Final score = baseline + SOS-scaled ML adjustment
                    base = (ps_adj + ml_delta * ml_scale).clip(0.0, 1.0)

                    # Log statistics for monitoring
                    avg_ml_scale = ml_scale.mean()
                    ml_adjusted_count = (ml_scale > 0).sum()
                    logger.info(
                        f"  📊 Age {age}: ML scaling applied - avg_scale={avg_ml_scale:.3f}, "
                        f"teams_with_ml_authority={ml_adjusted_count}/{len(teams_age)}"
                    )
                else:
                    # No ML or no SOS available - use baseline directly
                    base = ps_adj
                    if not has_ml:
                        logger.info(f"  📊 Age {age}: No ML data, using powerscore_adj directly")
                    elif not has_sos:
                        logger.info(f"  📊 Age {age}: No SOS data, using powerscore_adj directly")

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
            if "power_score_true" in teams_combined.columns and "gender" in teams_combined.columns:
                logger.info("🔒 Monotonicity validation (anchor must not change intra-cohort order):")
                for (age_val, gender), grp in teams_combined.groupby(["age_num", "gender"]):
                    if len(grp) < 2:
                        continue
                    pst_vals = grp["power_score_true"].dropna()
                    psf_vals = grp["power_score_final"].dropna()
                    if len(pst_vals) < 2 or len(psf_vals) < 2:
                        continue
                    rank_true = pst_vals.rank(ascending=False, method="min")
                    rank_final = psf_vals.loc[rank_true.index].rank(ascending=False, method="min")
                    mismatches = (rank_true != rank_final).sum()
                    if mismatches > 0:
                        raise ValueError(
                            f"❌ MONOTONICITY FAILURE: {age_val} {gender} has {mismatches} rank order "
                            f"changes between power_score_true and power_score_final"
                        )
                    logger.info(f"  {age_val} {gender}: {len(grp)} teams, rank order preserved ✅")

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
    if not teams_combined.empty:
        logger.info("💾 Saving combined ranking snapshot for all cohorts...")
        await save_ranking_snapshot(supabase_client=supabase_client, rankings_df=teams_combined)

    logger.info(f"✅ Two-pass SOS complete: {len(teams_combined):,} teams ranked")

    return {"teams": teams_combined, "games_used": games_used_combined}
