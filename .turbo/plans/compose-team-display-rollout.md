---
status: done
---

# Plan: Roll out composeTeamDisplay to remaining team_name display surfaces

## Context

PR #722 (`Clean team display in rankings, Compare, and search`, merged 2026-05-05, `origin/main` HEAD `9325b666c`) introduced `composeTeamDisplay(team)` in `frontend/lib/utils.ts:125` and adopted it in the rankings table, global search, Compare panel, TeamSelector, and RecentMovers. The helper composes a label from `club_name + league + distinction` and short-circuits to raw `team_name` for Modular 11 / MLS Next teams (`has_modular11_alias === true`). Producers — `useRankings` (via the rankings RPCs) and `useTeamSearch` (via a one-shot `fetchModular11TeamIds()` probe) — already attach `has_modular11_alias` to every `RankingRow` they emit.

Five infographic components, their five renderer scripts, and `UnknownOpponentLink` were deferred from PR #722 as out of scope. They still render raw `team_name`, so the same team appears with two different labels depending on surface. This plan rolls `composeTeamDisplay` into those surfaces, completing the consistency work. All target surfaces already consume `RankingRow` (or a `RankingRow & { ... }` extension), so no producer-side type plumbing or fetch changes are required — the rollout is render-time only.

Confirmed product calls from /draft-plan discussion: (a) **swap renderers in addition to components** so downloadable images match on-page previews; (b) **swap inside `canvasRenderer.ts` directly** (single edit point — though note that despite the generic name, this file is currently the standalone Top 10 renderer, not a shared base); (c) **one step per component+renderer pair** for clean per-surface verification; (d) **no new tests** — rely on `tsc --noEmit` + smoke verification, since `composeTeamDisplay` is already unit-tested and consumers swapping `team.team_name` → `composeTeamDisplay(team)` is mechanical; (e) **swap all 4 visible sites in `UnknownOpponentLink`** (3 visible-text + 1 dropdown aria-label — the input-echo edge case at :243 is acknowledged below).

## Pattern Survey

### Analogous Features

- `frontend/components/RankingsTable.tsx` (post-PR #722) — Renders the row label via `composeTeamDisplay(team)` at `:518`; uses it in JSON-LD row data (`:298`) and the team-column sort key (`:133-134`). The row-link `aria-label` at `:462` deliberately stays on raw `team_name` (`View ${team.team_name} team details`), as does the click-tracking carve-out at `:453` (`trackTeamRowClicked({ team_name: team.team_name, club_name, ... })`) — render surfaces use composed text, analytics payloads and the row-link aria-label stay raw. The composed-`aria-label` exemplars are in GlobalSearch and TeamSelector below (dropdown row aria-labels).
- `frontend/components/GlobalSearch.tsx` — Dropdown rows render `highlightMatch(composeTeamDisplay(team), query)`; the dropdown-row `aria-label` at `:247` uses `composeTeamDisplay(team)`. **This is the canonical pattern to mirror at `UnknownOpponentLink.tsx:543/545`.**
- `frontend/components/ComparePanel.tsx` — Header cells, prediction props, common-opponent rows, and radar legend all call `composeTeamDisplay(teamNDetails | teamNData)`. Tracking events (`trackCompareOpened`, `trackComparisonGenerated`, `trackPredictionViewed`, `trackTeamsSwapped`) keep raw `team_name`/`team_a_name`/`team_b_name`.
- `frontend/components/TeamSelector.tsx` — Selected-team echo, dropdown rows, dropdown-row `aria-label` at `:241`, and "Selected:" indicator use `composeTeamDisplay(team)`.
- `frontend/components/RecentMovers.tsx` — Computes `const displayName = composeTeamDisplay(team)` once, reuses it for visible label and `aria-label`.

### Reusable Utilities

- `frontend/lib/utils.ts:125` — `composeTeamDisplay(team)`. Reads `team_name`, `club_name`, `league`, `distinction`, `has_modular11_alias`. Returns raw `team.team_name` when `club_name` is null OR `has_modular11_alias` is truthy; otherwise returns `[abbreviateClubName(club_name), formatLeague(league), formatDistinction(distinction)].filter(Boolean).join(' ')`. Shape-tolerant (extra fields ignored), so passing a full `RankingRow` is the idiomatic call.
- `frontend/types/RankingRow.ts:14` — `RankingRow.has_modular11_alias?: boolean | null`. Already populated by both rankings RPCs (`get_national_rankings`, `get_state_rankings`) and by `useTeamSearch` (via `modular11TeamIds.has(team.team_id_master)` at `frontend/hooks/useTeamSearch.ts:131`).

### Convention Anchors

- **Import path**: `import { composeTeamDisplay } from '@/lib/utils';` — single named export. None of the target files currently import from `@/lib/utils`, so each gets one new import line.
- **What gets passed**: the full team object (`team`, `team1`, `team2`, `champion.team`, `selectedTeam`, etc.) — never field-spread or pre-extracted. Helper is shape-tolerant.
- **Tracking carve-out rule**: visible text, `aria-label`, JSON-LD, and sort keys use `composeTeamDisplay`; analytics payloads keep raw `team_name`. Enforced by call site, not the helper. Survey confirms zero `track*` / `posthog` / `gtag` calls in `frontend/app/infographics/**` and `UnknownOpponentLink.tsx` — **no carve-outs to preserve in the target surfaces**.
- **Filter/sort over raw text** is *not* a display surface. `UnknownOpponentLink.tsx:220, :226-227` use `(team.searchable_name || team.team_name)` for filtering against the user's typed query and sorting matches; these stay on raw text.
- **Renderer execution context**: every `*Renderer.ts` runs in the browser (calls `document.createElement('canvas')`, imported from the `'use client'` page at `frontend/app/infographics/page.tsx`). No Node-side image generation in scope.
- **`canvasRenderer.ts` is misleadingly named**: despite the generic file name, it is the standalone Top-10 renderer — its sole export `renderInfographicToCanvas` is imported only by `frontend/app/infographics/page.tsx:15`. The other renderers (`headToHeadRenderer`, `rankingMoversRenderer`, `stateChampionsRenderer`, `teamSpotlightRenderer`) are independent and do not delegate to it.
- **Renderer truncation pattern**: each renderer does `let teamName = team.team_name.toUpperCase()` then runs a width-based truncation loop against `ctx.measureText(...)`. The idiomatic swap is `let teamName = composeTeamDisplay(team).toUpperCase()` — the truncation logic continues to operate on the visible (composed) string, which is the correct behavior.

### Proposed Alignment

The rollout follows PR #722's pattern wholesale: replace `team.team_name` with `composeTeamDisplay(team)` at the leaf JSX/`ctx.fillText` site in each target file, add the `composeTeamDisplay` import, and rely on the fact that `has_modular11_alias` already flows in via `RankingRow`. No prop plumbing, no new fetches, no type changes.

The single deliberate deviation from PR #722: **no analytics carve-outs** — verified absent from every target surface. Every `team_name` reference in scope is either a render-time use (swap) or a filter/sort-time use over `searchable_name || team_name` (skip). Both categories are explicitly enumerated in Implementation Steps below.

## Implementation Steps

1. **Pair 1 — HeadToHead (preview + renderer)**
   - `frontend/components/infographics/HeadToHeadPreview.tsx`: add `import { composeTeamDisplay } from '@/lib/utils';` next to the existing `RankingRow` type import. Replace `{team.team_name}` at `:56` with `{composeTeamDisplay(team)}`.
   - `frontend/components/infographics/headToHeadRenderer.ts`: add `import { composeTeamDisplay } from '@/lib/utils';` below the `RankingRow` import. At `:152` replace `let team1Name = team1.team_name.toUpperCase();` with `let team1Name = composeTeamDisplay(team1).toUpperCase();`. At `:181` apply the same change for `team2Name = team2.team_name.toUpperCase()` → `composeTeamDisplay(team2).toUpperCase()`. Width-truncation loop downstream is unchanged — it operates on the composed string.

2. **Pair 2 — Top 10 (preview + canvasRenderer)**
   - `frontend/components/infographics/Top10Infographic.tsx`: add `composeTeamDisplay` import. Inside `RankingRowItem` (function defined at `:199`), replace `{team.team_name}` at `:264` with `{composeTeamDisplay(team)}`.
   - `frontend/components/infographics/canvasRenderer.ts`: add `composeTeamDisplay` import. At `:194` replace `let teamName = team.team_name.toUpperCase();` with `let teamName = composeTeamDisplay(team).toUpperCase();`. The `while (ctx.measureText(teamName).width > maxTeamWidth ...)` loop at `:196-198` is unchanged. The clubName/state line at `:202` (`${team.club_name || ''} | ${team.state || 'N/A'}`) stays — it's a separate descriptor, not a team-name surface.

3. **Pair 3 — StateChampions (preview + renderer)**
   - `frontend/components/infographics/StateChampionsPreview.tsx`: add `composeTeamDisplay` import. Replace `{champion.team.team_name}` at `:188` with `{composeTeamDisplay(champion.team)}`.
   - `frontend/components/infographics/stateChampionsRenderer.ts`: add `composeTeamDisplay` import. At `:153` replace `let teamName = champ.team.team_name.toUpperCase();` with `let teamName = composeTeamDisplay(champ.team).toUpperCase();`. Width-truncation downstream operates on the composed string.

4. **Pair 4 — BiggestMovers (preview + rankingMoversRenderer)**
   - `frontend/components/infographics/BiggestMoversPreview.tsx`: add `composeTeamDisplay` import. Replace `{team.team_name}` at `:83` with `{composeTeamDisplay(team)}`. (`MoverTeam extends RankingRow` declared at `:7` — `has_modular11_alias` flows through automatically.)
   - `frontend/components/infographics/rankingMoversRenderer.ts`: add `composeTeamDisplay` import. At `:152` replace `let name = team.team_name.toUpperCase();` with `let name = composeTeamDisplay(team).toUpperCase();`. The `team` parameter at `:119` is `RankingRow & { change: number; rank?: number }` — composer accepts the shape.

5. **Pair 5 — TeamSpotlight (preview + renderer)**
   - `frontend/components/infographics/TeamSpotlightPreview.tsx`: add `composeTeamDisplay` import. Replace `{team.team_name}` at `:171` with `{composeTeamDisplay(team)}`. (Component prop `team: RankingRow & { rank?: number }` declared at `:8`.)
   - `frontend/components/infographics/teamSpotlightRenderer.ts`: add `composeTeamDisplay` import. At `:129` replace `let teamName = team.team_name.toUpperCase();` with `let teamName = composeTeamDisplay(team).toUpperCase();`.

6. **UnknownOpponentLink — visible text, aria-label, and selected-team summary**
   - `frontend/components/UnknownOpponentLink.tsx`: add `import { composeTeamDisplay } from '@/lib/utils';` next to the existing `RankingRow` and `useTeamSearch` imports. The component already consumes `useTeamSearch()` at `:186`, which populates `has_modular11_alias` on every team via `modular11TeamIds.has(team.team_id_master)` at `useTeamSearch.ts:131`.
   - **Swap (4 sites — all visible-text rendering)**:
     - `:243` — `setSearchQuery(team.team_name)` → `setSearchQuery(composeTeamDisplay(team))`. This populates the search input after a click; the user sees the composed label they selected. The "subsequent re-typing" path is non-blocking by design: `searchable_name` is constructed at `useTeamSearch.ts:80-128` to include `team_name + club_name + U{age} + league + leagueDisplay + distinction + distinctionDisplay`, so every token `composeTeamDisplay` outputs is already a substring of `searchable_name` — the filter at line 220 will continue to find the originally selected team when the user re-types any fragment. Aligns with the "what you selected is what's shown" UX pattern in `TeamSelector.tsx`. Confirmed in /draft-plan discussion.
     - `:543` — `aria-label={`Select ${team.team_name}`}` → ``aria-label={`Select ${composeTeamDisplay(team)}`}``. (Survey originally listed 3 sites but missed this aria-label — included here for accessibility consistency with the dropdown row at `:545`.)
     - `:545` — `<div className="font-medium">{highlightMatch(team.team_name, deferredSearchQuery)}</div>` → `{highlightMatch(composeTeamDisplay(team), deferredSearchQuery)}`. The club/state secondary line below at `:547-549` stays as-is — it's a separate descriptor.
     - `:675` — `{selectedTeam.team_name}` → `{composeTeamDisplay(selectedTeam)}` inside the green confirmation panel.
   - **Do NOT swap (filter/sort sites — operate on raw text by design)**:
     - `:220` — `const searchText = ((team.searchable_name || team.team_name) + ' ' + (team.club_name || '')).toLowerCase();` (filter input)
     - `:226-227` — `const aText = ((a.searchable_name || a.team_name) + ' ' + (a.club_name || '')).toLowerCase();` and the `bText` companion (sort key)
     - These match the user's typed query against normalized text; swapping would break search-as-you-type.
   - **Branch baseline note**: this rollout assumes `origin/main` (PR #722 merged at `9325b666c`). Cut a fresh branch from `origin/main` — do not branch from `scraper/squadi-nj` or any other branch behind main, since those branches do not yet have the modular11-aware `composeTeamDisplay` (verified locally — `scraper/squadi-nj` is `behind 3` from main and shows the pre-PR-#722 helper signature). **Foot-gun**: the local working tree currently has `frontend/lib/utils.ts` modified (the modifications delete the modular11 short-circuit and move `composeTeamDisplay` from `:125` to `:62`); doing `git switch -c <name>` from a dirty working tree carries those modifications onto the new branch and silently overwrites PR #722's helper. Branch with `git switch -c <name> origin/main` and verify `git diff origin/main -- frontend/lib/utils.ts` is empty before starting any edits. If the diff is non-empty, stash or discard the local `utils.ts` modifications first.

## Verification

After implementing, verify each surface manually since `composeTeamDisplay` itself is already unit-tested and the swap is mechanical.

- **Type check**: from `frontend/`, run `npx tsc --noEmit`. Expect zero errors. (Catches type-shape mismatches — e.g., a target file's team object missing `team_name` or `club_name`. **Does NOT catch missing `has_modular11_alias` plumbing**: the helper signature is structurally loose with all modular11-related fields optional, so a producer that omits the flag typechecks cleanly while silently losing the short-circuit. The Modular11 spot-check below is the only verification that proves the modular11 path works — treat it as mandatory, not optional.)
- **Lint**: from `frontend/`, run `npm run lint`. The new imports must satisfy import-order rules.
- **Smoke test (infographics page)**:
  1. Start the dev server: `cd frontend && npm run dev`.
  2. Open `/rankings/national/u14/m` (or any populated cohort) in a second tab and find a row whose displayed label in the existing rankings table **visibly differs** from the row's raw `team_name` — specifically, a row showing both a league suffix (e.g., "ECNL") AND a trailing distinction token (e.g., "White", "Smith", "2"). This guarantees the team has `club_name + league + distinction` populated and is **not** a Modular11 team — so the swap will produce an observable difference. Use that team in each infographic. For each Preview component, confirm the on-page rendered label is composed (matches the rankings-table label, not the raw `team_name`). Picking a row at random (e.g., a generic "U14 ECNL" team) is **not safe** — many such rows have null `distinction` or `has_modular11_alias = true`, both of which short-circuit to raw `team_name` and would silently pass the verification without proving the swap.
  3. Click "Generate" or whatever triggers `renderInfographicToCanvas` / each `*Renderer` to produce the downloadable image. Open the resulting PNG and confirm the team name pixel-text matches the on-page preview (composed label, all caps where the renderer applies `.toUpperCase()`).
  4. Repeat for each of the 5 infographic types: Top 10, Head-to-Head, State Champions, Biggest Movers, Team Spotlight.
- **Modular11 spot-check**: navigate to a roster that includes an MLS Next / Modular 11 team (e.g., MLS Next U15). Confirm those teams render the **raw** `team_name` (the helper short-circuits when `has_modular11_alias === true`). Verify both in the preview and the generated image. This is the regression-most-critical check, since silently dropping the short-circuit would break the parent rule from PR #722.
- **Smoke test (UnknownOpponentLink)**: as a premium user, navigate to a team detail page that has a "link unknown opponent" entry. Confirm:
  - Dropdown rows show composed labels.
  - `aria-label` reads "Select {composed label}" (verify with screen reader or DevTools accessibility panel).
  - Clicking a row populates the search input with the composed label and shows the green selected-team confirmation panel with the composed label.
  - Filtering still works while typing — the user can find a team by typing a fragment of the raw `team_name` (because line 220 still matches against raw text).
- **Edge case to spot-check**: a team with `club_name = null`. The helper falls back to raw `team_name`; both preview and renderer should render raw text without truncation regression.

## Context Files

Files to read in full before starting implementation:

- `frontend/lib/utils.ts` (lines 1-200, especially `:125-145`) — definition of `composeTeamDisplay`, `formatLeague`, `formatDistinction`, `abbreviateClubName`.
- `frontend/types/RankingRow.ts` — the canonical team-row type; confirms `has_modular11_alias?: boolean | null` is already optional and that `league`/`distinction` are non-optional. All target renderers/components extend or alias this type.
- `frontend/hooks/useTeamSearch.ts` (lines 1-150) — confirms the `has_modular11_alias` plumbing path that feeds `UnknownOpponentLink`. Reference for understanding why no producer changes are needed.
- `frontend/components/RankingsTable.tsx` (around the `composeTeamDisplay(team)` call sites and the `:453` tracking carve-out) — canonical reference for how PR #722 wired the helper, including the analytics-vs-render split. Use as a sanity anchor for each swap.
- `frontend/components/GlobalSearch.tsx` (around the `highlightMatch(composeTeamDisplay(team), ...)` site) — reference for the `highlightMatch` + `composeTeamDisplay` composition idiom used at `UnknownOpponentLink.tsx:545`.
- `frontend/components/RecentMovers.tsx` (the `const displayName = composeTeamDisplay(team)` reuse pattern) — small-component reference closest in shape to the infographic components.
- `frontend/app/infographics/page.tsx` — orchestrator; confirms client-side execution context for all 5 renderers and the data flow (`useRankings` → `RankingRow[]` → preview + renderer).
