"""
Python port of TypeScript matchPredictor.ts
Mirrors exact constants and formulas from frontend/lib/matchPredictor.ts

Source: frontend/lib/matchPredictor.ts
Last synced: 2025-01-XX
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Base feature weights (optimized for close matchups - 74.7% accuracy)
# Source: matchPredictor.ts lines 20-25
BASE_WEIGHTS = {
    'POWER_SCORE': 0.50,  # Base strength
    'SOS': 0.18,          # Schedule strength
    'RECENT_FORM': 0.28,  # Last 5 games momentum - KEY PREDICTOR for close games!
    'MATCHUP': 0.04,      # Offense vs defense
}

# Adaptive weights for large skill gaps (>0.15 power diff = 15 percentile points)
# Source: matchPredictor.ts lines 28-33
BLOWOUT_WEIGHTS = {
    'POWER_SCORE': 0.75,  # Power dominates in mismatches
    'SOS': 0.10,          # Schedule matters less
    'RECENT_FORM': 0.12,  # Recent form matters less
    'MATCHUP': 0.03,      # Matchup details matter less
}

# Thresholds for adaptive weighting
# Source: matchPredictor.ts lines 36-39
SKILL_GAP_THRESHOLDS = {
    'LARGE': 0.15,   # >15 percentile points = large gap, use blowout weights
    'MEDIUM': 0.10,  # 10-15 percentile points = transition zone
}

# Prediction parameters
# Source: matchPredictor.ts lines 42-44
SENSITIVITY = 4.5
MARGIN_COEFFICIENT = 8.0
RECENT_GAMES_COUNT = 5

# Confidence thresholds (used in old logic, kept for compatibility)
# Source: matchPredictor.ts lines 47-51
CONFIDENCE_THRESHOLDS = {
    'HIGH': 0.70,    # >70% probability = high confidence
    'MEDIUM': 0.60,  # 60-70% = medium confidence
}


@dataclass
class TeamRanking:
    """Team ranking data structure matching TeamWithRanking interface"""
    team_id_master: str
    power_score_final: Optional[float] = None
    sos_norm: Optional[float] = None
    offense_norm: Optional[float] = None
    defense_norm: Optional[float] = None
    age: Optional[int] = None
    games_played: int = 0


@dataclass
class Game:
    """Game data structure matching Game interface"""
    id: str
    home_team_master_id: Optional[str]
    away_team_master_id: Optional[str]
    home_score: Optional[int]
    away_score: Optional[int]
    game_date: str


@dataclass
class MatchPrediction:
    """Match prediction result matching MatchPrediction interface"""
    predicted_winner: str  # 'team_a' | 'team_b' | 'draw'
    win_probability_a: float
    win_probability_b: float
    expected_score: Dict[str, float]  # {'teamA': float, 'teamB': float}
    expected_margin: float
    confidence: str  # 'high' | 'medium' | 'low'
    components: Dict[str, float]
    form_a: float
    form_b: float


def sigmoid(x: float) -> float:
    """
    Sigmoid function for win probability
    Source: matchPredictor.ts line 148-150
    """
    return 1.0 / (1.0 + np.exp(-x))


def calculate_recent_form(
    team_id: str,
    all_games: List[Game],
    n: int = RECENT_GAMES_COUNT
) -> float:
    """
    Calculate recent form from game history
    Returns average goal differential in last N games, weighted by sample size
    
    Sample size weighting prevents overconfidence from small samples:
    - 1 game out of 5 needed = 20% weight
    - 3 games out of 5 needed = 60% weight
    - 5+ games out of 5 needed = 100% weight
    
    Source: matchPredictor.ts lines 62-100
    """
    # Get team's recent games
    team_games = [
        g for g in all_games
        if (g.home_team_master_id == team_id or g.away_team_master_id == team_id)
    ]
    
    # Sort by date descending (most recent first)
    team_games.sort(key=lambda g: g.game_date, reverse=True)
    team_games = team_games[:n]
    
    if len(team_games) == 0:
        return 0.0
    
    # Calculate average goal differential
    total_goal_diff = 0.0
    games_with_scores = 0
    
    for game in team_games:
        is_home = game.home_team_master_id == team_id
        team_score = game.home_score if is_home else game.away_score
        opp_score = game.away_score if is_home else game.home_score
        
        if team_score is not None and opp_score is not None:
            total_goal_diff += (team_score - opp_score)
            games_with_scores += 1
    
    if games_with_scores == 0:
        return 0.0
    
    # Calculate average goal differential
    avg_goal_diff = total_goal_diff / games_with_scores
    
    # Weight by sample size to reduce noise from small samples
    # This prevents a team with 1 game from being treated as reliably as a team with 5 games
    sample_size_weight = games_with_scores / n
    
    return avg_goal_diff * sample_size_weight


def normalize_recent_form(goal_diff: float) -> float:
    """
    Normalize recent form to 0-1 scale using sigmoid
    Sigmoid normalization: goalDiff of +2 -> ~0.73, -2 -> ~0.27
    
    Source: matchPredictor.ts lines 105-108
    """
    return 1.0 / (1.0 + np.exp(-goal_diff * 0.5))


def get_adaptive_weights(power_diff: float) -> Dict[str, float]:
    """
    Calculate adaptive weights based on power score differential
    Large skill gaps → power score dominates
    Close matchups → recent form and SOS matter more
    
    Source: matchPredictor.ts lines 115-143
    """
    abs_power_diff = abs(power_diff)
    
    # Small gap (<10 percentile points): use base weights optimized for close games
    if abs_power_diff < SKILL_GAP_THRESHOLDS['MEDIUM']:
        return BASE_WEIGHTS.copy()
    
    # Large gap (>15 percentile points): use blowout weights
    if abs_power_diff >= SKILL_GAP_THRESHOLDS['LARGE']:
        return BLOWOUT_WEIGHTS.copy()
    
    # Transition zone (10-15 percentile points): interpolate between base and blowout
    transition_progress = (
        (abs_power_diff - SKILL_GAP_THRESHOLDS['MEDIUM']) /
        (SKILL_GAP_THRESHOLDS['LARGE'] - SKILL_GAP_THRESHOLDS['MEDIUM'])
    )
    
    return {
        'POWER_SCORE': BASE_WEIGHTS['POWER_SCORE'] +
            (BLOWOUT_WEIGHTS['POWER_SCORE'] - BASE_WEIGHTS['POWER_SCORE']) * transition_progress,
        'SOS': BASE_WEIGHTS['SOS'] +
            (BLOWOUT_WEIGHTS['SOS'] - BASE_WEIGHTS['SOS']) * transition_progress,
        'RECENT_FORM': BASE_WEIGHTS['RECENT_FORM'] +
            (BLOWOUT_WEIGHTS['RECENT_FORM'] - BASE_WEIGHTS['RECENT_FORM']) * transition_progress,
        'MATCHUP': BASE_WEIGHTS['MATCHUP'] +
            (BLOWOUT_WEIGHTS['MATCHUP'] - BASE_WEIGHTS['MATCHUP']) * transition_progress,
    }


def get_league_average_goals(age: Optional[int]) -> float:
    """
    Get age-adjusted league average goals per team
    Based on empirical data from youth soccer:
    - U10-U11: ~2.0 goals/team
    - U12-U14: ~2.5 goals/team
    - U15-U18: ~2.8 goals/team
    - U19+: ~3.0 goals/team
    
    Source: matchPredictor.ts lines 160-167
    """
    if age is None:
        return 2.5  # Default to middle range if age unknown
    
    if age <= 11:
        return 2.0      # U10-U11
    if age <= 14:
        return 2.5      # U12-U14
    if age <= 18:
        return 2.8      # U15-U18
    return 3.0         # U19+


def predict_match(
    team_a: TeamRanking,
    team_b: TeamRanking,
    all_games: List[Game]
) -> MatchPrediction:
    """
    Predict match outcome with enhanced model using adaptive weights
    
    Source: matchPredictor.ts lines 202-302
    """
    # 1. Base power score differential
    power_diff = (team_a.power_score_final or 0.5) - (team_b.power_score_final or 0.5)
    
    # 2. Calculate adaptive weights based on skill gap
    weights = get_adaptive_weights(power_diff)
    
    # 3. SOS differential
    sos_diff = (team_a.sos_norm or 0.5) - (team_b.sos_norm or 0.5)
    
    # 4. Recent form
    form_a = calculate_recent_form(team_a.team_id_master, all_games)
    form_b = calculate_recent_form(team_b.team_id_master, all_games)
    form_diff_raw = form_a - form_b
    form_diff_norm = normalize_recent_form(form_diff_raw) - 0.5
    
    # 5. Offense vs Defense matchup asymmetry
    offense_a = team_a.offense_norm or 0.5
    defense_a = team_a.defense_norm or 0.5
    offense_b = team_b.offense_norm or 0.5
    defense_b = team_b.defense_norm or 0.5
    
    matchup_advantage = (offense_a - defense_b) - (offense_b - defense_a)
    
    # 6. Composite differential (weighted combination with adaptive weights)
    composite_diff = (
        weights['POWER_SCORE'] * power_diff +
        weights['SOS'] * sos_diff +
        weights['RECENT_FORM'] * form_diff_norm +
        weights['MATCHUP'] * matchup_advantage
    )
    
    # 7. Win probability
    win_prob_a = sigmoid(SENSITIVITY * composite_diff)
    win_prob_b = 1.0 - win_prob_a
    
    # 8. Expected goal margin with non-linear amplification for blowouts
    # For close games: use base coefficient
    # For blowouts: amplify margin to reflect larger skill gaps
    abs_composite_diff = abs(composite_diff)
    margin_multiplier = 1.0
    
    if abs_composite_diff > 0.12:
        # Large gap (>0.12): amplify margin by 2.5x for realistic blowouts
        margin_multiplier = 2.5
    elif abs_composite_diff > 0.08:
        # Medium gap (0.08-0.12): interpolate from 1.0x to 2.5x
        transition_progress = (abs_composite_diff - 0.08) / (0.12 - 0.08)
        margin_multiplier = 1.0 + (1.5 * transition_progress)
    
    expected_margin = composite_diff * MARGIN_COEFFICIENT * margin_multiplier
    
    # 9. Expected scores using age-adjusted league average
    # Use teamA's age (matchups are typically same-age groups)
    league_avg_goals = get_league_average_goals(team_a.age)
    expected_score_a = max(0.0, league_avg_goals + (expected_margin / 2.0))
    expected_score_b = max(0.0, league_avg_goals - (expected_margin / 2.0))
    
    # 10. Predicted winner
    # Always pick the favored team (no draw threshold - draws only occur ~16% of the time)
    predicted_winner = 'team_a' if win_prob_a >= 0.5 else 'team_b'
    
    # 11. Confidence level (old logic - will be replaced by variance-based confidence in frontend)
    prob_diff = abs(win_prob_a - 0.5)
    if prob_diff >= (CONFIDENCE_THRESHOLDS['HIGH'] - 0.5):
        confidence = 'high'
    elif prob_diff >= (CONFIDENCE_THRESHOLDS['MEDIUM'] - 0.5):
        confidence = 'medium'
    else:
        confidence = 'low'
    
    return MatchPrediction(
        predicted_winner=predicted_winner,
        win_probability_a=win_prob_a,
        win_probability_b=win_prob_b,
        expected_score={'teamA': expected_score_a, 'teamB': expected_score_b},
        expected_margin=expected_margin,
        confidence=confidence,
        components={
            'powerDiff': power_diff,
            'sosDiff': sos_diff,
            'formDiffRaw': form_diff_raw,
            'formDiffNorm': form_diff_norm,
            'matchupAdvantage': matchup_advantage,
            'compositeDiff': composite_diff,
        },
        form_a=form_a,
        form_b=form_b,
    )







