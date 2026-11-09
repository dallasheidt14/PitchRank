---
status: done
---

# Plan: Stop linking a team record to a row of the opposite gender

## Context

On 2026-11-09, 27 live team rows were found to each hold a boys squad and a girls squad: a second
provider record (almost always GotSport) had been attached to a row of the other gender, so the row
carried both squads' games. When the rename step picked the wrong record to name the row, it also got
the other squad's name. All 27 were split by hand. This plan stops new ones forming.

Each attached record carries the time its link was written. Of the 34 records involved:

- **24 were linked on a Tuesday evening (UTC) by the weekly unknown-opponent job**
  (`unknown-opponent-hygiene-weekly.yml`, cron Tuesday 18:00 UTC). Each record's first games had
  arrived days earlier as an unmatched opponent on another team's schedule.
- 6 were linked by the initial bulk load on 2025-11-04.
- 4 were linked by one-off runs in March 2026.

The weekly job's gate, `scripts/due_diligence_unknown_opponents.py`, has a gender check. Before
2026-08-30 its GotSport lookup read a `gender` key the endpoint does not return, so the check always
came back "unknown" and passed; #1060 changed it to read `display_gender`. Two links made after that fix
still went wrong, because the target row's *stored* gender was itself wrong:

- LFA's boys row (named `LFA 17/18B …`) was stored as girls.
- `2019 Chicago Rush South Boys Premier` was stored as girls.

The row's own name would have caught both. Separately, `scripts/reconcile_teams_with_gotsport.py`
copies the chosen GotSport record's name onto the row, and nothing compares that record's gender with
the row's.

The intended outcome: every path that attaches a record to an existing row, or renames a row from one,
refuses or holds a record whose gender contradicts the row's. The row's gender is read from its own
name as well as its stored column.

### Owner decisions (2026-11-09)

- **Cover three paths:** the weekly unknown-opponent gate, the GotSport rename step, and the game
  matcher's automatic name match.
- **In the weekly job, hold a record whose gender cannot be read.** That is the case where GotSport
  gives no answer and the record's name states no gender. Holding it means the job does not auto-link
  it this week. Its game sides stay NULL, so `scripts/export_unknown_opponents.py` (which selects games
  with a NULL master id, `:178`) proposes it again the next Tuesday.
- **Carry the export's GotSport gender through to the gate (re-asked and decided the same day).**
  Replaying the 2026-11-03 weekly run's artifacts showed how often the hold would fire.
  - The gate's own GotSport lookups answered 0 of its 88 auto-link candidates inside the job, so the
    hold above would have held 15 of the 66 approvals every week, indefinitely.
  - The export step, which runs first in the same job, had GotSport's `display_gender` for all 106
    candidate rows, in the aggregate CSV's `unknown_gender` column (`export_unknown_opponents.py:154`,
    `:395`).
  - With that gender as a record reading, all 88 pass: 66 approved, 0 held, 0 mismatched.
  - The owner chose to carry the export's gender to the gate, so the hold stays rare.

### Out of scope, deliberately

- **Automatic merges.** `FUZZY_AUTO_MERGE_ENABLED` is `'false'` (`data-hygiene-weekly.yml`).
  `cleany-auto` has no writer on main. Operator merges through `apply_vetted_team_merges.py` already
  re-check gender against the vetted list.
- **`scripts/maintain_gotsport_direct_id_aliases.py`.** It relabels approved aliases as `direct_id` but
  never changes which row a record points at.
- **Modular11's own accept path** (`src/models/modular11_matcher.py`).
  - Its `_match_team` replaces the base one without calling `super()`, so the base accept-point guard
    never runs for it.
  - It accepts a match through `fuzzy_match_modular11_team` (`:741`), whose acceptance at `:970` checks
    birth years and confidence but not gender, and writes `fuzzy_auto` at `:550-560`.
  - The owner has ruled Modular11 code out of scope, so it stays unguarded.
- **The other auto-creating matchers' reuse of a row by provider id.** SincSports, PlayMetrics,
  Affinity OR, Affinity WA, Athletes2Events, YSSL, Tourney Central and Soccer Events Group create a
  team on an unmatched result, as TGS does, and look a row up by `teams.provider_team_id` first.
  - Measured 2026-11-09: none of those eight providers has a live row whose own id lacks an approved
    alias, so their reuse path has nothing to reach. TGS has 619, of which 2 are named for the other
    gender.
  - Only TGS is guarded (step 4).
- **The event-roster alias writer** (`src/tournaments/alias_writer.py` via
  `src/tournaments/event_team_matcher.py`). Event scrapes are manual-dispatch only.
- **Folding the four existing name-gender readers onto the new one.** Those are `spelled_gender` and
  `any_gender` in `scripts/fix_gender_from_registered_name.py`, `stated_gender` in
  `scripts/find_cross_provider_duplicates.py`, and `spelled_gender` in `scripts/decide_team_merges.py`. Doing
  so would change merge-screen behaviour on names like `Premier 1B`. It is a follow-up, tracked in the
  backlog entry "Read a team's gender with one grammar instead of seven", which also names
  `gender_from_name`, `read_label` and the value normalizers.
- **`fetch_gotsport_aliases`' highest-id selection rule.** The rename-step veto removes the harm it
  caused.

### Branch and local-state hazard

`C:\PitchRank` sits on a detached HEAD roughly 190 commits behind `origin/main`, with unrelated
modified and staged files. Do not edit there.

- Work in the worktree `C:\pitchrank-gender-link-guard` on branch
  `fix/stop-opposite-gender-record-links`, created from `origin/main` at 2b3183767.
- Before the first edit, run `git -C C:/pitchrank-gender-link-guard status --short`. It must show only
  this plan file.
- Before the first edit, run `git -C C:/pitchrank-gender-link-guard log -1 --format=%H origin/main..HEAD`.
  It must print nothing; anything else means the branch has picked up commits that are not on main.
- If `origin/main` has moved, merge it into the branch. Do not rebase: the guard blocks force-push.

## Pattern Survey

The full survey ran against `origin/main` 2b3183767; the load-bearing items were re-read for this plan.

### Analogous Features

- **The birth-year guard is the exact model.**
  - It sits at `GameHistoryMatcher._match_team`'s accept point (`src/models/game_matcher.py:889-966`),
    which every provider subclass reaches through `super()`. A conflict sets `year_conflict`, which
    demotes an otherwise auto-approved fuzzy match to the review queue rather than dropping it.
  - The same guard skips conflicting candidates in the base candidate loop (`:1401-1402`).
  - It is wiring-tested by source inspection over a hand-written subclass list
    (`tests/unit/test_birth_year_guard_wiring.py`).
- **The rename step's cohort veto is the model for a veto there.**
  - `decide` in `scripts/reconcile_teams_with_gotsport.py:365-426` withholds `team_name` when the
    record's cohort disagrees with the row's (`:395-404`).
  - It reads a provider field only to withhold a write, never to make one.
  - It never blocks a club or state fill. The tests to mirror are
    `tests/unit/test_reconcile_teams_with_gotsport.py:233` and `:340`.
- **The weekly gate already computes the right shape of check.**
  - `due_diligence_unknown_opponents.py:356-360` computes `gender_check` as "ok", "mismatch" or
    "unknown", and the `core_ok` rule at `:429-443` refuses only a "mismatch". This plan widens what
    counts as a reading and makes "unknown" hold.
  - `cohort_gender_check` (`:419-423`, opponents' stored gender) stays as it is.

### Reusable Utilities

- **The B/G patterns.** `WORD_B`, `WORD_G`, `AFFIX_B` and `AFFIX_G` in
  `scripts/fix_gender_from_registered_name.py:50-53` are the starting point.
  - Their affix rule also matches a lone single digit plus a letter (`1B`, `5G`, `B1`). The owner's
    rule treats those as squad codes, not genders.
  - That module calls `load_dotenv` and imports supabase at import time, so the new reader must not
    import from it.
- **`stated_gender` in `scripts/find_cross_provider_duplicates.py:186-205` has the right shape.** A
  word wins, a name stating both says neither, and otherwise the letter decides.
  - Measured on 43 of today's names on 2026-11-09, it read every real case correctly.
  - It failed only the traps: `Premier 1B` read as Male, `Strikers 5G` as Female, and
    `FC Dallas 2012 Girls 1B` as None.
- **`registered_name`** (`find_cross_provider_duplicates.py:177-183`) prefers `team_name_original`.
- **The weekly gate's GotSport reader returns the record's own gender.** `GotSportResolver.resolve`
  (`due_diligence_unknown_opponents.py:201-245`) gives `gender` from `display_gender` and `name` from
  the record.
- **The rename step's reader already carries the record's gender.** `provider_values`
  (`reconcile_teams_with_gotsport.py:333-345`) puts it in `provider["gender"]`.

### Convention Anchors

- **Match failure mode: demote to review, not drop.** See `game_matcher.py:907-966`.
- **A veto, never a value.** A provider field or a name only withholds a write. CLAUDE.md, "That
  asymmetry is what makes a provider cohort safely usable as a veto".
- **A spelled word wins over a letter.** The owner's rule, recorded 2026-11-08:
  - A spelled word decides: `Boys` or `Girls`.
  - Failing that, a B/G letter attached to an age or year decides: `B2014`, `U11G`, `17B`, `12/13G`,
    `BU07`, `11UG`.
  - A lone `1B` or `5G`, a name stating both, or a name stating neither gives no reading.
- **The game's own gender is not a team reading.** It comes from the event division, girls teams play
  in boys divisions, and GotSport team-schedule games carry none at all
  (`src/scrapers/gotsport.py:798-817`).
- **Opponents' stored gender is not independent evidence.** The same imports that mislabel a row set
  it too (CLAUDE.md, Age Groups).
- **The match report's `unknown_gender_used` can be such a guess.** `auto_match_unknown_opponents.py`
  falls back to `top_known_team_gender` (`:206-207`), the gender of the team the record played.
- **Light imports for anything a hygiene workflow loads.** The unknown-opponent workflow installs only
  supabase, python-dotenv and requests (`unknown-opponent-hygiene-weekly.yml:80`).
- **Test doubles record at `.execute()` and refuse what production refuses** (CLAUDE.md, Verification).
  `tests/unit/test_game_matcher_blank_provider_id.py:24-100` records at `execute()`, but it ignores
  insert and update payloads, so a test asserting "no alias written" must extend it to record writes.

### Proposed Alignment

- **One small stdlib reader in `src/utils/`, used by all three guards.** Each guard follows the pattern
  already beside it: the birth-year guard in the matcher, the cohort veto in the rename step, and the
  `core_ok` rule in the weekly gate.
- **Each guard reads the row's gender from its stored column and both of its names.** That is
  `team_name` and `team_name_original`. It reads the record's gender only from the record itself: the
  provider's own field and the record's name.

## Implementation Steps

1. **Add the shared reader, `src/utils/team_gender.py`** (stdlib `re` only, no other imports).
   - `name_gender(name) -> Optional[str]` returns `"Male"`, `"Female"` or `None` by the owner's rule:
     - A spelled `boy(s)` or `girl(s)` decides. A name spelling both returns `None`.
     - Otherwise a B/G letter counts only when attached to an age or year.
       - A leading letter counts before two or more digits or a U-age: `B2014`, `B13`, `G11`,
         `BU07`, `GU14`.
       - A trailing letter counts after two digits (`14B`, `17/18B`, `U11G`, `'16G`), after a U-age
         (`U9G`), or after an age-then-U (`11UG`).
       - A lone `1B`, `5G`, `B1` or `G1` gives no reading.
       - A name carrying both letters returns `None`.
   - `stored_gender(value) -> Optional[str]` maps `Male`/`Female` and the spellings CLAUDE.md's Gender
     Normalization lists (`B`, `Boy`, `Boys`, `M`; `G`, `Girl`, `Girls`, `F`) and returns `None` for
     anything else.
   - `row_genders(row)` returns a team row's three readings: `stored_gender` of its `gender`, and
     `name_gender` of its `team_name` and `team_name_original`. Every guard reads a row through it.
     - Do not use a normalizer that defaults to Male: the scraper-patterns skill notes `normalize_gender("")` returns
       `"Male"`, and `seeding_optimizer.normalize_gender_label` does the same.
   - `gender_verdict(record_readings, row_readings) -> str` returns one of three values.
     - `"unknown"` when no record reading is present.
     - `"mismatch"` when the present readings across both sides are not all equal. That covers a record
       contradicting the row, a record contradicting itself, and a row contradicting itself (a boys
       name on a row stored as girls).
     - `"ok"` otherwise.
     - `None` entries are ignored. A row with no reading at all does not block.
   - Docstrings name the owner's rule and say the reader only ever withholds a write.

2. **Gate the weekly unknown-opponent job.**
   - **In `scripts/auto_match_unknown_opponents.py`, carry the export's gender to the gate.**
     - Add a match-report column `unknown_provider_gender` to the row built in `report_rows.append`
       (`:522-545`).
     - Set it to the export row's own `unknown_gender` (`row.get("unknown_gender")`, where `row` is the
       export row of the loop at `:469`), written verbatim and never filled from the resolver or from
       `top_known_team_gender`.
     - That column is GotSport's `display_gender` for the record itself, written by
       `export_unknown_opponents.py:154` and carried at `:395`.
     - It is distinct from `unknown_gender_used` (see Context).
   - **In `scripts/due_diligence_unknown_opponents.py`:**
   - Add `team_name_original` to the matched-team select at `:316`.
   - Build the record readings, in this order:
     - the resolver's `gender` (GotSport `display_gender`);
     - `name_gender` of the resolver's `name`;
     - `stored_gender` of each grouped row's `unknown_provider_gender` (the export's GotSport gender);
     - `name_gender` of the match report's `unknown_team_name_used`.
     - **Do not read `unknown_gender_used`.** It can be the opponent's stored gender.
     - A match report written before the new column exists reads it as absent, which is no reading.
   - **A Coed answer is not held.**
     - GotSport files some young teams as `Coed`: 12 of the 377 export records in the 2026-11-09 replay.
     - When nothing else reads and the export says `Coed`, `gender_check` is `"coed"`, and `core_ok`
       accepts it beside `"ok"`.
     - A Coed record whose name contradicts the row still comes back `"mismatch"`.
     - Added during implementation: otherwise those records would be held every week, and GotSport
       did answer for them.
   - Build the row readings with `row_genders(team)`.
   - Replace the `gender_check` computation at `:356-360` with `gender_verdict(...)`.
   - In `core_ok` at `:429-441`, require `gender_check` to be `"ok"` or `"coed"`, so that both
     "mismatch" and "unknown" give `needs_review`. Comment it with the owner decision, 2026-11-09.
   - Add `record_gender_readings` and `row_gender_readings` columns to `verdict_row` (`:445-475`), so a
     held row shows why.
   - Leave `cohort_gender_check`, the alias-conflict guard and the other checks unchanged.
   - `scripts/apply_unknown_opponent_matches.py` needs no change: it applies only the approved CSV.

3. **Veto the rename, `scripts/reconcile_teams_with_gotsport.py`.**
   - Add `team_name_original` to `fetch_target_teams`' select at `:278`.
   - In `decide` (`:365-426`), before `provider["team_name"]` can replace the stored name, compute
     `gender_verdict` with:
     - record readings: `stored_gender(provider["gender"])` and `name_gender(provider["team_name"])`;
     - row readings: `row_genders(team)`.
   - On `"mismatch"`, append `"team_name"` to `blocked`, as the cohort veto does.
   - `"unknown"` does not veto. This step renames a row and attaches nothing, so a record with no
     gender reading cannot change the row's stated gender.
   - The veto must never block a club or state fill.
   - Comment it with the 2026-11-09 cause: a boys row took a girls record's name.

4. **Guard the matcher's automatic name match, `src/models/game_matcher.py`.**
   - **At the accept point in `_match_team` (`:889-966`).** Once a fuzzy match exists and the
     birth-year checks have run:
     - Read the matched row's `team_name`, `team_name_original` and `gender` with one `teams` select
       by `team_id_master`. The fuzzy result carries only `team_id`, `team_name` and `confidence`
       (`:1465-1469`), and subclasses override `_fuzzy_match_team`. So this lookup covers every
       matcher that reaches the base accept point through `super()._match_team`: all of them except
       Modular11, which is out of scope (see above).
     - Record readings: `name_gender(team_name)` only. The game's `gender` argument is the division's,
       not the team's.
     - On `"mismatch"`, demote exactly as `year_conflict` does: no alias, and a review-queue entry.
       Name the flag `gender_conflict` and fold it into the existing `and not year_conflict`
       condition. Read the row only when the match would otherwise auto-approve (confidence at or
       above `auto_approve_threshold` and no `year_conflict`); every matcher's
       `auto_approve_threshold` is at or above its `review_threshold`, so the existing review branch
       then takes the demoted match without an `or gender_conflict` clause.
     - If the lookup raises or returns no row, demote too. `"unknown"` proceeds as today, because the
       candidates were already filtered by the game's gender and fuzzy matching runs only when one is
       set (`:889`).
   - **At the top of the base candidate loop of `_fuzzy_match_team`, ahead of Gate 1.**
     Skip a candidate whose `team_name` states the opposite gender to the record's name, so a B/G twin
     cannot win the search over the right row.
   - The lookup is a read, so it runs in dry runs too.
   - **Keep TGS's create-on-unmatched fallback from undoing the hold, `src/models/tgs_matcher.py`.**
     - `TGSGameMatcher._match_team` (`:517`) creates a team whenever the base result is unmatched,
       including a gender hold.
     - `_create_new_tgs_team` (`:591`) returns an existing row found by `(provider_id,
       provider_team_id)` from two places: the pre-check (`:634`) and the lookup after a duplicate-key
       error (`:722`).
     - That existing row is the record's own, so when its stored gender or names contradict the
       incoming team name, it is the very row the guard just held, and the fallback would link it with
       an approved `direct_id` alias.
     - At both places, capture the found id inside the existing `try` and check it after the `try`
       closes. Both `try` blocks swallow every exception (`:635`, and the `lookup_error` handler after
       `:722`), so a raise inside them would be silently caught.
     - The check is `_reusable(team_name, found_id)`, which calls `self._genders_conflict` and raises
       `ReuseRefused` on a conflict. `_create_new_tgs_team` re-raises it past its duplicate-key
       handler, and `_match_team` catches it in its own `except ReuseRefused`, logged at info, then
       returns the base result: unmatched, with the base's review-queue entry kept.
     - A row stored as one gender and named for the other conflicts too, by `gender_verdict`'s rule.
       Two TGS rows matched that shape on 2026-11-09; their new games will wait in review until their
       label is fixed.

5. **Tests.**
   - **`tests/unit/test_team_gender.py` (new).** Use a literal table of names and expected readings.
     - Every real name from the 2026-11-09 split.
     - The traps: `Premier 1B`, `Strikers 5G`, `FC Dallas 2012 Girls 1B` (Female, because the word
       wins), `2009B Girls` (Female), and a name stating both words.
     - Names that state nothing: `U13 (13/14) Chicago Rush DPL`, `2016 Blue II`.
     - `gender_verdict` cases:
       - a record contradicting the row;
       - a record contradicting itself (GotSport `display_gender` Male, name `12/13G`, the Hawaii RUSH
         Azul case);
       - a row contradicting itself (the LFA case);
       - no record reading;
       - all readings agreeing.
   - **Weekly gate.** Drive `due_diligence_unknown_opponents.main()` end to end, with a Supabase double
     that records at `.execute()` and a stubbed `GotSportResolver`, over a small match-report CSV. Bind
     it at this altitude because the defect hides in the fetch (`team_name_original` missing from the
     select). Assert on the approved and needs-review CSVs:
     - a girls record onto a boys-named row stored as girls is held;
     - a record GotSport did not answer for, with a silent name, is held, with its report rows carrying
       `unknown_gender_used` equal to the row's gender, the way the matcher's `top_known_team_gender`
       fallback fills it in production, so that reading that column makes this test fail;
     - a record GotSport did not answer for, with a silent name but an export gender that agrees with
       the row, is approved;
     - a record whose export gender contradicts the row is held;
     - a same-gender record is approved (the control).
   - **Match step.** Add `tests/unit/test_auto_match_provider_gender.py`.
     - It imports the script packaged (`from scripts import auto_match_unknown_opponents`); the
       existing `tests/unit/test_unknown_opponent_resolvers.py` imports it bare, which CLAUDE.md
       forbids.
     - It drives `main()` without `--execute` over a two-row aggregate CSV, with `sys.argv`,
       `load_env` and `get_supabase` patched.
       - Row one: `unknown_gender` = `Female`.
       - Row two: `unknown_gender` empty and `top_known_team_gender` = `Male`.
     - Its Supabase double records at `execute()`, returns only selected columns, and raises on
       anything it does not model. It models the `providers` select and the `teams` candidate query
       (`ilike`, `or_`, `eq`, `limit`); an empty `teams` table is enough, since a report row is written
       for every action.
     - It asserts on the written report: `unknown_provider_gender` is `Female` on row one and empty on
       row two, while row two's `unknown_gender_used` is `Male`.
   - **TGS fallback.** Add a test to `tests/unit/test_game_matcher_gender_guard.py`, using that file's
     double, whose `.single()` already raises unless exactly one row matches, as PostgREST does.
     - It drives `TGSGameMatcher._match_team` with a girls team name against a TGS-owned row carrying
       the same provider team id, no approved alias, a boys name and a stored girls gender.
     - It asserts that no `team_alias_map` write executes and that the result is unmatched.
   - **Rename step.** In `tests/unit/test_reconcile_teams_with_gotsport.py`, mirror `:233` and `:340`:
     - a girls registration's name is withheld from a boys row;
     - a gender disagreement never blocks a club or state fill;
     - an agreeing registration's name is taken.
   - **Matcher.**
     - Extend `tests/unit/test_birth_year_guard_wiring.py` with source-inspection assertions that
       `_match_team` consults the gender guard and demotes on it, and that the base candidate loop
       calls it.
     - Add a semantic test in `tests/unit/test_game_matcher_gender_guard.py` with its own double,
       which records every call with its payload at `execute()` and raises on a `.single()` that
       does not find exactly one row. Match a record named
       `LFA 17/18G Red Star Swift (2036)` against a single candidate named
       `LFA 17/18B Red Star Swift (2036)`, and assert that no `team_alias_map` write executed and that
       one review-queue entry did.

## Verification

- **Each new test must be the one a mutation kills.** Collect the failing test names after each
  mutation and confirm a new test is among them, not only pre-existing ones (CLAUDE.md, "A mutation has
  to kill *your* test").
  - Revert each guard one line at a time: the `core_ok` condition, the select column, the `decide` veto,
    the accept-point flag, and the candidate-loop skip.
  - Fill `unknown_provider_gender` from `profile.gender` instead of the export row. The match-step test
    must die.
  - Drop the gate's `unknown_provider_gender` reading. The "export gender agrees → approved" test must
    die.
  - Add an `unknown_gender_used` reading to the gate. The silent-name held test must die.
  - Remove the TGS reuse check at each of its two places, separately. The TGS fallback test must die
    for the pre-check. A duplicate-key fixture is needed for the second place; if none is written,
    record that mutation as unkilled.
- **Replay against the real cases.** For each of the 34 second records split on 2026-11-09, run
  `gender_verdict` with the record's GotSport name and `display_gender` (in the session's
  `split_check_13.json` and `split_check_18.json`) against the row as it stood before the split (the
  gitignored logs `data/backups/fused_fix_2026-11-09*/prior_*.json`). Expect every one to come back
  `"mismatch"` or `"unknown"`, and read any that come back `"ok"`.
- **Negative control on live data, through the new plumbing.** Download the artifacts from the latest
  `unknown-opponent-hygiene-weekly` run with `gh run download`. Then:
  - Re-run the new `auto_match_unknown_opponents.py` on that run's aggregate CSV, without `--execute`,
    so it writes only a fresh match report.
  - Run the new `due_diligence_unknown_opponents.py` on that report, with `GotSportResolver.resolve`
    stubbed to return `{}`, since the job's own lookups answered nothing in CI.
  - Writes nothing; the database reads are selects.
  - Today's candidate pool differs from the run's, because the run linked some of them, so compare the
    new verdicts with an old-gate run over the same fresh report rather than with the artifact's
    verdicts.
  - Baseline, the 2026-11-03 run: 66 approved stay approved, 0 held, 0 mismatched with the export
    gender; 15 held without it.
  - Report how many previously approved rows the new check holds, and read every held row: each should
    be a real contradiction or a record nothing could read.
  - A large hold count means the reader is too eager, or the export's gender stopped arriving.
- **The CI gate's two Python checks pass:**
  `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` and
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.

## Context Files

- `src/models/game_matcher.py` — `_match_team` (`:828-1009`) and its accept point and birth-year guard
  (`:889-966`); `_fuzzy_match_team` (`:1268-1476`) and its candidate loop.
- `scripts/due_diligence_unknown_opponents.py` — the weekly gate: `GotSportResolver` (`:201-245`),
  the team select (`:316`), the checks and `core_ok` (`:340-443`), and `verdict_row` (`:445-475`).
- `scripts/reconcile_teams_with_gotsport.py` — `fetch_target_teams` (`:278`), `provider_values` and
  `decide` (`:333-426`).
- `scripts/find_cross_provider_duplicates.py:177-205` — `registered_name` and `stated_gender`, the
  shape the new reader refines.
- `scripts/fix_gender_from_registered_name.py:50-86` — the B/G patterns and their lone-digit trap.
- `tests/unit/test_birth_year_guard_wiring.py` — the wiring-test pattern for a guard at the accept point.
- `tests/unit/test_reconcile_teams_with_gotsport.py:233-345` — the cohort-veto tests to mirror.
- `.github/workflows/unknown-opponent-hygiene-weekly.yml:120-190` — how the match, gate and apply
  steps chain.
- `scripts/auto_match_unknown_opponents.py` — `build_unknown_profile` (`:165-218`), the export-row loop
  (`:469`) and the report row (`:522-545`).
- `scripts/export_unknown_opponents.py:113-160, 380-400` — where the record's own GotSport gender
  enters the export.
- `src/models/tgs_matcher.py:517-590, 591-727` — the create-on-unmatched fallback and the two places
  `_create_new_tgs_team` returns an existing row.

## As built (2026-11-09)

### What shipped

All four implementation steps, the export-gender column and the Coed rule.

- New code: `src/utils/team_gender.py`.
- Changed scripts: `scripts/due_diligence_unknown_opponents.py`, `scripts/auto_match_unknown_opponents.py`,
  `scripts/reconcile_teams_with_gotsport.py`.
- Changed matchers: `src/models/game_matcher.py`, `src/models/tgs_matcher.py`.
- Changed UI: `dashboard.py`, Due Diligence Review (added in review round 1).
- Changed skill doc: `.claude/skills/reconcile-gotsport/SKILL.md`, which lists the rename vetoes.
- New tests: `tests/unit/test_team_gender.py`, `tests/unit/test_due_diligence_gender_gate.py`,
  `tests/unit/test_auto_match_provider_gender.py`, `tests/unit/test_game_matcher_gender_guard.py`.
- Extended tests: `tests/unit/test_birth_year_guard_wiring.py`,
  `tests/unit/test_reconcile_teams_with_gotsport.py`.

### Changes to existing tests

- `test_a_reported_field_stays_out_of_an_update_that_happens_anyway` pinned "gender never vetoes a
  rename". It now pins only that age and gender are never written.
- The collision tests' `_rename` helper takes a gender, because their fixtures renamed girls teams
  (`U13G DPL`, `ECNL RL G2013/14`) on rows defaulted to boys. `_to_u13g_dpl` builds the replayed
  `U13G DPL` rows. `test_a_collision_never_withholds_a_club_or_state_fill` renames girls rows and
  asserts both renames are dropped, since with boys rows the gender veto withheld them first and the
  test exercised no collision.

### Review round 1 (2026-11-09)

- The new tests `test_gotsport_s_gender_alone_withholds_a_name_that_states_none` and
  `test_the_gender_veto_never_blocks_a_club_or_state_fill` use a row name with no birth year. The
  default `Crossfire Premier B12 Red` let `keeps_our_name` withhold the rename on its own, so both
  passed with the veto deleted.
- The accept-point read runs only when the match would auto-approve, and `or gender_conflict` is gone
  from the review branch (see step 4).
- `stored_gender` reads `B` and `G`. No live row is affected: `teams.gender` holds only `Male` and
  `Female`, and GotSport's answer already passes through `gotsport_team_details._gender`, which maps
  both letters.
- The three guards read a row through `row_genders`.
- New tests: a girls record in a boys division against a boys row whose names state nothing (only the
  stored column reads); a B/G twin listed before the right row; TGS's duplicate-key reuse, reached
  without concurrency when the first own-id lookup fails and is swallowed; a registration whose name
  alone states the other gender (GotSport says `Coed`).
- The gate and auto-match tests share one double, and the gate's resolver stub is a closure.
- Not taken: returning `None` instead of raising `ReuseRefused`, since both handlers fall through to
  the same unmatched result; folding `name_gender` into `read_label`, which reads `2009B Girls`
  differently from the owner's rule (backlog entry above).

### Mutations

Each guard line, the export column's write and read, and each TGS reuse site were broken one at a
time; every break was killed by a new test.

- Before review round 1, the TGS check after a duplicate-key insert was unkilled; it was believed to
  need a concurrent insert. A failed first lookup reaches it too, and a test now drives that.

### Replay of the 2026-11-09 split records

32 records replayed.

- 27 were the other gender to the row they joined. Against the squad each row kept, 26 are refused.
- The 27th is La Masia, whose GotSport record was reused for a girls squad after it was linked. No
  link-time guard can see that.
- 5 were same-gender extra squads, which this change does not address.

### Live negative control

The 2026-11-03 export, replayed through the new match step and both gates, with GotSport lookups
answering nothing as in CI: 334 records, of which the old gate approves 309.

- The new gate approves 308 of the 309, 11 of them as Coed.
- It holds 1: `DSC G2011`, a row stored as girls under a registered name of `DSC BU14`.
- Re-run later on 2026-11-09 through both scripts' `main()` on the same export (cause of the lower
  totals not traced): 318 candidates,
  the old gate approves 294, the new one 293 (11 Coed), and the one held is again `DSC G2011`. No
  record was held for an unread gender.

### Left open

- **Records GotSport reuses for the other gender after linking** (La Masia, Saints, DSC). The rename
  veto stops the name copy, but nothing re-checks an existing link.
- **The gate's own GotSport lookups answered nothing in CI** (0 of 88 on 2026-11-03). Its age, state,
  club and tier checks are blind there too.
