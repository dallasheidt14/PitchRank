"""
ML-Based Match Predictor using XGBoost

This module provides a machine learning approach to match prediction that can be
tested against the existing hard-coded matchPredictor.ts implementation.

Features:
- XGBoost models for win probability and score prediction
- Rich feature engineering from team rankings and game history
- Model persistence for saving/loading trained models
- Compatible with existing data structures
"""

from __future__ import annotations

import os
import pickle
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

try:
    from xgboost import XGBClassifier, XGBRegressor
    _HAS_XGB = True
except ImportError:
    _HAS_XGB = False
    print("WARNING: XGBoost not available. Install with: pip install xgboost")

from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error, log_loss


@dataclass
class MatchPrediction:
    """ML-based match prediction result"""
    predicted_winner: str  # 'team_a', 'team_b', or 'draw'
    win_probability_a: float
    win_probability_b: float
    expected_score_a: float
    expected_score_b: float
    expected_margin: float
    confidence: str  # 'high', 'medium', 'low'
    model_features: Optional[Dict] = None  # For debugging/explanation


class MLMatchPredictor:
    """
    Machine Learning-based match predictor using XGBoost
    
    This predictor can be trained on historical game data and used to
    make predictions that can be compared against the existing hard-coded predictor.
    """
    
    def __init__(
        self,
        model_dir: str = "models/match_predictor",
        lookback_days: int = 365,
        min_games_per_team: int = 5
    ):
        """
        Initialize ML Match Predictor
        
        Args:
            model_dir: Directory to save/load trained models
            lookback_days: Number of days of historical data to use for training
            min_games_per_team: Minimum games a team must have to be included
        """
        if not _HAS_XGB:
            raise ImportError("XGBoost is required. Install with: pip install xgboost")
        
        self.model_dir = model_dir
        self.lookback_days = lookback_days
        self.min_games_per_team = min_games_per_team
        
        # Models
        self.win_probability_model: Optional[XGBClassifier] = None
        self.score_margin_model: Optional[XGBRegressor] = None
        self.team_a_score_model: Optional[XGBRegressor] = None
        self.team_b_score_model: Optional[XGBRegressor] = None
        
        # Feature names (for reference)
        self.feature_names: List[str] = []
        
        # Training metadata
        self.training_metadata: Dict = {}
        
        # Create model directory if it doesn't exist
        os.makedirs(model_dir, exist_ok=True)
    
    def build_features(
        self,
        games_df: pd.DataFrame,
        rankings_df: pd.DataFrame,
        team_histories: Optional[Dict[str, pd.DataFrame]] = None
    ) -> pd.DataFrame:
        """
        Build feature matrix from games and rankings data
        
        Args:
            games_df: DataFrame with columns: home_team_master_id, away_team_master_id,
                     home_score, away_score, game_date
            rankings_df: DataFrame with team rankings (power_score_final, sos_norm, etc.)
            team_histories: Optional dict mapping team_id to their game history DataFrame
        
        Returns:
            DataFrame with features for each game
        """
        features_list = []
        
        skipped_no_ids = 0
        
        # Convert team_id_master to string for consistent matching
        if 'team_id_master' in rankings_df.columns:
            rankings_df['team_id_master'] = rankings_df['team_id_master'].astype(str)
        
        # Create a lookup dict for faster access
        rankings_dict = {}
        for _, row in rankings_df.iterrows():
            team_id = str(row['team_id_master'])
            rankings_dict[team_id] = row
        
        for idx, game in games_df.iterrows():
            home_id = game.get('home_team_master_id')
            away_id = game.get('away_team_master_id')
            
            # Skip if missing team IDs
            if pd.isna(home_id) or pd.isna(away_id):
                skipped_no_ids += 1
                continue
            
            # Convert to string for matching
            home_id = str(home_id)
            away_id = str(away_id)
            
            # Get rankings for both teams (use lookup dict for speed)
            home_rank = rankings_dict.get(home_id)
            away_rank = rankings_dict.get(away_id)
            
            # If teams don't have rankings, use default values (0.5 for normalized scores)
            if home_rank is None:
                home_rank = pd.Series({
                    'power_score_final': 0.5,
                    'sos_norm': 0.5,
                    'offense_norm': 0.5,
                    'defense_norm': 0.5,
                    'win_percentage': 0.5,
                    'games_played': 0,
                    'rank_in_cohort_final': 1000,
                })
            
            if away_rank is None:
                away_rank = pd.Series({
                    'power_score_final': 0.5,
                    'sos_norm': 0.5,
                    'offense_norm': 0.5,
                    'defense_norm': 0.5,
                    'win_percentage': 0.5,
                    'games_played': 0,
                    'rank_in_cohort_final': 1000,
                })
            
            # Basic ranking features
            feature_dict = {
                # Power score features
                'home_power_score': home_rank.get('power_score_final', 0.5) or 0.5,
                'away_power_score': away_rank.get('power_score_final', 0.5) or 0.5,
                'power_score_diff': (home_rank.get('power_score_final', 0.5) or 0.5) - 
                                   (away_rank.get('power_score_final', 0.5) or 0.5),
                
                # SOS features
                'home_sos_norm': home_rank.get('sos_norm', 0.5) or 0.5,
                'away_sos_norm': away_rank.get('sos_norm', 0.5) or 0.5,
                'sos_diff': (home_rank.get('sos_norm', 0.5) or 0.5) - 
                           (away_rank.get('sos_norm', 0.5) or 0.5),
                
                # Offense/Defense features
                'home_offense_norm': home_rank.get('offense_norm', 0.5) or 0.5,
                'away_offense_norm': away_rank.get('offense_norm', 0.5) or 0.5,
                'home_defense_norm': home_rank.get('defense_norm', 0.5) or 0.5,
                'away_defense_norm': away_rank.get('defense_norm', 0.5) or 0.5,
                
                # Matchup asymmetry
                'offense_vs_defense': (home_rank.get('offense_norm', 0.5) or 0.5) - 
                                     (away_rank.get('defense_norm', 0.5) or 0.5),
                'defense_vs_offense': (home_rank.get('defense_norm', 0.5) or 0.5) - 
                                     (away_rank.get('offense_norm', 0.5) or 0.5),
                
                # Win percentage
                'home_win_pct': home_rank.get('win_percentage', 0.5) or 0.5,
                'away_win_pct': away_rank.get('win_percentage', 0.5) or 0.5,
                'win_pct_diff': (home_rank.get('win_percentage', 0.5) or 0.5) - 
                               (away_rank.get('win_percentage', 0.5) or 0.5),
                
                # Games played (experience)
                'home_games_played': home_rank.get('games_played', 0) or 0,
                'away_games_played': away_rank.get('games_played', 0) or 0,
                
                # Rank features
                'home_rank': home_rank.get('rank_in_cohort_final', 1000) or 1000,
                'away_rank': away_rank.get('rank_in_cohort_final', 1000) or 1000,
                'rank_diff': (away_rank.get('rank_in_cohort_final', 1000) or 1000) - 
                            (home_rank.get('rank_in_cohort_final', 1000) or 1000),  # Lower rank is better
                
                # Additional interaction features
                'power_score_product': (home_rank.get('power_score_final', 0.5) or 0.5) * 
                                      (away_rank.get('power_score_final', 0.5) or 0.5),
                'sos_product': (home_rank.get('sos_norm', 0.5) or 0.5) * 
                              (away_rank.get('sos_norm', 0.5) or 0.5),
                'offense_product': (home_rank.get('offense_norm', 0.5) or 0.5) * 
                                  (away_rank.get('offense_norm', 0.5) or 0.5),
                'defense_product': (home_rank.get('defense_norm', 0.5) or 0.5) * 
                                  (away_rank.get('defense_norm', 0.5) or 0.5),
                
                # Ratio features
                'power_score_ratio': (home_rank.get('power_score_final', 0.5) or 0.5) / 
                                     max(0.01, (away_rank.get('power_score_final', 0.5) or 0.5)),
                'games_played_ratio': (home_rank.get('games_played', 0) or 0) / 
                                     max(1, (away_rank.get('games_played', 0) or 0)),
            }
            
            # Add recent form features if team histories are provided
            if team_histories:
                home_form = self._calculate_recent_form(home_id, team_histories.get(home_id, pd.DataFrame()))
                away_form = self._calculate_recent_form(away_id, team_histories.get(away_id, pd.DataFrame()))
                
                feature_dict.update({
                    'home_recent_form': home_form,
                    'away_recent_form': away_form,
                    'recent_form_diff': home_form - away_form,
                })
            
            # Add game metadata
            feature_dict.update({
                'game_id': game.get('id', idx),
                'game_date': game.get('game_date', ''),
                'home_team_id': home_id,
                'away_team_id': away_id,
            })
            
            # Add actual outcomes (for training)
            if 'home_score' in game and 'away_score' in game:
                if pd.notna(game['home_score']) and pd.notna(game['away_score']):
                    feature_dict.update({
                        'actual_home_score': int(game['home_score']),
                        'actual_away_score': int(game['away_score']),
                        'actual_margin': int(game['home_score']) - int(game['away_score']),
                        'actual_winner': self._get_winner(int(game['home_score']), int(game['away_score'])),
                    })
            
            features_list.append(feature_dict)
        
        features_df = pd.DataFrame(features_list)
        
        if skipped_no_ids > 0:
            print(f"Warning: Skipped {skipped_no_ids} games due to missing team IDs")
        
        return features_df
    
    def _calculate_recent_form(self, team_id: str, team_games: pd.DataFrame, n: int = 5) -> float:
        """Calculate recent form (average goal differential in last N games)"""
        if team_games.empty:
            return 0.0
        
        # Convert team_id to string for comparison
        team_id_str = str(team_id)
        
        # Sort by date descending (should already be sorted, but ensure it)
        team_games = team_games.sort_values('game_date', ascending=False).head(n)
        
        if team_games.empty:
            return 0.0
        
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
    
    def _get_winner(self, home_score: int, away_score: int) -> str:
        """Determine winner from scores"""
        if home_score > away_score:
            return 'home'
        elif away_score > home_score:
            return 'away'
        else:
            return 'draw'
    
    def train(
        self,
        features_df: pd.DataFrame,
        test_size: float = 0.2,
        random_state: int = 42
    ) -> Dict:
        """
        Train XGBoost models on historical game data
        
        Args:
            features_df: DataFrame with features and actual outcomes
            test_size: Proportion of data to use for testing
            random_state: Random seed for reproducibility
        
        Returns:
            Dictionary with training metrics
        """
        if features_df.empty:
            raise ValueError("Features DataFrame is empty")
        
        # Check required columns
        required_cols = ['actual_home_score', 'actual_away_score', 'actual_margin', 'actual_winner']
        missing_cols = [col for col in required_cols if col not in features_df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")
        
        # Prepare feature columns (exclude metadata and targets)
        exclude_cols = [
            'game_id', 'game_date', 'home_team_id', 'away_team_id',
            'actual_home_score', 'actual_away_score', 'actual_margin', 'actual_winner'
        ]
        feature_cols = [col for col in features_df.columns if col not in exclude_cols]
        self.feature_names = feature_cols
        
        X = features_df[feature_cols].fillna(0).astype(float)
        
        # Check minimum data requirements
        if len(features_df) < 10:
            raise ValueError(f"Insufficient data: only {len(features_df)} games with features. Need at least 10 games.")
        
        # Prepare targets
        y_winner = features_df['actual_winner'].map({'home': 1, 'away': 0, 'draw': 0.5})
        y_margin = features_df['actual_margin'].astype(float)
        y_home_score = features_df['actual_home_score'].astype(float)
        y_away_score = features_df['actual_away_score'].astype(float)
        
        # Adjust test_size if we have too few samples
        min_train_size = 10
        if len(features_df) < min_train_size / (1 - test_size):
            test_size = max(0.1, 1 - (min_train_size / len(features_df)))
            print(f"Adjusted test_size to {test_size:.2f} to ensure minimum training samples")
        
        # Split data
        X_train, X_test, y_winner_train, y_winner_test, y_margin_train, y_margin_test, \
        y_home_train, y_home_test, y_away_train, y_away_test = train_test_split(
            X, y_winner, y_margin, y_home_score, y_away_score,
            test_size=test_size, random_state=random_state
        )
        
        print(f"Training on {len(X_train)} games, testing on {len(X_test)} games")
        print(f"Features: {len(feature_cols)}")
        
        # Check for class balance in training set
        y_winner_binary = (y_winner_train > 0.5).astype(int)
        unique_classes = np.unique(y_winner_binary)
        
        if len(unique_classes) < 2:
            raise ValueError(
                f"Insufficient class diversity in training set. "
                f"Only found class(es): {unique_classes.tolist()}. "
                f"Need both home wins and away wins/draws in training data."
            )
        
        # Train win probability model (binary classification: home win vs not)
        print("\nTraining win probability model...")
        self.win_probability_model = XGBClassifier(
            n_estimators=300,  # Increased from 200
            max_depth=7,  # Increased from 6
            learning_rate=0.05,  # Lower learning rate for better generalization
            subsample=0.85,
            colsample_bytree=0.85,
            reg_alpha=0.2,  # Slightly more regularization
            reg_lambda=1.5,
            min_child_weight=3,  # Added to prevent overfitting
            gamma=0.1,  # Added minimum loss reduction
            random_state=random_state,
            n_jobs=-1,
            eval_metric='logloss',
            early_stopping_rounds=20  # Early stopping
        )
        
        # Convert to binary: home win (1) vs not home win (0)
        # Use validation set for early stopping
        X_train_fit, X_val, y_train_fit, y_val = train_test_split(
            X_train, y_winner_binary, test_size=0.1, random_state=random_state
        )
        self.win_probability_model.fit(
            X_train_fit, y_train_fit,
            eval_set=[(X_val, y_val)],
            verbose=False
        )
        
        # Train score margin model
        print("Training score margin model...")
        self.score_margin_model = XGBRegressor(
            n_estimators=300,
            max_depth=7,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_alpha=0.2,
            reg_lambda=1.5,
            min_child_weight=3,
            gamma=0.1,
            random_state=random_state,
            n_jobs=-1,
            eval_metric='rmse',
            early_stopping_rounds=20
        )
        self.score_margin_model.fit(X_train, y_margin_train, eval_set=[(X_test, y_margin_test)], verbose=False)
        
        # Train individual score models
        print("Training home score model...")
        self.team_a_score_model = XGBRegressor(
            n_estimators=300,
            max_depth=7,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_alpha=0.2,
            reg_lambda=1.5,
            min_child_weight=3,
            gamma=0.1,
            random_state=random_state,
            n_jobs=-1,
            eval_metric='rmse',
            early_stopping_rounds=20
        )
        self.team_a_score_model.fit(X_train, y_home_train, eval_set=[(X_test, y_home_test)], verbose=False)
        
        print("Training away score model...")
        self.team_b_score_model = XGBRegressor(
            n_estimators=300,
            max_depth=7,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_alpha=0.2,
            reg_lambda=1.5,
            min_child_weight=3,
            gamma=0.1,
            random_state=random_state,
            n_jobs=-1,
            eval_metric='rmse',
            early_stopping_rounds=20
        )
        self.team_b_score_model.fit(X_train, y_away_train, eval_set=[(X_test, y_away_test)], verbose=False)
        
        # Evaluate models
        print("\nEvaluating models...")
        metrics = self._evaluate_models(
            X_test, y_winner_test, y_margin_test, y_home_test, y_away_test
        )
        
        # Store training metadata
        self.training_metadata = {
            'training_date': datetime.now().isoformat(),
            'n_train': len(X_train),
            'n_test': len(X_test),
            'n_features': len(feature_cols),
            'feature_names': feature_cols,
            'metrics': metrics
        }
        
        return metrics
    
    def _evaluate_models(
        self,
        X_test: pd.DataFrame,
        y_winner_test: pd.Series,
        y_margin_test: pd.Series,
        y_home_test: pd.Series,
        y_away_test: pd.Series
    ) -> Dict:
        """Evaluate trained models on test set"""
        metrics = {}
        
        # Win probability model
        y_winner_pred_proba = self.win_probability_model.predict_proba(X_test)[:, 1]
        y_winner_pred = (y_winner_pred_proba > 0.5).astype(int)
        y_winner_true = (y_winner_test > 0.5).astype(int)
        
        metrics['win_probability'] = {
            'accuracy': accuracy_score(y_winner_true, y_winner_pred),
            'log_loss': log_loss(y_winner_true, y_winner_pred_proba),
        }
        
        # Score margin model
        y_margin_pred = self.score_margin_model.predict(X_test)
        metrics['score_margin'] = {
            'mae': mean_absolute_error(y_margin_test, y_margin_pred),
            'rmse': np.sqrt(mean_squared_error(y_margin_test, y_margin_pred)),
        }
        
        # Individual score models
        y_home_pred = self.team_a_score_model.predict(X_test)
        y_away_pred = self.team_b_score_model.predict(X_test)
        
        metrics['home_score'] = {
            'mae': mean_absolute_error(y_home_test, y_home_pred),
            'rmse': np.sqrt(mean_squared_error(y_home_test, y_home_pred)),
        }
        
        metrics['away_score'] = {
            'mae': mean_absolute_error(y_away_test, y_away_pred),
            'rmse': np.sqrt(mean_squared_error(y_away_test, y_away_pred)),
        }
        
        return metrics
    
    def predict(
        self,
        team_a_features: Dict,
        team_b_features: Dict,
        is_home_away: bool = True
    ) -> MatchPrediction:
        """
        Predict match outcome for two teams
        
        Args:
            team_a_features: Dictionary with team A features (power_score_final, sos_norm, etc.)
            team_b_features: Dictionary with team B features
            is_home_away: If True, team_a is home, team_b is away
        
        Returns:
            MatchPrediction object
        """
        if not self.win_probability_model:
            raise ValueError("Model not trained. Call train() first or load a saved model.")
        
        # Build feature vector
        if is_home_away:
            home_features = team_a_features
            away_features = team_b_features
        else:
            home_features = team_b_features
            away_features = team_a_features
        
        feature_dict = {
            'home_power_score': home_features.get('power_score_final', 0.5) or 0.5,
            'away_power_score': away_features.get('power_score_final', 0.5) or 0.5,
            'power_score_diff': (home_features.get('power_score_final', 0.5) or 0.5) - 
                               (away_features.get('power_score_final', 0.5) or 0.5),
            'home_sos_norm': home_features.get('sos_norm', 0.5) or 0.5,
            'away_sos_norm': away_features.get('sos_norm', 0.5) or 0.5,
            'sos_diff': (home_features.get('sos_norm', 0.5) or 0.5) - 
                       (away_features.get('sos_norm', 0.5) or 0.5),
            'home_offense_norm': home_features.get('offense_norm', 0.5) or 0.5,
            'away_offense_norm': away_features.get('offense_norm', 0.5) or 0.5,
            'home_defense_norm': home_features.get('defense_norm', 0.5) or 0.5,
            'away_defense_norm': away_features.get('defense_norm', 0.5) or 0.5,
            'offense_vs_defense': (home_features.get('offense_norm', 0.5) or 0.5) - 
                                 (away_features.get('defense_norm', 0.5) or 0.5),
            'defense_vs_offense': (home_features.get('defense_norm', 0.5) or 0.5) - 
                                 (away_features.get('offense_norm', 0.5) or 0.5),
            'home_win_pct': home_features.get('win_percentage', 0.5) or 0.5,
            'away_win_pct': away_features.get('win_percentage', 0.5) or 0.5,
            'win_pct_diff': (home_features.get('win_percentage', 0.5) or 0.5) - 
                           (away_features.get('win_percentage', 0.5) or 0.5),
            'home_games_played': home_features.get('games_played', 0) or 0,
            'away_games_played': away_features.get('games_played', 0) or 0,
            'home_rank': home_features.get('rank_in_cohort_final', 1000) or 1000,
            'away_rank': away_features.get('rank_in_cohort_final', 1000) or 1000,
            'rank_diff': (away_features.get('rank_in_cohort_final', 1000) or 1000) - 
                        (home_features.get('rank_in_cohort_final', 1000) or 1000),
        }
        
        # Add recent form if available
        if 'recent_form' in home_features:
            feature_dict['home_recent_form'] = home_features.get('recent_form', 0.0)
        else:
            feature_dict['home_recent_form'] = 0.0
        
        if 'recent_form' in away_features:
            feature_dict['away_recent_form'] = away_features.get('recent_form', 0.0)
        else:
            feature_dict['away_recent_form'] = 0.0
        
        feature_dict['recent_form_diff'] = feature_dict['home_recent_form'] - feature_dict['away_recent_form']
        
        # Convert to DataFrame with correct feature order
        feature_vector = pd.DataFrame([feature_dict])
        feature_vector = feature_vector[[col for col in self.feature_names if col in feature_vector.columns]]
        # Fill missing features with 0
        for col in self.feature_names:
            if col not in feature_vector.columns:
                feature_vector[col] = 0.0
        
        feature_vector = feature_vector[self.feature_names].fillna(0).astype(float)
        
        # Predict
        win_prob_home = self.win_probability_model.predict_proba(feature_vector)[0, 1]
        predicted_margin = self.score_margin_model.predict(feature_vector)[0]
        predicted_home_score = self.team_a_score_model.predict(feature_vector)[0]
        predicted_away_score = self.team_b_score_model.predict(feature_vector)[0]
        
        # Ensure non-negative scores
        predicted_home_score = max(0, predicted_home_score)
        predicted_away_score = max(0, predicted_away_score)
        
        # Determine winner probabilities
        if is_home_away:
            win_prob_a = win_prob_home
            win_prob_b = 1 - win_prob_home
            score_a = predicted_home_score
            score_b = predicted_away_score
        else:
            win_prob_a = 1 - win_prob_home
            win_prob_b = win_prob_home
            score_a = predicted_away_score
            score_b = predicted_home_score
        
        # Determine predicted winner
        if win_prob_a > 0.55:
            predicted_winner = 'team_a'
        elif win_prob_a < 0.45:
            predicted_winner = 'team_b'
        else:
            predicted_winner = 'draw'
        
        # Confidence level
        prob_diff = abs(win_prob_a - 0.5)
        if prob_diff >= 0.20:
            confidence = 'high'
        elif prob_diff >= 0.10:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        return MatchPrediction(
            predicted_winner=predicted_winner,
            win_probability_a=win_prob_a,
            win_probability_b=win_prob_b,
            expected_score_a=score_a,
            expected_score_b=score_b,
            expected_margin=predicted_margin if is_home_away else -predicted_margin,
            confidence=confidence,
            model_features=feature_dict
        )
    
    def save(self, model_name: str = "match_predictor"):
        """Save trained models to disk"""
        if not self.win_probability_model:
            raise ValueError("No models to save. Train models first.")
        
        model_path = os.path.join(self.model_dir, f"{model_name}.pkl")
        metadata_path = os.path.join(self.model_dir, f"{model_name}_metadata.json")
        
        # Save models
        with open(model_path, 'wb') as f:
            pickle.dump({
                'win_probability_model': self.win_probability_model,
                'score_margin_model': self.score_margin_model,
                'team_a_score_model': self.team_a_score_model,
                'team_b_score_model': self.team_b_score_model,
                'feature_names': self.feature_names,
            }, f)
        
        # Save metadata
        with open(metadata_path, 'w') as f:
            json.dump(self.training_metadata, f, indent=2)
        
        print(f"Models saved to {model_path}")
        print(f"Metadata saved to {metadata_path}")
    
    def load(self, model_name: str = "match_predictor"):
        """Load trained models from disk"""
        model_path = os.path.join(self.model_dir, f"{model_name}.pkl")
        metadata_path = os.path.join(self.model_dir, f"{model_name}_metadata.json")
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found: {model_path}")
        
        # Load models
        with open(model_path, 'rb') as f:
            models = pickle.load(f)
            self.win_probability_model = models['win_probability_model']
            self.score_margin_model = models['score_margin_model']
            self.team_a_score_model = models['team_a_score_model']
            self.team_b_score_model = models['team_b_score_model']
            self.feature_names = models['feature_names']
        
        # Load metadata
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                self.training_metadata = json.load(f)
        
        print(f"Models loaded from {model_path}")
        return True

