# ML-Based Match Predictor

This document describes the new ML-based match prediction system that uses XGBoost to predict match outcomes. This system is designed to be tested against the existing hard-coded `matchPredictor.ts` implementation.

## Overview

The ML Match Predictor uses XGBoost models trained on historical game data to predict:
- Win probabilities for each team
- Expected scores
- Expected goal margin
- Match winner

This is a **standalone system** that does not modify any existing code. It can be trained, tested, and compared against the current hard-coded predictor.

## Features

### Rich Feature Engineering

The ML predictor uses a comprehensive set of features:

**Team Ranking Features:**
- Power score (final ML-adjusted score)
- Strength of Schedule (SOS) normalized
- Offense and Defense normalized scores
- Win percentage
- Games played
- Rank in cohort

**Matchup Features:**
- Power score differential
- SOS differential
- Offense vs Defense matchup
- Rank difference
- Recent form (last 5 games goal differential)

**Recent Form:**
- Average goal differential in last 5 games
- Captures team momentum and hot/cold streaks

### Multiple Models

The system uses separate XGBoost models for:
1. **Win Probability Model** (XGBClassifier): Predicts probability of home team winning
2. **Score Margin Model** (XGBRegressor): Predicts goal margin
3. **Home Score Model** (XGBRegressor): Predicts home team score
4. **Away Score Model** (XGBRegressor): Predicts away team score

## Installation

Ensure you have the required dependencies:

```bash
pip install xgboost scikit-learn pandas numpy
```

These should already be in `requirements.txt`.

## Usage

### 1. Train the ML Models

Train the XGBoost models on historical game data:

```bash
python scripts/train_ml_match_predictor.py
```

**Options:**
- `--lookback-days 365`: Number of days of historical data to use (default: 365)
- `--min-games 5`: Minimum games per team to include (default: 5)
- `--model-name match_predictor`: Name for saved model (default: match_predictor)
- `--test-size 0.2`: Proportion of data for testing (default: 0.2)

**Example:**
```bash
python scripts/train_ml_match_predictor.py --lookback-days 730 --min-games 10
```

The trained models will be saved to `models/match_predictor/match_predictor.pkl`.

### 2. Compare Against Existing Predictor

Compare the ML predictor against the hard-coded `matchPredictor.ts` logic:

```bash
python scripts/compare_predictors.py
```

**Options:**
- `--lookback-days 180`: Days of games to test on (default: 180)
- `--limit 1000`: Maximum number of games to test (default: 1000)
- `--model-name match_predictor`: Name of saved ML model (default: match_predictor)

**Example:**
```bash
python scripts/compare_predictors.py --lookback-days 90 --limit 500
```

This will:
1. Load the trained ML model
2. Fetch recent games from the database
3. Make predictions using both methods
4. Compare accuracy, MAE, RMSE, and other metrics
5. Generate a detailed comparison report
6. Save results to CSV

### 3. Use in Code

```python
from src.predictions.ml_match_predictor import MLMatchPredictor

# Load trained model
predictor = MLMatchPredictor()
predictor.load('match_predictor')

# Get team features (from rankings_view)
team_a_features = {
    'power_score_final': 0.65,
    'sos_norm': 0.72,
    'offense_norm': 0.68,
    'defense_norm': 0.61,
    'win_percentage': 0.75,
    'games_played': 25,
    'rank_in_cohort_final': 150,
    'recent_form': 1.2,  # Average goal diff in last 5 games
}

team_b_features = {
    'power_score_final': 0.58,
    'sos_norm': 0.65,
    'offense_norm': 0.62,
    'defense_norm': 0.59,
    'win_percentage': 0.65,
    'games_played': 22,
    'rank_in_cohort_final': 280,
    'recent_form': -0.3,
}

# Predict (team_a is home, team_b is away)
prediction = predictor.predict(team_a_features, team_b_features, is_home_away=True)

print(f"Predicted Winner: {prediction.predicted_winner}")
print(f"Win Probability A: {prediction.win_probability_a:.1%}")
print(f"Win Probability B: {prediction.win_probability_b:.1%}")
print(f"Expected Score: {prediction.expected_score_a:.1f} - {prediction.expected_score_b:.1f}")
print(f"Expected Margin: {prediction.expected_margin:+.1f}")
print(f"Confidence: {prediction.confidence}")
```

## Model Architecture

### Feature Engineering

The predictor builds features from:
- **Team Rankings**: Power scores, SOS, offense/defense, win percentage
- **Matchup Features**: Differences and interactions between teams
- **Recent Form**: Last 5 games performance (goal differential)
- **Historical Context**: Games played, rank positions

### Model Training

1. **Data Preparation**: 
   - Fetch games with valid scores
   - Fetch current team rankings
   - Build team game histories
   - Extract features for each game

2. **Train/Test Split**: 
   - 80% training, 20% testing (configurable)
   - Random state for reproducibility

3. **Model Training**:
   - XGBoost with optimized hyperparameters
   - Separate models for different prediction tasks
   - Cross-validation metrics

4. **Evaluation**:
   - Direction accuracy (winner prediction)
   - MAE/RMSE for score predictions
   - Log loss for probability calibration

## Comparison Metrics

The comparison script evaluates:

1. **Direction Accuracy**: % of games where winner is correctly predicted
2. **Score Margin MAE**: Mean absolute error in goal margin prediction
3. **Score Margin RMSE**: Root mean squared error
4. **Individual Score MAE**: Accuracy of home/away score predictions
5. **Confidence Breakdown**: Accuracy by confidence level

## Model Persistence

Trained models are saved to:
- `models/match_predictor/match_predictor.pkl`: Serialized models
- `models/match_predictor/match_predictor_metadata.json`: Training metadata

Models can be loaded and used without retraining.

## Advantages of ML Approach

1. **Learns from Data**: Automatically discovers patterns and feature interactions
2. **Non-linear Relationships**: Captures complex relationships between features
3. **Feature Importance**: Can identify which features matter most
4. **Adaptive**: Can be retrained as more data becomes available
5. **Comprehensive**: Uses all available team and matchup information

## Limitations

1. **Requires Training Data**: Needs sufficient historical games to train
2. **Model Complexity**: Less interpretable than hard-coded rules
3. **Training Time**: Initial training takes time (but models can be reused)
4. **Data Quality**: Performance depends on quality of rankings and game data

## Next Steps

1. **Train Initial Model**: Run training script on historical data
2. **Compare Performance**: Use comparison script to evaluate vs existing predictor
3. **Iterate**: Adjust features, hyperparameters, or training data based on results
4. **Deploy**: If ML predictor performs better, integrate into production

## Troubleshooting

**Model not found error:**
- Train the model first: `python scripts/train_ml_match_predictor.py`

**No games found:**
- Check database connection and SUPABASE_URL/SUPABASE_SERVICE_KEY
- Verify games exist in the database

**Poor performance:**
- Try training on more historical data (increase `--lookback-days`)
- Check feature quality (ensure rankings are up to date)
- Adjust hyperparameters in `ml_match_predictor.py`

**XGBoost import error:**
- Install XGBoost: `pip install xgboost`

## Files

- `src/predictions/ml_match_predictor.py`: Main ML predictor class
- `scripts/train_ml_match_predictor.py`: Training script
- `scripts/compare_predictors.py`: Comparison script
- `models/match_predictor/`: Directory for saved models



