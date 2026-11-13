---
status: done
---

# Plan: Stop PlayMetrics tournament imports creating copies of existing teams

## As built

Departures from the steps below, and the verification:

- **Both club spellings count as club words.** `_match_team` keeps the club as PlayMetrics writes
  it in `_written_club`, as `Athletes2EventsGameMatcher` does, and `_fuzzy_match_team` strips its
  words too. Stored names carry either spelling (GotSport's `RASA 2017 Lotus` sits under club
  `AFC Union`). Stripping only the stored name left `rasa` reading as a squad word, which refused
  the right team.
- **A birth year has to fit the U-age.** `_years_outside_u_age` refuses a candidate whose name
  states a birth year outside the two-year band the other name's U-age names, in both directions
  (a stored U-age counts only while current, as the existing U-age check has it). The replay found
  the tournament's `AFC Union U10G Red` tying at 0.903 between `AFC Union G 2017 Red`, the right
  team, and `AFC Union G 2018 Red`, a U9 row filed on the u10 board. That was a coin-flip auto-link
  to the wrong team, newly reachable once the club gate passed AFC Union; the owner chose the check
  on 2026-11-12.
- **Exact club spellings.** `STORED_CLUB_NAMES` is keyed by the spelling PlayMetrics writes and
  matched exactly. The weekly club cleanup's "exact" rules ignore case; PlayMetrics writes each
  club as registered.
- **The test double now refuses what production refuses**, in `_Db` in
  `tests/unit/test_playmetrics_matcher_row_state.py`:
  - It answers the gender guard's read of the matched team with only the selected columns.
  - It answers the review queue's provider lookup with a real code.
  - It raises on an insert that cannot be serialized to JSON.

  Before this, a mock provider code went into the review row unnoticed, while postgrest would
  have refused the write and the base class would have swallowed the error.
- **Two more pins.**
  - The pipeline building the tournament matcher with `default_state_code=None` (and the league's
    with `"WI"`) is tested through `EnhancedETLPipeline._ensure_initialized`.
  - A test fails if the weekly cleanup's `CLUB_CANONICAL_OVERRIDES` ever renames one of the stored
    club names.
- **The review-band fixture holds under both scorers.** `difflib` scores Pegasus `Girls U14 Red`
  against `Girls 2012/2013 Red` at 0.923 and links it, so the hold tests use `Lotus` against
  `RASA 2017 Lotus`, 0.883 under either. CI runs without `rapidfuzz`.
- **Mutation checks.** Each revert, made alone, failed the named new test:
  - Dropping the club translation fails the link cases and the new-team cases.
  - Dropping an entry fails its own case.
  - Not stripping the written spelling fails the `RASA 2017 Lotus` case.
  - Dropping the hold fails the tournament review test.
  - Holding on the league, or on any unscoped row, fails the league tests.
  - Building the tournament matcher without `default_state_code=None` fails the pipeline test.
  - A cleanup override renaming `AFC Union` fails the overrides test.
  - A misspelt column in the gender guard's select fails the link cases.
  - A mock provider code fails the review tests.
  - Dropping either direction of the birth-year check fails its own case (`U10G` against `2018`,
    `2009` against `U19`).
- **Replay against live pools (read-only).** The Harvest Classic cleanup's two merge lists hold 49
  pairs. In 46 of them, one side is a `playmetrics_tournament` row (31 created 2026-11-10, 15 on
  2026-10-05); in 7 of those the tournament row was the one kept. The other 3 pairs are Soccer
  Events Group copies. Each tournament row was matched with its original PlayMetrics club spelling
  against today's `teams` pool for its age and gender, minus the 46 tournament rows, with no writes.
  The name score depends on whether `rapidfuzz` is installed: it is in neither requirements file,
  so the import workflow scores with `difflib`, while a local run (as on 2026-11-10) has it.
  - With `rapidfuzz`: this branch linked 19 to the right team, held 19 for review, created 8;
    `main` created 45 and linked 1.
  - With `difflib`: this branch linked 35, held 3, created 8; `main` created 29 and linked 17.
  - Neither scorer linked any row to a wrong team on this branch.

  An earlier replay took each list's `merge` side as the copy and reported 18 / 20 / 11 over 49.
  That mixed in the 7 reversed and 3 Soccer Events Group pairs, and it hid the wrong link above.

## Context

The Harvest Classic cleanup of 2026-11-10 merged 46 PlayMetrics tournament rows that copied an
existing team, from that day's import and the one of 2026-10-05, by hand. Replayed on `main`, 45 of
them are created again. Three causes:

1. **Club spelling (21 copies).** PlayMetrics writes `RASA - AFC Union`, `RASA Arsenal F.C.`,
   `Forward Madison FC Youth` and `Rush Wisconsin Southeast`. PitchRank stores `AFC Union`,
   `Forward Madison FC` and `RUSH WI Southeast`. `are_same_club` (threshold 0.9) rejects every
   pair, so `PlayMetricsGameMatcher._fuzzy_match_team` drops the real team before scoring it.
2. **Review band (16 same-club copies under `rapidfuzz`).** These are same-club teams such as Pegasus `Girls U14 Red` against
   `Girls 2012/2013 Red`, scoring 0.875-0.899. The base matcher queued them for review, and
   `_match_team` then created a new team anyway. The Athletes2Events and Soccer Events Group
   matchers return early on `fuzzy_review` instead.
3. **Name gates (8 same-club copies).** These are same-club names the distinction gates refuse
   before scoring, such as `PSG-NORTHSHORE U14 BOYS` against `PSG ACADEMY NORTHSHORE U14 BOYS`.
   They are out of scope, and they are the 8 the replay above still creates.

On 2026-11-12 the owner chose to fix the first two, holding review-band teams on the tournament
import only. The weekly league import keeps creating them, because games it held would wait
unlinked on an unattended weekly run with nobody watching for them.

## Steps

1. `src/models/playmetrics_matcher.py`:
   - Add `STORED_CLUB_NAMES`, the four spellings mapped to PitchRank's club names.
   - `_match_team` replaces the club before the base call. That one replacement feeds the club
     gate, the review entry and team creation, so a new AFC Union team is filed under `AFC Union`
     and takes that club's state.
   - On the tournament flow (`default_state_code is None`), return the base result when it is
     `fuzzy_review` rather than creating a team.
2. Tests in `tests/unit/test_playmetrics_matcher_row_state.py`, each driving `match_game_history`
   through the file's `_Db` double:
   - Each of three clubs links to its stored team.
   - A new team is filed under the stored club name.
   - A tournament review-band team is held, with its review suggestion.
   - A league review-band team is still created.
3. Docs:
   - Rewrite the copy-paths paragraph of the scraper-patterns skill's *PlayMetrics Tournaments*
     section.
   - Add an `Update` note to the backlog entry, which stays open for its age-rule tests.

## What a held team means

A held team's games count in no ranking until it is linked. The scraper-patterns skill's
*PlayMetrics Tournaments* section has the procedure for settling it and re-importing.
