# Modular11 EA Import — Step 2: Teams and Played Games into PitchRank

**Date:** 2026-10-05
**Status:** Draft (pending user review)
**Slug:** `modular11-ea-import`
**Builds on:** `.turbo/specs/modular11-ea-scraper.md` (step 1: scraper + match report, branch `feat/ea-scraper`)

## Goal

Load one EA age group at a time into PitchRank, starting with U17, so EA teams get ranked. The
order is: link the confident teams, create the no-match teams, import their played games, and then
hand the user a list of the newly created teams to check for matches.

## What the user decided (2026-10-04 / 2026-10-05)

- First import: "confident+new teams but then I want a list of the new teams so I can try and
  match myself".
- Decisions travel by **spreadsheet** (CSV/Excel with a legend and an example row).
- Approach: one age group at a time. Nothing waits on the user before the first import. The
  review teams wait until the user decides them.

## Decisions made for the user (overridable)

- **New teams get no state.** The roster gives only regions (e.g. "PACNW"), and deriving state
  from a guess is what the disabled backfill steps did wrong (CLAUDE.md). The state is filled later
  through the `assigning-team-states` flow.
- **Played games only.** Scheduled fixtures come in on a later re-run, once they are played. The
  pipeline gives each game an id made of the provider, the date and both PitchRank teams, so a
  re-run never duplicates a game.
- **Separate source.** A new provider code `modular11_ea` (one seed migration, mirroring
  `20260919120000_seed_athletes2events_provider.sql`). MLS NEXT's `modular11` is untouched.

## Flow, per age group

1. **Scrape.** Run the step-1 scraper and match report for the age (already built).
2. **Link (dry run by default, `--execute` to write):**
   - **Confident** rows: write a `team_alias_map` row (`modular11_ea`, EA team id → existing
     `team_id_master`).
   - **No-match** rows: create a `teams` row (EA display name, club, age, `Male`, state blank,
     `provider_id = modular11_ea`, `provider_team_id = EA id`) plus its `direct_id` alias.
   - **Review** rows: write nothing.
   - Every write goes to a log file so the batch can be undone. The dry run prints exactly what it
     would write.
   - An optional `--decisions <spreadsheet>` applies the user's picks (a PitchRank team id,
     `new`, or `skip`), each of which overrides the report's bucket for that team.
3. **Import games** through the standard pipeline (`scripts/import_games_enhanced.py <csv>
   modular11_ea`), with a thin `modular11_ea` matcher that resolves teams **only** through
   `modular11_ea` aliases and never fuzzy-matches or creates a team. The CSV holds played games
   where both teams are linked. Games with an unlinked team are held back and counted. Both loader
   column whitelists must admit every column the CSV relies on (CLAUDE.md, "Adding a new scraper").
4. **Hand-back.** A spreadsheet goes to the user: the teams created this run (to check for
   existing matches) and the review teams with their candidates and an empty "your pick" column.
   It carries a legend and one real example per row type. Matches the user finds for **created**
   teams are fixed by the standard duplicate merge (`merging-duplicate-teams`). Picks for **review**
   teams go back in through `--decisions` on the next run.

## Safety

- **Measure the ranking impact before the first real import** (`.claude/rules/ranking-changes.md`):
  games added, teams touched, and how many cross the 12-game provisional threshold. The numbers go
  to the user before `--execute`.
- The dry run must write nothing at any layer: the linker, the matcher, or the pipeline. Verify
  this against the database, not the summary.
- **Age rollover:** the link step and the import both write age groups, so the EA Scraper workflow's
  import step joins the `AGE_ROLLOVER_FREEZE` gate list and its coverage test.
- **Re-running is safe:** existing aliases and teams are reused, and games already imported are
  skipped by their match-number id.

## Workflow

The "EA Scraper" action gains an `execute` checkbox, off by default. When off it stays files-only,
as today. When on, it runs the link and import for the chosen age. The first U17 import is run by
hand after the user has seen the dry run and the impact numbers.

## Out of scope

- Scheduled-fixture import and score fills.
- Fixing the club-name recall gaps or `EA1` naming (the user chose to leave them, 2026-10-04).
- Any change to MLS NEXT (`modular11`) code, data or workflows.
