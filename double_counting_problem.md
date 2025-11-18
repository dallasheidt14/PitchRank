# CRITICAL FLAW: Double-Counting Problem in Power Score

## The Problem

**Offense and defense are NOT adjusted for opponent strength**, creating a double-counting issue where teams are rewarded/penalized twice for schedule strength.

---

## Code Analysis

### How Offense is Calculated (`/home/user/PitchRank/src/etl/v53e.py:262-284`)

```python
# Layer 3: Aggregate goals
g["gf_weighted"] = g["gf"] * g["w_game"]  # w_game = recency weight × context weight
g["ga_weighted"] = g["ga"] * g["w_game"]

team = g.groupby(["team_id", "age", "gender"]).agg({
    "gf_weighted": "sum",
    "ga_weighted": "sum",
    "w_game": "sum",
})

# Calculate weighted average (NO opponent strength adjustment!)
team["off_raw"] = team["gf_weighted"] / team["w_game"]  # Just raw goals scored
team["sad_raw"] = team["ga_weighted"] / team["w_game"]  # Just raw goals allowed
```

**Key Point:** Offense and defense are calculated as simple weighted averages of goals scored/allowed. They are **NOT adjusted for opponent strength**.

### How SOS is Calculated (`/home/user/PitchRank/src/etl/v53e.py:469-516`)

```python
# Layer 8: SOS calculation (SEPARATE from offense/defense)
g_sos["opp_strength"] = g_sos["opp_id"].map(lambda o: strength_map.get(o, 0.35))

# Weighted average of opponent strengths
sos = weighted_average(opp_strength, w_sos)
```

**Key Point:** SOS is calculated independently as the weighted average of opponent strengths.

### Final Power Score (`/home/user/PitchRank/src/etl/v53e.py:571-576`)

```python
powerscore_core = (
    0.25 × off_norm      # RAW offense (not opponent-adjusted)
    + 0.25 × def_norm    # RAW defense (not opponent-adjusted)
    + 0.50 × sos_norm    # Strength of schedule
    + perf_centered × 0.15
)
```

---

## The Double-Counting Effect

### Team Playing WEAK Opponents (PRFC Scottsdale)

| Factor | Impact | Power Score Contribution |
|--------|--------|-------------------------|
| **Plays weak opponents** | → Scores MORE goals (easier) | `off_norm = 0.863` → **+0.2157** ✓ |
| **Plays weak opponents** | → Allows FEWER goals (easier) | `def_norm = 0.925` → **+0.2311** ✓ |
| **Plays weak opponents** | → Lower SOS | `sos_norm = 0.745` → **+0.3725** |
| **Total** | | **0.8194** |

**Result:** Team gets HIGH offense/defense scores by beating weak opponents, and only pays a MODERATE SOS penalty.

---

### Team Playing STRONG Opponents (Dynamos SC)

| Factor | Impact | Power Score Contribution |
|--------|--------|-------------------------|
| **Plays strong opponents** | → Scores FEWER goals (harder) | `off_norm = 0.590` → **+0.1475** ✗ |
| **Plays strong opponents** | → Allows MORE goals (harder) | `def_norm = 0.910` → **+0.2275** |
| **Plays strong opponents** | → Higher SOS | `sos_norm = 0.850` → **+0.4250** ✓ |
| **Total** | | **0.8000** |

**Result:** Team gets LOW offense scores by competing against strong opponents, and the HIGHER SOS doesn't fully compensate.

---

## The Root Cause

**Offense and defense should be opponent-adjusted**, but they're not. This means:

1. **PRFC scores 3 goals/game against weak teams** → `off_norm = 0.863` (high)
2. **Dynamos scores 2 goals/game against strong teams** → `off_norm = 0.590` (low)

But scoring 2 goals against elite teams might be MORE impressive than scoring 3 goals against weak teams!

The current system doesn't account for this because:
- Offense = raw goals scored (no opponent adjustment)
- Defense = raw goals allowed (no opponent adjustment)
- SOS = separate metric

---

## Why This Matters: PRFC vs Dynamos

### PRFC Scottsdale (Playing Weaker Schedule)
```
Against 74.5%ile opponents:
  - Scores more goals → offense_norm = 0.863 → +0.2157
  - Allows fewer goals → defense_norm = 0.925 → +0.2311
  - Weak schedule penalty → sos_norm = 0.745 → +0.3725

Total: 0.8194
```

### Dynamos SC (Playing Stronger Schedule)
```
Against 85.0%ile opponents (10.5 points harder):
  - Scores fewer goals → offense_norm = 0.590 → +0.1475  (-0.0682 vs PRFC)
  - Allows slightly more goals → defense_norm = 0.910 → +0.2275  (-0.0036 vs PRFC)
  - Strong schedule bonus → sos_norm = 0.850 → +0.4250  (+0.0524 vs PRFC)

Total: 0.8000 (-0.0194 vs PRFC)
```

**Net Effect:** PRFC's inflated offense/defense (+0.0718) MORE THAN OFFSETS their SOS penalty (-0.0524).

---

## The Circular Logic Problem

The system has circular reasoning:

1. **Iteration 1:**
   - Calculate offense/defense from raw goals
   - Calculate SOS from opponent strengths
   - Calculate power score = f(offense, defense, sos)

2. **Problem:** Offense and defense already implicitly include schedule strength!
   - Teams playing weak opponents naturally score more (high offense)
   - Teams playing strong opponents naturally score less (low offense)
   - Then we add SOS as a "separate" factor, but it's already baked into offense/defense!

---

## Proposed Solutions

### Option 1: Opponent-Adjusted Offense/Defense (RECOMMENDED)

Adjust offense and defense for opponent strength BEFORE normalizing:

```python
# For each game, calculate expected goals based on opponent strength
g["expected_gf"] = f(opp_strength)  # What we'd expect to score against this opponent
g["expected_ga"] = f(opp_strength)  # What we'd expect to allow against this opponent

# Calculate opponent-adjusted offense/defense
g["off_adjusted"] = g["gf"] / g["expected_gf"]  # Performance relative to expectation
g["def_adjusted"] = g["expected_ga"] / g["ga"]  # Performance relative to expectation

# Now aggregate
team["off_raw"] = weighted_average(g["off_adjusted"])
team["def_raw"] = weighted_average(g["def_adjusted"])
```

This way:
- PRFC scoring 3 goals against weak opponents (expected 2.8) → `off_adjusted = 3.0/2.8 = 1.07`
- Dynamos scoring 2 goals against strong opponents (expected 1.5) → `off_adjusted = 2.0/1.5 = 1.33`

**Now Dynamos gets credit for outperforming expectations!**

---

### Option 2: Increase SOS Weight to Compensate

If we keep offense/defense unadjusted, we need to increase SOS weight to offset the double-counting:

| SOS Weight | Offense/Defense Weight | Winner | Difference |
|------------|----------------------|--------|------------|
| 50% | 25% / 25% | PRFC | +0.0194 |
| 55% | 22.5% / 22.5% | PRFC | +0.0070 |
| **60%** | **20% / 20%** | **Dynamos** | **-0.0055** |
| 65% | 17.5% / 17.5% | Dynamos | -0.0179 |
| 70% | 15% / 15% | Dynamos | -0.0303 |

At **60% SOS weight**, Dynamos would rank higher than PRFC.

**But this doesn't fix the root problem** - it just compensates for it.

---

### Option 3: Remove Offense/Defense from Power Score Entirely

Use only SOS-adjusted metrics:

```python
powerscore = (
    0.50 × sos_norm              # Schedule strength
    + 0.50 × perf_norm           # Over/under-performance (already opponent-adjusted)
)
```

This eliminates the double-counting but loses information about raw offensive/defensive prowess.

---

## Recommendation

**Implement Option 1: Opponent-Adjusted Offense/Defense**

This is the most principled solution because:
1. Offense and defense should measure **performance relative to expectation**
2. SOS should measure **difficulty of schedule**
3. These are orthogonal concepts and shouldn't double-count

### Implementation Steps:

1. Calculate expected goals for/against based on opponent strength
2. Adjust offense/defense by dividing by expected values
3. Keep SOS calculation as-is
4. Keep current weights (25% / 25% / 50%)

This way:
- A team that scores 3 goals against weak opponents gets appropriate credit (not excessive)
- A team that scores 2 goals against strong opponents gets appropriate credit (not penalized)
- SOS independently captures schedule difficulty

---

## Impact Analysis

Re-running rankings with opponent-adjusted offense/defense would likely:

1. **Promote teams** with strong SOS who are competing well (like Dynamos)
2. **Demote teams** with weak SOS who are just dominating weak opponents (like PRFC)
3. **Better reflect actual team quality** rather than schedule selection

---

## Verification Test

To verify this is a real problem, compare:

1. **Current system:** Teams with weak SOS but high OFF/DEF
2. **Adjusted system:** Same teams with opponent-adjusted OFF/DEF

If the rankings change significantly, this confirms the double-counting issue.

---

## Conclusion

The current system has a **fundamental design flaw** where offense and defense are not adjusted for opponent strength, leading to double-counting of schedule difficulty.

**Teams are incentivized to:**
- Play weaker opponents (inflate offense/defense)
- Accept the moderate SOS penalty
- Net benefit: higher power score

**The fix:** Adjust offense and defense for opponent strength before including them in the power score formula.
