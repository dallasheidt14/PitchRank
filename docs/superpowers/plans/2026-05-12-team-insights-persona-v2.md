# Team Insights Persona v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the premium Team Insights card feel personalized by adding a Title Contender tier label, a separate Surging/Slumping form badge, an auto-picked trait line citing specific opponents, and enriched modal explanations that name signature wins.

**Architecture:** Three additive layers on the existing insight engine — (1) extend `persona.ts` with Title Contender + helpers for signature wins and trait-line selection, (2) new `formBadge.ts` module that returns `Surging | Slumping | null` from `ranking_history` deltas combined with recent game results, (3) UI changes to render the third badge and trait line, and remove the buried "Current Form" block. Spec lives at `docs/superpowers/specs/2026-05-12-team-insights-persona-v2-design.md`.

**Tech Stack:** TypeScript, Next.js App Router, vitest (test runner), Supabase JS client, Tailwind/shadcn UI, lucide-react icons.

---

## File Structure

| File | Role |
|---|---|
| `frontend/lib/insights/types.ts` | + `FormBadgeLabel`, `FormBadgeInsight`; extend `PersonaInsight.details` + `InsightInputData` |
| `frontend/lib/insights/persona.ts` | + `findSignatureWins`, + `buildPersonaTrait`, + Title Contender branch, enriched explanations |
| `frontend/lib/insights/formBadge.ts` *(new)* | `generateFormBadge(data): FormBadgeInsight \| null` |
| `frontend/lib/insights/index.ts` | wire `generateFormBadge` into `generateAllInsights` |
| `frontend/lib/insights/__tests__/persona.test.ts` *(new)* | unit tests for `findSignatureWins`, `buildPersonaTrait`, Title Contender branch, enriched explanations |
| `frontend/lib/insights/__tests__/formBadge.test.ts` *(new)* | unit tests for Surging / Slumping / null branches |
| `frontend/app/api/insights/[teamId]/route.ts` | + state-cohort rank query, pass into `InsightInputData` |
| `frontend/components/TeamInsightsCard.tsx` | render 3rd badge, render trait line under signature result, remove old "Current Form" block |
| `frontend/components/insights/InsightModal.tsx` | render 3rd badge + trait line for parity |

---

## Task 1: Extend types

**Files:**
- Modify: `frontend/lib/insights/types.ts`

- [ ] **Step 1: Add FormBadge types and extend Persona + InsightInputData**

Replace the existing `PersonaInsight` interface and add the new types. Open `frontend/lib/insights/types.ts` and apply these edits:

After the `PlayStyle` type (line ~31), add:

```ts
/**
 * Form Badge label — temporal signal showing whether a team is trending up or down.
 * Independent of tier-based persona; a team can be a "Giant Killer · Surging".
 */
export type FormBadgeLabel = 'Surging' | 'Slumping';

/**
 * Form Badge Insight — separate from tier persona, surfaces recent-trend signal.
 * Returns null when neither trigger fires; the badge is hidden in that case.
 */
export interface FormBadgeInsight {
  type: 'form_badge';
  label: FormBadgeLabel;
  /** Negative = rank improved (Surging); positive = rank dropped (Slumping) */
  rankDelta: number;
  /** Days between oldest and newest snapshot used */
  daySpan: number;
  /** Last-5 record as "W-L-D", e.g. "5-0-0" or "1-3-1" */
  recentRecord: string;
}
```

Modify the `PersonaInsight` interface to add Title Contender, the trait line, and the cited signature wins:

```ts
export interface PersonaInsight {
  type: 'persona';
  label: 'Title Contender' | 'Giant Killer' | 'Flat Track Bully' | 'Gatekeeper' | 'Wildcard';
  explanation: string;
  details: {
    winsVsHigherRanked: number;
    totalVsHigherRanked: number;
    winsVsLowerRanked: number;
    totalVsLowerRanked: number;
    winRateVsTop: number;
    winRateVsBottom: number;
    /** Best win description, e.g. "Beat #3 opponent 4-1" */
    signatureResult: string | null;
    /** Auto-picked trait line, e.g. "Beat #3, #7, and #12 this season". Null when no trait qualifies. */
    trait: string | null;
    /** Up to 3 signature wins sorted by impressiveness (lowest opponent_rank first, tie-break by margin) */
    signatureWins: Array<{ opponent_rank: number; teamScore: number; oppScore: number }>;
  };
}
```

Add `FormBadgeInsight` to the union:

```ts
export type TeamInsight = SeasonTruthInsight | ConsistencyInsight | PersonaInsight | FormBadgeInsight;
```

Modify `InsightInputData` to add the state-cohort rank field used by the trait line:

```ts
export interface InsightInputData {
  // ... existing fields unchanged ...
  cohortStats: {
    totalTeams: number;
    medianPowerScore: number;
    percentile: number;
  };
  /** State-cohort rank info for the state-leaderboard trait. Null when state_code is missing or cohort < 5 teams. */
  stateCohort: {
    rank: number;
    totalTeams: number;
  } | null;
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd C:/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -20`

Expected: errors at every call site that constructs `InsightInputData` or returns `PersonaInsight` — that's fine, downstream tasks will fix them. The first few errors should be in `app/api/insights/[teamId]/route.ts` (missing `stateCohort`) and `lib/insights/persona.ts` (missing `trait` / `signatureWins` in `details`).

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/insights/types.ts && git commit -m "feat(insights): extend types for FormBadge + persona trait line"
```

---

## Task 2: Add `findSignatureWins` helper

**Files:**
- Create: `frontend/lib/insights/__tests__/persona.test.ts`
- Modify: `frontend/lib/insights/persona.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/insights/__tests__/persona.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { findSignatureWins } from '../persona';

const TEAM_ID = 'team-a';

function game(opts: {
  opp_rank: number | null;
  team_score: number;
  opp_score: number;
  team_is_home?: boolean;
}) {
  const isHome = opts.team_is_home ?? true;
  return {
    game_date: '2026-05-01',
    home_team_master_id: isHome ? TEAM_ID : 'opp',
    away_team_master_id: isHome ? 'opp' : TEAM_ID,
    home_score: isHome ? opts.team_score : opts.opp_score,
    away_score: isHome ? opts.opp_score : opts.team_score,
    opponent_rank: opts.opp_rank,
    opponent_power_score: null,
  };
}

describe('findSignatureWins', () => {
  it('returns up to 3 wins sorted by lowest opponent_rank, tie-break by margin', () => {
    const games = [
      game({ opp_rank: 50, team_score: 5, opp_score: 0 }), // rank too high, ignored unless ≤25
      game({ opp_rank: 11, team_score: 2, opp_score: 0 }),
      game({ opp_rank: 4, team_score: 3, opp_score: 1 }),
      game({ opp_rank: 4, team_score: 4, opp_score: 0 }), // same rank, bigger margin — wins tiebreak
      game({ opp_rank: 18, team_score: 1, opp_score: 0 }),
      game({ opp_rank: 7, team_score: 0, opp_score: 2 }), // a loss, ignored
    ];

    const result = findSignatureWins(games, TEAM_ID, 3);

    expect(result).toEqual([
      { opponent_rank: 4, teamScore: 4, oppScore: 0 },
      { opponent_rank: 4, teamScore: 3, oppScore: 1 },
      { opponent_rank: 11, teamScore: 2, oppScore: 0 },
    ]);
  });

  it('skips games with null opponent_rank or null scores', () => {
    const games = [
      game({ opp_rank: null, team_score: 5, opp_score: 0 }),
      { ...game({ opp_rank: 3, team_score: 0, opp_score: 0 }), home_score: null },
      game({ opp_rank: 8, team_score: 2, opp_score: 0 }),
    ];

    const result = findSignatureWins(games, TEAM_ID, 3);

    expect(result).toEqual([{ opponent_rank: 8, teamScore: 2, oppScore: 0 }]);
  });

  it('returns empty array when no wins exist', () => {
    const games = [game({ opp_rank: 5, team_score: 0, opp_score: 1 })];
    expect(findSignatureWins(games, TEAM_ID, 3)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/persona.test.ts`

Expected: FAIL — `findSignatureWins is not exported from '../persona'`.

- [ ] **Step 3: Implement the helper**

Open `frontend/lib/insights/persona.ts`. Add this function near the bottom, before the existing `findSignatureResult`:

```ts
/**
 * Returns up to `limit` of the team's most impressive wins.
 * Sorted by lowest opponent_rank first; ties broken by larger goal margin.
 */
export function findSignatureWins(
  games: InsightInputData['games'],
  teamId: string,
  limit: number
): Array<{ opponent_rank: number; teamScore: number; oppScore: number }> {
  const wins: Array<{ opponent_rank: number; teamScore: number; oppScore: number }> = [];

  for (const game of games) {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const oppScore = isHome ? game.away_score : game.home_score;

    if (teamScore === null || oppScore === null) continue;
    if (teamScore <= oppScore) continue;
    if (game.opponent_rank === null) continue;

    wins.push({
      opponent_rank: game.opponent_rank,
      teamScore,
      oppScore,
    });
  }

  wins.sort((a, b) => {
    if (a.opponent_rank !== b.opponent_rank) return a.opponent_rank - b.opponent_rank;
    return b.teamScore - b.oppScore - (a.teamScore - a.oppScore);
  });

  return wins.slice(0, limit);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/persona.test.ts`

Expected: PASS — all 3 `findSignatureWins` tests green.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/insights/persona.ts frontend/lib/insights/__tests__/persona.test.ts && git commit -m "feat(insights): findSignatureWins helper for persona explanations"
```

---

## Task 3: Add `buildPersonaTrait` helper

**Files:**
- Modify: `frontend/lib/insights/__tests__/persona.test.ts`
- Modify: `frontend/lib/insights/persona.ts`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/lib/insights/__tests__/persona.test.ts`:

```ts
import { buildPersonaTrait } from '../persona';
import type { InsightInputData } from '../types';

function buildInput(overrides: Partial<InsightInputData> = {}): InsightInputData {
  return {
    team: {
      team_id_master: TEAM_ID,
      team_name: 'Test FC',
      state: 'WI',
      age: 14,
      gender: 'F',
    },
    ranking: {
      rank_in_cohort_final: null,
      power_score_final: null,
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
    games: [],
    rankingHistory: [],
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
    ...overrides,
  };
}

describe('buildPersonaTrait', () => {
  it('returns signature-wins trait when ≥2 top-25 wins exist', () => {
    const data = buildInput({
      games: [
        game({ opp_rank: 3, team_score: 2, opp_score: 1 }),
        game({ opp_rank: 7, team_score: 4, opp_score: 0 }),
        game({ opp_rank: 12, team_score: 1, opp_score: 0 }),
      ],
    });
    expect(buildPersonaTrait(data)).toBe('Beat #3, #7, and #12 this season');
  });

  it('uses "and" for exactly two signature wins', () => {
    const data = buildInput({
      games: [
        game({ opp_rank: 5, team_score: 2, opp_score: 1 }),
        game({ opp_rank: 9, team_score: 3, opp_score: 0 }),
      ],
    });
    expect(buildPersonaTrait(data)).toBe('Beat #5 and #9 this season');
  });

  it('falls through to big-game record when fewer than 2 top-25 wins but ≥3 top-10 games', () => {
    const data = buildInput({
      games: [
        game({ opp_rank: 5, team_score: 2, opp_score: 1 }),   // win vs top-10 (and top-25)
        game({ opp_rank: 8, team_score: 0, opp_score: 2 }),   // loss vs top-10
        game({ opp_rank: 9, team_score: 1, opp_score: 1 }),   // draw vs top-10
      ],
    });
    // Only 1 top-25 win → signature-wins requires ≥2 → falls through to big-game record.
    expect(buildPersonaTrait(data)).toBe('1-1-1 vs top-10 opponents');
  });

  it('falls through to state leaderboard when in top 5 of state cohort', () => {
    const data = buildInput({
      games: [],
      stateCohort: { rank: 3, totalTeams: 42 },
    });
    expect(buildPersonaTrait(data)).toBe('#3 in WI U14 Girls');
  });

  it('falls through to national percentile when in top 5% nationally', () => {
    const data = buildInput({
      games: [],
      stateCohort: null,
      cohortStats: { totalTeams: 500, medianPowerScore: 50, percentile: 97 },
    });
    expect(buildPersonaTrait(data)).toBe('Top 3% nationally');
  });

  it('falls through to margin profile when ≥6 wins played', () => {
    const games = Array.from({ length: 6 }, () => game({ opp_rank: 80, team_score: 4, opp_score: 1 }));
    const data = buildInput({ games });
    expect(buildPersonaTrait(data)).toBe('Wins by 3.0 goals on average');
  });

  it('returns null when nothing qualifies', () => {
    const data = buildInput({ games: [game({ opp_rank: 80, team_score: 1, opp_score: 0 })] });
    expect(buildPersonaTrait(data)).toBeNull();
  });

  it('skips state-leaderboard when state cohort is too small', () => {
    const data = buildInput({ stateCohort: { rank: 1, totalTeams: 3 } });
    expect(buildPersonaTrait(data)).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/persona.test.ts`

Expected: FAIL — `buildPersonaTrait is not exported from '../persona'`.

- [ ] **Step 3: Implement the helper**

Open `frontend/lib/insights/persona.ts`. Add this function near `findSignatureWins`, and import `formatGender` from `@/lib/constants`:

At the top of the file, add the import alongside the existing imports:

```ts
import { formatGender } from '@/lib/constants';
```

Then add the helper:

```ts
const GOAL_DIFF_CAP = 6;
const TOP_OPP_RANK_SIGNATURE = 25;
const TOP_OPP_RANK_BIG_GAME = 10;
const MIN_STATE_COHORT_SIZE = 5;
const STATE_LEADERBOARD_TOP_N = 5;
const NATIONAL_TOP_PERCENTILE = 95; // i.e. percentile ≥ 95 → top 5% nationally
const MIN_WINS_FOR_MARGIN = 6;

function formatRankList(ranks: number[]): string {
  if (ranks.length === 1) return `Beat #${ranks[0]} this season`;
  if (ranks.length === 2) return `Beat #${ranks[0]} and #${ranks[1]} this season`;
  const head = ranks.slice(0, -1).map((r) => `#${r}`).join(', ');
  return `Beat ${head}, and #${ranks[ranks.length - 1]} this season`;
}

/**
 * Picks the single most distinguishing trait for this team.
 * Priority order — first match wins:
 *   1. Signature wins list (≥2 wins vs opponents ranked top 25)
 *   2. Big-game record (≥3 games vs opponents ranked top 10)
 *   3. State leaderboard (top 5 in state cohort, cohort ≥ MIN_STATE_COHORT_SIZE)
 *   4. National percentile (cohortStats.percentile ≥ 95)
 *   5. Margin profile (≥6 wins played, capped at +6 goals per game per v53e)
 * Returns null when nothing qualifies.
 */
export function buildPersonaTrait(data: InsightInputData): string | null {
  const { team, games, cohortStats, stateCohort } = data;

  // 1. Signature wins list
  const topWins: number[] = [];
  for (const g of games) {
    const isHome = g.home_team_master_id === team.team_id_master;
    const ts = isHome ? g.home_score : g.away_score;
    const os = isHome ? g.away_score : g.home_score;
    if (ts === null || os === null) continue;
    if (ts <= os) continue;
    if (g.opponent_rank === null) continue;
    if (g.opponent_rank > TOP_OPP_RANK_SIGNATURE) continue;
    topWins.push(g.opponent_rank);
  }
  if (topWins.length >= 2) {
    topWins.sort((a, b) => a - b);
    return formatRankList(topWins.slice(0, 3));
  }

  // 2. Big-game record
  let bigW = 0,
    bigL = 0,
    bigD = 0;
  for (const g of games) {
    const isHome = g.home_team_master_id === team.team_id_master;
    const ts = isHome ? g.home_score : g.away_score;
    const os = isHome ? g.away_score : g.home_score;
    if (ts === null || os === null) continue;
    if (g.opponent_rank === null || g.opponent_rank > TOP_OPP_RANK_BIG_GAME) continue;
    if (ts > os) bigW++;
    else if (ts < os) bigL++;
    else bigD++;
  }
  if (bigW + bigL + bigD >= 3) {
    const recordParts = [bigW, bigL];
    if (bigD > 0) recordParts.push(bigD);
    return `${recordParts.join('-')} vs top-10 opponents`;
  }

  // 3. State leaderboard
  if (
    stateCohort &&
    stateCohort.totalTeams >= MIN_STATE_COHORT_SIZE &&
    stateCohort.rank <= STATE_LEADERBOARD_TOP_N &&
    team.state &&
    team.age !== null
  ) {
    const genderLabel = formatGender(team.gender);
    return `#${stateCohort.rank} in ${team.state} U${team.age} ${genderLabel}`;
  }

  // 4. National percentile
  if (cohortStats.percentile >= NATIONAL_TOP_PERCENTILE && cohortStats.totalTeams > 0) {
    const topPct = 100 - cohortStats.percentile;
    return `Top ${topPct}% nationally`;
  }

  // 5. Margin profile (fallback)
  let wins = 0;
  let marginSum = 0;
  for (const g of games) {
    const isHome = g.home_team_master_id === team.team_id_master;
    const ts = isHome ? g.home_score : g.away_score;
    const os = isHome ? g.away_score : g.home_score;
    if (ts === null || os === null) continue;
    if (ts <= os) continue;
    const margin = Math.min(GOAL_DIFF_CAP, ts - os);
    wins++;
    marginSum += margin;
  }
  if (wins >= MIN_WINS_FOR_MARGIN) {
    const avg = (marginSum / wins).toFixed(1);
    return `Wins by ${avg} goals on average`;
  }

  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/persona.test.ts`

Expected: PASS — all `buildPersonaTrait` cases green.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/insights/persona.ts frontend/lib/insights/__tests__/persona.test.ts && git commit -m "feat(insights): buildPersonaTrait selects single auto-picked trait"
```

---

## Task 4: Add Title Contender branch + enrich explanations + wire trait into `generatePersonaInsight`

**Files:**
- Modify: `frontend/lib/insights/__tests__/persona.test.ts`
- Modify: `frontend/lib/insights/persona.ts`

- [ ] **Step 1: Write failing tests for Title Contender + enriched explanation**

Append to `frontend/lib/insights/__tests__/persona.test.ts`:

```ts
import { generatePersonaInsight } from '../persona';

describe('generatePersonaInsight — Title Contender', () => {
  it('returns Title Contender when team beats both tiers handily', () => {
    // 4 games vs stronger (3 wins → 75%), 4 games vs weaker (4 wins → 100%)
    const data = buildInput({
      ranking: {
        ...buildInput().ranking,
        power_score_final: 0.5,
      },
      games: [
        // vs stronger (opp power higher than team's 0.5 by > 0.056 = 0.08*0.7 anchor)
        { ...game({ opp_rank: 3, team_score: 2, opp_score: 1 }), opponent_power_score: 0.7 },
        { ...game({ opp_rank: 5, team_score: 3, opp_score: 0 }), opponent_power_score: 0.7 },
        { ...game({ opp_rank: 8, team_score: 1, opp_score: 0 }), opponent_power_score: 0.7 },
        { ...game({ opp_rank: 6, team_score: 0, opp_score: 1 }), opponent_power_score: 0.7 },
        // vs weaker
        { ...game({ opp_rank: 80, team_score: 5, opp_score: 0 }), opponent_power_score: 0.2 },
        { ...game({ opp_rank: 90, team_score: 4, opp_score: 1 }), opponent_power_score: 0.2 },
        { ...game({ opp_rank: 100, team_score: 3, opp_score: 0 }), opponent_power_score: 0.2 },
        { ...game({ opp_rank: 110, team_score: 6, opp_score: 0 }), opponent_power_score: 0.2 },
      ],
    });
    const result = generatePersonaInsight(data);
    expect(result.label).toBe('Title Contender');
  });

  it('Giant Killer explanation cites up to 3 signature wins', () => {
    const data = buildInput({
      ranking: { ...buildInput().ranking, power_score_final: 0.5 },
      games: [
        { ...game({ opp_rank: 3, team_score: 2, opp_score: 1 }), opponent_power_score: 0.7 },
        { ...game({ opp_rank: 11, team_score: 2, opp_score: 0 }), opponent_power_score: 0.7 },
        { ...game({ opp_rank: 18, team_score: 1, opp_score: 0 }), opponent_power_score: 0.7 },
      ],
    });
    const result = generatePersonaInsight(data);
    expect(result.label).toBe('Giant Killer');
    expect(result.explanation).toContain('beat #3 ');
    expect(result.explanation).toContain('#11 ');
    expect(result.explanation).toContain('#18 ');
  });

  it('populates details.trait and details.signatureWins', () => {
    const data = buildInput({
      games: [
        game({ opp_rank: 4, team_score: 2, opp_score: 0 }),
        game({ opp_rank: 9, team_score: 1, opp_score: 0 }),
      ],
    });
    const result = generatePersonaInsight(data);
    expect(result.details.trait).toBe('Beat #4 and #9 this season');
    expect(result.details.signatureWins).toHaveLength(2);
    expect(result.details.signatureWins[0]).toEqual({ opponent_rank: 4, teamScore: 2, oppScore: 0 });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/persona.test.ts`

Expected: FAIL — multiple expectations including `result.label === 'Title Contender'` getting `'Giant Killer'` instead, missing `trait` / `signatureWins` fields, no cited opponents in explanation.

- [ ] **Step 3: Modify `determinePersona` to add the Title Contender branch**

Open `frontend/lib/insights/persona.ts`. Find the `determinePersona` function and insert the Title Contender branch **before** the Giant Killer branch. The full updated function:

```ts
function determinePersona(stats: ReturnType<typeof analyzePerformanceByTier>): {
  label: PersonaInsight['label'];
  explanation: string;
} {
  const { winsVsHigherRanked, totalVsHigherRanked, winsVsLowerRanked, totalVsLowerRanked, bigWins, bigLosses } = stats;

  const winRateVsTop = totalVsHigherRanked > 0 ? winsVsHigherRanked / totalVsHigherRanked : 0;
  const winRateVsBottom = totalVsLowerRanked > 0 ? winsVsLowerRanked / totalVsLowerRanked : 0;

  const hasEnoughTopGames = totalVsHigherRanked >= 2;
  const hasEnoughBottomGames = totalVsLowerRanked >= 2;

  // Title Contender: handles both tiers — stricter than Giant Killer.
  if (hasEnoughTopGames && hasEnoughBottomGames && winRateVsTop >= 0.4 && winRateVsBottom >= 0.75) {
    return {
      label: 'Title Contender',
      explanation: `Won ${winsVsHigherRanked} of ${totalVsHigherRanked} vs stronger opponents AND ${winsVsLowerRanked} of ${totalVsLowerRanked} vs weaker (${Math.round(winRateVsBottom * 100)}%). This team handles every tier — the mark of a serious contender.`,
    };
  }

  // Giant Killer: Strong performance against stronger teams (40%+ win rate)
  if (hasEnoughTopGames && winRateVsTop >= 0.4 && winsVsHigherRanked >= 2) {
    return {
      label: 'Giant Killer',
      explanation: `Won ${winsVsHigherRanked} of ${totalVsHigherRanked} games against stronger opponents (by power score). This team rises to the occasion against elite competition and shouldn't be underestimated in big matchups.`,
    };
  }

  // Flat Track Bully: Dominates weaker teams but struggles against stronger
  if (hasEnoughTopGames && hasEnoughBottomGames && winRateVsTop < 0.25 && winRateVsBottom > 0.8) {
    return {
      label: 'Flat Track Bully',
      explanation: `Dominant against weaker competition (${Math.round(winRateVsBottom * 100)}% win rate vs lower-powered teams) but struggles against elite opponents (${Math.round(winRateVsTop * 100)}% vs stronger teams). Their record may be inflated by favorable scheduling.`,
    };
  }

  // Gatekeeper: Beats weaker teams reliably, competitive but rarely beats stronger
  if (hasEnoughBottomGames && winRateVsBottom > 0.65 && (winRateVsTop < 0.3 || !hasEnoughTopGames)) {
    return {
      label: 'Gatekeeper',
      explanation: `A reliable gatekeeper who consistently handles weaker opponents (${Math.round(winRateVsBottom * 100)}% win rate) but hasn't broken through against top-tier teams. They define the line between contenders and pretenders.`,
    };
  }

  const totalGames = totalVsHigherRanked + totalVsLowerRanked;
  const hasVolatileResults = bigWins >= 2 && bigLosses >= 2;

  if (hasVolatileResults) {
    return {
      label: 'Wildcard',
      explanation: `Unpredictable results with ${bigWins} blowout wins and ${bigLosses} heavy defeats. On any given day, this team can beat anyone or lose to anyone. Their floor-to-ceiling range makes them dangerous but unreliable.`,
    };
  }

  if (totalGames < 4) {
    return {
      label: 'Wildcard',
      explanation: `With limited games against varied competition, it's difficult to establish a clear pattern. This team's true identity is still emerging.`,
    };
  }

  return {
    label: 'Wildcard',
    explanation: `This team defies easy categorization with mixed results across different opponent tiers. They're neither consistently dominant nor consistently vulnerable, making them a true wildcard in any matchup.`,
  };
}
```

- [ ] **Step 4: Enrich explanations with cited games for Title Contender / Giant Killer**

Still in `frontend/lib/insights/persona.ts`. Modify `generatePersonaInsight` (the existing exported function). The full replacement:

```ts
/**
 * Generate the Persona insight
 */
export function generatePersonaInsight(data: InsightInputData): PersonaInsight {
  const { team, ranking, games } = data;

  const anchor = (team.age !== null ? AGE_TO_ANCHOR[team.age] : null) ?? 1.0;
  const scaledThreshold = BASE_POWER_DIFF_THRESHOLD * anchor;

  const stats = analyzePerformanceByTier(games, team.team_id_master, ranking.power_score_final, scaledThreshold);

  const { label, explanation: baseExplanation } = determinePersona(stats);
  const signatureResult = findSignatureResult(games, team.team_id_master);
  const signatureWins = findSignatureWins(games, team.team_id_master, 3);
  const trait = buildPersonaTrait(data);

  // Enrich Title Contender + Giant Killer explanations with cited wins.
  let explanation = baseExplanation;
  if ((label === 'Title Contender' || label === 'Giant Killer') && signatureWins.length > 0) {
    const cited = signatureWins
      .map((w) => `#${w.opponent_rank} ${w.teamScore}-${w.oppScore}`)
      .join(', ');
    // Inject "(beat #X ...)" before the first period.
    const firstPeriod = baseExplanation.indexOf('.');
    if (firstPeriod !== -1) {
      explanation =
        baseExplanation.slice(0, firstPeriod) + ` (beat ${cited})` + baseExplanation.slice(firstPeriod);
    }
  }

  const winRateVsTop =
    stats.totalVsHigherRanked > 0 ? Math.round((stats.winsVsHigherRanked / stats.totalVsHigherRanked) * 100) : 0;
  const winRateVsBottom =
    stats.totalVsLowerRanked > 0 ? Math.round((stats.winsVsLowerRanked / stats.totalVsLowerRanked) * 100) : 0;

  return {
    type: 'persona',
    label,
    explanation,
    details: {
      winsVsHigherRanked: stats.winsVsHigherRanked,
      totalVsHigherRanked: stats.totalVsHigherRanked,
      winsVsLowerRanked: stats.winsVsLowerRanked,
      totalVsLowerRanked: stats.totalVsLowerRanked,
      winRateVsTop,
      winRateVsBottom,
      signatureResult,
      signatureWins,
      trait,
    },
  };
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/persona.test.ts`

Expected: PASS — all persona tests green (Title Contender, enriched explanation, trait + signatureWins details).

- [ ] **Step 6: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/insights/persona.ts frontend/lib/insights/__tests__/persona.test.ts && git commit -m "feat(insights): add Title Contender tier + cite signature wins in explanation"
```

---

## Task 5: Create `formBadge.ts` module

**Files:**
- Create: `frontend/lib/insights/formBadge.ts`
- Create: `frontend/lib/insights/__tests__/formBadge.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/lib/insights/__tests__/formBadge.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { generateFormBadge } from '../formBadge';
import type { InsightInputData } from '../types';

const TEAM_ID = 'team-a';

function inputWith(opts: {
  recentResults: ('W' | 'L' | 'D')[]; // newest first
  rankNow: number;
  rankThen: number;
  daysAgo: number;
}): InsightInputData {
  const games = opts.recentResults.map((r, i) => ({
    game_date: `2026-05-${(10 - i).toString().padStart(2, '0')}`,
    home_team_master_id: TEAM_ID,
    away_team_master_id: 'opp',
    home_score: r === 'W' ? 2 : r === 'L' ? 0 : 1,
    away_score: r === 'W' ? 0 : r === 'L' ? 2 : 1,
    opponent_rank: 50,
    opponent_power_score: null,
  }));

  const newestSnapshot = new Date('2026-05-10');
  const oldestSnapshot = new Date(newestSnapshot.getTime() - opts.daysAgo * 24 * 60 * 60 * 1000);

  return {
    team: { team_id_master: TEAM_ID, team_name: 'T', state: 'WI', age: 14, gender: 'F' },
    ranking: {
      rank_in_cohort_final: opts.rankNow,
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
    rankingHistory: [
      {
        snapshot_date: newestSnapshot.toISOString().slice(0, 10),
        rank_in_cohort_final: opts.rankNow,
        rank_in_cohort: opts.rankNow,
        power_score_final: 0.5,
      },
      {
        snapshot_date: oldestSnapshot.toISOString().slice(0, 10),
        rank_in_cohort_final: opts.rankThen,
        rank_in_cohort: opts.rankThen,
        power_score_final: 0.5,
      },
    ],
    cohortStats: { totalTeams: 100, medianPowerScore: 50, percentile: 50 },
    stateCohort: null,
  };
}

describe('generateFormBadge', () => {
  it('returns Surging when rank improved ≥10 spots over ≥21 days AND last 5 are ≥4W with 0 losses', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'W', 'D'],
      rankNow: 20,
      rankThen: 45,
      daysAgo: 30,
    });
    const result = generateFormBadge(data);
    expect(result?.label).toBe('Surging');
    expect(result?.rankDelta).toBe(-25);
    expect(result?.recentRecord).toBe('4-0-1');
  });

  it('returns Slumping when rank dropped ≥10 spots AND last 5 include ≥3 losses', () => {
    const data = inputWith({
      recentResults: ['L', 'L', 'L', 'W', 'D'],
      rankNow: 60,
      rankThen: 40,
      daysAgo: 30,
    });
    const result = generateFormBadge(data);
    expect(result?.label).toBe('Slumping');
    expect(result?.rankDelta).toBe(20);
    expect(result?.recentRecord).toBe('1-3-1');
  });

  it('returns null when rank improved but only 1 loss in last 5 — neither trigger fires', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'L', 'W', 'W'], // 4W 1L → fails Surging (loss present); rank dropped? no, improved
      rankNow: 20,
      rankThen: 45,
      daysAgo: 30,
    });
    expect(generateFormBadge(data)).toBeNull();
  });

  it('returns null when rank dropped but last 5 only have 2 losses', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'L', 'L'],
      rankNow: 60,
      rankThen: 40,
      daysAgo: 30,
    });
    expect(generateFormBadge(data)).toBeNull();
  });

  it('returns null when daySpan is below 21', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'W', 'W'],
      rankNow: 10,
      rankThen: 40,
      daysAgo: 14,
    });
    expect(generateFormBadge(data)).toBeNull();
  });

  it('returns null when ranking history has fewer than 2 snapshots', () => {
    const data = inputWith({
      recentResults: ['W', 'W', 'W', 'W', 'W'],
      rankNow: 10,
      rankThen: 40,
      daysAgo: 30,
    });
    data.rankingHistory = [data.rankingHistory[0]];
    expect(generateFormBadge(data)).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/formBadge.test.ts`

Expected: FAIL — `Cannot find module '../formBadge'`.

- [ ] **Step 3: Implement the module**

Create `frontend/lib/insights/formBadge.ts`:

```ts
/**
 * Form Badge — Surging / Slumping / null
 *
 * Combines two signals to avoid false positives:
 *   1. Sustained rank movement: ≥10 spots over ≥21 days in ranking_history
 *   2. Recent game results: last 5 played games (newest first)
 *
 * Surging = sustained rank improvement AND ≥4 wins, 0 losses in last 5
 * Slumping = sustained rank drop AND ≥3 losses in last 5
 * Otherwise = null (badge hidden)
 */

import type { InsightInputData, FormBadgeInsight } from './types';

const RANK_MOVEMENT_THRESHOLD = 10;
const MIN_DAY_SPAN = 21;
const RECENT_GAME_WINDOW = 5;
const SURGING_MIN_WINS = 4;
const SLUMPING_MIN_LOSSES = 3;

export function generateFormBadge(data: InsightInputData): FormBadgeInsight | null {
  const { games, rankingHistory, team } = data;

  if (rankingHistory.length < 2) return null;

  // History is ordered most-recent-first by the API.
  const latest = rankingHistory[0];
  const oldest = rankingHistory[rankingHistory.length - 1];

  const getRank = (h: (typeof rankingHistory)[number]) =>
    h.rank_in_cohort_final ?? h.rank_in_cohort_ml ?? h.rank_in_cohort;

  const rankNow = getRank(latest);
  const rankThen = getRank(oldest);
  const rankDelta = rankNow - rankThen; // negative = improved

  const daySpan = Math.round(
    (new Date(latest.snapshot_date).getTime() - new Date(oldest.snapshot_date).getTime()) / (1000 * 60 * 60 * 24)
  );

  if (daySpan < MIN_DAY_SPAN) return null;

  // Walk newest-first, collect up to RECENT_GAME_WINDOW played results.
  let wins = 0,
    losses = 0,
    draws = 0;
  for (const game of games) {
    if (wins + losses + draws >= RECENT_GAME_WINDOW) break;
    const isHome = game.home_team_master_id === team.team_id_master;
    const ts = isHome ? game.home_score : game.away_score;
    const os = isHome ? game.away_score : game.home_score;
    if (ts === null || os === null) continue;
    if (ts > os) wins++;
    else if (ts < os) losses++;
    else draws++;
  }

  const total = wins + losses + draws;
  const recentRecord = draws > 0 ? `${wins}-${losses}-${draws}` : `${wins}-${losses}`;

  if (total < RECENT_GAME_WINDOW) return null; // not enough recent games

  // Surging
  if (rankDelta <= -RANK_MOVEMENT_THRESHOLD && wins >= SURGING_MIN_WINS && losses === 0) {
    return {
      type: 'form_badge',
      label: 'Surging',
      rankDelta,
      daySpan,
      recentRecord,
    };
  }

  // Slumping
  if (rankDelta >= RANK_MOVEMENT_THRESHOLD && losses >= SLUMPING_MIN_LOSSES) {
    return {
      type: 'form_badge',
      label: 'Slumping',
      rankDelta,
      daySpan,
      recentRecord,
    };
  }

  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights/__tests__/formBadge.test.ts`

Expected: PASS — all 6 cases green.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/insights/formBadge.ts frontend/lib/insights/__tests__/formBadge.test.ts && git commit -m "feat(insights): formBadge module computes Surging/Slumping/null"
```

---

## Task 6: Wire `generateFormBadge` into `generateAllInsights`

**Files:**
- Modify: `frontend/lib/insights/index.ts`

- [ ] **Step 1: Update the index to include the form badge (when non-null)**

Replace the contents of `frontend/lib/insights/index.ts` with:

```ts
/**
 * Team Insight Engine
 *
 * Premium-only scouting-style insights computed from team data.
 * Insight types:
 * 1. Season Truth Summary - narrative evaluation
 * 2. Consistency Score (0-100)
 * 3. Team Persona Label (tier + auto-picked trait)
 * 4. Form Badge (Surging / Slumping; optional)
 */

export * from './types';
export { generateSeasonTruth } from './seasonTruth';
export { generateConsistencyScore } from './consistency';
export { generatePersonaInsight } from './persona';
export { generateFormBadge } from './formBadge';

import type { InsightInputData, TeamInsight, TeamInsightsResponse } from './types';
import { generateSeasonTruth } from './seasonTruth';
import { generateConsistencyScore } from './consistency';
import { generatePersonaInsight } from './persona';
import { generateFormBadge } from './formBadge';

export function generateAllInsights(data: InsightInputData): TeamInsightsResponse {
  const insights: TeamInsight[] = [
    generateSeasonTruth(data),
    generateConsistencyScore(data),
    generatePersonaInsight(data),
  ];

  const formBadge = generateFormBadge(data);
  if (formBadge) insights.push(formBadge);

  return {
    teamId: data.team.team_id_master,
    teamName: data.team.team_name,
    insights,
    generatedAt: new Date().toISOString(),
  };
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd C:/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -10`

Expected: still has errors in `app/api/insights/[teamId]/route.ts` (missing `stateCohort` field on `InsightInputData`). The insights modules themselves should be clean.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add frontend/lib/insights/index.ts && git commit -m "feat(insights): wire generateFormBadge into generateAllInsights"
```

---

## Task 7: Update API route — add state-cohort query, pass `stateCohort`

**Files:**
- Modify: `frontend/app/api/insights/[teamId]/route.ts`

- [ ] **Step 1: Add the state-cohort query and pass to InsightInputData**

Open `frontend/app/api/insights/[teamId]/route.ts`. After the existing `cohortStats` block (the one that queries `rankings_view` for the national age+gender cohort), add a parallel block for state cohort:

```ts
    // State-cohort rank (for state-leaderboard persona trait)
    let stateCohort: InsightInputData['stateCohort'] = null;
    if (team.state_code && ranking?.age && ranking?.gender) {
      const { data: stateCohortData, error: stateCohortError } = await supabase
        .from('rankings_view')
        .select('team_id_master, power_score_final')
        .eq('age', ranking.age)
        .eq('gender', ranking.gender)
        .eq('state_code', team.state_code)
        .eq('status', 'Active')
        .order('power_score_final', { ascending: false });

      if (!stateCohortError && stateCohortData && stateCohortData.length >= 5) {
        const idx = (stateCohortData as Array<{ team_id_master: string }>).findIndex(
          (r) => r.team_id_master === teamId
        );
        if (idx >= 0) {
          stateCohort = { rank: idx + 1, totalTeams: stateCohortData.length };
        }
      }
    }
```

Then locate the `insightData: InsightInputData = { ... }` literal further down. Add `stateCohort` as a new field alongside `cohortStats`:

```ts
      cohortStats,
      stateCohort,
    };
```

- [ ] **Step 2: Verify typecheck**

Run: `cd C:/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -10`

Expected: clean (no errors).

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add frontend/app/api/insights/[teamId]/route.ts && git commit -m "feat(insights): fetch state cohort rank for persona trait line"
```

---

## Task 8: Update `TeamInsightsCard` — 3rd badge + trait line + remove old "Current Form" block

**Files:**
- Modify: `frontend/components/TeamInsightsCard.tsx`

- [ ] **Step 1: Import the new type, derive the formBadge insight**

Open `frontend/components/TeamInsightsCard.tsx`.

In the type-only import block at the top, add `FormBadgeInsight`:

```ts
import type {
  TeamInsightsResponse,
  SeasonTruthInsight,
  ConsistencyInsight,
  PersonaInsight,
  FormBadgeInsight,
} from '@/lib/insights/types';
```

After the existing `const persona = ...` derivation (around line 93), add:

```ts
  const formBadge = insights?.insights.find((i) => i.type === 'form_badge') as FormBadgeInsight | undefined;
```

- [ ] **Step 2: Add the 3rd badge to the top-row badge container and the trait line under the signature result**

Locate the block that renders the persona badge + play style badge (the `<div className="flex flex-wrap items-center gap-2">` containing them). At the end of that flex container, immediately after the `Play Style Badge` block closes (the `seasonTruth?.details.playStyle && ...` block), add:

```tsx
          {/* Form Badge — Surging / Slumping (independent of tier persona) */}
          {formBadge && (
            <div
              className={cn(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold text-sm',
                formBadge.label === 'Surging'
                  ? 'bg-orange-500/20 text-orange-700 dark:text-orange-300'
                  : 'bg-sky-500/20 text-sky-700 dark:text-sky-300'
              )}
            >
              {formBadge.label === 'Surging' ? <Flame className="h-4 w-4" /> : <Snowflake className="h-4 w-4" />}
              {formBadge.label}
            </div>
          )}
```

`Flame` and `Snowflake` are already imported in the existing icon set — no import changes needed.

Immediately after the existing `Signature Result` italic line (which renders `persona?.details.signatureResult`), add:

```tsx
        {/* Auto-picked trait line under signature result */}
        {persona?.details.trait && (
          <p className="text-xs text-foreground/70 italic">✨ {persona.details.trait}</p>
        )}
```

- [ ] **Step 3: Remove the "Current Form" block (replaced by the new top-row Form badge)**

Locate the existing block in the same file that begins with `{/* Form/Momentum - Only show notable streaks */}` and renders the inline "Hot Streak / Cold Streak" pill. Delete the entire conditional, from the comment line through its closing brace `)}`. Also remove the now-unused imports if no other code references `Flame` and `Snowflake` — but since the new Form badge uses both, leave them.

- [ ] **Step 4: Verify typecheck**

Run: `cd C:/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -10`

Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd C:/PitchRank && git add frontend/components/TeamInsightsCard.tsx && git commit -m "feat(insights-card): 3rd Form badge + trait line; remove buried Current Form block"
```

---

## Task 9: Update `InsightModal` for parity

**Files:**
- Modify: `frontend/components/insights/InsightModal.tsx`

- [ ] **Step 1: Import FormBadgeInsight, derive formBadge, render 3rd badge + trait line**

Open `frontend/components/insights/InsightModal.tsx`.

Add `FormBadgeInsight` to the type-only import alongside `PersonaInsight` etc.:

```ts
import type {
  // ...existing imports...
  FormBadgeInsight,
} from '@/lib/insights/types';
```

After the existing `const persona = ...` derivation, add:

```ts
  const formBadge = insights?.insights.find((i) => i.type === 'form_badge') as FormBadgeInsight | undefined;
```

In the top-of-modal badge row (around line 142, where the `currentStreak` badge is rendered), add the Form badge inside the same flex container immediately after the existing `playStyle` chip:

```tsx
                  {/* Form Badge — Surging / Slumping */}
                  {formBadge && (
                    <span
                      className={cn(
                        'inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full font-medium',
                        formBadge.label === 'Surging'
                          ? 'bg-orange-500/20 text-orange-700 dark:text-orange-400'
                          : 'bg-sky-500/20 text-sky-700 dark:text-sky-400'
                      )}
                    >
                      {formBadge.label === 'Surging' ? <Flame className="h-3 w-3" /> : <Snowflake className="h-3 w-3" />}
                      {formBadge.label}
                    </span>
                  )}
```

If `Flame` / `Snowflake` aren't already imported in `InsightModal.tsx`, add them to the existing lucide-react import.

Locate where `persona.explanation` is rendered (around line 339: `<p className="text-foreground/90 leading-relaxed">{persona.explanation}</p>`). Immediately after that paragraph, add the trait line:

```tsx
                {persona.details.trait && (
                  <p className="text-sm text-foreground/70 italic mt-2">✨ {persona.details.trait}</p>
                )}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd C:/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -10`

Expected: clean.

- [ ] **Step 3: Commit**

```bash
cd C:/PitchRank && git add frontend/components/insights/InsightModal.tsx && git commit -m "feat(insights-modal): mirror 3rd Form badge + trait line"
```

---

## Task 10: Full validation — tests, typecheck, manual smoke

**Files:** none modified

- [ ] **Step 1: Run full insights test suite**

Run: `cd C:/PitchRank/frontend && npx vitest run lib/insights`

Expected: PASS — all persona + formBadge tests green.

- [ ] **Step 2: Full typecheck**

Run: `cd C:/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -20`

Expected: no errors.

- [ ] **Step 3: Lint**

Run: `cd C:/PitchRank/frontend && npx eslint lib/insights components/TeamInsightsCard.tsx components/insights/InsightModal.tsx`

Expected: clean.

- [ ] **Step 4: Manual smoke test in dev server**

Start: `cd C:/PitchRank/frontend && npm run dev`

In a browser logged in with a premium account, navigate to the team page for `d21d8035-6eb5-4b10-8814-1473f553b19e` (Rush Union Wisconsin 2012 Premier). On the Team Insights card, verify:

- Three badges in the top row: a tier persona, a play style, and a Surging form badge (this team has won 8 straight and rank-climbing).
- Below the persona/play-style row, the signature-result italic line still appears.
- Below that, the new trait line (e.g. "✨ Beat #X, #Y, and #Z this season" or similar).
- The Persona's modal view (click the persona badge / hover info) shows the cited wins inside the `explanation` text.
- No "Current Form: Hot Streak" line at the bottom of the card (the old block is gone).

Sanity-check at least one other team that does NOT have a signature win record — verify the trait line falls through gracefully or is hidden, and no Form badge appears if neither trigger fires.

- [ ] **Step 5: Open PR**

```bash
cd C:/PitchRank && git push -u origin HEAD
gh pr create --base main --title "feat(insights): Title Contender tier + Surging/Slumping Form badge + trait line" --body "Spec: docs/superpowers/specs/2026-05-12-team-insights-persona-v2-design.md\nPlan: docs/superpowers/plans/2026-05-12-team-insights-persona-v2.md\n\nSee spec for full design rationale. PR includes:\n- Title Contender as primary tier label for two-way dominant teams\n- Surging / Slumping Form badge (independent axis from tier persona)\n- Auto-picked trait line under signature result\n- Modal explanations cite specific signature wins (up to 3)\n- Removes the buried Current Form block in the lower card"
```

Note: The branch must be based on `origin/main`, not the stale `seo/ma-wa-state-pillars` branch. If currently on that branch, follow the same worktree-off-`origin/main` pattern used for PR #740.

---

## Self-Review Notes

- **Spec coverage**: Every section of the spec maps to a task — types (Task 1), Title Contender + cited explanations (Task 4), Surging/Slumping (Tasks 5–6), trait line (Tasks 2–4), API state-cohort (Task 7), card UI (Task 8), modal UI (Task 9), validation (Task 10).
- **Placeholder scan**: No TBD/TODO; every code step has full code, every command has expected output.
- **Type consistency**: `FormBadgeInsight`, `PersonaInsight.details.trait`, `PersonaInsight.details.signatureWins`, and `InsightInputData.stateCohort` are introduced in Task 1 and referenced under the same names in every later task. `buildPersonaTrait` / `findSignatureWins` / `generateFormBadge` keep consistent signatures across tests and implementations.
- **Edge cases covered by tests**: null opponent_rank, null scores, empty games, insufficient cohort size, sub-21-day day span, single-snapshot history, two-vs-three vs many signature wins (singular/plural copy).
