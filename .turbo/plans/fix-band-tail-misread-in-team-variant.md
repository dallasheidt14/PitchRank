---
status: done
---

# Plan: Read a birth-year band as one age token in every team-variant reader

## Outcome (2026-10-16)

Shipped on branch `fix/band-variant-reader`, with these departures from the steps below:

- **Club extractors.** The three club extractors and `extract_program_tier` widen as well (owner, 2026-10-15: "Fix it now"). Step 2's "out of scope" line no longer holds.
- **U-age pattern.** The span helper is built on `_BAND_RUN_RE` and a new `_UAGE_RUN`, not `_UAGE_TOKEN`. `_UAGE_RUN` also reads "Under 13B" and "13/14U".
- **u19 rule.** It reads `_stated_years`: `birth_years` plus the consecutive years of a band glued to a letter ("M08/09"), with U-ages stripped first. Its season defaults to `CURRENT_YEAR`.
- **u19 routing, beyond step 4.** The queue matcher (`find_best_match` and `resolve_via_stored_candidates`) and the event-team matcher also route the u19 pairing. The event-team matcher reviews it only when the pair would otherwise have linked.
- **Review confidence.** The base review insert caps confidence at 0.89, and the Athletes2Events and Soccer Events Group clamps are gone. This is IMP-230's clamp half.
- **`birth_years`.** It now reads en-dash bands and consecutive mixed-width bands such as "09/2008" (owner, 2026-10-16: "Fix it now"). Over the 212,732 unique live names, only 3 change.
- **Queue matcher.** It compares squad labels after removing the candidate's club from the queue name.
- **Copy guard.** It finds readers by their age-pattern loop.

**Corrections to the plan's claims:**
- "decide_team_merges already sends band-vs-single to REVIEW" no longer holds for en-dash, mixed-width and four-digit-pair bands. IMP-372 must be fixed before duplicate scans resume.
- The change settles the band half of IMP-231's variant misread. The hyphenated-tier misread remains.
- The "keep in sync" comments were left alone.

**Measured over unique live names:**
- Each variant-reader copy reads a `/NN` label for 17,822–18,571 names before and 69–72 after.
- The club extractors change 4,669 names, and clubs ending in "/" fall from 4,560 to 74.

**Follow-ups:** IMP-365 to IMP-372.

## Context

Three hand-copied `extract_team_variant` functions find a team name's age token and read the
next word as the squad label (coach, colour, tier). None of them knows a two-year band, so the
age token stops at `B2012` and the label becomes the band's tail: `NTH NASA ECNL RL B2012/13`
reads `/13`, and `Club 2013/2014 Riedell` reads `/2014` instead of `riedell`. Measured on
2026-10-14 against every live team name (origin/main b94a37cb5): 19,697 names get a `/NN`
label, and 7,002 of them hide a real squad word behind it.

The misread fails both ways. A band name never matches its single-year spelling (`ECNL RL 2013`
against `NTH NASA ECNL RL B2012/13`, a real duplicate merged by hand 2026-10-13). And two
coaches' squads in one band read the same label (`B2016/17 Rodriguez` and `B2016/17 Gonzalez`
both read `/17`), so the variant gate treats them as one squad. The copy in
`src/models/game_matcher.py` hard-gates the Oregon, Utah and Washington importers every Monday.
The copy in `scripts/find_queue_matches.py` feeds the duplicate scan and Tuesday's
unknown-opponent auto-match. The copy in `src/utils/team_name_utils.py` scores TGS and
SincSports candidates and feeds `extract_distinctions`.

Fixing the read exposes one ambiguity the misread was hiding. The u19 board holds two squads per
club, 2009/08 and 2008/07, so a name stating only `2008` fits both. Owner decision 2026-10-14:
such a pairing goes to review, never auto-link or auto-merge ("Send it to review").

Closes IMP-344. Settles the variant half of IMP-231; its tie-break and dry-run-registry halves
stay open.

## Pattern Survey

### Analogous Features
- `src/utils/team_utils.py:82` `_BAND_RUN_RE` matches a whole band run in one piece: `B2012/13`,
  `2013/2014`, `B13/14/15`, `2015/16B`, `13/14G`, `'15/16`, `B2007/08/09`, `2013 - 2014`,
  `B07/B08`, en-dash and curly apostrophes. It refuses U-led ranges by lookbehind. It backs
  `extract_band_birth_year` (`:94`), which CLAUDE.md names as the canonical band reader.
- `src/utils/team_name_utils.py:451` `_UAGE_TOKEN` consumes U-led ranges whole (`U11/12G`,
  `U14/15`, `GU18/19`); for `13/14U` it takes only `14U`.
- `scripts/normalize_team_names.py:215` `_resolve_band`, `src/tournaments/cohort_labels.py:36`
  `AGE_RUN`, `scripts/find_squad_key_duplicates.py:187` `read_name`: other band readers. None
  returns the span the variant readers need, and the first two cover fewer forms or sit in the
  wrong package.
- The three copies: `scripts/find_queue_matches.py:267` (takes `club_name`, local age list
  `:545-551`, `age_match` at `:553-578` with a two-word before-age window),
  `src/models/game_matcher.py:279` (`_AGE_PATTERNS:270`, `age_end_pos` at `:327`, ALL-CAPS and
  last-word fallbacks), `src/utils/team_name_utils.py:705` (`_VARIANT_AGE_PATTERNS:415`,
  `age_end_pos` at `:752`, maps `nth` to `north`). All take the first pattern in list order,
  then pass `/13` through the digit filter (`find_queue_matches.py:537`, `game_matcher.py:350`,
  `team_name_utils.py:775`) because it starts with `/`.
- `src/utils/team_name_utils.py:1124-1129` `resolve_distinction` already drops a non-alpha coach
  with the comment `"/07" from masked age spans` -- the one existing workaround.

### Reusable Utilities
- `team_utils._BAND_RUN_RE`, `team_name_utils._UAGE_TOKEN` (already imported cross-module by
  `decide_team_merges.py:54` and `find_squad_key_duplicates.py:100`).
- `team_name_utils.birth_years` (`:499`) returns `{2008}` for a bare 2008 and both years for a
  band; `birth_years_conflict` (`:551`) is the subset guard.
- `src/models/game_matcher.py:890-933`, the choke point in `GameHistoryMatcher._match_team`:
  `year_conflict = birth_years_conflict(...)` demotes a fuzzy match to the review queue. Every
  provider subclass reaches it through `super()._match_team()`, and
  `tests/unit/test_birth_year_guard_wiring.py:43-44` pins the `and not year_conflict` /
  `or year_conflict` wiring.

### Convention Anchors
- Consolidation precedent: `src/utils/age_group.py` (one dependency-free module replacing drifted
  copies) and `src/utils/placeholder_clubs.py` with `tests/unit/test_placeholder_clubs.py:125-205`
  (AST-derived copy guard, planted-file self-test, stale-entry test).
- `birth_years_conflict`'s bare-vs-band `False` is pinned on purpose
  (`tests/unit/test_birth_years_guard.py` ~`:151`, `:196-206`: equality refuses 55 of 2,929 kept
  human merges, subset 6). The u19 rule must not go inside it.
- `scripts/decide_team_merges.py:336-339` already sends band-vs-single to REVIEW, so the
  duplicate scan's decision layer needs no new rule.
- Tests: one flat file per module under `tests/unit/`, `@pytest.mark.parametrize` with a comment
  per row, season pinned by monkeypatching `team_utils.CURRENT_YEAR` to 2026
  (`tests/unit/test_extract_band_birth_year.py`), pairs asserted in both directions.

### Proposed Alignment
Share only the age-token span: one helper in `src/utils/team_name_utils.py`, built on the two
existing regexes. Each copy keeps its own skip sets, fallbacks and selection order, so a name
without a band reads exactly as today. Guard parity with an AST-derived test. Put the u19 rule
beside `birth_years_conflict` at the existing review choke points, not inside it.

## Implementation Steps

0. **Branch setup.** `C:\PitchRank` sits on an unrelated branch with unrelated modified files,
   so work in a worktree off `origin/main` (CLAUDE.md worktree exception):
   `git fetch --all --prune`, then
   `git worktree add C:\PitchRank\.turbo\worktrees\band-variant-reader -b fix/band-variant-reader origin/main`.
   Before the first edit, `git -C <worktree> status --short` must be empty. Copy this plan into
   the worktree's `.turbo/plans/`. The worktree has no `.env`; load `C:\PitchRank\.env`
   explicitly for any database read. Re-check that none of the files below changed on
   `origin/main` since b87a01a71 (`git log b87a01a71..origin/main -- <files>`); re-measure if
   they did.

1. **Add the shared span helper** in `src/utils/team_name_utils.py`, next to `_UAGE_TOKEN`:
   - `age_token_span(name: str, start: int, end: int) -> tuple[int, int]`. Given the span a
     caller's age pattern matched, return the span of the band run (`team_utils._BAND_RUN_RE`)
     or U-age token (`_UAGE_TOKEN`) that overlaps it, widened to cover both; otherwise return
     `(start, end)` unchanged. Import `_BAND_RUN_RE` from `src.utils.team_utils` (the module
     already imports from there).
   - Respect `team_utils._BAND_SCAN_LIMIT` (200 chars): longer names return the span unchanged.
   - Docstring: why it widens rather than re-picks (each copy's pattern-order selection stays
     as is, so only band and range names change), with `B2012/13`, `2013/2014 Riedell`,
     `B13/14/15` and `U11/12G` as examples.

2. **Call it from all three readers**, right after each picks its age match:
   - `scripts/find_queue_matches.py` `extract_team_variant`: after `age_match` is set
     (`:553-558`), compute the widened span once and use its end for `after_age` (`:562`) and
     its start for `before_age` (`:569`).
   - `src/models/game_matcher.py` `extract_team_variant`: widen `age_end_pos` (`:327`). The
     module imports `team_name_utils` inside a try/except (`:41-55`); import `age_token_span`
     there, and keep the fallback branch working when the import fails (no widening).
   - `src/utils/team_name_utils.py` `extract_team_variant`: widen `age_end_pos` (`:752`).
   - Update the three "keep in sync" comments (`find_queue_matches.py:256-263`, which also
     wrongly cites `_tokenize` in `find_fuzzy_duplicate_teams.py`; `game_matcher.py:294-300`;
     `team_name_utils.py:720-727`) to say the age span is shared and the parity test enforces it.
   - Out of scope, left as is: `find_queue_matches.extract_club_from_name` (`:170`) and
     `extract_program_tier` (`:798`), which use the same age list with different selection rules;
     and `team_name_utils` mapping `nth` to `north`.

3. **Add the u19 shared-year check** in `src/utils/team_name_utils.py`, beside
   `birth_years_conflict` (not inside it):
   - `u19_shared_year_ambiguous(name_a, name_b, age_group, season=None) -> bool`. True only when
     `age_group` normalizes to `u19`, one name's `birth_years` is exactly `{S}` where
     `S = season - 18` (2008 in 2026-27, the year both u19 bands contain), and the other name's
     `birth_years` has two or more years including `S`. Season defaults to
     `team_utils._soccer_season_year()`.
   - Two bare 2008s, two bands, a bare 2009 against 2009/08, and any non-u19 board return False.

4. **Route that pairing to review in the importers.** In `GameHistoryMatcher._match_team`
   (`src/models/game_matcher.py:890`), extend the existing flag:
   `year_conflict = birth_years_conflict(...) or u19_shared_year_ambiguous(team_name, fuzzy_match.get("team_name"), age_group)`.
   - Keep the variable name and the `and not year_conflict` / `or year_conflict` lines, which
     `test_birth_year_guard_wiring.py:43-44` pins. Log the u19 reason separately from the
     birth-year one.
   - This covers every subclass that reaches the base `_match_team`. Before relying on that,
     confirm each subclass with its own `_match_team` (`affinity_or:456`, `affinity_wa:265`,
     `tgs:517`, `sincsports:554`, `playmetrics:441`, `yssl:118`, `athletes2events:283`,
     `soccereventsgroup:217`) reaches the base choke point for fuzzy matches. Any that decides
     auto-approve itself gets the same `or` at its own site.

5. **Route it to review in the unknown-opponent auto-match.**
   `scripts/auto_match_unknown_opponents.py:303-316`: when the best candidate's stored age group
   is u19 and `u19_shared_year_ambiguous(profile name, candidate name, "u19")`, classify an
   `auto_link` as `review`. Leave `score_team_pair` alone: the duplicate scan already routes
   band-vs-single to REVIEW at `decide_team_merges.py:336-339`.

6. **Tests** (new `tests/unit/test_age_token_span.py`, plus additions to existing files):
   - `age_token_span` across every form in the measurement: `B2012/13`, `G2014/15`,
     `2013/2014`, `B13/14`, `B13/14/15`, `2015/16B`, `13/14G`, `U11/12G`, `U14/15`, `'15/16`,
     `B2007/08/09`, `2009/08`, plus non-band names whose span must come back unchanged.
   - Parity: the three `extract_team_variant` copies, imported packaged
     (`from scripts import find_queue_matches`), each read `NTH NASA ECNL RL B2012/13`,
     `Club 2013/2014 Riedell`, `FC Dallas Youth Pre-ECNL B2016/17 Rodriguez` and
     `Club G2014/15 Premier` with no `/`-led label, and name the literal expected value for each.
   - AST-derived copy guard (`test_placeholder_clubs.py:125-205` pattern): glob `src/` and
     `scripts/` for every function named `extract_team_variant`, assert each calls
     `age_token_span`, plus a planted-file self-test showing the detector fires.
   - `u19_shared_year_ambiguous`: rows `(a, b, age_group, expected)` asserted both directions,
     including `("X 2008", "X B08/07", "u19", True)`, `("X 2008", "X 2009/08", "u19", True)`,
     `("X 2009", "X 2009/08", "u19", False)`, `("X 2008", "X 2008", "u19", False)`,
     `("X 2014", "X 2013/14", "u13", False)`. Season pinned to 2026.
   - Base matcher: extend `tests/unit/test_birth_year_guard_wiring.py` (or the closest existing
     `_match_team` test) so a 0.95-confidence fuzzy match between `2008` and `B08/07` on u19
     lands in the review queue and writes no alias. Record at the terminal call, per CLAUDE.md.
   - Auto-match: a u19 ambiguous best candidate above `auto_threshold` is classified `review`.
   - Leave `test_birth_years_guard.py`'s pinned bare-vs-band `False` untouched.

7. **Docs and backlog.**
   - `.claude/skills/scraper-patterns/SKILL.md`, Provider Matcher Name Parsing: the bullet
     saying `extract_team_variant` reads "the `/13` of `G2012/13`" as a coach becomes stale.
     Re-test the `ECNL-RL` half of that claim after the change and keep only what still holds.
   - `.turbo/improvements.md`: close IMP-344 (Status done, Refs this PR) and move it to
     `.turbo/improvements-archive.md` by hand. Add a dated `Update` line to IMP-231 for the
     variant half. Note `team_name_utils` reading `NTH` as the direction North as a new entry.

## Verification

- **Reader diff over every live name.** Replay all ~229K live `team_name` values through each
  copy before and after (old copy imported from `git show origin/main:<path>` under its own
  module name). Every name whose reading changes must contain a band run or U-age range; any
  other change is a regression. Report counts per copy: `/`-led labels before (expect ~19.7K for
  the import copy) and after (expect 0), and how many now read a real word (expect ~7K).
- **Duplicate scan.** Re-run the 2026-10-14 measurement (`measure_a.py` in
  `C:\Users\Dallas Heidt\pitchrank-merge-runs\season-reregistration-2026-10-14`) against the
  real change instead of the regex stand-in. Expect about 455 pairs newly over 0.90 (about 399
  u19) and about 5 removed. Confirm every u19 band-vs-bare addition lands as REVIEW, not MERGE,
  through `decide_team_merges.decide`. Read the removed pairs by name.
- **Importer replay, flips both ways.** Download the latest Monday artifacts for `or-scraper`,
  `ut-scraper`, `wa-scraper` and `tgs-event-scrape-import`. Run each provider's matcher with
  `dry_run=True` (the scraper-patterns replay recipe) on the old and new code, and diff the
  per-team outcome (linked to X / review / create). Read every flip by name, especially the
  coach-squad bands that used to link and should now split.
- **Unknown-opponent replay.** Replay the latest `unknown-opponent-hygiene-weekly` export
  through `auto_match_unknown_opponents.py` without `--execute`, old and new, and diff the
  auto/review/no_match buckets.
- **Mutation checks**, each run separately on a scratch copy, collecting failing test names and
  confirming the new test is among them: drop the band-run widening; drop the U-range widening;
  remove the call from one copy only; make `u19_shared_year_ambiguous` ignore `age_group`; make
  it accept a bare 2009; drop the `or` at the base choke point.
- CI gate: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` and
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.

## Context Files

- `src/utils/team_utils.py` (`_BAND_RUN_RE`, `extract_band_birth_year`) -- the band grammar reused.
- `src/utils/team_name_utils.py` (`_UAGE_TOKEN`, `birth_years`, `birth_years_conflict`,
  `extract_team_variant`, `resolve_distinction`) -- where the helpers land.
- `scripts/find_queue_matches.py` `extract_team_variant` -- the copy with the before-age window.
- `src/models/game_matcher.py` (`extract_team_variant`, `_match_team` choke point `:870-933`).
- `scripts/auto_match_unknown_opponents.py` (classification `:296-320`).
- `scripts/decide_team_merges.py` (`decide`, `:326-342`) -- why the duplicate scan needs no rule.
- `tests/unit/test_birth_years_guard.py`, `tests/unit/test_birth_year_guard_wiring.py`,
  `tests/unit/test_placeholder_clubs.py`, `tests/unit/test_extract_band_birth_year.py`.
- `.claude/skills/merging-duplicate-teams/references/failure-modes.md` -- the u19 two-squad hazard.
