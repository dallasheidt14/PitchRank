# Team Insights Persona v2 — Design

**Status:** Approved 2026-05-12
**Scope:** Premium Team Insights card and modal — persona/style badge area + new trait line + Surging/Slumping form badge + enriched explanations.

## Problem

Today's persona system has four labels (Giant Killer, Flat Track Bully, Gatekeeper, Wildcard) derived from a single signal: win rate vs. stronger / weaker opponents by power score. Practical limitations:

- Teams that beat **both** tiers (high win rate vs stronger AND vs weaker) collapse to Giant Killer, which sells them short.
- Tier-based labels cannot express **temporal** signals — a hot or cold stretch is invisible at the top of the card. The buried "Current Form" line near the bottom only surfaces when `perf_centered` is extreme.
- The persona explanation is generic ("Won 2 of 5 games against stronger opponents…"). It never names a specific opponent or score, so it doesn't feel scouted.
- The compact card under-uses already-fetched data (`opponent_rank`, `ranking_history`, cohort stats).

## Goals

1. Add a primary tier label for two-way dominant teams.
2. Surface temporal trend (Surging / Slumping) without overloading the tier label.
3. Add a single auto-picked **trait line** that surfaces the most distinguishing fact about this team that isn't already visible on the card.
4. Make the long-form explanation in `InsightModal` cite specific games.

Non-goals: changing the underlying v53e signals, expanding the persona to play-style decisions, modifying the non-premium teaser.

## Design

### Top-of-card badge row — 3 badges

Today: `[Persona] [PlayStyle]`.
New: `[Tier] [Style] [Form]` — each independent, each can be missing.

```
🗡️ Giant Killer   🏆 Two-Way Powerhouse   🔥 Surging
"Beat #4 Eclipse 3-1, fell to #6 Sockers 1-2"   ← signature line (existing)
✨ 3-1 vs top-10 opponents                       ← trait line (new)
```

The buried "Current Form: Hot Streak / Cold Streak" block at the bottom of the card is **removed** — its signal is promoted into the Form badge.

### Tier badge — adds **Title Contender**

Modifies `determinePersona()` in `frontend/lib/insights/persona.ts`. New decision tree (first match wins):

| Label | Threshold | Min sample |
|---|---|---|
| **Title Contender** *(new)* | `winRateVsStronger ≥ 0.40` AND `winRateVsWeaker ≥ 0.75` | ≥2 games vs stronger AND ≥2 vs weaker |
| **Giant Killer** | `winRateVsStronger ≥ 0.40` AND `winsVsStronger ≥ 2` | ≥2 games vs stronger |
| **Flat Track Bully** | `winRateVsStronger < 0.25` AND `winRateVsWeaker > 0.80` | ≥2 games each tier |
| **Gatekeeper** | `winRateVsWeaker > 0.65` AND (`winRateVsStronger < 0.30` OR <2 games vs stronger) | ≥2 games vs weaker |
| **Wildcard (volatile)** | ≥2 blowout wins AND ≥2 blowout losses | — |
| **Wildcard (default)** | none of the above | — |

Title Contender is placed **first** so the strongest teams aren't downgraded into Giant Killer.

The same age-anchor-scaled power-score threshold used today (`BASE_POWER_DIFF_THRESHOLD = 0.08` × age anchor) defines stronger / weaker / similar buckets — unchanged.

### Form badge — new, separate from tier

New module `frontend/lib/insights/formBadge.ts`. Sources:

- `ranking_history` (already fetched by the insights API; same data feeding the existing `Movement (Nationally)` line).
- The team's last 5 played games (from `games` payload, ignoring null-score scheduled games).

Decision (first match wins; otherwise no badge):

| Label | Trigger |
|---|---|
| **Surging** | `latest_rank − rank_at_least_21_days_ago ≤ −10` AND last 5 games have ≥4 wins and 0 losses |
| **Slumping** | `latest_rank − rank_at_least_21_days_ago ≥ +10` AND last 5 games include ≥3 losses |
| *(hidden)* | neither |

Rank deltas use the 3-level fallback already present in `computeRankVelocity()` (`rank_in_cohort_final` → `rank_in_cohort_ml` → `rank_in_cohort`). The 21-day floor exists so a single noisy week of snapshots cannot trip the badge — there must be a sustained shift.

The "or" form considered for Slumping was rejected in design: it caused false positives where a team had a rough week without any underlying rank movement.

### Trait line — single auto-picked trait

New function in `frontend/lib/insights/personaTrait.ts` (or co-located in `persona.ts`). Picks the first qualifying entry, returns `null` if none qualify:

| Priority | Trait | Trigger | Example output |
|---|---|---|---|
| 1 | **Signature wins list** | ≥2 wins where `opponent_rank ≤ 25` | "Beat #3, #7, and #12 this season" (top 3 by rank, ascending) |
| 2 | **Big-game record** | ≥3 games where `opponent_rank ≤ 10` | "3-1 vs top-10 opponents" |
| 3 | **State leaderboard** | team is top 5 in its state cohort *(state = `team.state_code`, cohort = state + age + gender, Active only)* | "#3 in WI U14 Girls" |
| 4 | **National percentile** | team is top 5% of national cohort *(reuses `cohortStats` already computed)* | "Top 3% nationally" |
| 5 | **Margin profile** *(fallback)* | ≥6 wins played | "Wins by 2.4 goals on average" (capped at +6 per game to mirror v53e) |

Notes:

- The state-leaderboard trait requires a new lightweight Supabase query (rank within `state_code + age + gender` filtered to `status='Active'`). Cohort-stat computation already does the national cut; the state cut is the same query with one more `.eq()`.
- Trait line is rendered as plain text, italic + small, under the existing signature-result line. No icon, no chip styling — keeps the badge row visually dominant.
- Per memory `feedback_no_powerscore_tiers_in_content.md`: traits surface ranks and counts, not power-score tier thresholds. Premium-only feature, but kept consistent with public conventions.

### Modal explanations — cite real games

`persona.explanation` (rendered in `frontend/components/insights/InsightModal.tsx:339`) is enriched for tier labels that reference stronger-opponent wins.

For **Title Contender** and **Giant Killer**, append a parenthetical listing up to **3 signature wins** (highest-ranked beaten, tie-broken by margin):

> "Won 3 of 5 games against stronger opponents (beat #4 Eclipse 3-1, #11 Sockers 2-0, #18 Burn 1-0). This team rises to the occasion against elite competition and shouldn't be underestimated in big matchups."

For **Flat Track Bully** / **Gatekeeper** / **Wildcard**, explanations are unchanged — there are no signature wins worth citing.

Card tooltip is untouched (too small to fit a game list; stays generic-by-label).

## Data flow

```
GET /api/insights/[teamId]
  └─ existing fetches (team, ranking, games, opponent rankings, ranking_history, cohortStats)
  └─ NEW: state-cohort query for state-leaderboard trait
  │
  ▼
generateAllInsights(data)
  ├─ generateSeasonTruth(data)   ← existing, unchanged
  ├─ generateConsistency(data)   ← existing, unchanged
  ├─ generatePersonaInsight(data)
  │    ├─ determinePersona()     ← + Title Contender branch
  │    ├─ findSignatureResult()  ← existing
  │    ├─ findSignatureWins(data, n=3)   ← NEW
  │    └─ buildPersonaTrait(data)        ← NEW (5-priority pool)
  └─ generateFormBadge(data)     ← NEW (Surging / Slumping / null)
```

## Types

```ts
// types.ts additions
export type FormBadgeLabel = 'Surging' | 'Slumping';

export interface FormBadgeInsight {
  type: 'form_badge';
  label: FormBadgeLabel;
  rankDelta: number;        // negative = improved
  daySpan: number;
  recentRecord: string;     // "5-0-0" or "1-3-1"
}

// PersonaInsight.details additions
trait: string | null;       // e.g. "Beat #3, #7, and #12 this season"
signatureWins: Array<{ opponent_rank: number; teamScore: number; oppScore: number }>;
```

## File changes

| File | Change |
|---|---|
| `frontend/lib/insights/types.ts` | + `FormBadgeInsight`, `FormBadgeLabel`; extend `PersonaInsight.details` |
| `frontend/lib/insights/persona.ts` | + Title Contender branch, + `findSignatureWins`, + `buildPersonaTrait`, enrich `explanation` for Title Contender & Giant Killer |
| `frontend/lib/insights/formBadge.ts` *(new)* | `generateFormBadge(data)` producing `FormBadgeInsight \| null` |
| `frontend/lib/insights/index.ts` | wire `generateFormBadge` into `generateAllInsights` |
| `frontend/app/api/insights/[teamId]/route.ts` | + state-cohort query (state_code + age + gender, Active), pass into `InsightInputData` |
| `frontend/components/TeamInsightsCard.tsx` | render 3rd badge (Form), render trait line under signature result, remove the "Current Form" block (lines ~467-500) |
| `frontend/components/insights/InsightModal.tsx` | render 3rd badge, render trait line, parity with card |

## Edge cases

- **Sparse ranking_history**: Form badge requires ≥21 days of snapshots. Hide badge if too few.
- **No opponent rank data**: Trait line falls through priorities; if `opponent_rank` is missing for all games, traits 1 and 2 are unreachable — that's intentional.
- **State cohort < 5 teams**: State-leaderboard trait skipped (sample too small to be meaningful); fall through to national percentile.
- **`team.state_code` is null**: State-leaderboard trait skipped (no state to query); fall through.
- **Title Contender stealing from Giant Killer**: by design — Title Contender is a stricter, more impressive label.
- **Form badge conflicting with persona**: by design — they're independent axes. A "Giant Killer · Surging" team is a valid and useful combo.
- **Existing data assumptions**: `home_team_master_id` / `away_team_master_id` are pre-normalized to canonical `team_id_master` upstream of insight generators (fix shipped in PR #740) — Form badge can compare with `===`.

## Out of scope

- Changing v53e signals or power-score formula
- Touching the non-premium blurred teaser layout
- Adding tournament-vs-league split (data not reliably tagged on games)
- Adding home/away split (home field irrelevant in youth soccer per project convention)
- Defensive-identity trait (overlaps with the existing Defensive Wall play style badge)

## Test plan

- Rush Union Wisconsin 2012 Premier (`d21d8035-…`) — should now show: Tier=Giant Killer or Title Contender, Form=Surging (8 straight, rank climbing), Trait=top-25 wins citation.
- A bottom-cohort team with rank dropping and recent losses — Form=Slumping.
- A team with no top-25 wins but in top 5% nationally — Trait falls through to "Top X% nationally".
- A team with insufficient `ranking_history` — Form badge hidden.
- Tooltip on the new Form badge — explains the signal in plain language.

## Migration / rollout

- Premium-only feature; no DB migration needed.
- All changes are additive at the API level; the only user-visible removal is the "Current Form" line at the bottom of the card (its signal moves to the Form badge).
- No flag rollout planned — ship in one PR.
