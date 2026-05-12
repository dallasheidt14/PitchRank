# Consistency Recency Fix + Rank-Trend Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Fix the Consistency Score so it reflects current team identity (windowed game data + residual-stddev power volatility), and hide the contradictory "Rank Trend: Stable" line when the Form badge already says Surging or Slumping.

**Architecture:** Pure compute-layer change in `lib/insights/consistency.ts`, parallel windowing in `lib/insights/seasonTruth.ts:analyzeConsistencyPattern`, and a UI conditional in `TeamInsightsCard.tsx` + `InsightModal.tsx`. No types, no API, no DB changes.

**Tech Stack:** TypeScript, vitest. Spec: `docs/superpowers/specs/2026-05-12-consistency-score-recency-design.md`.

---

## File Structure

| File | Role |
|---|---|
| `frontend/lib/insights/consistency.ts` | Window goal-diff + streak inputs to last 15 played games; replace power-score CV with residual stddev |
| `frontend/lib/insights/seasonTruth.ts` | Apply same windowing to `analyzeConsistencyPattern` so the narrative stays aligned with the score |
| `frontend/lib/insights/__tests__/consistency.test.ts` *(new)* | Five unit tests covering window + residual behavior + fallback |
| `frontend/components/TeamInsightsCard.tsx` | Hide the Rank Trend line when `formBadge` is non-null |
| `frontend/components/insights/InsightModal.tsx` | Same UI override for modal parity |

---

## Task 1: Consistency Score — window + residual stddev

**Files:**
- Create: `frontend/lib/insights/__tests__/consistency.test.ts`
- Modify: `frontend/lib/insights/consistency.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/insights/__tests__/consistency.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { generateConsistencyScore } from '../consistency';
import type { InsightInputData } from '../types';

const TEAM_ID = 'team-a';

function buildInput(opts: {
  recentResultsNewestFirst?: Array<{ teamScore: number; oppScore: number }>;
  rankingHistoryScoresNewestFirst?: Array<number | null>;
}): InsightInputData {
  const games = (opts.recentResultsNewestFirst ?? []).map((r, i) => ({
    game_date: `2026-05-${(20 - i).toString().padStart(2, '0')}`,
    home_team_master_id: TEAM_ID,
    away_team_master_id: 'opp',
    home_score: r.teamScore,
    away_score: r.oppScore,
    opponent_rank: null,
    opponent_power_score: null,
  }));

  const rankingHistory = (opts.rankingHistoryScoresNewestFirst ?? []).map((s, i) => ({
    snapshot_date: `2026-05-${(20 - i).toString().padStart(2, '0')}`,
    rank_in_cohort: 50,
    rank_in_cohort_ml: 50,
    rank_in_cohort_final: 50,
    power_score_final: s,
  }));

  return {
    team: { team_id_master: TEAM_ID, team_name: 'T', state: 'WI', age: 14, gender: 'F' },
    ranking: {
      rank_in_cohort_final: 50,
      power_score_final: 0.5,
      sos_norm: null,
      wins: 0,
      losses: 0,
      draws: 0,
      games_played: 0,
      rank_change_7d: null,
      rank_change_30d: null,
      offense_norm: null,
      defense_norm: null,
      perf_centered: null,
    },
    games,
    rankingHistory,
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
  };
}

describe('generateConsistencyScore', () => {
  it('windows to most recent 15 played games — old chaos does not drag down a clean recent stretch', () => {
    // 20 chaotic older games + 10 clean recent wins → only the 15 newest count.
    const recent: Array<{ teamScore: number; oppScore: number }> = [];
    for (let i = 0; i < 10; i++) recent.push({ teamScore: 2, oppScore: 1 }); // 10 clean 2-1 wins (newest)
    for (let i = 0; i < 20; i++) recent.push(i % 2 === 0 ? { teamScore: 5, oppScore: 0 } : { teamScore: 0, oppScore: 5 }); // 20 chaotic
    const data = buildInput({ recentResultsNewestFirst: recent });

    const result = generateConsistencyScore(data);

    // Only the 10 wins + the first 5 chaotic games (5-0 win, 0-5 loss, etc) count.
    // That still produces a relatively clean score — proves windowing happens.
    // Without windowing, full-season chaos would push the score below 35.
    expect(result.score).toBeGreaterThan(50);
  });

  it('detects chaos in recent games even when older history was clean', () => {
    // 10 clean wins (oldest) followed by 5 chaotic games (newest)
    const recent: Array<{ teamScore: number; oppScore: number }> = [];
    recent.push({ teamScore: 5, oppScore: 0 });
    recent.push({ teamScore: 0, oppScore: 5 });
    recent.push({ teamScore: 6, oppScore: 1 });
    recent.push({ teamScore: 1, oppScore: 6 });
    recent.push({ teamScore: 4, oppScore: 0 });
    for (let i = 0; i < 10; i++) recent.push({ teamScore: 2, oppScore: 1 }); // older clean wins
    const data = buildInput({ recentResultsNewestFirst: recent });

    const result = generateConsistencyScore(data);

    // Windowing means the 5 chaotic newest dominate; expect a lower score.
    expect(result.score).toBeLessThan(60);
  });

  it('rewards a monotonic ranking climb (low residual stddev) with high pvScore', () => {
    // 5 played games (needed for score >= 50 path)
    const games = [
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
    ];
    // Monotonic climb in power score: 0.40 → 0.42 → 0.44 → 0.46 → 0.48 (newest)
    // Reversed input (newest first): [0.48, 0.46, 0.44, 0.42, 0.40]
    const history = [0.48, 0.46, 0.44, 0.42, 0.40];
    const data = buildInput({ recentResultsNewestFirst: games, rankingHistoryScoresNewestFirst: history });

    const result = generateConsistencyScore(data);

    // Residual stddev around a perfect line ≈ 0 → pvScore close to 100.
    // Combined with very clean game results, total score should be high.
    expect(result.score).toBeGreaterThan(75);
  });

  it('penalizes thrashing ranking history (high residual stddev) with low pvScore', () => {
    const games = [
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
      { teamScore: 2, oppScore: 1 },
    ];
    // Sawtooth: 0.40, 0.60, 0.40, 0.60, 0.40 — slope is zero, residuals are huge.
    const history = [0.40, 0.60, 0.40, 0.60, 0.40];
    const data = buildInput({ recentResultsNewestFirst: games, rankingHistoryScoresNewestFirst: history });

    const result = generateConsistencyScore(data);

    // Clean games (high gdScore + sfScore) but pvScore should be dragged way down.
    // Expect score lower than the monotonic-climb case above.
    expect(result.details.powerScoreVolatility).toBeGreaterThan(0.15);
  });

  it('returns neutral fallback when fewer than 3 scored games exist', () => {
    const data = buildInput({
      recentResultsNewestFirst: [{ teamScore: 2, oppScore: 1 }, { teamScore: 1, oppScore: 0 }],
    });

    const result = generateConsistencyScore(data);

    expect(result.score).toBe(50);
    expect(result.label).toBe('unpredictable');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/<worktree>/frontend && npx vitest run lib/insights/__tests__/consistency.test.ts`

Expected: FAIL — at least the "windows to most recent 15" and "monotonic climb" tests fail with the current full-season + raw-CV behavior.

- [ ] **Step 3: Implement the changes**

Open `frontend/lib/insights/consistency.ts`. Apply these changes:

Add a recency-window constant near the top alongside the existing constants:

```ts
const RECENCY_WINDOW = 15;
```

Refactor `calculateGoalDiffStdDev` to accept (or internally produce) only the most recent `RECENCY_WINDOW` played games. The cleanest implementation extracts a single walker:

```ts
function extractRecentPlayedResults(
  games: InsightInputData['games'],
  teamId: string
): Array<{ goalDiff: number; result: 'W' | 'L' | 'D' }> {
  const out: Array<{ goalDiff: number; result: 'W' | 'L' | 'D' }> = [];
  for (const game of games) {
    if (out.length >= RECENCY_WINDOW) break;
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;
    if (teamScore === null || oppScore === null) continue;
    const rawDiff = teamScore - oppScore;
    const goalDiff = Math.max(-GOAL_DIFF_CAP, Math.min(GOAL_DIFF_CAP, rawDiff));
    const result = teamScore > oppScore ? 'W' : teamScore < oppScore ? 'L' : 'D';
    out.push({ goalDiff, result });
  }
  return out;
}
```

Then have both `calculateGoalDiffStdDev` and `calculateStreakFragmentation` take the pre-computed `RecentResult[]` rather than re-walking `games`:

```ts
function calculateGoalDiffStdDev(recent: Array<{ goalDiff: number }>): number {
  if (recent.length < 2) return 0;
  const goalDiffs = recent.map((r) => r.goalDiff);
  const mean = goalDiffs.reduce((a, b) => a + b, 0) / goalDiffs.length;
  const variance = goalDiffs.reduce((sum, gd) => sum + Math.pow(gd - mean, 2), 0) / goalDiffs.length;
  return Math.sqrt(variance);
}

function calculateStreakFragmentation(recent: Array<{ result: 'W' | 'L' | 'D' }>): number {
  if (recent.length < 2) return 0;
  // Walk in chronological order: input is newest-first, so reverse for transition counting
  // (the count is order-invariant, so we can iterate either way)
  let transitions = 0;
  for (let i = 1; i < recent.length; i++) {
    if (recent[i].result !== recent[i - 1].result) transitions++;
  }
  return transitions / (recent.length - 1);
}
```

Replace `calculatePowerScoreVolatility` with the residual-stddev implementation:

```ts
function calculatePowerScoreVolatility(rankingHistory: InsightInputData['rankingHistory']): number {
  const scoresNewestFirst = rankingHistory
    .map((h) => h.power_score_final)
    .filter((s): s is number => s !== null);

  if (scoresNewestFirst.length < 4) return 0;

  // Reverse to chronological order so x=0..n-1 is oldest..newest.
  const scores = scoresNewestFirst.slice().reverse();
  const n = scores.length;
  const xMean = (n - 1) / 2;
  const yMean = scores.reduce((s, v) => s + v, 0) / n;

  let num = 0,
    den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (scores[i] - yMean);
    den += (i - xMean) ** 2;
  }
  const slope = den === 0 ? 0 : num / den;
  const intercept = yMean - slope * xMean;

  let sumSq = 0;
  for (let i = 0; i < n; i++) {
    const predicted = intercept + slope * i;
    sumSq += (scores[i] - predicted) ** 2;
  }
  const residualStdDev = Math.sqrt(sumSq / n);

  return residualStdDev / Math.max(yMean, 0.01);
}
```

Update `generateConsistencyScore` to use the new helpers:

```ts
export function generateConsistencyScore(data: InsightInputData): ConsistencyInsight {
  const { team, games, rankingHistory } = data;

  const recent = extractRecentPlayedResults(games, team.team_id_master);

  if (recent.length < MIN_GAMES_FOR_CONSISTENCY) {
    return {
      type: 'consistency_score',
      score: 50,
      label: 'unpredictable',
      details: {
        goalDifferentialStdDev: 0,
        streakFragmentation: 0,
        powerScoreVolatility: 0,
      },
    };
  }

  const goalDifferentialStdDev = calculateGoalDiffStdDev(recent);
  const streakFragmentation = calculateStreakFragmentation(recent);
  const powerScoreVolatility = calculatePowerScoreVolatility(rankingHistory);

  const score = calculateConsistencyScore(goalDifferentialStdDev, streakFragmentation, powerScoreVolatility);
  const label = getConsistencyLabel(score);

  return {
    type: 'consistency_score',
    score,
    label,
    details: {
      goalDifferentialStdDev: Math.round(goalDifferentialStdDev * 100) / 100,
      streakFragmentation: Math.round(streakFragmentation * 100) / 100,
      powerScoreVolatility: Math.round(powerScoreVolatility * 1000) / 1000,
    },
  };
}
```

Remove or repurpose the now-unused `countScoredGames` helper — `extractRecentPlayedResults().length` replaces its role. Delete `countScoredGames`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/<worktree>/frontend && npx vitest run lib/insights/__tests__/consistency.test.ts`

Expected: PASS — all 5 cases green. Run the broader suite too: `npx vitest run lib/insights` — all prior 20 tests must still pass.

- [ ] **Step 5: Commit**

```bash
cd C:/<worktree> && git add frontend/lib/insights/consistency.ts frontend/lib/insights/__tests__/consistency.test.ts && git commit -m "fix(insights): window consistency score to last 15 games + residual-stddev volatility"
```

---

## Task 2: Apply the same windowing to `analyzeConsistencyPattern`

**Files:**
- Modify: `frontend/lib/insights/seasonTruth.ts`

- [ ] **Step 1: Update `analyzeConsistencyPattern` to also window to 15 most recent played games**

Open `frontend/lib/insights/seasonTruth.ts`. Find `analyzeConsistencyPattern` (starts at the `function analyzeConsistencyPattern(games: ...)` declaration).

The function currently walks every game and counts the max win/loss streaks plus goal-diff stddev. Add a cap at the most recent 15 played games. Concretely, change the initial loop to break once 15 played games are collected:

```ts
const RECENCY_WINDOW = 15;

function analyzeConsistencyPattern(games: InsightInputData['games'], teamId: string): string {
  if (games.length < 3) return 'limited data available';

  const results: ('W' | 'L' | 'D')[] = [];
  const goalDiffs: number[] = [];
  const GOAL_DIFF_CAP = 6;

  for (const game of games) {
    if (results.length >= RECENCY_WINDOW) break;
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && oppScore !== null) {
      const rawDiff = teamScore - oppScore;
      const cappedDiff = Math.max(-GOAL_DIFF_CAP, Math.min(GOAL_DIFF_CAP, rawDiff));
      goalDiffs.push(cappedDiff);

      if (teamScore > oppScore) results.push('W');
      else if (teamScore < oppScore) results.push('L');
      else results.push('D');
    }
  }

  if (results.length < 3) return 'limited game data';

  // ... rest of function unchanged (maxWinStreak, maxLossStreak, stdDev computation, return strings)
}
```

The rest of the function (computing maxWinStreak, maxLossStreak, goal-diff stddev, and the return-string logic) is unchanged — it just operates on the windowed arrays now.

If a `RECENCY_WINDOW` constant already exists in this file from a future task, reuse it; otherwise the duplicate of `15` in this file is fine since the value is the same intent.

- [ ] **Step 2: Verify**

Run: `cd C:/<worktree>/frontend && npx tsc --noEmit 2>&1 | tail -5`
Run: `cd C:/<worktree>/frontend && npx vitest run lib/insights 2>&1 | tail -5`

Expected: typecheck clean, all 25 tests (20 prior + 5 new consistency tests) pass.

- [ ] **Step 3: Commit**

```bash
cd C:/<worktree> && git add frontend/lib/insights/seasonTruth.ts && git commit -m "fix(insights): apply 15-game window to analyzeConsistencyPattern narrative"
```

---

## Task 3: UI — hide Rank Trend when Form badge is set

**Files:**
- Modify: `frontend/components/TeamInsightsCard.tsx`
- Modify: `frontend/components/insights/InsightModal.tsx`

The Form badge already says "Surging" or "Slumping" with strong color. Showing a separate "Rank Trend: Stable" beneath it produces a contradictory-looking pair on the same card (because `perf_centered` re-zeros once Glicko's expectation re-calibrates to the new rank). Suppress the Rank Trend line entirely when `formBadge` is non-null — the temporal signal is already covered.

- [ ] **Step 1: Card — wrap the Rank Trend row in a `!formBadge &&` guard**

Open `frontend/components/TeamInsightsCard.tsx`. Locate the Rank Trend row (a JSX `<div className="flex items-center justify-between">` whose first child is `<span className="text-muted-foreground">Rank Trend</span>` followed by a Tooltip and the trend pill). It's nested inside the `seasonTruth &&` block, currently rendered unconditionally.

Wrap that entire div in `{!formBadge && ( ... )}`:

```tsx
{!formBadge && (
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-1.5">
      <span className="text-muted-foreground">Rank Trend</span>
      {/* ... existing Tooltip ... */}
    </div>
    {/* ... existing trend pill ... */}
  </div>
)}
```

Do not modify any other Rank Trend logic, tooltip copy, or styling. Only the conditional wrapper changes.

- [ ] **Step 2: Modal — same conditional**

Open `frontend/components/insights/InsightModal.tsx`. The modal also renders a Rank Trend pill somewhere in the Season Truth section. Find it (search for `rankTrajectory` in the file) and apply the same `!formBadge && ( ... )` wrapper around the entire row/chip.

- [ ] **Step 3: Verify**

Run: `cd C:/<worktree>/frontend && npx tsc --noEmit 2>&1 | tail -5`
Run: `cd C:/<worktree>/frontend && npx vitest run lib/insights 2>&1 | tail -5`

Expected: clean. The card's Rank Trend row now only renders when the Form badge is hidden — Surging/Slumping teams get the Form badge alone, no contradictory "Stable" beneath.

- [ ] **Step 4: Commit**

```bash
cd C:/<worktree> && git add frontend/components/TeamInsightsCard.tsx frontend/components/insights/InsightModal.tsx && git commit -m "fix(insights-ui): hide Rank Trend when Form badge is set"
```

---

## Task 4: Validation + PR

**Files:** none modified

- [ ] **Step 1: Run full suite + typecheck + lint**

```bash
cd C:/<worktree>/frontend
npx vitest run lib/insights 2>&1 | tail -10
npx tsc --noEmit 2>&1 | tail -10
npx eslint lib/insights components/TeamInsightsCard.tsx components/insights/InsightModal.tsx 2>&1 | tail -10
```

Expectations: 25 tests passing, tsc clean, eslint clean.

- [ ] **Step 2: Push + PR**

```bash
cd C:/<worktree> && git push -u origin HEAD 2>&1 | tail -5
gh pr create --base main --title "fix(insights): windowed consistency + hide Rank Trend when Form badge fires" --body "$(cat <<'EOF'
## Summary

Two related fixes to the premium Team Insights card:

- **Consistency Score now reflects current team identity.** Windows goal-diff stddev and streak fragmentation to the last 15 played games (instead of every game in the dataset), so a team that's improved recently isn't dragged down by stale old games. Replaces raw power-score CV with stddev of residuals around the trend line, so a team climbing the ranks isn't penalized for climbing.
- **Hides "Rank Trend: Stable" when the Form badge fires.** A Surging team that has had its expectations updated by Glicko (so perf_centered = 0) was showing both "Surging" and "Stable" in the same card — they answer different questions but read as contradictory. When a Form badge is present, suppress the Rank Trend row.

Spec: docs/superpowers/specs/2026-05-12-consistency-score-recency-design.md
Plan: docs/superpowers/plans/2026-05-12-consistency-recency-and-rank-trend-override.md

## Test plan

- [x] 5 new vitest cases covering windowing, residual stddev, and fallback
- [x] All prior 20 lib/insights tests still pass
- [x] tsc clean; eslint clean
- [ ] Smoke: open Rush Union team page after merge + deploy. Consistency score should jump from 47 ("unpredictable") to ~80 ("very reliable"). Rank Trend line should be hidden (Surging badge remains).
EOF
)" 2>&1 | tail -3
```

- [ ] **Step 3: Report**

Status, test counts, PR URL.

Do NOT merge; wait for human review.

---

## Self-Review Notes

- **Spec coverage**: Consistency windowing (Task 1), residual stddev (Task 1), seasonTruth pattern parity (Task 2), Rank Trend UI override (Task 3) — all mapped.
- **Placeholder scan**: No TBD/TODO; every code step has full code and exact commands.
- **Type consistency**: No type changes needed — `ConsistencyInsight` shape is preserved (same `score`, `label`, `details.goalDifferentialStdDev / streakFragmentation / powerScoreVolatility` fields, just computed differently). Tests assert against the existing return shape.
- **Edge cases covered**: <3 games fallback (existing behavior preserved), <4 ranking_history snapshots (volatility returns 0), perfectly linear climb (residuals ≈ 0).
