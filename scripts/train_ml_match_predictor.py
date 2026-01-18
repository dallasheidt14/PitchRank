"""
Training Script for ML Match Predictor

This script trains XGBoost models on historical game data to predict match outcomes.
The trained models can then be compared against the existing hard-coded matchPredictor.ts.

Usage:
    python scripts/train_ml_match_predictor.py [--lookback-days 365] [--min-games 5]

Environment:
    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Dict, Optional
from pathlib import Path

import pandas as pd
import numpy as np
from dotenv import load_dotenv

# Load environment variables
env_local = Path('.env.local')
if env_local.exists():
    load_dotenv(env_local, override=True)
else:
    load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from supabase import create_client, Client
from src.predictions.ml_match_predictor import MLMatchPredictor


async def fetch_games(supabase: Client, limit: int = 5000) -> pd.DataFrame:
    """Fetch historical games from database"""
    print(f"Fetching {limit} games with valid scores and team IDs...")
    
    # Fetch games with scores and matched team IDs - fetch in batches to avoid Supabase limits
    all_games = []
    batch_size = 1000
    offset = 0
    
    while len(all_games) < limit:
        response = (
            supabase.table('games')
            .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
            .not_.is_('home_team_master_id', 'null')
            .not_.is_('away_team_master_id', 'null')
            .not_.is_('home_score', 'null')
            .not_.is_('away_score', 'null')
            .order('game_date', desc=True)  # Most recent first
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        
        if not response.data:
            break
        
        all_games.extend(response.data)
        offset += batch_size
        
        if len(response.data) < batch_size:
            break
        
        if len(all_games) >= limit:
            break
    
    games_df = pd.DataFrame(all_games[:limit])  # Ensure we don't exceed limit
    print(f"Fetched {len(games_df)} games with valid scores and team IDs")
    
    return games_df


async def fetch_rankings(supabase: Client, use_full: bool = False) -> pd.DataFrame:
    """Fetch current team rankings - returns empty DataFrame if can't fetch (we'll use defaults)"""
    print("Fetching team rankings...")
    
    # Try rankings_full first (has more teams), fall back to rankings_view
    if use_full:
        try:
            response = supabase.table('rankings_full').select('team_id, power_score_final, sos_norm, offense_norm, defense_norm, win_percentage, games_played, rank_in_cohort').limit(50000).execute()
            rankings_df = pd.DataFrame(response.data)
            # Map column names to match what we expect
            if 'team_id' in rankings_df.columns:
                rankings_df['team_id_master'] = rankings_df['team_id']
            if 'rank_in_cohort' in rankings_df.columns:
                rankings_df['rank_in_cohort_final'] = rankings_df['rank_in_cohort']
            print(f"Fetched rankings from rankings_full for {len(rankings_df)} teams")
            return rankings_df
        except Exception as e:
            print(f"Could not fetch from rankings_full: {e}, trying rankings_view...")
    
    # Try rankings_view with limit to avoid timeout
    try:
        response = supabase.table('rankings_view').select('team_id_master, power_score_final, sos_norm, offense_norm, defense_norm, win_percentage, games_played, rank_in_cohort_final').limit(50000).execute()
        rankings_df = pd.DataFrame(response.data)
        print(f"Fetched rankings from rankings_view for {len(rankings_df)} teams")
        return rankings_df
    except Exception as e:
        print(f"Could not fetch from rankings_view: {e}")
        print("Will use default rankings (0.5) for all teams")
        return pd.DataFrame()  # Return empty - we'll use defaults


async def build_team_histories(
    supabase: Client,
    games_df: pd.DataFrame,
    lookback_days: int = 365,
    max_teams: int = 5000,
    limit_per_team: int = 20
) -> Dict[str, pd.DataFrame]:
    """
    Build game history for each team - optimized for large datasets
    
    Args:
        supabase: Supabase client
        games_df: DataFrame with games
        lookback_days: Days to look back for history
        max_teams: Maximum number of teams to fetch histories for (to avoid timeouts)
        limit_per_team: Maximum games per team to fetch (for recent form calculation)
    """
    print("Building team game histories (optimized for large datasets)...")
    
    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    # Get all unique team IDs
    team_ids = list(set(
        list(games_df['home_team_master_id'].dropna().unique()) +
        list(games_df['away_team_master_id'].dropna().unique())
    ))
    
    # Limit number of teams if too many (prioritize teams that appear more often)
    if len(team_ids) > max_teams:
        print(f"Limiting to {max_teams} most frequent teams (out of {len(team_ids)})")
        # Count team appearances in games
        team_counts = {}
        for _, game in games_df.iterrows():
            home_id = game.get('home_team_master_id')
            away_id = game.get('away_team_master_id')
            if pd.notna(home_id):
                team_counts[str(home_id)] = team_counts.get(str(home_id), 0) + 1
            if pd.notna(away_id):
                team_counts[str(away_id)] = team_counts.get(str(away_id), 0) + 1
        
        # Sort by frequency and take top teams
        sorted_teams = sorted(team_counts.items(), key=lambda x: x[1], reverse=True)
        team_ids = [team_id for team_id, _ in sorted_teams[:max_teams]]
    
    team_histories = {}
    batch_size = 50  # Process teams in batches
    total_batches = (len(team_ids) + batch_size - 1) // batch_size
    
    for batch_idx in range(0, len(team_ids), batch_size):
        batch_teams = team_ids[batch_idx:batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1
        
        print(f"Processing team batch {batch_num}/{total_batches} ({len(batch_teams)} teams)...", end='\r')
        
        # Fetch games for all teams in this batch in a single query
        # Build OR conditions for batch
        or_conditions = []
        for team_id in batch_teams:
            or_conditions.append(f'home_team_master_id.eq.{team_id}')
            or_conditions.append(f'away_team_master_id.eq.{team_id}')
        
        # Supabase has limits on OR conditions, so we'll do smaller sub-batches
        sub_batch_size = 10  # 10 teams = 20 OR conditions
        for sub_batch_idx in range(0, len(batch_teams), sub_batch_size):
            sub_batch = batch_teams[sub_batch_idx:sub_batch_idx + sub_batch_size]
            sub_or_conditions = []
            for team_id in sub_batch:
                sub_or_conditions.append(f'home_team_master_id.eq.{team_id}')
                sub_or_conditions.append(f'away_team_master_id.eq.{team_id}')
            
            try:
                # Fetch games for this sub-batch
                response = (
                    supabase.table('games')
                    .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
                    .gte('game_date', cutoff_date)
                    .or_(','.join(sub_or_conditions))
                    .order('game_date', desc=True)
                    .limit(limit_per_team * len(sub_batch))  # Limit total results
                    .execute()
                )
                
                batch_games = pd.DataFrame(response.data)
                
                # Group games by team
                for team_id in sub_batch:
                    team_id_str = str(team_id)
                    # Convert to string for comparison
                    batch_games['home_team_master_id_str'] = batch_games['home_team_master_id'].astype(str)
                    batch_games['away_team_master_id_str'] = batch_games['away_team_master_id'].astype(str)
                    
                    team_games = batch_games[
                        (batch_games['home_team_master_id_str'] == team_id_str) |
                        (batch_games['away_team_master_id_str'] == team_id_str)
                    ].sort_values('game_date', ascending=False).head(limit_per_team)
                    
                    # Drop temporary columns
                    team_games = team_games.drop(columns=['home_team_master_id_str', 'away_team_master_id_str'], errors='ignore')
                    
                    if not team_games.empty:
                        team_histories[team_id_str] = team_games
                        
            except Exception as e:
                # If batch fails, try individual requests for this sub-batch
                print(f"\nWarning: Batch query failed, trying individual requests: {e}")
                for team_id in sub_batch:
                    try:
                        response = (
                            supabase.table('games')
                            .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
                            .gte('game_date', cutoff_date)
                            .or_(f'home_team_master_id.eq.{team_id},away_team_master_id.eq.{team_id}')
                            .order('game_date', desc=True)
                            .limit(limit_per_team)
                            .execute()
                        )
                        
                        team_games = pd.DataFrame(response.data)
                        if not team_games.empty:
                            team_histories[str(team_id)] = team_games
                    except Exception as e2:
                        # Skip this team if it fails
                        continue
        
        # Small delay between batches to avoid overwhelming the API
        import time
        if batch_idx + batch_size < len(team_ids):
            time.sleep(0.1)
    
    print(f"\nBuilt histories for {len(team_histories)} teams")
    return team_histories


async def main():
    """Main training script"""
    parser = argparse.ArgumentParser(description='Train ML Match Predictor')
    parser.add_argument('--min-games', type=int, default=5,
                       help='Minimum games per team to include (default: 5)')
    parser.add_argument('--model-name', type=str, default='match_predictor',
                       help='Name for saved model (default: match_predictor)')
    parser.add_argument('--test-size', type=float, default=0.2,
                       help='Proportion of data for testing (default: 0.2)')
    parser.add_argument('--limit', type=int, default=20000,
                       help='Maximum number of games to fetch for training (default: 20000)')
    parser.add_argument('--use-full-rankings', action='store_true',
                       help='Use rankings_full table instead of rankings_view')
    
    args = parser.parse_args()
    
    # Check environment
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    
    if not url or not key:
        print("ERROR: Missing environment variables")
        print("Required: SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_SERVICE_ROLE_KEY)")
        sys.exit(1)
    
    # Create Supabase client
    supabase = create_client(url, key)
    
    # Initialize predictor
    predictor = MLMatchPredictor(
        min_games_per_team=args.min_games
    )
    
    try:
        # Fetch data
        games_df = await fetch_games(supabase, args.limit)
        
        if games_df.empty:
            print("ERROR: No games found in database")
            sys.exit(1)
        
        rankings_df = await fetch_rankings(supabase, use_full=args.use_full_rankings)
        
        if rankings_df.empty:
            print("ERROR: No rankings found in database")
            sys.exit(1)
        
        # Build team histories for recent form features (use 365 days lookback for form)
        # For large datasets, limit teams and games per team to avoid timeouts
        max_teams_for_history = min(5000, len(games_df) // 2)  # Adaptive based on dataset size
        team_histories = await build_team_histories(
            supabase, games_df, 
            lookback_days=365,
            max_teams=max_teams_for_history,
            limit_per_team=20  # Only need last 20 games for recent form
        )
        
        # Build features
        print("\nBuilding features...")
        print(f"Games with scores: {len(games_df)}")
        print(f"Teams in rankings: {len(rankings_df)}")
        
        features_df = predictor.build_features(games_df, rankings_df, team_histories)
        
        if features_df.empty:
            print("ERROR: No features could be built (missing rankings?)")
            print("This usually means games don't have both teams in the rankings_view.")
            print("Try:")
            print("  1. Ensure rankings are up to date")
            print("  2. Check that games have valid team_id_master values")
            print("  3. Increase --lookback-days to get more games")
            sys.exit(1)
        
        print(f"Built features for {len(features_df)} games")
        
        if len(features_df) < 50:
            print(f"WARNING: Only {len(features_df)} games with features. Model may not train well.")
            print("Consider increasing --lookback-days or checking data quality.")
        
        # Train models
        print("\nTraining models...")
        metrics = predictor.train(features_df, test_size=args.test_size)
        
        # Print results
        print("\n" + "="*70)
        print("TRAINING RESULTS")
        print("="*70)
        print(f"\nWin Probability Model:")
        print(f"  Accuracy: {metrics['win_probability']['accuracy']:.1%}")
        print(f"  Log Loss: {metrics['win_probability']['log_loss']:.4f}")
        
        print(f"\nScore Margin Model:")
        print(f"  MAE: {metrics['score_margin']['mae']:.2f} goals")
        print(f"  RMSE: {metrics['score_margin']['rmse']:.2f} goals")
        
        print(f"\nHome Score Model:")
        print(f"  MAE: {metrics['home_score']['mae']:.2f} goals")
        print(f"  RMSE: {metrics['home_score']['rmse']:.2f} goals")
        
        print(f"\nAway Score Model:")
        print(f"  MAE: {metrics['away_score']['mae']:.2f} goals")
        print(f"  RMSE: {metrics['away_score']['rmse']:.2f} goals")
        
        # Save models
        print(f"\nSaving models...")
        predictor.save(args.model_name)
        
        print("\n✅ Training complete!")
        print(f"Models saved to: {predictor.model_dir}")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

