# Team Name Normalization — Structured Identity (Hygiene Initiative)

**Date:** 2026-05-01
**Owner:** Dallas Heidt
**Status:** Draft

## Problem

`teams.team_name` is a freeform string doing two jobs (display + matching) and reliably doing neither. Step 1 of `data-hygiene-weekly.yml` already canonicalizes age tokens and strips gender words, but the structure of the resulting string still varies wildly. Dry-run analysis (`scripts/dryrun_team_distinction.py`, `scripts/dryrun_investigate_c_and_d.py`) surfaced three distinct hygiene gaps that all collapse the same canonical team identity:

1. **No persisted "distinction" facet** — the squad-level distinguisher (color, numeral, word, coach, direction) is re-parsed on every run instead of stored.
2. **Age-group misclassification (~316 candidates)** — club names with embedded numbers (e.g., `Union 10 FC`) eat the age parser before the real birth year token is reached.
3. **Missing `league` values for u13+ teams (~1,510, real ≈ 1,200–1,300 after Pre-* false positives)** — `backfill_team_leagues.py` either never ran on these or its detector is weaker than expected.

Fixing (1) without (2)/(3) leaves the canonical key noisy. Fixing them together once gives clean ranking-engine cohort identity.

## Canonical Team Identity

Every team is uniquely identified by:

```
Club Name  +  Age Group  +  League  +  Distinction
```

with `gender` and `state_code` as orthogonal cohort axes (already canonical).

- **Club Name** (`club_name`) — already canonical via Monday's `update-missing-club-and-state.yml`.
- **Age Group** (`age_group`) — `u10`–`u19`, U18 merged into U19. Owned by `scripts/fix_team_age_groups.py` (Step 2 of weekly hygiene). Patched in this initiative (workstream B).
- **League** (`league`) — canonical enum (`ECNL`, `ECNL_RL`, `GA`, `NPL`, `NL`, `DPL`, `MLS_NEXT_AD`, `MLS_NEXT_HD`, `EA`, `EA2`, `ASPIRE`, NULL). **Only populated for u13+** (ranking-engine scope). Owned by `scripts/backfill_team_leagues.py`. Patched in this initiative (workstream C).
- **Distinction** (NEW — workstream A) — composite, ordered token list disambiguating squads inside the same club + age + league + gender. Lowercase tokens joined with `|`.

Two teams that share `(club_name, age_group, league, gender, state_code, distinction)` are the same team.

## Workstream A — Distinction Column

### Schema

Additive only.

```sql
ALTER TABLE teams ADD COLUMN distinction text NULL;
COMMENT ON COLUMN teams.distinction IS
  'Composite squad distinguisher within (club, age, league, gender). '
  'Lowercase tokens joined with "|", ordered by category priority. '
  'NULL when team_name has no distinguisher (single squad in cohort).';

CREATE INDEX teams_distinction_idx ON teams (club_name, age_group, league, gender, distinction);
```

### Resolution

Source: existing `extract_distinctions(name)` in `src/utils/team_name_utils.py`. New helper `resolve_distinction(name, club_name) -> Optional[str]` builds the composite by appending every distinguisher in this order, deduped, lowercase, joined with `|`:

1. `coach_name`
2. `team_number`
3. `colors` (sorted)
4. `directions` (sorted)
5. `squad_words` (sorted) — **after stripping any token that matches the team's own `club_name`** (prevents `Cheshire SA → Cheshire 2009 DPL` emitting `cheshire`)
6. `programs` from `extract_distinctions` filtered to a fixed allowlist: `premier`, `select`, `elite`, `classic`, `competitive`, `comp`, `recreational`, `development`, `showcase`, `challenge`, `division`, `reserve`, `copa`, `tal`, `stxcl`, `fdl`, `sccl` (excludes league-equivalents like `ecnl`, `npl`, `ga`, `dpl`, `nal`, `aspire` — those live in `league`)
7. **Length-2 and length-3 alpha tokens** (e.g., coach initials `KH`, `CV`, `NT`; short squad words `Ace`) that the extractor's Pass-4 dump-bucket misclassifies as `location_codes`. Filter set: not in `LOCATION_CODES`, `US_STATES`, `NOISE_WORDS`, `TEAM_COLORS`, `DIRECTION_CANONICAL`, `PROGRAM_WORDS`, `_LEAGUE_EQUIVS`, club tokens, or stop-words `the/and/for`.

Returns `NULL` when the resulting list is empty.

Validated by dry-run: 89.5% coverage, 3.0% live-team collision rate (down from 17.6% with the original priority rule).

### Files

| File | Change |
|---|---|
| `supabase/migrations/<ts>_add_teams_distinction.sql` | NEW |
| `src/utils/team_name_utils.py` | EDIT — add `resolve_distinction()` |
| `scripts/backfill_team_distinction.py` | NEW — one-shot backfill |
| `.github/workflows/data-hygiene-weekly.yml` | EDIT — add Step 1b |
| `src/models/game_matcher.py` | EDIT — populate on team create |
| `src/models/playmetrics_matcher.py` | EDIT — same |
| `src/models/sincsports_matcher.py` | EDIT — same |
| `src/models/tgs_matcher.py` | EDIT — same |
| `src/models/modular11_matcher.py` | EDIT — same |
| `src/models/affinity_wa_matcher.py` | EDIT — same |
| `src/etl/enhanced_pipeline.py` | EDIT — thread distinction through team-create write |

## Workstream B — Age-Group Misclassification Sweep

### Root cause

`scripts/fix_team_age_groups.py` (and the underlying `parse_age_gender` in `scripts/team_name_normalizer.py`) iterates tokens and picks the **first** parseable age token. When a club name embeds a number (e.g., `Union 10 FC 2008`), the `10` is parsed as a 2-digit birth-year shorthand → 2010 → u14/u15/u16 (year-dependent), drowning the real `2008` token that comes later.

Sample bug: 5 teams `Union 10 FC 2008`, `… 2009`, `… 2010`, `… 2011`, `… 2012` all stored as u16 (the "10" wins every time).

### Fix

Patch `parse_age_gender` (or its caller in `normalize_team_names.py` / `fix_team_age_groups.py`) to:

1. **Skip number tokens that match a token in the team's own `club_name`** before age parsing. Reuses the same club-token-strip logic added in Workstream A.
2. **Skip 4-digit "season years" 2019+ when other birth-year-eligible tokens are also present** — `2019`, `2020`, `Spring 2025` etc. are likely season labels, not birth years.
3. **Normalize dual-age tokens to the OLDER cohort consistently** (per `gotcha_slash_age_tokens.md`). Spot-check that `2012/2013` always resolves to u14 (2012), not u13.

### One-shot sweep

Run `fix_team_age_groups.py --rerun-all` over the 316 candidates from `logs/age_misclass_candidates.csv` after the parser fix lands. Manually review the residual ~50–100 that remain misclassified (likely true ambiguous cases).

### Files

| File | Change |
|---|---|
| `scripts/team_name_normalizer.py` | EDIT — `parse_age_gender` skips club-token numbers and post-2018 season years |
| `scripts/fix_team_age_groups.py` | EDIT — accept `--ids-from-csv` flag for targeted re-run |
| `logs/age_misclass_candidates.csv` | INPUT — produced by `dryrun_investigate_c_and_d.py` |

## Workstream C — League Backfill Gap (u13+)

### Root cause

`backfill_team_leagues.py` left ~1,510 u13+ teams with `league=NULL` despite the team_name containing recognizable league markers (ECNL_RL: 390, MLS_NEXT_AD: 347, NPL: 276, ECNL: 175, DPL: 163, GA: 71, EA: 55, NL: 15, ASPIRE: 11, EA2: 7).

Two unknowns to investigate before patching:
1. Is the script not running on all u13+ teams? (Filter scope or batch limit issue.)
2. Are its detection regexes weaker than the ones in `dryrun_investigate_c_and_d.py:LEAGUE_MARKERS`?

### Fix

1. Audit `backfill_team_leagues.py` against the 1,510 candidates — measure how many it now catches with no changes (smoke test of current behavior).
2. Patch detection gaps where the script misses cases the dry-run finds (regex broadening, dash/space variants, embedded markers in `Pre-X` names).
3. **Add explicit Pre-* handling** — `Pre-ECNL`, `Pre-MLS-NEXT`, `Pre-NPL`, `Pre-NL` are separate tiers. Don't backfill them as the parent league. Decision: leave `league=NULL` for Pre-* tiers in this initiative (no enum value yet), or add new enum values? **Recommendation: leave NULL for now; track Pre-* as a future enum extension if needed for ranking-engine cohorts.**
4. Re-run `backfill_team_leagues.py` over all u13+ teams — confirm gap closes from ~1,510 → near zero (excluding Pre-*).

### Files

| File | Change |
|---|---|
| `scripts/backfill_team_leagues.py` | EDIT — broaden regexes, exclude Pre-* explicitly, add `--rerun-all` over u13+ |
| `logs/missing_league_candidates.csv` | INPUT — 1,510-row gap report from dry-run |

## Out of Scope (Explicitly)

- **No UI changes.** `ComparePanel`, `TeamHeader`, `RankingsTable`, search, filters — untouched.
- **No `team_name` rewrite.** `team_name` keeps whatever Step 1 produced. (Future, optional Phase 2.)
- **No new `team_color` / `coach` / `squad_word` / `region_code` columns.** A single composite `distinction` field is the contract.
- **No league backfill for u10/u11/u12.** League is ranking-engine scope (u13+). Younger cohorts stay NULL by design.
- **No new league enum values for Pre-* tiers** in this initiative. Tracked as a future extension.
- **No changes to ranking, prediction, scraping, marketing, or SEO surfaces.**

## Execution Order

Workstreams have a partial ordering dictated by data dependencies:

1. **B (age-group fix) first** — distinction column reads `age_group` for its uniqueness key. Fixing the Union-10-FC pattern first means fewer teams move cohorts after distinction is backfilled.
2. **C (league backfill) second** — distinction key includes `league`. Filling the gap before backfill means fewer teams shift cohort after distinction lands.
3. **A (distinction column) third** — final layer. Backfill once, hygiene step keeps it fresh.

All three can ship in one PR or in sequence; recommend sequence so each step is independently verifiable.

## Backfill / Sweep Plan

### Workstream A
1. Dry-run: emit `(state, league, age_group, gender, club_name, team_count, distinction_resolved, distinction_null)` report.
2. Apply via `psycopg2` chunked at 1000 rows (per `gotcha_supabase_bulk_updates.md`).
3. Sample-audit 100 random rows across cohorts. Verify `(club_name, age_group, league, gender, distinction)` is unique within sampled cohorts.

### Workstream B
1. Dry-run already produced `logs/age_misclass_candidates.csv` (316 rows).
2. After parser patch, re-run `fix_team_age_groups.py` over those IDs.
3. Manually review residual misclassifications.

### Workstream C
1. Dry-run already produced `logs/missing_league_candidates.csv` (1,510 rows).
2. After regex broadening + Pre-* exclusion, re-run `backfill_team_leagues.py` over u13+ teams.
3. Confirm gap closes.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Distinction priority collapses meaningfully different squads | Composite list preserves all distinguishers; dry-run validated 3.0% collision rate. `should_skip_pair` still compares full distinction set for fuzzy-merge precision. |
| Age-group fix moves teams between cohorts mid-season | Run during weekly hygiene window; rankings recompute from scratch on next weekly run. |
| League backfill writes wrong league for ambiguous names | Pre-* explicit exclusion + dry-run audit before live write. |
| New providers ship formats that miss extractor patterns | Same risk as today's fuzzy-merge. Weekly hygiene step + low-confidence queue catch drift. |

## Verification

### Workstream A
- `SELECT COUNT(*) FROM teams WHERE distinction IS NOT NULL` ≥ ~85% (dry-run showed 89.5%).
- Spot-check 5 cohorts where the team list is known — every squad has the correct composite distinction.
- After hygiene step ships: next Tuesday run shows `distinction` populated on all new teams.
- After import write paths ship: insert one new team via dry-run scrape, confirm `distinction` set.

### Workstream B
- After parser fix: re-run `dryrun_investigate_c_and_d.py` — the Union-10-FC-pattern teams resolve to correct `age_group`.
- 316 → < 50 residual candidates after sweep.

### Workstream C
- After backfill: re-run `dryrun_investigate_c_and_d.py` — `(d) Missing league` count drops from 1,510 → near zero (Pre-* excluded).
- Spot-check `Solar SC`, `FC Dallas`, `Atletico Dallas Youth` — top-leak clubs are clean.

## Files Touched (Combined)

| File | Workstream | Change |
|---|---|---|
| `supabase/migrations/<ts>_add_teams_distinction.sql` | A | NEW |
| `src/utils/team_name_utils.py` | A | EDIT — add `resolve_distinction()` |
| `scripts/backfill_team_distinction.py` | A | NEW |
| `scripts/team_name_normalizer.py` | B | EDIT — club-token + season-year filters |
| `scripts/fix_team_age_groups.py` | B | EDIT — `--ids-from-csv` |
| `scripts/backfill_team_leagues.py` | C | EDIT — broaden regex + Pre-* exclusion |
| `.github/workflows/data-hygiene-weekly.yml` | A | EDIT — add Step 1b |
| `src/models/game_matcher.py` | A | EDIT — populate distinction on team create |
| `src/models/playmetrics_matcher.py` | A | EDIT — same |
| `src/models/sincsports_matcher.py` | A | EDIT — same |
| `src/models/tgs_matcher.py` | A | EDIT — same |
| `src/models/modular11_matcher.py` | A | EDIT — same |
| `src/models/affinity_wa_matcher.py` | A | EDIT — same |
| `src/etl/enhanced_pipeline.py` | A | EDIT — thread distinction through write |

No frontend files. No ranking files. No GitHub Actions other than the one hygiene workflow.

## Inputs (Already Produced)

- `scripts/dryrun_team_distinction.py` — dry-run for Workstream A; output at `logs/distinction_bucket4_likely_merges.csv`
- `scripts/dryrun_investigate_c_and_d.py` — dry-run for Workstreams B & C; outputs at `logs/age_misclass_candidates.csv`, `logs/missing_league_candidates.csv`
