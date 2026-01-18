"""
Compare ML Match Predictor vs Existing Hard-Coded Predictor

This script compares predictions from the ML-based predictor against the
existing hard-coded matchPredictor.ts logic to see which performs better.

Usage:
    python scripts/compare_predictors.py [--lookback-days 180] [--limit 1000]

Environment:
    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables
"""

import os
import sys
import asyncio
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
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


def predict_match_hardcoded(team_a: Dict, team_b: Dict) -> Dict:
    """
    Replicate the hard-coded matchPredictor.ts logic in Python
    
    This matches the algorithm from frontend/lib/matchPredictor.ts
    """
    # Base weights (from matchPredictor.ts)
    BASE_WEIGHTS = {
        'POWER_SCORE': 0.50,
        'SOS': 0.18,
        'RECENT_FORM': 0.28,
        'MATCHUP': 0.04,
    }
    
    BLOWOUT_WEIGHTS = {
        'POWER_SCORE': 0.75,
        'SOS': 0.10,
        'RECENT_FORM': 0.12,
        'MATCHUP': 0.03,
    }
    
    SKILL_GAP_THRESHOLDS = {
        'LARGE': 0.15,
        'MEDIUM': 0.10,
    }
    
    SENSITIVITY = 4.5
    MARGIN_COEFFICIENT = 8.0
    LEAGUE_AVG_GOALS = 2.5
    
    # Get team features
    power_a = team_a.get('power_score_final', 0.5) or 0.5
    power_b = team_b.get('power_score_final', 0.5) or 0.5
    power_diff = power_a - power_b
    
    # Adaptive weights
    abs_power_diff = abs(power_diff)
    if abs_power_diff < SKILL_GAP_THRESHOLDS['MEDIUM']:
        weights = BASE_WEIGHTS
    elif abs_power_diff >= SKILL_GAP_THRESHOLDS['LARGE']:
        weights = BLOWOUT_WEIGHTS
    else:
        transition = (abs_power_diff - SKILL_GAP_THRESHOLDS['MEDIUM']) / \
                    (SKILL_GAP_THRESHOLDS['LARGE'] - SKILL_GAP_THRESHOLDS['MEDIUM'])
        weights = {
            'POWER_SCORE': BASE_WEIGHTS['POWER_SCORE'] + 
                          (BLOWOUT_WEIGHTS['POWER_SCORE'] - BASE_WEIGHTS['POWER_SCORE']) * transition,
            'SOS': BASE_WEIGHTS['SOS'] + 
                   (BLOWOUT_WEIGHTS['SOS'] - BASE_WEIGHTS['SOS']) * transition,
            'RECENT_FORM': BASE_WEIGHTS['RECENT_FORM'] + 
                          (BLOWOUT_WEIGHTS['RECENT_FORM'] - BASE_WEIGHTS['RECENT_FORM']) * transition,
            'MATCHUP': BASE_WEIGHTS['MATCHUP'] + 
                      (BLOWOUT_WEIGHTS['MATCHUP'] - BASE_WEIGHTS['MATCHUP']) * transition,
        }
    
    # SOS differential
    sos_a = team_a.get('sos_norm', 0.5) or 0.5
    sos_b = team_b.get('sos_norm', 0.5) or 0.5
    sos_diff = sos_a - sos_b
    
    # Recent form (simplified - would need game history in real implementation)
    form_a = team_a.get('recent_form', 0.0) or 0.0
    form_b = team_b.get('recent_form', 0.0) or 0.0
    form_diff_raw = form_a - form_b
    
    # Normalize recent form
    def sigmoid(x):
        return 1 / (1 + np.exp(-x))
    
    form_diff_norm = sigmoid(form_diff_raw * 0.5) - 0.5
    
    # Matchup asymmetry
    offense_a = team_a.get('offense_norm', 0.5) or 0.5
    defense_a = team_a.get('defense_norm', 0.5) or 0.5
    offense_b = team_b.get('offense_norm', 0.5) or 0.5
    defense_b = team_b.get('defense_norm', 0.5) or 0.5
    
    matchup_advantage = (offense_a - defense_b) - (offense_b - defense_a)
    
    # Composite differential
    composite_diff = (
        weights['POWER_SCORE'] * power_diff +
        weights['SOS'] * sos_diff +
        weights['RECENT_FORM'] * form_diff_norm +
        weights['MATCHUP'] * matchup_advantage
    )
    
    # Win probability
    win_prob_a = sigmoid(SENSITIVITY * composite_diff)
    win_prob_b = 1 - win_prob_a
    
    # Expected margin
    abs_composite_diff = abs(composite_diff)
    if abs_composite_diff > 0.12:
        margin_multiplier = 2.5
    elif abs_composite_diff > 0.08:
        transition = (abs_composite_diff - 0.08) / (0.12 - 0.08)
        margin_multiplier = 1.0 + (1.5 * transition)
    else:
        margin_multiplier = 1.0
    
    expected_margin = composite_diff * MARGIN_COEFFICIENT * margin_multiplier
    
    # Expected scores
    expected_score_a = max(0, LEAGUE_AVG_GOALS + (expected_margin / 2))
    expected_score_b = max(0, LEAGUE_AVG_GOALS - (expected_margin / 2))
    
    # Predicted winner
    if win_prob_a > 0.55:
        predicted_winner = 'team_a'
    elif win_prob_a < 0.45:
        predicted_winner = 'team_b'
    else:
        predicted_winner = 'draw'
    
    return {
        'predicted_winner': predicted_winner,
        'win_probability_a': win_prob_a,
        'win_probability_b': win_prob_b,
        'expected_score_a': expected_score_a,
        'expected_score_b': expected_score_b,
        'expected_margin': expected_margin,
    }


async def fetch_comparison_data(supabase: Client, limit: int = 5000) -> Tuple[pd.DataFrame, Dict]:
    """Fetch games and rankings for comparison"""
    print(f"Fetching {limit} games with valid scores and team IDs...")
    
    # Fetch games with scores and matched team IDs
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
            .order('game_date', desc=True)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        
        if not response.data:
            break
        
        all_games.extend(response.data)
        offset += batch_size
        
        if len(response.data) < batch_size or len(all_games) >= limit:
            break
    
    games_df = pd.DataFrame(all_games[:limit])
    print(f"Fetched {len(games_df)} games")
    
    # Fetch rankings (with limit to avoid timeout)
    print("Fetching rankings...")
    try:
        response = supabase.table('rankings_view').select('team_id_master, power_score_final, sos_norm, offense_norm, defense_norm, win_percentage, games_played, rank_in_cohort_final').limit(50000).execute()
        rankings_df = pd.DataFrame(response.data)
    except Exception as e:
        print(f"Could not fetch from rankings_view: {e}")
        print("Using empty rankings (will use defaults)")
        rankings_df = pd.DataFrame()
    
    # Create rankings dict
    rankings_dict = {}
    for _, row in rankings_df.iterrows():
        rankings_dict[str(row['team_id_master'])] = row.to_dict()
    
    print(f"Fetched rankings for {len(rankings_dict)} teams")
    
    return games_df, rankings_dict


async def build_team_histories_for_comparison(
    supabase: Client,
    team_ids: List[str],
    lookback_days: int = 365,
    max_teams: int = 5000,
    limit_per_team: int = 20
) -> Dict[str, pd.DataFrame]:
    """
    Build game histories for teams - optimized for large datasets
    
    Args:
        supabase: Supabase client
        team_ids: List of team IDs to fetch histories for
        lookback_days: Days to look back for history
        max_teams: Maximum number of teams to fetch (to avoid timeouts)
        limit_per_team: Maximum games per team to fetch
    """
    print("Building team histories (optimized)...")
    
    cutoff_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    # Limit number of teams if too many
    if len(team_ids) > max_teams:
        print(f"Limiting to {max_teams} teams (out of {len(team_ids)})")
        team_ids = team_ids[:max_teams]
    
    team_histories = {}
    batch_size = 50  # Process teams in batches
    total_batches = (len(team_ids) + batch_size - 1) // batch_size
    
    for batch_idx in range(0, len(team_ids), batch_size):
        batch_teams = team_ids[batch_idx:batch_idx + batch_size]
        batch_num = (batch_idx // batch_size) + 1
        
        print(f"Processing team batch {batch_num}/{total_batches} ({len(batch_teams)} teams)...", end='\r')
        
        # Fetch games for teams in this batch
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
                    .limit(limit_per_team * len(sub_batch))
                    .execute()
                )
                
                batch_games = pd.DataFrame(response.data)
                
                # Group games by team
                for team_id in sub_batch:
                    team_id_str = str(team_id)
                    # Convert to string for comparison
                    if not batch_games.empty:
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


def calculate_recent_form(team_id: str, team_games: pd.DataFrame, n: int = 5) -> float:
    """Calculate recent form (average goal differential)"""
    if team_games.empty:
        return 0.0
    
    # Convert team_id to string for comparison
    team_id_str = str(team_id)
    
    team_games = team_games.sort_values('game_date', ascending=False).head(n)
    
    goal_diffs = []
    for _, game in team_games.iterrows():
        if pd.notna(game.get('home_score')) and pd.notna(game.get('away_score')):
            home_id = str(game.get('home_team_master_id', ''))
            if home_id == team_id_str:
                goal_diff = game.get('home_score', 0) - game.get('away_score', 0)
            else:
                goal_diff = game.get('away_score', 0) - game.get('home_score', 0)
            goal_diffs.append(goal_diff)
    
    return np.mean(goal_diffs) if goal_diffs else 0.0


async def compare_predictors(
    games_df: pd.DataFrame,
    rankings_dict: Dict,
    ml_predictor: MLMatchPredictor,
    team_histories: Dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """Compare predictions from both methods"""
    print("\nComparing predictions...")
    
    results = []
    skipped = 0
    
    for idx, game in games_df.iterrows():
        home_id = game['home_team_master_id']
        away_id = game['away_team_master_id']
        
        # Get rankings (use defaults if not found, just like in training)
        home_rank = rankings_dict.get(str(home_id))
        away_rank = rankings_dict.get(str(away_id))
        
        # Use default rankings if team not in rankings (same as training)
        if home_rank is None:
            home_rank = {
                'power_score_final': 0.5,
                'sos_norm': 0.5,
                'offense_norm': 0.5,
                'defense_norm': 0.5,
                'win_percentage': 0.5,
                'games_played': 0,
                'rank_in_cohort_final': 1000,
            }
        else:
            home_rank = home_rank.copy()  # Make a copy to avoid modifying original
        
        if away_rank is None:
            away_rank = {
                'power_score_final': 0.5,
                'sos_norm': 0.5,
                'offense_norm': 0.5,
                'defense_norm': 0.5,
                'win_percentage': 0.5,
                'games_played': 0,
                'rank_in_cohort_final': 1000,
            }
        else:
            away_rank = away_rank.copy()  # Make a copy to avoid modifying original
        
        # Add recent form
        home_form = calculate_recent_form(home_id, team_histories.get(home_id, pd.DataFrame()))
        away_form = calculate_recent_form(away_id, team_histories.get(away_id, pd.DataFrame()))
        
        home_rank['recent_form'] = home_form
        away_rank['recent_form'] = away_form
        
        # Actual outcome
        actual_home_score = int(game['home_score'])
        actual_away_score = int(game['away_score'])
        actual_margin = actual_home_score - actual_away_score
        
        if actual_margin > 0:
            actual_winner = 'home'
        elif actual_margin < 0:
            actual_winner = 'away'
        else:
            actual_winner = 'draw'
        
        # Hard-coded prediction (convert to dict format)
        home_rank_dict = {
            'power_score_final': home_rank.get('power_score_final', 0.5) or 0.5,
            'sos_norm': home_rank.get('sos_norm', 0.5) or 0.5,
            'offense_norm': home_rank.get('offense_norm', 0.5) or 0.5,
            'defense_norm': home_rank.get('defense_norm', 0.5) or 0.5,
            'recent_form': home_rank.get('recent_form', 0.0),
        }
        
        away_rank_dict = {
            'power_score_final': away_rank.get('power_score_final', 0.5) or 0.5,
            'sos_norm': away_rank.get('sos_norm', 0.5) or 0.5,
            'offense_norm': away_rank.get('offense_norm', 0.5) or 0.5,
            'defense_norm': away_rank.get('defense_norm', 0.5) or 0.5,
            'recent_form': away_rank.get('recent_form', 0.0),
        }
        
        hardcoded_pred = predict_match_hardcoded(home_rank_dict, away_rank_dict)
        hardcoded_winner = 'home' if hardcoded_pred['predicted_winner'] == 'team_a' else 'away'
        if hardcoded_pred['predicted_winner'] == 'draw':
            hardcoded_winner = 'draw'
        
        # ML prediction
        try:
            # Convert dict to format expected by predictor
            home_features = {
                'power_score_final': home_rank.get('power_score_final', 0.5) or 0.5,
                'sos_norm': home_rank.get('sos_norm', 0.5) or 0.5,
                'offense_norm': home_rank.get('offense_norm', 0.5) or 0.5,
                'defense_norm': home_rank.get('defense_norm', 0.5) or 0.5,
                'win_percentage': home_rank.get('win_percentage', 0.5) or 0.5,
                'games_played': home_rank.get('games_played', 0) or 0,
                'rank_in_cohort_final': home_rank.get('rank_in_cohort_final', 1000) or 1000,
                'recent_form': home_rank.get('recent_form', 0.0),
            }
            
            away_features = {
                'power_score_final': away_rank.get('power_score_final', 0.5) or 0.5,
                'sos_norm': away_rank.get('sos_norm', 0.5) or 0.5,
                'offense_norm': away_rank.get('offense_norm', 0.5) or 0.5,
                'defense_norm': away_rank.get('defense_norm', 0.5) or 0.5,
                'win_percentage': away_rank.get('win_percentage', 0.5) or 0.5,
                'games_played': away_rank.get('games_played', 0) or 0,
                'rank_in_cohort_final': away_rank.get('rank_in_cohort_final', 1000) or 1000,
                'recent_form': away_rank.get('recent_form', 0.0),
            }
            
            ml_pred = ml_predictor.predict(home_features, away_features, is_home_away=True)
            ml_winner = 'home' if ml_pred.predicted_winner == 'team_a' else 'away'
            if ml_pred.predicted_winner == 'draw':
                ml_winner = 'draw'
        except Exception as e:
            print(f"ML prediction failed for game {game.get('id')}: {e}")
            skipped += 1
            continue
        
        # Check correctness
        hardcoded_correct = (hardcoded_winner == actual_winner)
        ml_correct = (ml_winner == actual_winner)
        
        results.append({
            'game_id': game.get('id'),
            'game_date': game.get('game_date'),
            'home_team_id': home_id,
            'away_team_id': away_id,
            'actual_home_score': actual_home_score,
            'actual_away_score': actual_away_score,
            'actual_winner': actual_winner,
            'actual_margin': actual_margin,
            # Hard-coded predictions
            'hardcoded_winner': hardcoded_winner,
            'hardcoded_win_prob_home': hardcoded_pred['win_probability_a'],
            'hardcoded_expected_home_score': hardcoded_pred['expected_score_a'],
            'hardcoded_expected_away_score': hardcoded_pred['expected_score_b'],
            'hardcoded_expected_margin': hardcoded_pred['expected_margin'],
            'hardcoded_correct': hardcoded_correct,
            # ML predictions
            'ml_winner': ml_winner,
            'ml_win_prob_home': ml_pred.win_probability_a,
            'ml_expected_home_score': ml_pred.expected_score_a,
            'ml_expected_away_score': ml_pred.expected_score_b,
            'ml_expected_margin': ml_pred.expected_margin,
            'ml_correct': ml_correct,
        })
    
    print(f"Compared {len(results)} games (skipped {skipped})")
    return pd.DataFrame(results)


def print_comparison_report(results_df: pd.DataFrame):
    """Print comparison report"""
    if results_df.empty:
        print("No results to compare")
        return
    
    print("\n" + "="*70)
    print("PREDICTOR COMPARISON REPORT")
    print("="*70)
    
    total = len(results_df)
    
    # Direction accuracy
    hardcoded_accuracy = results_df['hardcoded_correct'].mean()
    ml_accuracy = results_df['ml_correct'].mean()
    
    print(f"\n📊 DIRECTION ACCURACY (Winner Prediction)")
    print("-" * 70)
    print(f"Hard-coded Predictor: {hardcoded_accuracy:.1%} ({results_df['hardcoded_correct'].sum()}/{total})")
    print(f"ML Predictor:         {ml_accuracy:.1%} ({results_df['ml_correct'].sum()}/{total})")
    print(f"Difference:           {ml_accuracy - hardcoded_accuracy:+.1%}")
    
    # Margin prediction accuracy
    hardcoded_mae = abs(results_df['actual_margin'] - results_df['hardcoded_expected_margin']).mean()
    ml_mae = abs(results_df['actual_margin'] - results_df['ml_expected_margin']).mean()
    
    hardcoded_rmse = np.sqrt(((results_df['actual_margin'] - results_df['hardcoded_expected_margin'])**2).mean())
    ml_rmse = np.sqrt(((results_df['actual_margin'] - results_df['ml_expected_margin'])**2).mean())
    
    print(f"\n📊 SCORE MARGIN PREDICTION")
    print("-" * 70)
    print(f"Hard-coded Predictor:")
    print(f"  MAE:  {hardcoded_mae:.2f} goals")
    print(f"  RMSE: {hardcoded_rmse:.2f} goals")
    print(f"ML Predictor:")
    print(f"  MAE:  {ml_mae:.2f} goals")
    print(f"  RMSE: {ml_rmse:.2f} goals")
    print(f"Improvement: MAE {hardcoded_mae - ml_mae:+.2f}, RMSE {hardcoded_rmse - ml_rmse:+.2f}")
    
    # Score prediction accuracy
    hardcoded_home_mae = abs(results_df['actual_home_score'] - results_df['hardcoded_expected_home_score']).mean()
    ml_home_mae = abs(results_df['actual_home_score'] - results_df['ml_expected_home_score']).mean()
    
    hardcoded_away_mae = abs(results_df['actual_away_score'] - results_df['hardcoded_expected_away_score']).mean()
    ml_away_mae = abs(results_df['actual_away_score'] - results_df['ml_expected_away_score']).mean()
    
    print(f"\n📊 INDIVIDUAL SCORE PREDICTION")
    print("-" * 70)
    print(f"Home Score MAE:")
    print(f"  Hard-coded: {hardcoded_home_mae:.2f} goals")
    print(f"  ML:         {ml_home_mae:.2f} goals")
    print(f"Away Score MAE:")
    print(f"  Hard-coded: {hardcoded_away_mae:.2f} goals")
    print(f"  ML:         {ml_away_mae:.2f} goals")
    
    # Breakdown by confidence
    print(f"\n📊 BREAKDOWN BY CONFIDENCE")
    print("-" * 70)
    
    # Hard-coded confidence (based on win prob difference from 0.5)
    results_df['hardcoded_confidence'] = abs(results_df['hardcoded_win_prob_home'] - 0.5)
    results_df['ml_confidence'] = abs(results_df['ml_win_prob_home'] - 0.5)
    
    for threshold in [0.2, 0.1]:
        hardcoded_high_conf = results_df[results_df['hardcoded_confidence'] >= threshold]
        ml_high_conf = results_df[results_df['ml_confidence'] >= threshold]
        
        if len(hardcoded_high_conf) > 0:
            hc_acc = hardcoded_high_conf['hardcoded_correct'].mean()
            print(f"\nHard-coded (confidence >= {threshold:.0%}):")
            print(f"  Accuracy: {hc_acc:.1%} (n={len(hardcoded_high_conf)})")
        
        if len(ml_high_conf) > 0:
            ml_acc = ml_high_conf['ml_correct'].mean()
            print(f"ML (confidence >= {threshold:.0%}):")
            print(f"  Accuracy: {ml_acc:.1%} (n={len(ml_high_conf)})")
    
    print("\n" + "="*70)
    
    # Winner
    if ml_accuracy > hardcoded_accuracy:
        print("✅ ML Predictor performs BETTER on direction accuracy")
    elif ml_accuracy < hardcoded_accuracy:
        print("⚠️  Hard-coded predictor performs BETTER on direction accuracy")
    else:
        print("🤝 Both predictors perform EQUALLY on direction accuracy")
    
    if ml_mae < hardcoded_mae:
        print("✅ ML Predictor performs BETTER on margin prediction")
    elif ml_mae > hardcoded_mae:
        print("⚠️  Hard-coded predictor performs BETTER on margin prediction")
    else:
        print("🤝 Both predictors perform EQUALLY on margin prediction")
    
    print("="*70)


async def main():
    """Main comparison script"""
    parser = argparse.ArgumentParser(description='Compare ML vs Hard-coded Predictor')
    parser.add_argument('--limit', type=int, default=5000,
                       help='Maximum number of games to test (default: 5000)')
    parser.add_argument('--model-name', type=str, default='match_predictor',
                       help='Name of saved ML model (default: match_predictor)')
    
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
    
    # Load ML predictor
    print("Loading ML predictor...")
    ml_predictor = MLMatchPredictor()
    try:
        ml_predictor.load(args.model_name)
    except FileNotFoundError:
        print(f"ERROR: ML model not found. Train first with:")
        print(f"  python scripts/train_ml_match_predictor.py")
        sys.exit(1)
    
    try:
        # Fetch data
        games_df, rankings_dict = await fetch_comparison_data(supabase, args.limit)
        
        if games_df.empty:
            print("ERROR: No games found")
            sys.exit(1)
        
        # Build team histories (optimized for large datasets)
        team_ids = list(set(games_df['home_team_master_id'].dropna().unique()) |
                       set(games_df['away_team_master_id'].dropna().unique()))
        
        # Limit teams and games per team to avoid timeouts
        max_teams_for_history = min(5000, len(team_ids))
        team_histories = await build_team_histories_for_comparison(
            supabase, team_ids,
            lookback_days=365,
            max_teams=max_teams_for_history,
            limit_per_team=20  # Only need last 20 games for recent form
        )
        
        # Compare
        results_df = await compare_predictors(games_df, rankings_dict, ml_predictor, team_histories)
        
        if results_df.empty:
            print("ERROR: No comparisons could be made")
            sys.exit(1)
        
        # Print report
        print_comparison_report(results_df)
        
        # Save results
        output_path = f"data/predictor_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        results_df.to_csv(output_path, index=False)
        print(f"\n💾 Results saved to: {output_path}")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

