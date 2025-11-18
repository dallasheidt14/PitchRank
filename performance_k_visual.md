# What Does Increasing PERFORMANCE_K Actually Do?

## Quick Answer

**PERFORMANCE_K controls how much over/underperformance affects your final power score.**

Increasing from **0.15 to 0.17** means:
- Teams that **exceed expectations** get **13% more reward**
- Teams that **disappoint expectations** get **13% more penalty**
- This affects **ALL teams**, not just PRFC and Dynamos

---

## The Math

### Current System (PERFORMANCE_K = 0.15)

```
powerscore_core = 0.25×OFF + 0.25×DEF + 0.50×SOS + perf_centered × 0.15
```

**Performance range:**
- Best team (100th percentile): `perf_centered = +0.5` → gets `+0.5 × 0.15 = +0.075` boost
- Worst team (0th percentile): `perf_centered = -0.5` → gets `-0.5 × 0.15 = -0.075` penalty
- **Maximum swing: 0.150 between best and worst**

---

### Proposed System (PERFORMANCE_K = 0.17)

```
powerscore_core = 0.25×OFF + 0.25×DEF + 0.50×SOS + perf_centered × 0.17
```

**Performance range:**
- Best team: `+0.5 × 0.17 = +0.085` boost
- Worst team: `-0.5 × 0.17 = -0.085` penalty
- **Maximum swing: 0.170 between best and worst**

**Difference: +0.020 more swing (13.3% increase)**

---

## What "Performance" Measures

The performance metric (`perf_centered`) measures whether a team performs **better or worse than expected** based on team strength vs opponent strength.

### How it's calculated:

```python
# For each game:
expected_margin = PERFORMANCE_GOAL_SCALE × (team_power - opp_power)
actual_margin = goals_for - goals_against
performance = actual_margin - expected_margin

# If you exceed expectations → positive performance
# If you disappoint → negative performance
```

### Example:

| Team | Opponent | Expected Result | Actual Result | Performance |
|------|----------|----------------|---------------|-------------|
| **Strong team** | Weak opponent | Win by 3 goals | Win by 2 goals | **Underperforming** (-1) |
| **Weak team** | Strong opponent | Lose by 3 goals | Lose by 1 goal | **Overperforming** (+2) |

---

## Why PRFC Likely Has Negative Performance

**PRFC Scottsdale:**
- Plays weak schedule (SOS 0.745)
- Scores lots of goals → high offense (0.863)
- This inflates their `power_presos` (used to calculate expected margins)
- When playing weak opponents:
  - **Expected:** Win by large margin (inflated power >> weak opponent)
  - **Actual:** Win by good margin, but not as large as inflated power suggests
  - **Result:** Negative performance (underperforming inflated expectations)

---

## Why Dynamos Likely Has Positive Performance

**Dynamos SC:**
- Plays strong schedule (SOS 0.850)
- Scores fewer goals → low offense (0.590)
- This deflates their `power_presos`
- When playing strong opponents:
  - **Expected:** Small margins or losses (deflated power ≈ strong opponent)
  - **Actual:** Competitive results, maybe even wins
  - **Result:** Positive performance (overperforming deflated expectations)

---

## Impact on PRFC vs Dynamos

### Hypothetical (we don't have actual perf_centered values):

| Team | perf_centered | Current (×0.15) | Proposed (×0.17) | Change |
|------|---------------|-----------------|------------------|--------|
| **PRFC** | -0.10 (underperforming) | -0.0150 | -0.0170 | -0.0020 worse |
| **Dynamos** | +0.15 (overperforming) | +0.0225 | +0.0255 | +0.0030 better |
| **Gap** | — | 0.0375 | 0.0425 | **+0.0050 more swing** |

**Current gap:** PRFC ahead by 0.000094
**After change:** Dynamos would be ahead by ~0.005

---

## The Problem: It Affects EVERYONE

Increasing PERFORMANCE_K doesn't just affect PRFC and Dynamos. It changes the formula for **all 50,000+ teams** in your database!

### Teams that would benefit:
- ✓ Teams playing tough schedules who compete well (like Dynamos)
- ✓ Clutch teams that exceed expectations in big games
- ✓ Underdog teams that punch above their weight

### Teams that would be penalized:
- ✗ Teams playing weak schedules who coast (like PRFC)
- ✗ Teams that underperform in key moments
- ✗ Overrated teams whose results don't match their metrics

---

## Current Formula Balance

With PERFORMANCE_K = 0.15:

| Component | Weight | Max Contribution |
|-----------|--------|------------------|
| **Offense** | 25% | 0.25 (if offense_norm = 1.0) |
| **Defense** | 25% | 0.25 (if defense_norm = 1.0) |
| **SOS** | 50% | 0.50 (if sos_norm = 1.0) |
| **Performance** | ~15% | 0.075 (if perf_centered = 0.5) |

**Total:** Components roughly add to 100% for an average team (though performance is additive, not part of the 100%)

---

With PERFORMANCE_K = 0.17:

| Component | Weight | Max Contribution |
|-----------|--------|------------------|
| **Offense** | 25% | 0.25 |
| **Defense** | 25% | 0.25 |
| **SOS** | 50% | 0.50 |
| **Performance** | **~17%** | **0.085** |

**This makes performance 13% more influential relative to the other components.**

---

## Analogy

Think of your ranking system like a recipe:

**Current recipe:**
- 1/4 cup offense
- 1/4 cup defense
- 1/2 cup SOS
- 3 tablespoons performance

**Proposed recipe:**
- 1/4 cup offense
- 1/4 cup defense
- 1/2 cup SOS
- **3.4 tablespoons performance** (+13% more)

**The question:** Do you want performance to have more influence across ALL rankings, or just for cases like PRFC vs Dynamos?

---

## Recommendations

### ✅ Option A: Accept the Current System

**Why:**
- The 0.000094 gap is negligible (essentially a tie)
- System is already 99% effective at correcting the double-counting
- No unintended consequences

---

### ⚠️ Option B: Increase PERFORMANCE_K to 0.17

**Why:**
- Rewards teams that exceed expectations more
- Penalizes teams that underperform more
- Might flip close matchups where performance matters

**Risk:**
- Affects all 50,000+ teams, not just this one case
- Might overcorrect in other scenarios
- Changes the fundamental balance of your formula

---

### 🔧 Option C: Opponent-Adjusted Offense/Defense

**Why:**
- Fixes the root cause instead of amplifying a correction mechanism
- Most principled approach
- Would eliminate double-counting at the source

**Risk:**
- Requires core algorithm changes
- More complex implementation

---

## What I Would Do

**Extract the actual `perf_centered` values for PRFC and Dynamos first!**

If you find that:
- PRFC has `perf_centered = -0.10` (underperforming)
- Dynamos has `perf_centered = +0.15` (overperforming)

Then **your system is already working as designed**. The performance metric is correctly identifying that PRFC is underperforming their inflated metrics and Dynamos is overperforming their deflated metrics.

In that case, **don't change anything** - the 0.000094 gap is just noise, and they're essentially tied.

---

## How to Extract perf_centered Values

Query your database to get the actual performance values:

```sql
SELECT
  team_name,
  power_score_final,
  sos_norm,
  offense_norm,
  defense_norm,
  perf_centered,     -- This is the key value!
  games_played
FROM rankings_full
WHERE team_name IN (
  'PRFC Scottsdale 14B Pre-Academy',
  'Dynamos SC 14B SC'
);
```

Once you have those values, you can make an informed decision about whether to change PERFORMANCE_K.
