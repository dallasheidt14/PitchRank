# Momentum Meter Logic Explanation

## Overview

The Momentum Meter on team detail pages shows how a team is performing **relative to expectations** in their recent games. It's not just about wins/losses—it measures whether they're **overperforming** or **underperforming** compared to what the ML model predicted.

---

## Core Concept: `ml_overperformance`

**What it is:**
- `ml_overperformance` = **Actual goal margin** - **Expected goal margin** (from home team's perspective)
- Stored in the `games` table for each game
- Calculated by Layer 13 (ML Predictive Adjustment) during ranking computation

**How it's calculated:**
1. ML model predicts expected goal margin based on:
   - Team PowerScore
   - Opponent PowerScore  
   - Age gap
   - Cross-gender flag
   - Recency (recent games weighted more)
   - Other features

2. Residual = Actual margin - Predicted margin
   - Positive = Team outperformed expectations (won by more than expected, or lost by less)
   - Negative = Team underperformed expectations (won by less than expected, or lost by more)
   - Near zero = Performed as expected

3. Stored per game from **home team's perspective**
   - For away teams, the sign is flipped in the frontend

---

## Momentum Calculation Logic

### Step 1: Get Recent Games
- Fetches last **8 games** (configurable, default: 8)
- Uses `useTeamGames(teamId, 12)` hook (fetches 12, uses 8)

### Step 2: Categorize Each Game

For each of the 8 recent games:

```typescript
// Get ml_overperformance from team's perspective
const isHome = game.home_team_master_id === teamId;
const performanceDelta = isHome 
  ? game.ml_overperformance 
  : -game.ml_overperformance;  // Flip sign for away games

// Categorize based on threshold (±2 goals)
if (performanceDelta >= 2.0) {
  greens++;  // Overperformed significantly
} else if (performanceDelta <= -2.0) {
  reds++;    // Underperformed significantly  
} else {
  neutrals++; // Performed as expected (±2 goal range)
}
```

**Threshold:** `PERFORMANCE_THRESHOLD = 2.0` goals
- **Green** = Beat expectations by 2+ goals
- **Red** = Missed expectations by 2+ goals
- **Neutral** = Within ±2 goals of expectations

### Step 3: Calculate Points

```typescript
points = greens - reds
// Green = +1 point, Red = -1 point, Neutral = 0 points
```

**Example:**
- 5 greens, 1 red, 2 neutrals → points = 5 - 1 = **+4**
- 2 greens, 4 reds, 2 neutrals → points = 2 - 4 = **-2**

### Step 4: Cap Points

```typescript
cappedPoints = Math.max(-4, Math.min(4, points))
```

**Rationale:** Prevents extreme scores from dominating. Max momentum swing is ±4 points.

### Step 5: Convert to 0-100 Score

```typescript
score = 50 + (cappedPoints × 12.5)
```

**Scoring Scale:**
- **-4 points** → 50 + (-4 × 12.5) = **0** (worst)
- **-2 points** → 50 + (-2 × 12.5) = **25**
- **0 points** → 50 + (0 × 12.5) = **50** (neutral)
- **+2 points** → 50 + (2 × 12.5) = **75**
- **+4 points** → 50 + (4 × 12.5) = **100** (best)

**Final score clamped:** `Math.max(0, Math.min(100, score))`

---

## Momentum Labels & Colors

### Labels (based on score):
- **≥80:** "Hot Streak" 🟢
- **≥60:** "Building Momentum" 🟢
- **≥50:** "As Expected" ⚪
- **≥25:** "Struggling" 🔴
- **<25:** "Slumping" 🔴

### Colors (interpolated):
- **<25:** Dark red `hsl(0, 70%, 35%)` - Slumping
- **25-50:** Light red `hsl(0, 65%, 50%)` - Struggling
- **50-60:** Gray `hsl(0, 0%, 50%)` - As Expected
- **60-80:** Light green `hsl(120, 50%, 45%)` - Building Momentum
- **≥80:** Dark green `hsl(120, 70%, 32%)` - Hot Streak

---

## Example Scenarios

### Scenario 1: Hot Streak Team
**Recent 8 games:**
- Game 1: Overperformed by +3 goals (Green)
- Game 2: Overperformed by +2.5 goals (Green)
- Game 3: Overperformed by +1.5 goals (Neutral)
- Game 4: Overperformed by +4 goals (Green)
- Game 5: Overperformed by +2 goals (Green)
- Game 6: Performed as expected +0.5 goals (Neutral)
- Game 7: Overperformed by +3 goals (Green)
- Game 8: Overperformed by +1 goal (Neutral)

**Calculation:**
- Greens: 5
- Reds: 0
- Neutrals: 3
- Points: 5 - 0 = **+5** → capped to **+4**
- Score: 50 + (4 × 12.5) = **100**
- Label: **"Hot Streak"** 🟢

### Scenario 2: Struggling Team
**Recent 8 games:**
- Game 1: Underperformed by -2.5 goals (Red)
- Game 2: Underperformed by -1 goal (Neutral)
- Game 3: Underperformed by -3 goals (Red)
- Game 4: Performed as expected -0.5 goals (Neutral)
- Game 5: Underperformed by -2 goals (Red)
- Game 6: Underperformed by -1.5 goals (Neutral)
- Game 7: Underperformed by -2.5 goals (Red)
- Game 8: Performed as expected +0.5 goals (Neutral)

**Calculation:**
- Greens: 0
- Reds: 4
- Neutrals: 4
- Points: 0 - 4 = **-4**
- Score: 50 + (-4 × 12.5) = **0**
- Label: **"Slumping"** 🔴

### Scenario 3: As Expected Team
**Recent 8 games:**
- Mix of small over/underperformance, all within ±2 goals

**Calculation:**
- Greens: 0
- Reds: 0
- Neutrals: 8
- Points: 0 - 0 = **0**
- Score: 50 + (0 × 12.5) = **50**
- Label: **"As Expected"** ⚪

---

## Key Insights

### Why This Matters:
1. **Not just wins/losses:** A team can win but still have negative momentum if they underperformed expectations
2. **Predictive value:** Teams with positive momentum are likely to continue overperforming
3. **Recent focus:** Only looks at last 8 games, so it's responsive to recent changes
4. **Context-aware:** Uses ML predictions that account for opponent strength, so beating a weak team doesn't inflate momentum

### Edge Cases:
- **Insufficient data:** If < 8 games available, uses whatever games exist
- **No games:** Returns score of 50 ("As Expected")
- **All neutrals:** Score stays at 50 (neutral momentum)

---

## Technical Details

### Data Source:
- `games` table → `ml_overperformance` column
- Calculated during ranking computation (Layer 13)
- Stored from home team's perspective

### Component:
- **File:** `frontend/components/MomentumMeter.tsx`
- **Hook:** `useTeamGames(teamId, 12)` - fetches last 12 games
- **Calculation:** `calculateMomentum(teamId, games, 8)` - uses last 8

### Animation:
- Score animates smoothly when it changes (800ms duration)
- Uses cubic ease-out animation
- Only animates if change > 0.1

---

## Relationship to Other Metrics

### vs. Recent Form (in Match Predictor):
- **Recent Form:** Average goal differential in last 5 games (raw performance)
- **Momentum:** Performance vs. expectations in last 8 games (relative performance)
- **Key difference:** Momentum accounts for opponent strength, form doesn't

### vs. PowerScore:
- **PowerScore:** Overall team strength rating (long-term)
- **Momentum:** Recent performance trend (short-term)
- **Relationship:** Momentum can indicate if PowerScore needs updating

---

## Summary

The Momentum Meter answers: **"Is this team playing better or worse than they should be?"**

- **Green (High Momentum):** Overperforming expectations → Likely to continue strong
- **Red (Low Momentum):** Underperforming expectations → May need to adjust
- **Neutral:** Performing as expected → Stable performance

This is valuable for:
- **Coaches:** Identify teams that are trending up/down
- **Scouts:** Find teams outperforming their ranking
- **Predictions:** Teams with positive momentum may be undervalued


















