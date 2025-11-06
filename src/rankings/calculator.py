"""Integrated Rankings Calculator (v53e + ML Layer)"""
from __future__ import annotations

import pandas as pd
from typing import Optional, Dict
from datetime import datetime

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
    
    # 2) Run v53e rankings engine
    base = compute_rankings(games_df=games_df, today=today, cfg=v53_cfg)
    
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

