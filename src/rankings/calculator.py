"""Integrated Rankings Calculator (v53e + ML Layer)"""
from __future__ import annotations

import pandas as pd
from typing import Optional, Dict
from datetime import datetime
import hashlib
import asyncio
from pathlib import Path

from src.etl.v53e import compute_rankings, V53EConfig
from src.rankings.layer13_predictive_adjustment import (
    apply_predictive_adjustment, Layer13Config
)
from src.rankings.data_adapter import fetch_games_for_rankings


async def compute_rankings_with_ml(
    supabase_client,
    games_df: Optional[pd.DataFrame] = None,  # Optional: pass games directly
    today: Optional[pd.Timestamp] = None,
    v53_cfg: Optional[V53EConfig] = None,
    layer13_cfg: Optional[Layer13Config] = None,
    fetch_from_supabase: bool = True,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
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
    if cache_file.exists():
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
        base = compute_rankings(games_df=games_df, today=today, cfg=v53_cfg)
        
        # Save to cache (only teams DataFrame)
        try:
            if not base["teams"].empty:
                base["teams"].to_parquet(cache_file, index=False)
        except Exception:
            # Cache save failed - continue without caching
            pass
    
    teams_base = base["teams"]
    games_used = base.get("games_used")
    
    if teams_base.empty:
        return {
            "teams": teams_base,
            "games_used": games_used or pd.DataFrame()
        }
    
    # 3) Apply ML predictive adjustment
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
        "games_used": games_used or pd.DataFrame()
    }


async def compute_rankings_v53e_only(
    supabase_client,
    games_df: Optional[pd.DataFrame] = None,
    today: Optional[pd.Timestamp] = None,
    v53_cfg: Optional[V53EConfig] = None,
    fetch_from_supabase: bool = True,
    lookback_days: int = 365,
    provider_filter: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Run v53e rankings engine only (without ML layer).
    
    Useful for comparison or when ML is disabled.
    """
    v53_cfg = v53_cfg or V53EConfig()
    
    # Get games data
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
    
    # Run v53e rankings engine
    result = compute_rankings(games_df=games_df, today=today, cfg=v53_cfg)
    
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

