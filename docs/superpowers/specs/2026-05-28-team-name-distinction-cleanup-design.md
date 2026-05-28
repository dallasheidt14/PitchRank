# Team-Name Distinction Cleanup — Design

**Date:** 2026-05-28
**Status:** Approved (Phase 0 scoped; later phases decided by data)
**Owner:** Dallas Heidt

## Goal

Produce clean, human-readable team names for public display in the format:

> **Club Name + League/Distinction + Age Group + (State Code)**

…and, where it can be done safely, improve the underlying data so the
duplicate-matching/dedup system also benefits — **without** breaking it and
**without** a large, churny rewrite.

## Background — why this isn't a fresh build

The display composer **already exists**: `frontend/lib/utils.ts` →
`composeTeamDisplay` / `formatLeague` / `formatDistinction` /
`abbreviateClubName`. It builds the name from structured columns
(`club_name`, `league`, `distinction`, age) and already special-cases
Modular11 (MLS NEXT) via `has_modular11_alias` to keep those names verbatim.

It shipped in PR #722, then PR #743 **reverted it on the two flagship
surfaces** (rankings table + global search) while keeping it live on Compare,
TeamSelector, RecentMovers, infographics, and UnknownOpponentLink. The
composer logic is sound; what looked bad on the scrutinized surfaces was the
**input data quality** — chiefly the `distinction` field carrying junk
(club abbreviations like `pbg`/`lpfc`, the literal `unknown`, league-redundant
tokens) and `club_name` gaps.

**Conclusion:** rebuilding the display layer would just re-ship the reverted
code. The real unblock is improving **distinction data quality at the source.**

## Key architecture facts (risk map)

- `extract_distinctions()` (parser, `src/utils/team_name_utils.py`) is the
  shared root. It feeds **both**:
  - `should_skip_pair()` — the merge/dedup gate. Recomputes from raw team
    names; **does not read** the stored `distinction` column. **Highest risk**
    to change (gates merges on ~170K teams).
  - `resolve_distinction()` — composes the stored `teams.distinction` string.
    Feeds display + the identity-grouping key. **Medium risk** (stored value +
    5 ingest matchers + weekly backfill write it; merge gate unaffected).
- So there's a risk ladder: **display formatter (read-only) < resolve_distinction (composer) < extract_distinctions (parser).**
- Matcher-logic changes have a history of being reverted when they regress
  (e.g. `Revert united/real from NOISE_WORDS`, `Revert protected division…`).
  The missing ingredient last time was a **regression safety net.**

## Scope decisions (locked)

- **Modular11 / MLS NEXT (AD/HD):** leave the format untouched. `ad`/`hd` are
  load-bearing there, never blocklisted.
- **`unknown` rows (8,074):** out of scope here. These are GotSport
  placeholder/stub teams (`team_name = "unknown_<id>"`, no club/league). They
  need an identity **backfill**, tracked separately — not a distinction fix.
- **Bias:** public display first; matcher/dedup gains taken only where free of
  churn/breakage.

## Approach — phased, diagnostic-first (decide as we go)

- **Phase 0 — Characterization harness (measure only; no changes).** ← current
- **Phase 1 — Enhance the logic, gated by the harness.** Scope (composer-only
  vs. root parser) decided after reading Phase 0.
- **Phase 2 — Re-run the distinction backfill** on the improved logic; measure
  the drop in junk rates.
- **Phase 3 — Re-enable `composeTeamDisplay`** on rankings + global search
  (un-revert the #743 surfaces) once quality clears an agreed bar.

## Phase 0 detail (this increment)

Two read-only artifacts, both **reusing existing scripts**:

**A. Distinction quality report** — modernize `scripts/dryrun_team_distinction.py`:
- Run the **canonical** `resolve_distinction` (from
  `src/utils/team_name_utils.py`, not the script's drifted local copy) over all
  active teams.
- Report coverage (non-null %), the `(club, age, league, gender, state,
  distinction)` uniqueness-key **collision rate**, and **problem-bucket counts
  with examples**: club-abbreviation leakage, `unknown`, league-redundant
  tokens, multi-token composites, single-char tokens.

**B. Merge-verdict baseline** — rewire `scripts/validate_normalizer.py`:
- Corpus: historically merged pairs (`team_merge_map` deprecated↔canonical,
  which *should* match) + a sample of real same-club/cohort pairs.
- Snapshot the current `should_skip_pair()` verdict per pair → frozen baseline.
- Headline safety metric: **how often the gate would block a real historical
  merge** (a regression if it worsens after any Phase 1 change).
- Fix the stale hardcoded path; wire to `should_skip_pair` / `extract_distinctions`.

**Deliverable:** a committed report (counts, collision rate, problem buckets
with examples, merge-verdict baseline) + the two refreshed scripts. We review
it together, then decide Phase 1 scope.

**Explicitly NOT in Phase 0:** no changes to `resolve_distinction` /
`extract_distinctions`, no DB writes, no display/frontend changes.

## Open questions (deferred to data)

- Phase 1 scope: composer-only (`resolve_distinction`) vs. root parser
  (`extract_distinctions`) — decided by what the Phase 0 report shows.
- The quality bar that gates Phase 3 (re-enabling composed names on
  rankings/search).
