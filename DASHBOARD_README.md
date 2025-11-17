# PitchRank Settings Dashboard

An easy-to-use web-based UI for viewing all tunable parameters in the PitchRank ranking engine.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the Dashboard

```bash
streamlit run dashboard.py
```

The dashboard will automatically open in your default web browser at `http://localhost:8501`

## Features

### 📊 Comprehensive Parameter View
- **V53E Ranking Engine**: All 24 core parameters across 11 processing layers
- **Machine Learning Layer**: XGBoost and Random Forest hyperparameters
- **Matching Configuration**: Team name fuzzy matching settings
- **ETL & Data Processing**: Batch processing and cache settings
- **Age Groups**: Birth years and anchor scores for cross-age normalization

### 🎯 Organized Sections
Navigate easily between:
- **Overview**: Quick stats and critical parameters at a glance
- **V53E Ranking Engine**: Detailed view of all 11 layers
- **Machine Learning Layer**: ML enhancement settings
- **Matching Configuration**: Fuzzy matching parameters
- **ETL & Data**: Data processing and cache settings
- **Age Groups**: Age group configuration
- **Environment Variables**: Complete reference for all configurable env vars

### 💡 Key Capabilities
- View current values for all parameters
- See descriptions and units for each setting
- Quick validation (e.g., weights sum to 1.0)
- Copy-pasteable environment variable examples
- Visual charts for age group progression

## Critical Parameters

The dashboard highlights these critical tunable settings:

1. **SOS_TRANSITIVITY_LAMBDA** (0.20)
   - Controls strength of schedule transitivity
   - 0.20 = 80% direct opponents, 20% opponents of opponents

2. **RECENT_SHARE** (0.65)
   - Weight given to recent games vs older games
   - Higher = more emphasis on recent performance

3. **SHRINK_TAU** (8.0)
   - Bayesian shrinkage strength
   - Higher = more conservative estimates

4. **ML_ALPHA** (0.12)
   - Machine learning layer contribution
   - 0 = no ML, 1 = full ML

5. **Component Weights**
   - OFF_WEIGHT: 0.25
   - DEF_WEIGHT: 0.25
   - SOS_WEIGHT: 0.50
   - Must sum to 1.0

## Configuration Methods

All parameters support three configuration methods:

### 1. Environment Variables (Recommended)
```bash
export SOS_TRANSITIVITY_LAMBDA=0.25
export RECENT_SHARE=0.70
export ML_ALPHA=0.15
```

Or create a `.env` file:
```
SOS_TRANSITIVITY_LAMBDA=0.25
RECENT_SHARE=0.70
ML_ALPHA=0.15
```

### 2. Direct Config File Edit
Edit `config/settings.py`:
```python
RANKING_CONFIG = {
    'sos_transitivity_lambda': 0.25,
    'recent_share': 0.70,
    # ...
}
```

### 3. Programmatic Override
```python
from src.etl.v53e import V53EConfig

config = V53EConfig(
    SOS_TRANSITIVITY_LAMBDA=0.25,
    RECENT_SHARE=0.70
)
```

## Parameter Categories

### Layer-by-Layer Breakdown

**Layer 1: Time Window & Visibility**
- `WINDOW_DAYS`: 365 days
- `INACTIVE_HIDE_DAYS`: 180 days

**Layer 2: Game Limits & Outlier Protection**
- `MAX_GAMES_FOR_RANK`: 30 games
- `GOAL_DIFF_CAP`: 6 goals
- `OUTLIER_GUARD_ZSCORE`: 2.5σ

**Layer 3: Recency Weighting**
- `RECENT_K`: 15 games
- `RECENT_SHARE`: 0.65
- Tail dampening parameters

**Layer 4: Defense Ridge**
- `RIDGE_GA`: 0.25

**Layer 5: Adaptive K-Factor**
- `ADAPTIVE_K_ALPHA`: 0.5
- `ADAPTIVE_K_BETA`: 0.6
- `TEAM_OUTLIER_GUARD_ZSCORE`: 2.5σ

**Layer 6: Performance Adjustment**
- `PERFORMANCE_K`: 0.15
- `PERFORMANCE_DECAY_RATE`: 0.08
- Performance threshold and scaling

**Layer 7: Bayesian Shrinkage**
- `SHRINK_TAU`: 8.0

**Layer 8: Strength of Schedule**
- `SOS_ITERATIONS`: 3
- `SOS_TRANSITIVITY_LAMBDA`: 0.20
- `SOS_REPEAT_CAP`: 4

**Layer 10: Component Weights**
- `OFF_WEIGHT`: 0.25
- `DEF_WEIGHT`: 0.25
- `SOS_WEIGHT`: 0.50

**Layer 13: ML Enhancement**
- `ML_ALPHA`: 0.12
- XGBoost and Random Forest hyperparameters

## Troubleshooting

### Dashboard won't start
```bash
# Ensure streamlit is installed
pip install streamlit>=1.28.0

# Check if port 8501 is already in use
streamlit run dashboard.py --server.port 8502
```

### Missing dependencies
```bash
# Reinstall all requirements
pip install -r requirements.txt --upgrade
```

### Can't see updated values
- Environment variables require restarting the dashboard
- Config file changes also require restart
- Click "Always rerun" in Streamlit when prompted

## Advanced Usage

### Custom Port
```bash
streamlit run dashboard.py --server.port 8080
```

### Headless Mode (No Browser)
```bash
streamlit run dashboard.py --server.headless true
```

### External Access
```bash
streamlit run dashboard.py --server.address 0.0.0.0
```

## Related Files

- **Config File**: `config/settings.py`
- **V53E Engine**: `src/etl/v53e.py`
- **ML Layer**: `src/rankings/layer13_predictive_adjustment.py`
- **Calculator**: `src/rankings/calculator.py`

## Support

For issues or questions:
1. Check parameter descriptions in the dashboard
2. Review `config/settings.py` for current values
3. Consult `src/etl/v53e.py` for V53EConfig defaults

## Version

Dashboard Version: 2.0.0
PitchRank Version: 2.0.0
