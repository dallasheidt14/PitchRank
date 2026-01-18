# Prediction Engine Maintenance Guide

## Overview

The calibrated prediction engine uses multiple JSON parameter files that need periodic updates as new game data accumulates. This guide covers when and how to maintain the system.

---

## Maintenance Schedule

### Regular Maintenance (Recommended)

**Frequency:** Every 3-6 months or after ~50,000+ new games

**Why:** As more games are played, the calibration parameters may drift. Regular updates ensure predictions stay accurate.

### After Major Changes

Re-calibrate if you:
- Change ranking algorithm significantly
- Add new features to the prediction model
- Notice prediction accuracy declining
- Have a full season of new data

---

## Maintenance Steps

### Step 1: Run Full Backtest

```bash
# Generate fresh backtest data
python scripts/backtest_predictor.py --lookback-days 365 --limit None --no-charts
```

**What it does:**
- Fetches all games from last 365 days
- Makes predictions using current model
- Generates `data/backtest_results/raw_backtest.csv`
- Expected: 50,000+ games

**Time:** 1-4 hours depending on data volume

**Output:** `data/backtest_results/raw_backtest.csv`

---

### Step 2: Run Calibration Scripts

After backtest completes, run all calibration scripts:

```bash
# Option 1: Run individually
python scripts/calibrate_probability.py
python scripts/calibrate_margin_v2.py
python scripts/calibrate_confidence_v2.py

# Option 2: Use automation script (if available)
python scripts/run_calibration_v2.py
```

**What each script does:**

#### `calibrate_probability.py`
- Tunes `SENSITIVITY` constant for win probability calibration
- Ensures 60% predicted win rate ≈ 60% actual win rate
- **Output:** `data/calibration/probability_parameters.json`

#### `calibrate_margin_v2.py`
- Optimizes `margin_scale` and per-age `margin_mult` values
- Minimizes mean absolute margin error
- **Output:** `data/calibration/margin_parameters_v2.json`

#### `calibrate_confidence_v2.py`
- Fits logistic regression weights for confidence calculation
- Improves confidence accuracy by 20-40%
- **Output:** `data/calibration/confidence_parameters_v2.json`

**Time:** 10-30 minutes total

---

### Step 3: Copy JSONs to Frontend

```powershell
# Copy calibrated parameters to frontend public directory
Copy-Item "data\calibration\probability_parameters.json" -Destination "frontend\public\data\calibration\" -Force
Copy-Item "data\calibration\margin_parameters_v2.json" -Destination "frontend\public\data\calibration\" -Force
Copy-Item "data\calibration\confidence_parameters_v2.json" -Destination "frontend\public\data\calibration\" -Force
```

**Why:** Frontend needs these files to load calibrated parameters at runtime.

---

### Step 4: Validate Changes

**Check calibration outputs:**

1. **Probability Calibration:**
   - Open `data/calibration/probability_parameters.json`
   - Verify `sensitivity` is reasonable (typically 4.0-5.0)
   - Check `calibration_error` is low (< 0.15)

2. **Margin Calibration:**
   - Open `data/calibration/margin_parameters_v2.json`
   - Verify `margin_scale` is reasonable (typically 0.5-1.0)
   - Check `overall_mae` improved or stayed similar

3. **Confidence Calibration:**
   - Open `data/calibration/confidence_parameters_v2.json`
   - Verify `accuracy_improvement` is positive
   - Check weights are reasonable

**Test frontend:**
- Deploy changes
- Test a few match predictions
- Verify confidence levels look reasonable
- Check that predictions load without errors

---

### Step 5: Run Cross-Validation (Optional but Recommended)

```bash
python scripts/cross_validate_predictor.py --lookback-days 365
```

**What it does:**
- 5-fold time-split validation
- Tests stability across different time periods
- **Output:** `data/calibration/cross_validation_results.json`

**When to run:**
- After major calibration updates
- When investigating prediction stability
- Before deploying significant changes

---

## Monitoring & Validation

### Key Metrics to Track

1. **Prediction Accuracy**
   - Overall win/loss prediction accuracy (target: 70%+)
   - Accuracy by probability buckets (should match predicted rates)

2. **Margin Error**
   - Mean Absolute Error (MAE) - target: < 2.5 goals
   - Per-age-group MAE

3. **Confidence Accuracy**
   - High confidence predictions should be correct 75%+
   - Medium confidence predictions should be correct 60-70%
   - Low confidence predictions should be correct 50-60%

4. **Calibration Error**
   - Probability calibration error (target: < 0.15)
   - Should decrease after re-calibration

### How to Monitor

**Option 1: Manual Spot Checks**
- Periodically check predictions for known matchups
- Compare predicted vs actual outcomes
- Look for systematic biases

**Option 2: Automated Monitoring Script** (Future Enhancement)
```bash
# Could create: scripts/monitor_predictions.py
# Runs weekly, compares recent predictions to outcomes
# Alerts if accuracy drops below thresholds
```

---

## File Structure

### Calibration Files (Backend)
```
data/calibration/
├── probability_parameters.json      # SENSITIVITY tuning
├── margin_parameters_v2.json        # Margin multipliers
├── confidence_parameters_v2.json    # Confidence weights
└── cross_validation_results.json     # Stability metrics
```

### Frontend Files (Public)
```
frontend/public/data/calibration/
├── probability_parameters.json      # Copied from backend
├── margin_parameters_v2.json        # Copied from backend
├── confidence_parameters_v2.json    # Copied from backend
└── age_group_parameters.json        # From calibrate_age_groups.py
```

### Backtest Results
```
data/backtest_results/
├── raw_backtest.csv                  # Full prediction results
├── bucket_accuracy.csv               # Accuracy by probability bucket
├── margin_error.csv                  # Margin prediction errors
├── age_accuracy.csv                  # Accuracy by age group
└── *.png                             # Optional charts
```

---

## Troubleshooting

### Issue: Calibration Scripts Fail

**Check:**
- `raw_backtest.csv` exists and has data
- File has required columns: `predicted_winner`, `actual_winner`, `predicted_prob`, etc.
- Python dependencies installed: `scipy`, `sklearn`, `pandas`, `numpy`

**Fix:**
```bash
pip install scipy scikit-learn pandas numpy
```

### Issue: Frontend Not Loading Parameters

**Check:**
- JSON files exist in `frontend/public/data/calibration/`
- Files are valid JSON (no syntax errors)
- Browser console for 404 errors

**Fix:**
- Re-copy files from backend
- Validate JSON syntax
- Clear browser cache

### Issue: Predictions Seem Off

**Check:**
- When was last calibration? (check file modification dates)
- Has ranking algorithm changed significantly?
- Are there new age groups or data quality issues?

**Fix:**
- Re-run full calibration cycle
- Check `cross_validation_results.json` for stability issues
- Review recent backtest accuracy metrics

---

## Best Practices

### 1. Version Control
- Commit calibration JSONs to git
- Tag releases with calibration dates
- Document any manual parameter adjustments

### 2. Backup Before Changes
```bash
# Backup current parameters
cp -r data/calibration data/calibration_backup_$(date +%Y%m%d)
cp -r frontend/public/data/calibration frontend/public/data/calibration_backup_$(date +%Y%m%d)
```

### 3. Gradual Rollout
- Test new parameters on staging first
- Compare old vs new predictions side-by-side
- Monitor for 1-2 weeks before full deployment

### 4. Document Changes
- Note what changed in calibration results
- Record any manual adjustments made
- Track prediction accuracy before/after

---

## Quick Reference

### Full Calibration Cycle (3-6 months)

```bash
# 1. Backtest
python scripts/backtest_predictor.py --lookback-days 365 --limit None --no-charts

# 2. Calibrate
python scripts/calibrate_probability.py
python scripts/calibrate_margin_v2.py
python scripts/calibrate_confidence_v2.py

# 3. Copy to frontend
Copy-Item "data\calibration\*.json" -Destination "frontend\public\data\calibration\" -Force

# 4. Validate
python scripts/cross_validate_predictor.py --lookback-days 365

# 5. Deploy
git add frontend/public/data/calibration/*.json
git commit -m "Update prediction engine calibration - $(date +%Y-%m-%d)"
git push
```

### Quick Check (Monthly)

```bash
# Run small backtest to check accuracy
python scripts/backtest_predictor.py --lookback-days 90 --limit 10000

# Review accuracy metrics
# If accuracy drops significantly, run full calibration
```

---

## Future Enhancements

### Automated Monitoring
- Weekly accuracy reports
- Alert when calibration needed
- Dashboard showing prediction metrics

### Continuous Calibration
- Auto-run calibration monthly
- A/B test new parameters
- Gradual rollout of improvements

### Enhanced Validation
- Real-time prediction tracking
- Outcome comparison automation
- Performance regression detection

---

## Summary Checklist

**Every 3-6 months:**
- [ ] Run full backtest (365 days)
- [ ] Run all calibration scripts
- [ ] Copy JSONs to frontend
- [ ] Run cross-validation
- [ ] Validate changes
- [ ] Deploy to production
- [ ] Monitor for 1-2 weeks

**Monthly:**
- [ ] Quick accuracy check
- [ ] Review prediction quality
- [ ] Check for data quality issues

**When issues arise:**
- [ ] Check last calibration date
- [ ] Review backtest results
- [ ] Compare old vs new parameters
- [ ] Re-run calibration if needed


















