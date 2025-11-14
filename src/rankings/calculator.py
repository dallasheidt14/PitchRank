"""Integrated Rankings Calculator (v53e + ML Layer)"""
from __future__ import annotations

import pandas as pd
from typing import Optional, Dict
from datetime import datetime
import hashlib
import asyncio
from pathlib import Path
import logging

from src.etl.v53e import compute_rankings, V53EConfig
from src.rankings.layer13_predictive_adjustment import (
    apply_predictive_adjustment, Layer13Config
)
from src.rankings.data_adapter import fetch_games_for_rankings

logger = logging.getLogger(__name__)


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
            games_df = await fetch_games_for_rankings(
                supabase_client=supabase_client,
                lookback_days=lookback_days,
                provider_filter=provider_filter,
                today=today
            )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")
    
    if games_df.empty:
        logger.warning("⚠️  No games found - returning empty results")
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame()
        }
    
    logger.info(f"📊 Computing rankings for {len(games_df):,} game perspectives...")
    
    # 2) Check cache before running v53e rankings engine
    cache_dir = Path("data/cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate hash key from game IDs (use first 1000 IDs for performance)
    game_ids_sample = games_df["game_id"].head(1000).astype(str).tolist() if "game_id" in games_df.columns else []
    hash_input = "".join(sorted(game_ids_sample)) + str(lookback_days) + (provider_filter or "")
    cache_key = hashlib.md5(hash_input.encode()).hexdigest()
    cache_file = cache_dir / f"rankings_{cache_key}.parquet"
    
    # Try to load from cache
    base = None
    if not force_rebuild and cache_file.exists():
        try:
            cached_teams = pd.read_parquet(cache_file)
            if not cached_teams.empty:
                # Cache hit - use cached teams, but still need games_used
                # Run v53e to get games_used (or skip if not needed)
                base = compute_rankings(games_df=games_df, today=today, cfg=v53_cfg)
                base["teams"] = cached_teams  # Override with cached teams
        except Exception:
            # Cache load failed - continue with computation
            pass
    
    # 2) Run v53e rankings engine (if not cached)
    if base is None:
        logger.info(f"🔁 Rebuilding v53e rankings from raw data... (force_rebuild={force_rebuild})")
        base = compute_rankings(games_df=games_df, today=today, cfg=v53_cfg)
        logger.info(f"✅ v53e engine completed: {len(base['teams']):,} teams ranked")
        
        # Save to cache (only teams DataFrame)
        try:
            if not base["teams"].empty:
                base["teams"].to_parquet(cache_file, index=False)
                logger.debug(f"💾 Cached rankings to {cache_file}")
        except Exception:
            # Cache save failed - continue without caching
            pass
    else:
        logger.info("💾 Using cached v53e rankings")
    
    teams_base = base["teams"]
    games_used = base.get("games_used")
    
    if teams_base.empty:
        return {
            "teams": teams_base,
            "games_used": games_used if not getattr(games_used, "empty", True) else pd.DataFrame()
        }
    
    # Diagnostic: Log PowerScore max before ML layer
    if not teams_base.empty and "powerscore_adj" in teams_base.columns:
        logger.info("📊 PowerScore max BEFORE ML layer (per age/gender):")
        ps_max_before = teams_base.groupby(["age", "gender"])["powerscore_adj"].max().round(3)
        for (age, gender), ps_max in ps_max_before.items():
            logger.info(f"    {age} {gender}: max_powerscore_adj={ps_max:.3f}")
        
        # Log team counts per cohort for completeness
        team_counts = teams_base.groupby(["age", "gender"]).size()
        logger.info("  Team counts per cohort: %s", team_counts.to_dict())
    
    # 3) Apply ML predictive adjustment
    logger.info("🤖 Applying ML predictive adjustment layer...")
    ml_cfg = layer13_cfg or Layer13Config(
        lookback_days=v53_cfg.WINDOW_DAYS,
        alpha=0.12,
        norm_mode="percentile",
        min_team_games_for_residual=6,
        recency_decay_lambda=0.06,
        table_name="games",
        provider_filter=provider_filter,
    )
    
    teams_with_ml = await apply_predictive_adjustment(
        supabase_client=supabase_client,
        teams_df=teams_base,
        games_used_df=games_used,  # Use games from v53e output
        cfg=ml_cfg,
    )
    logger.info(f"✅ ML adjustment completed: {len(teams_with_ml):,} teams processed")
    
    # Diagnostic: Log PowerScore max after ML layer
    if not teams_with_ml.empty and "powerscore_ml" in teams_with_ml.columns:
        logger.info("📊 PowerScore max AFTER ML layer (per age/gender):")
        ps_max_after = teams_with_ml.groupby(["age", "gender"])["powerscore_ml"].max().round(3)
        for (age, gender), ps_max in ps_max_after.items():
            logger.info(f"    {age} {gender}: max_powerscore_ml={ps_max:.3f}")
        
        # Compare before/after to detect flattening
        if "powerscore_adj" in teams_with_ml.columns:
            logger.info("📈 Anchor scaling preservation check:")
            ps_max_before_ml = teams_with_ml.groupby(["age", "gender"])["powerscore_adj"].max().round(3)
            ps_max_after_ml = teams_with_ml.groupby(["age", "gender"])["powerscore_ml"].max().round(3)
            
            for (age, gender) in ps_max_before_ml.index:
                before = ps_max_before_ml[(age, gender)]
                after = ps_max_after_ml.get((age, gender), 0)
                diff = after - before
                logger.info(f"    {age} {gender}: before={before:.3f}, after={after:.3f}, diff={diff:+.3f}")
    
    # Add rank change tracking (7d and 30d)
    if not teams_with_ml.empty and "rank_in_cohort_ml" in teams_with_ml.columns:
        # Sort by age, gender, team_id, and rank for diff calculation (team_id ensures consistent alignment)
        teams_with_ml = teams_with_ml.sort_values(["age", "gender", "team_id", "rank_in_cohort_ml"]).reset_index(drop=True)
        
        # Calculate rank changes within each cohort
        teams_with_ml["rank_change_7d"] = teams_with_ml.groupby(["age", "gender"])["rank_in_cohort_ml"].diff(7).fillna(0)
        teams_with_ml["rank_change_30d"] = teams_with_ml.groupby(["age", "gender"])["rank_in_cohort_ml"].diff(30).fillna(0)
    else:
        # Add empty columns if rank_in_cohort_ml doesn't exist
        teams_with_ml["rank_change_7d"] = 0
        teams_with_ml["rank_change_30d"] = 0
    
    return {
        "teams": teams_with_ml,
        "games_used": games_used if not getattr(games_used, "empty", True) else pd.DataFrame()
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
) -> Dict[str, pd.DataFrame]:
    """
    Run v53e rankings engine only (without ML layer).
    
    Useful for comparison or when ML is disabled.
    """
    v53_cfg = v53_cfg or V53EConfig()
    
    # Get games data
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            logger.info("🔍 Fetching games from Supabase...")
            games_df = await fetch_games_for_rankings(
                supabase_client=supabase_client,
                lookback_days=lookback_days,
                provider_filter=provider_filter,
                today=today
            )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")
    
    if games_df.empty:
        logger.warning("⚠️  No games found - returning empty results")
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame()
        }
    
    logger.info(f"📊 Computing v53e rankings for {len(games_df):,} game perspectives...")
    
    # Run v53e rankings engine
    logger.info("⚙️  Running v53e rankings engine...")
    result = compute_rankings(games_df=games_df, today=today, cfg=v53_cfg)
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
) -> Dict[str, pd.DataFrame]:
    """
    Compute rankings for all cohorts in parallel.
    
    Groups games_df by (age, gender) and runs compute_rankings_with_ml() concurrently
    for each cohort, then merges results.
    """
    # Get games data if not provided
    if games_df is None or games_df.empty:
        if fetch_from_supabase:
            games_df = await fetch_games_for_rankings(
                supabase_client=supabase_client,
                lookback_days=lookback_days,
                provider_filter=provider_filter,
                today=today
            )
        else:
            raise ValueError("games_df is required if fetch_from_supabase is False")
    
    if games_df.empty:
        return {
            "teams": pd.DataFrame(),
            "games_used": pd.DataFrame()
        }
    
    # Group by (age, gender) cohorts
    cohorts = games_df.groupby(["age", "gender"])
    
    # Create tasks for each cohort
    tasks = []
    for (age, gender), cohort_games in cohorts:
        task = compute_rankings_with_ml(
            supabase_client=supabase_client,
            games_df=cohort_games,
            today=today,
            v53_cfg=v53_cfg,
            layer13_cfg=layer13_cfg,
            fetch_from_supabase=False,  # Already have games_df
            lookback_days=lookback_days,
            provider_filter=provider_filter,
            force_rebuild=force_rebuild,
        )
        tasks.append(task)
    
    # Run all cohorts concurrently
    results = await asyncio.gather(*tasks)
    
    # Merge results from all cohorts
    all_teams = []
    all_games_used = []
    
    for result in results:
        if not result["teams"].empty:
            all_teams.append(result["teams"])
        if not result.get("games_used", pd.DataFrame()).empty:
            all_games_used.append(result["games_used"])
    
    # Combine results
    teams_combined = pd.concat(all_teams, ignore_index=True) if all_teams else pd.DataFrame()
    games_used_combined = pd.concat(all_games_used, ignore_index=True) if all_games_used else pd.DataFrame()
    
    return {
        "teams": teams_combined,
        "games_used": games_used_combined
    }

