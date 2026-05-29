# Distinction Cleanup — Phase 1b: Re-enable Composed Display on Rankings + Global Search

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the cleaned, composed team name (`composeTeamDisplay`) on the two surfaces PR #743 reverted to raw `team_name` — the rankings table and global search — now that the underlying distinction data is clean.

**Architecture:** Pure frontend display change. `composeTeamDisplay(team)` already exists and is live on every other surface (Compare, Team Selector, Recent Movers, infographics, Unknown-Opponent). We re-wire it into `RankingsTable` (cell render + team-column sort key + SEO JSON-LD + in-table filter haystack) and `GlobalSearch` (dropdown label). Search *matching* is unchanged — `useTeamSearch.searchable_name` already folds in league/distinction tokens. Navigation uses `team_id_master`, so display text changes cannot affect links. Modular11/MLS NEXT teams stay verbatim because `has_modular11_alias` is populated on both surfaces' rows and `composeTeamDisplay` short-circuits on it.

**Tech Stack:** Next.js 16 / React 19 / TypeScript, `frontend/lib/utils.ts` (`composeTeamDisplay`).

**Spec:** `docs/superpowers/specs/2026-05-28-team-name-distinction-cleanup-design.md`
**Reverted-by:** PR #743 (`42180ba21`); this un-reverts its two surfaces against current code.

**Branch:** `feat/distinction-cleanup` (continue on it).

**Why no unit-test-first (TDD note):** This is a display re-wire of an already-unit-tested helper (`composeTeamDisplay`). The behavior that broke last time was *visual* (names looked bad due to dirty data, now fixed). The meaningful gate is the **visual smoke test in Task 3**, plus `tsc`/lint. Component snapshot tests would be brittle and are not added.

---

## File Structure

- **Modify** `frontend/components/RankingsTable.tsx` — 4 edits: import, cell render, team-column sort key, SEO schema name, in-table filter haystack.
- **Modify** `frontend/components/GlobalSearch.tsx` — 2 edits: import, dropdown label (+ aria-label).
- No backend, no type, no data changes.

---

## Task 1: RankingsTable — composed name in cell, sort, SEO, and filter

**Files:**
- Modify: `frontend/components/RankingsTable.tsx`

- [ ] **Step 1: Import `composeTeamDisplay`**

Add `composeTeamDisplay` to the imports from `@/lib/utils`. If `RankingsTable.tsx` already imports from `@/lib/utils`, add it to that import list; otherwise add a new line near the other `@/components`/`@/lib` imports (e.g. just after the `RankingsSchema` import on line 16):
```tsx
import { composeTeamDisplay } from '@/lib/utils';
```

- [ ] **Step 2: Render the composed name in the team cell**

Replace the visible team-name span (currently around line 569):
```tsx
                              {team.team_name}
```
with:
```tsx
                              {composeTeamDisplay(team)}
```
(Leave the `{club_name} • {STATE}` subline below it unchanged.)

- [ ] **Step 3: Sort the team column by the composed name**

In the `sortedRankings` `sort` callback, the `case 'team':` branch (around lines 139–142) currently reads:
```tsx
        case 'team':
          aValue = a.team_name.toLowerCase();
          bValue = b.team_name.toLowerCase();
          break;
```
Change it to:
```tsx
        case 'team':
          aValue = composeTeamDisplay(a).toLowerCase();
          bValue = composeTeamDisplay(b).toLowerCase();
          break;
```

- [ ] **Step 4: Use the composed name in the SEO schema**

In `topTeamsForSchema` (around line 324), change:
```tsx
      teamName: team.team_name,
```
to:
```tsx
      teamName: composeTeamDisplay(team),
```

- [ ] **Step 5: Make the in-table filter match the composed name**

The `visibleRankings` haystack (around line 192) currently reads:
```tsx
      const haystack = normalize(`${team.team_name ?? ''} ${team.club_name ?? ''}`);
```
Change it to also include the league + distinction tokens that now appear in the visible name:
```tsx
      const haystack = normalize(
        `${team.team_name ?? ''} ${team.club_name ?? ''} ${team.league ?? ''} ${(team.distinction ?? '').replace(/\|/g, ' ')}`
      );
```

- [ ] **Step 6: Typecheck + lint the change**

```bash
cd /c/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -20
cd /c/PitchRank/frontend && npx eslint components/RankingsTable.tsx 2>&1 | tail -20
cd /c/PitchRank/frontend && npx prettier --write components/RankingsTable.tsx
```
Expected: `tsc` reports no errors in `RankingsTable.tsx`; eslint clean; prettier reformats if needed. (Do NOT run `prettier --check .` repo-wide — on Windows it false-flags CRLF; only format the changed file.)

- [ ] **Step 7: Commit**

```bash
cd /c/PitchRank
git add frontend/components/RankingsTable.tsx
git commit -m "feat(rankings): render composed team name in rankings table (re-enable #722 display)"
```

---

## Task 2: GlobalSearch — composed name in the dropdown

**Files:**
- Modify: `frontend/components/GlobalSearch.tsx`

- [ ] **Step 1: Import `composeTeamDisplay`**

Add near the existing imports (e.g. after the `useTeamSearch` import on line 11):
```tsx
import { composeTeamDisplay } from '@/lib/utils';
```

- [ ] **Step 2: Render the composed name in the result row**

The dropdown label (line 249) currently reads:
```tsx
                      <div className="font-medium truncate">{highlightMatch(team.team_name, deferredSearchQuery)}</div>
```
Change it to:
```tsx
                      <div className="font-medium truncate">{highlightMatch(composeTeamDisplay(team), deferredSearchQuery)}</div>
```

- [ ] **Step 3: Update the row aria-label to match the visible name**

Line 247 currently reads:
```tsx
                      aria-label={`Select ${team.team_name}`}
```
Change it to:
```tsx
                      aria-label={`Select ${composeTeamDisplay(team)}`}
```
(Leave the search-matching logic in `searchResults` untouched — it already uses `searchable_name`, which includes the composed tokens, so typing either the raw or composed form still finds the team.)

- [ ] **Step 4: Typecheck + lint the change**

```bash
cd /c/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -20
cd /c/PitchRank/frontend && npx eslint components/GlobalSearch.tsx 2>&1 | tail -20
cd /c/PitchRank/frontend && npx prettier --write components/GlobalSearch.tsx
```
Expected: no `tsc` errors, eslint clean.

- [ ] **Step 5: Commit**

```bash
cd /c/PitchRank
git add frontend/components/GlobalSearch.tsx
git commit -m "feat(search): render composed team name in global search dropdown (re-enable #722 display)"
```

---

## Task 3: Visual smoke test (the gate that #743 failed)

This is the verification that the composed names now read well on the live UI. No code change unless a defect is found.

- [ ] **Step 1: Whole-project typecheck**

```bash
cd /c/PitchRank/frontend && npx tsc --noEmit 2>&1 | tail -20
```
Expected: no errors.

- [ ] **Step 2: Start the dev server**

```bash
cd /c/PitchRank/frontend && npm run dev
```
(Run in background; wait for "Ready"/local URL. `.env.local` is present in `C:/PitchRank/frontend`.)

- [ ] **Step 3: Verify the rankings table**

Open the rankings page (e.g. `http://localhost:3000/rankings?ageGroup=u14&gender=male`, or the app's default rankings route). Confirm:
- Team names render as composed (e.g. `Phoenix Premier FC Premier` / `SD Surf ECNL RL Blue`-style), **not** raw or junk.
- A **Modular11 / MLS NEXT** team (filter to one, or find an `... U13 AD/HD` team) still shows its **raw verbatim name** (e.g. `Carolina Core FC U13 HD`), not a composed/duplicated `... MLS Next HD HD`.
- The `{club} • {STATE}` subline still shows.
- Clicking a row navigates to `/teams/<id>` (links still work).
- Typing in the in-table cohort search matches the visible composed name (e.g. search a distinction word like `premier` or a league like `ecnl`).
- No console errors.

- [ ] **Step 4: Verify global search**

Use the top-nav search box. Confirm:
- Dropdown rows show the composed name (clean), Modular11 teams show raw.
- Typing the **raw** form (e.g. part of `team_name`) finds the team.
- Typing a **composed** token (e.g. a distinction word or league) finds the team.
- Selecting a result navigates to the team page.

- [ ] **Step 5: Stop the dev server and report**

Stop `npm run dev`. Report the smoke-test outcome (pass, or specific visual issues). If a defect is found (e.g. a class of names still reads poorly), capture the example and STOP for a fix decision — do not paper over it.

---

## Self-Review

**Spec coverage:** Phase 1b goal = "re-enable composed names on the two reverted flagship surfaces." Task 1 covers RankingsTable (render/sort/schema/filter); Task 2 covers GlobalSearch (label/aria); Task 3 is the visual gate. ✅

**Placeholder scan:** Every code step shows the exact before/after snippet; commands have expected output. The only soft spots are line numbers ("around line N") — intentional, since formatting may shift; the code anchors are exact. ✅

**Type/name consistency:** `composeTeamDisplay(team)` is called with `RankingRow` in both files; `RankingRow` includes `team_name`, `club_name`, `league`, `distinction`, `has_modular11_alias` (verified in `frontend/types/RankingRow.ts`), which is structurally compatible with `composeTeamDisplay`'s parameter type. `has_modular11_alias` is populated on rankings rows (RPC migration `20260505000000`) and on search rows (`useTeamSearch.ts:131`). ✅
