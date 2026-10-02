# Add Utah (UYSA) as an Affinity provider

## Goal

Import the UYSA 2026 fall league (`uysa.sportsaffinity.com`, tournament
`69C35A62-D325-418C-95D3-C61FA95030D3`) weekly, filing its teams in Utah.

The WA scraper cannot take it: its matcher searches only WA candidates and creates
every team with state WA, so Utah teams would land on Washington. Utah gets its own
provider code, `affinity_ut`, modelled on Oregon (`affinity_or`, #1133).

## What the source looks like (checked 2026-10-01)

- 147 boys and 75 girls divisions, on the same 10-column schedule layout as WA and OR,
  with scores posted.
- Division labels: `Boys 12U Premier`, `Girls 15U North A`, `Boys 18/19U Premier`,
  `Boys 18/19 N1`, with girls `18U` and `19U` listed separately. Spacing is irregular,
  and one girls row is blank.
- The U-number is the PitchRank cohort for the 2026-27 season.
- Team names carry their own age (`Peak SC 13/14B`, `La Roca U12B`, `Athletic SC B10/11`),
  and teams play up (`La Roca U12B` in 13U).

## Changes

1. `scripts/scrape_affinity_or_tournament.py` becomes the shared engine:
   - Each tournament entry names its `provider`, `state` and `state_code`.
   - `main(tournaments)` scrapes the list it is given, labelling the run by its state codes.
   - The division parser also reads `<Boys|Girls> <n>U`, and reads a two-age pair as
     19 only when both ages fold into u19 (`18/19`). `13/14` and `17/18` are skipped.
   - An opt-in `age_from_team_name` tournament flag files each game by both teams'
     names, using `age_from_name`/`board_cohort` from the Athletes2Events importer.
     A game is held back, with a printed count, when either name cannot be placed on a
     board or when the two names land on different boards. Oregon leaves the flag off:
     its `13B` names a band's older year.
2. `scripts/scrape_affinity_ut_tournament.py`: Utah's tournament list with the flag on,
   calling the engine's `main`.
3. `src/models/affinity_or_matcher.py`: the default state moves to class attributes
   (`state_code`, `state_name`), and three hooks let a subclass change how names are
   normalized (`_normalize_provider_name`), how a stored team's club is compared
   (`_same_club_as_candidate`) and what marks two squads apart (`_squads_conflict`).
   Oregon's own versions keep its behaviour unchanged.
4. `src/models/affinity_ut_matcher.py`: `AffinityUTGameMatcher` adapts the OR matcher to
   Utah's names, which a first live dry run showed it misread (167 of 195 teams would have
   been created, many duplicating stored Utah teams, and three distinct squads were fused):
   - Bands (`13/14B`, `B1314`) become their younger year, and glued U-ages (`U12B`) and
     league tags (`(SFC)`, `(ind)`) are dropped before a name is compared.
   - The club is the words before the first age mark, less trailing coach initials.
   - A stored team is looked for first by squad key, the rule the merging-duplicate-teams
     skill uses to pair one squad's rows across providers (Doorway D, reusing
     `scripts/find_squad_key_duplicates.py`). Only a single live (not deprecated) stored
     team in the club's search state is taken, and only when its key, cohort, league, tier
     (a tier on one side only counts as a difference), the gender its name states and its
     squad marks all agree, and neither name is an MLS NEXT, AD, HD or EA squad; otherwise
     the OR fuzzy match runs. Bands reach the
     cohort check as written, since a band names one cohort and a bare year two. Doorway
     D's game screens cannot apply: a team being matched has no stored games yet.
   - Coach initials anywhere after the club ('MH Black' against 'ZZ Black'), or a squad
     number on one side only, mark different squads, on both the squad-key and fuzzy paths.
     When two stored squads tie for the best fuzzy score, neither is taken (Oregon still
     takes the first, `refuse_tied_best`).
   - A club is asked for its state only in Utah and its neighbours. Asked nationally, a
     generic club word such as `Avalanche` (stored only in Virginia) sent Utah teams to
     Virginia. A club carrying an ilike wildcard (`%`, `_`, `*`, `\`) is treated as unknown.
5. `src/etl/enhanced_pipeline.py`: an `affinity_ut` branch that passes `dry_run`.
6. `supabase/migrations/20261001120000_seed_affinity_ut_provider.sql`: the provider row.
7. `.github/workflows/ut-scraper.yml`: a copy of `or-scraper.yml` on two Monday crons
   (05:30 and 06:30 UTC). A guard step in America/Denver runs only the one that falls at
   Sunday 23:30 Mountain time. The `AGE_ROLLOVER_FREEZE` gate is kept.
8. Tests: `tests/unit/test_scrape_affinity_ut.py`, plus Oregon cases for the new keys and
   for the gate staying off, and `affinity_or`/`affinity_ut` rows in the dry-run
   registries and the pipeline class check.
9. `CLAUDE.md`: the provider and workflow tables, the freeze list, and the
   state-stamping paragraphs.

## Verification

- Ruff and pytest, run the same way CI runs them.
- A live scrape of every age and gender over 45 days: 2,925 of 3,115 games filed on
  their division's board, 1 moved to a younger board, and 189 held back.
- A matcher dry run against production on 195 UYSA teams (130 boys U13, 65 boys U16),
  with every database write blocked and recorded: 87 linked to stored Utah teams, 108
  would be created, none outside Utah, and zero writes attempted. All 87 links were read
  by hand. Most of the 108 carry coach initials no stored team shares; the rest are
  safe-direction misses such as two stored rows tied for one squad, and Copper Mountain
  names that number squads by school grade on one row and birth year on the other.
- `import_games_enhanced.py ... affinity_ut --dry-run` against production once the
  provider row exists. That needs the migration applied, which is the owner's call.

## Known gaps

- A squad whose stored name puts a word before the club that the UYSA name lacks
  (`Avalanche Pre-ECNL` against stored `Utah Avalanche Pre-ECNL`) is not linked.
- The OR matcher creates a team whenever its best match scores in the review range, so
  an uncertain match becomes a new team rather than a review item. Oregon behaves the
  same way.
