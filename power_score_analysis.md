# Power Score Analysis: PRFC Scottsdale vs Dynamos SC

## The Question
How could PRFC Scottsdale 14B Pre-Academy have a higher power score (rank #109) than Dynamos SC 14B SC (rank #111) when Dynamos has a significantly harder schedule (SOS: 0.8499 vs 0.7451)?

## The Data

### PRFC Scottsdale 14B Pre-Academy
- **Power Score Final:** 0.469727
- **Rank:** #109 nationally, #4 in Arizona
- **SOS Norm:** 0.7451 (74.5th percentile)
- **Offense Norm:** 0.8630 (86.3rd percentile) ⭐
- **Defense Norm:** 0.9245 (92.5th percentile) ⭐
- **Games Played:** 30
- **Win Percentage:** 64.47%

### Dynamos SC 14B SC
- **Power Score Final:** 0.469633
- **Rank:** #111 nationally, #5 in Arizona
- **SOS Norm:** 0.8499 (85.0th percentile) ⭐
- **Offense Norm:** 0.5902 (59.0th percentile)
- **Defense Norm:** 0.9101 (91.0th percentile)
- **Games Played:** 30
- **Win Percentage:** 69.23%

---

## The Breakdown

### Power Score Formula (from `/home/user/PitchRank/src/etl/v53e.py:571-576`)

```python
powerscore_core = (
    0.25 × offense_norm      # Offense: 25%
    + 0.25 × defense_norm    # Defense: 25%
    + 0.50 × sos_norm        # SOS: 50%
    + perf_centered × 0.15   # Performance: ~15% additive
)
```

---

## Component Contributions

### 1. Strength of Schedule (50% weight)

| Team | SOS Norm | × Weight | Contribution |
|------|----------|----------|--------------|
| Dynamos SC | 0.8499 | × 0.50 | **0.4250** |
| PRFC Scottsdale | 0.7451 | × 0.50 | **0.3726** |
| **Advantage** | Dynamos +0.1048 | | **Dynamos +0.0524** |

**Dynamos has a 10.5% harder schedule, giving them a +0.0524 advantage (50% of the difference)**

---

### 2. Offense (25% weight)

| Team | Offense Norm | × Weight | Contribution |
|------|--------------|----------|--------------|
| PRFC Scottsdale | 0.8630 | × 0.25 | **0.2157** |
| Dynamos SC | 0.5902 | × 0.25 | **0.1475** |
| **Advantage** | PRFC +0.2728 | | **PRFC +0.0682** |

**PRFC has a 27.3% better offense (46% better!), giving them a +0.0682 advantage**

---

### 3. Defense (25% weight)

| Team | Defense Norm | × Weight | Contribution |
|------|--------------|----------|--------------|
| PRFC Scottsdale | 0.9245 | × 0.25 | **0.2311** |
| Dynamos SC | 0.9101 | × 0.25 | **0.2275** |
| **Advantage** | PRFC +0.0144 | | **PRFC +0.0036** |

**PRFC has a 1.4% better defense, giving them a +0.0036 advantage**

---

## Net Effect

| Component | PRFC Advantage | Dynamos Advantage |
|-----------|----------------|-------------------|
| Offense | **+0.0682** | |
| Defense | **+0.0036** | |
| SOS | | **+0.0524** |
| **Total** | **+0.0718** | **+0.0524** |
| **Net Advantage** | **PRFC +0.0194** | |

**PRFC's combined offense + defense advantage (+0.0718) MORE THAN OVERCOMES Dynamos' SOS advantage (+0.0524)**

**Final Power Score Difference:** 0.469727 - 0.469633 = **+0.000094 for PRFC**

---

## The Answer

### Why PRFC Scottsdale Ranks Higher Despite Weaker SOS:

1. **Massive Offensive Superiority**
   - PRFC: 86.3rd percentile (top 14% offensively)
   - Dynamos: 59.0th percentile (barely above average)
   - **Difference: 27.3 percentage points** → Worth +0.0682 in power score

2. **Slight Defensive Edge**
   - PRFC: 92.5th percentile (elite defense)
   - Dynamos: 91.0th percentile (also elite, but slightly worse)
   - **Difference: 1.4 percentage points** → Worth +0.0036 in power score

3. **SOS Disadvantage**
   - Dynamos: 85.0th percentile (very tough schedule)
   - PRFC: 74.5th percentile (above average schedule)
   - **Difference: 10.5 percentage points** → Worth +0.0524 in power score for Dynamos

4. **Net Result:**
   - PRFC's offense/defense advantage: +0.0718
   - Dynamos' SOS advantage: +0.0524
   - **PRFC wins by +0.0194 in the core components**

---

## Key Insight: Offense Matters More Than You Think

Even though SOS is weighted at 50% (the highest), the **combination of offense (25%) and defense (25%) totals 50% as well**.

PRFC Scottsdale is **dominating weaker opponents** with:
- High goal-scoring offense (86.3rd percentile)
- Elite defense (92.5th percentile)

Meanwhile, Dynamos SC is **struggling against stronger opponents** with:
- Below-average offense (59.0th percentile)
- Elite defense (91.0th percentile)

The formula rewards teams that dominate their competition, even if that competition is slightly weaker.

---

## Is This Fair?

This raises an important question: **Should a team that dominates weaker opponents rank higher than a team that struggles against stronger opponents?**

### Arguments FOR the current system:
- PRFC is objectively performing better (higher margins, better results)
- SOS is already weighted at 50% (highest weight)
- The schedule difference isn't huge (0.745 vs 0.850, both above average)

### Arguments AGAINST the current system:
- Dynamos plays MUCH harder opponents (10.5 percentile points higher SOS)
- A 59th percentile offense against 85th percentile opponents might be more impressive than 86th percentile offense against 74th percentile opponents
- The performance term (not visible in this data) may be amplifying the difference

---

## Recommendation

Consider investigating:
1. **The `perf_centered` (performance) metric** for both teams - this could be amplifying the difference
2. **Whether the offense/defense metrics are properly adjusted for opponent strength** - they should already incorporate SOS, but it's worth verifying
3. **Whether 50% SOS weight is sufficient** - you might consider 60% SOS / 20% OFF / 20% DEF to further penalize weak schedules

---

## Summary Table

| Factor | PRFC Scottsdale | Dynamos SC | Winner |
|--------|----------------|------------|--------|
| **Schedule Difficulty** | 74.5th %ile | 85.0th %ile | Dynamos |
| **Offensive Performance** | 86.3rd %ile | 59.0th %ile | **PRFC** |
| **Defensive Performance** | 92.5th %ile | 91.0th %ile | **PRFC** |
| **Net Power Score** | 0.4697 | 0.4696 | **PRFC** |

**Conclusion:** PRFC's dominant offensive performance (+27.3 percentile points) and slight defensive edge (+1.4 points) outweigh Dynamos' tougher schedule (+10.5 points) in the current weighting system.
