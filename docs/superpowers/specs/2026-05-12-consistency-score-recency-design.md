# Consistency Score Recency Fix — Design

**Status:** Drafted 2026-05-12
**Scope:** `frontend/lib/insights/consistency.ts` — narrow the consistency window and stop penalizing teams whose rankings have improved.

## Problem

The current Consistency Score (`frontend/lib/insights/consistency.ts`) computes three inputs across a team's **entire** game and ranking-history dataset, then weights them as:

```
score = 50% × goalDiffScore  +  30% × streakScore  +  20% × powerVolatilityScore
```

For a team mid-climb, every input is dragged by stale data:

1. **No recency weighting.** A loss from 8 months ago counts equally with today's win.
2. **Power-score CV penalizes climbers.** Coefficient-of-variation around the *mean* cannot distinguish "rising fast" from "yo-yo'ing". A team climbing 62 spots monotonically gets penalized for the same magnitude of CV as a team thrashing up and down.
3. **Redundant with other signals.** The Form badge + Movement line already report trajectory. Consistency should answer *"are recent results stable?"*, not *"has the team changed since August?"*

Concrete case — Rush Union Wisconsin 2012 Premier, score = 47 ("unpredictable"):

| Component | Full season (36 games) | Recent 10 games |
|---|---|---|
| Goal-diff stddev | 2.14 → score 51 | 1.10 → score 82 |
| Streak fragmentation | 0.60 → score 40 | ~0.10 → score 100 |
| Power-score CV | 0.127 → score 49 | n/a |

The team has won 9 straight, climbed 62 spots in 6 weeks, and is labeled "Surging" — but the same card says they are "unpredictable". User-visible contradiction.

## Goals

1. Reflect *current* team identity in the consistency signal, not a multi-month average of two different versions of the team.
2. Stop penalizing teams whose ranking has improved.
3. Preserve the score's stated purpose: predictability of recent results.
4. Keep the 0-100 mapping and `'very reliable' | 'moderately reliable' | 'unpredictable' | 'highly volatile'` labels — pure input change.

Non-goals: changing the score's display, labels, thresholds, or weights beyond what's required to drop / replace one component.

## Design

### Change 1 — Window the game-based components to the most recent N played games

Both `calculateGoalDiffStdDev` and `calculateStreakFragmentation` walk the full `games` array. Cap the input at the most recent **15 played games** (skipping null scores). 15 is roughly the modern scouting horizon for youth soccer and is large enough that a single game can't dominate the stddev.

If fewer than the minimum `MIN_GAMES_FOR_CONSISTENCY = 3` played games are available within the window, keep the existing fallback (`score = 50`, `label = 'unpredictable'`).

```ts
const RECENCY_WINDOW = 15;

function extractRecentResults(games: InsightInputData['games'], teamId: string) {
  const out: { goalDiff: number; result: 'W' | 'L' | 'D' }[] = [];
  for (const g of games) {
    if (out.length >= RECENCY_WINDOW) break;
    const isHome = g.home_team_master_id === teamId;
    const ts = isHome ? g.home_score : g.away_score;
    const os = isHome ? g.away_score : g.home_score;
    if (ts === null || os === null) continue;
    const rawDiff = ts - os;
    const goalDiff = Math.max(-GOAL_DIFF_CAP, Math.min(GOAL_DIFF_CAP, rawDiff));
    const result = ts > os ? 'W' : ts < os ? 'L' : 'D';
    out.push({ goalDiff, result });
  }
  return out;
}
```

Refactor `calculateGoalDiffStdDev` and `calculateStreakFragmentation` to take this pre-computed array (or call the extractor internally — implementation detail).

### Change 2 — Replace power-score CV with trend-residual stddev

`calculatePowerScoreVolatility` currently returns `stdDev / mean` over `power_score_final` across `ranking_history` (newest-first). For a monotonic riser the stddev is high even though the team is consistent in its trajectory.

Replacement: fit a least-squares line through `power_score_final` vs time-index, then return the stddev of *residuals* around that line. A team rising smoothly has small residuals (consistent trajectory); a team thrashing has large residuals.

```ts
function calculatePowerScoreVolatility(rankingHistory: InsightInputData['rankingHistory']): number {
  const scores = rankingHistory
    .map((h) => h.power_score_final)
    .filter((s): s is number => s !== null)
    .reverse(); // ranking_history is newest-first; reverse to chronological

  if (scores.length < 4) return 0;

  // Fit a line: y = a + b*x where x is the index 0..n-1.
  const n = scores.length;
  const xMean = (n - 1) / 2;
  const yMean = scores.reduce((s, v) => s + v, 0) / n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (scores[i] - yMean);
    den += (i - xMean) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = yMean - slope * xMean;

  // Residual stddev around the trend.
  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    const predicted = intercept + slope * i;
    sumSq += (scores[i] - predicted) ** 2;
  }
  const residualStdDev = Math.sqrt(sumSq / n);

  // Normalize to the existing 0..~0.2 scale used in calculateConsistencyScore
  // so the existing `100 - volatility * 400` mapping still produces sane output.
  return residualStdDev / Math.max(yMean, 0.01);
}
```

The existing `pvScore` mapping (`100 - powerScoreVolatility * 400`) can stay — residual-based CV typically falls in the 0–0.10 range for stable trajectories and >0.15 for chaotic ones, similar to the prior raw CV range but properly directionless.

### Change 3 — Update tests

Add unit tests in `frontend/lib/insights/__tests__/consistency.test.ts` (new file — there's no existing test). Cover:

1. Team with 30 messy games but a clean recent 10 → high score (>=75).
2. Team with 30 clean games but a chaotic recent 10 → low score (<=35).
3. Team with monotonic ranking climb → residual volatility is low → `pvScore` is high.
4. Team with thrashing ranking history (up-down-up-down) → residual volatility is high → `pvScore` is low.
5. Fewer than `MIN_GAMES_FOR_CONSISTENCY` games → fallback score=50.

## File changes

| File | Change |
|---|---|
| `frontend/lib/insights/consistency.ts` | Add `RECENCY_WINDOW = 15`; refactor goal-diff + streak-fragmentation to use windowed input; replace `calculatePowerScoreVolatility` with residual-stddev implementation |
| `frontend/lib/insights/__tests__/consistency.test.ts` *(new)* | 5 unit tests above |
| `frontend/lib/insights/seasonTruth.ts` | `analyzeConsistencyPattern` also walks `games` array — apply same windowing to keep the narrative aligned with the score |

## Test plan

- Run new unit tests in `frontend/lib/insights/__tests__/consistency.test.ts` (5 cases).
- Run full `lib/insights` suite to ensure no regression in persona / formBadge / seasonTruth tests.
- Manual: re-preview Rush Union — score should rise from 47 to ~80, label `'very reliable'`.
- Manual: pick a team that has been stably mid-pack all year — score should remain similar to current (no over-correction).

## Edge cases

- **Team with fewer than 15 played games**: use whatever is available (window is a cap, not a requirement). The existing `MIN_GAMES_FOR_CONSISTENCY = 3` floor still applies.
- **Ranking history shorter than 4 snapshots**: skip the residual-stddev computation and use neutral `pvScore = 60` per the existing fallback logic.
- **Perfectly linear climb (slope > 0, residuals = 0)**: `pvScore` returns 100 — this is desired; a perfectly-tracked rise is the *most* consistent shape.

## Out of scope

- Changing the 0-100 score mapping or the label thresholds.
- Changing the weight balance (50/30/20).
- Recency-weighting (exponential decay) — simpler hard window suffices for the immediate UX problem.
- Touching the Form badge or trajectory logic.

## Migration / rollout

- No DB change, no API change.
- Pure compute-layer change inside `lib/insights`.
- Ship as a single small PR after PR #746 (state-column fix) merges.
