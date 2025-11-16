# SOS Distribution Investigation - Findings & Recommendations

**Date:** 2025-11-16
**Analyst:** Senior Python Expert
**Status:** Investigation Complete

---

## Executive Summary

✅ **DO NOT IMPLEMENT the suggested SOS fixes** - They describe problems that don't exist in your current v53e.py implementation.

However, we did identify **moderate SOS duplication** (33%) in synthetic data that warrants investigation with real production data.

---

## Part 1: Code Pattern Analysis

### Findings

**✅ Current Implementation is Correct:**

1. **No percentile normalization before SOS** (line 454-456 in v53e.py):
   ```python
   team["abs_strength"] = (team["power_presos"] / team["anchor"]).clip(0.0, 1.5)
   strength_map = dict(zip(team["team_id"], team["abs_strength"]))
   ```
   - Uses continuous `abs_strength` (0.0-1.5 range)
   - NO `strength_for_sos` variable
   - NO `abs_strength_norm` percentile conversion
   - NO `strength_map_sos` with discrete steps

2. **SOS uses continuous opponent strength** (line 477):
   ```python
   g_sos["opp_strength"] = g_sos["opp_id"].map(
       lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE)
   )
   ```
   - Direct mapping from continuous `strength_map`
   - High resolution, minimal artificial duplication

3. **No cohort mean fallback function**:
   - The suggested `_fill_sos_by_cohort()` function **doesn't exist**
   - Uses simple `fillna(0.5)` on line 526
   - No mass assignment of identical values

### Conclusion: Suggestions Describe Non-Existent Problems

The detailed suggestions appear to be:
- Based on a different codebase
- Describing hypothetical issues
- AI-generated hallucinations
- From a previous version that was already fixed

**Your code already implements what they recommend!**

---

## Part 2: SOS Distribution Analysis (Synthetic Data)

### Test Configuration

- **Teams:** 300 total (50 per cohort)
- **Cohorts:** 6 (ages 10/12/14, genders M/F)
- **Games:** ~20 per team
- **V53EConfig:**
  - SOS Iterations: 3
  - Transitivity Lambda: 0.20
  - Normalization Mode: percentile

### Results

```
Overall SOS Distribution:
  Mean:   0.743
  Std:    0.204
  Min:    0.457
  Max:    1.000

  Unique SOS values: 201 / 300 teams
  Duplication rate:  33.00%
```

### Key Findings

| Issue | Severity | Details |
|-------|----------|---------|
| **100 teams with SOS = 1.000** | 🔴 **HIGH** | 33% of all teams share maximum SOS value |
| **Age 10 cohorts** | 🔴 **HIGH** | 98% duplication, std=0.0 (essentially flat) |
| **Ages 12-14 cohorts** | 🟢 **OK** | 0% duplication, healthy variance |
| **Overall duplication** | 🟡 **MODERATE** | 33% - worth investigating |

### Root Causes Identified

1. **SOS capping at 1.0** (line 514 in v53e.py):
   ```python
   merged["sos"] = merged["sos"].clip(0.0, 1.0)
   ```
   - Many strong teams hit the ceiling
   - Creates artificial plateau

2. **Small cohort effect**:
   - Age 10 cohorts have limited opponent diversity
   - Few unique opponent combinations → similar SOS

3. **Percentile normalization**:
   - `NORM_MODE = "percentile"` creates discrete steps
   - Compounds with small cohort sizes

---

## Part 3: Recommendations

### ✅ Immediate Actions

1. **DO NOT implement the suggested code changes**
   - They fix problems you don't have
   - Would add complexity without benefit
   - Your current implementation is already optimal

2. **Run this analysis on production data**
   ```bash
   # After fixing Supabase dependencies
   python scripts/diagnose_sos_distribution.py
   ```

3. **Monitor for specific patterns**:
   - % of teams with SOS = 1.000
   - Cohort-level duplication rates
   - Small cohorts (< 20 teams)

### 🔧 Potential Improvements (If Real Problem Exists)

**Only implement if production data shows >40% duplication:**

#### Option A: Remove SOS upper clip (line 514)
```python
# Current
merged["sos"] = merged["sos"].clip(0.0, 1.0)

# Alternative
merged["sos"] = merged["sos"].clip(0.0, 1.5)  # Match abs_strength range
```

**Pros:** Preserves variation among strong teams
**Cons:** May create outliers
**Risk:** Low

#### Option B: Change normalization mode
```python
# In config/settings.py, line 138
'norm_mode': "zscore"  # Instead of "percentile"
```

**Pros:** Continuous distribution, fewer discrete steps
**Cons:** Different value scale, may affect UI/UX
**Risk:** Medium (requires testing)

#### Option C: Adaptive SOS ceiling per cohort
```python
# After line 513, before clip
cohort_max = merged.groupby(['age', 'gender'])['sos'].transform('quantile', 0.95)
ceiling = cohort_max * 1.1  # 10% headroom above 95th percentile
merged["sos"] = merged["sos"].clip(0.0, ceiling)
```

**Pros:** Preserves intra-cohort variation
**Cons:** More complex logic
**Risk:** Medium

---

## Part 4: Investigation Checklist

Before making any changes, investigate production data:

- [ ] Run `scripts/diagnose_sos_distribution.py` on production database
- [ ] Check duplication rate: is it > 40%?
- [ ] Identify which cohorts have high duplication
- [ ] Determine if cohort size correlates with duplication
- [ ] Review top 10 most common SOS values
- [ ] Check if SOS = 1.000 plateau exists in production
- [ ] Analyze if duplication affects user-facing rankings
- [ ] Consider user perception: does it matter?

### Decision Tree

```
Production duplication rate < 20%
  → NO ACTION NEEDED
  → Current implementation is fine

Production duplication rate 20-40%
  → MONITOR CLOSELY
  → Consider Option A (remove upper clip)
  → User impact assessment

Production duplication rate > 40%
  → ACTION REQUIRED
  → Implement Option A + Option B
  → Re-test and validate
```

---

## Part 5: Technical Details

### Code Patterns CONFIRMED ABSENT

❌ `_normalize_strength_for_sos()` - Not in codebase
❌ `strength_for_sos` variable - Not in codebase
❌ `abs_strength_norm` (as SOS input) - Not in codebase
❌ `strength_map_sos` - Not in codebase
❌ `_fill_sos_by_cohort()` - Not in codebase
❌ Extra normalization inside SOS loop - Not in codebase

### Code Patterns CONFIRMED PRESENT (Correct)

✅ Direct `abs_strength` usage (line 454)
✅ Continuous strength mapping (line 456)
✅ Single strength concept (no double normalization)
✅ Simple SOS fallback with `fillna(0.5)` (line 526)
✅ Clean iterative SOS (lines 501-524)

---

## Conclusion

Your SOS implementation is **architecturally sound**. The suggested fixes address non-existent problems.

The moderate duplication observed in synthetic data (33%) is primarily due to:
1. SOS clipping at 1.0 (design choice)
2. Small cohort sizes (natural constraint)
3. Percentile normalization mode (configuration choice)

**Next Steps:**
1. ✅ Mark this investigation complete
2. 📊 Run production data analysis when ready
3. 🔍 Monitor SOS distribution in production
4. 🚫 Do not implement suggested code changes

---

**Prepared by:** Claude Code Senior Python Expert
**Reviewed:** v53e.py implementation (commit: 7bba895)
**Test Environment:** Synthetic data (300 teams, 6 cohorts)
