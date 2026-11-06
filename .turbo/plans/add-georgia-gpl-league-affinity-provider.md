---
status: done
---

# Plan: Add Georgia's fall league as an Affinity provider and match each team at its own age

## Context

Georgia Soccer runs its competitive fall league on Sports Affinity as `Fall 26 Georgia Soccer
Scheduling` (`gs-fall26schedule.sportsaffinity.com`, GUID `72B7A2F4-DB78-434C-8D08-D119FEFD741C`).
PitchRank has none of it. Surveyed 2026-11-05: 19 divisions. One, `19U BOYS RIAS`, is Georgia
Soccer's rec schedule (5 teams, 13 scored games) and stays out. That leaves 18 divisions across GPL,
Pre-GPL, Championship and Conference, with 110 teams, 322 scored games dated Sep 11 to Nov 3, and 68
fixtures still to play through Nov 21. The owner asked for it after Hawaii, on the same Sunday-night
schedule as the other Affinity states.

73 of the 322 games (23%) pair teams of two ages, because divisions such as `15/16UB`, `17/19UB` and
`13/14UG` mix ages. Hawaii's rule holds such games back, which would lose a quarter of this league.
Storage does not require that: 18.7% of GotSport games since Aug 1 pair two ages, and
`games.age_group` is blank on every row checked. The limit is that `match_game_history` looks both
teams up at one age. The owner's rule (2026-11-05): "So it doesn't matter what division they are
playing in- a team can be playing up". So each Affinity team in Georgia and Hawaii is matched at the
age in its own name, which also brings in Hawaii's 26 held games. The division sets an age only for
a name that states none (owner, 2026-11-05).

## Pattern Survey

### Analogous Features

- `scripts/import_athletes2events_event.py:21-31`: imports games between two boards, reads each
  team's age from its own name, and takes the home team's age on the row.
- `scripts/import_demosphere.py:542-578`: per-team age with a division fallback.
- `src/models/athletes2events_matcher.py:137-154`: skips the base age gate, with the reason written.
  TGS, SincSports and PlayMetrics also override `_match_by_provider_id` without the gate.
- `scripts/scrape_affinity_hi_tournament.py`, `src/models/affinity_hi_matcher.py`,
  `.github/workflows/hi-scraper.yml`: the provider this one repeats.

### Reusable Utilities

- `src/tournaments/cohort_labels.py:128` `read_label(label, *, season=)`: pure, no `scripts` import,
  reads names and division labels. Run over all 110 real names it matched a by-hand reading on 100.
  Of the other 10, 3 state no age (`Atlanta Furious - CH/CF`, `BC Prime`, `BC Blazers`) and 7 need a
  respelling (see step 5). Use it rather than `age_from_name`, which reads `B17U` as born 2017.
- `scripts/decide_team_merges.py:103` `label_numbers`: the stated U-ages, already used by Hawaii.
- `src/models/yssl_matcher.py:48` `roman_to_digits`: Hawaii's squad numbers.
- `src/utils/team_name_utils.py` `NOISE_WORDS`: generic club words.

### Convention Anchors

- One age reaches both teams at `src/models/game_matcher.py:674` and `:684`. The row carries a single
  `age_group`, and neither loader nor `_transform_game_perspective` has a per-team age.
- `AffinityORGameMatcher._match_team` (`src/models/affinity_or_matcher.py:456`) is overridden by
  neither Utah nor Hawaii, and every lookup sits under it, so an override there changes no shared file.
- What each lookup does with the age: `_match_by_provider_id` requires it to equal the stored age;
  `_fuzzy_match_team` filters candidates on it; create writes it. `_match_by_alias` returns nothing on
  this path.
- A team handed the wrong age is not half-matched: fuzzy misses and OR's `_match_team` creates a
  duplicate on the wrong board. That is why Hawaii's hold was right until this change.
- No validator, dedup key, uid or ranking read compares a game's two teams. The matched record has no
  `age_group` key, and rankings read each team's age from `teams`.
- A pass in the workflow scrapes one age. `_youngest_division_age` schedules a mixed division on its
  youngest age, gated at `scripts/scrape_affinity_or_tournament.py:402`.
- `HARD_STOP_AT` (`scripts/team_cleanup/apply_stage.py:198`) is Sunday 22:00 Arizona, Monday 05:00
  UTC. Every entry in `WRITER_WORKFLOWS` must fire at or after it, and EA at 05:00 stays the earliest.
- `_team_hash` keys on the division's `age_u`, not the team's, so a team's id is stable within a league.

### Proposed Alignment

Follow the Athletes2Events rule that a two-board game imports and each side resolves at its own age.
Deliver it through one `_match_team` override in a base class extracted from Hawaii's matcher, with
Utah, Oregon and Washington untouched. The alternative, per-team CSV columns, touches both shared
loaders and `_transform_game_perspective` for no gain, because both matchers can read the name.

## Implementation Steps

1. **Set up after Hawaii merges**
   - Georgia builds on PR #1400's engine fixes and matcher. Confirm `gh pr view 1400 --json state`
     reads `MERGED` before starting, then branch `feat/affinity-ga-georgia-league` from `origin/main`
     in a new worktree, `C:/pitchrank-affinity-ga`.
   - Do not build in `C:/PitchRank`: that checkout sits on an unrelated HEAD, is behind `origin/main`
     and has uncommitted work. Copy this plan into the worktree before committing.

2. **Read Georgia's division labels in the shared engine** (`scripts/scrape_affinity_or_tournament.py`)
   - Add an age-first branch to `_extract_age_gender_from_division` for `12UB Pre GPL`, `13/14UG
     GPL/CH` and `17/19UB CH/CF North`, using `_pair_cohort` for a pair as the other branches do.
     `_pair_cohort` returns None for 13/14, 15/16, 17/18 and 17/19, and 19 for 18/19 (measured).
   - Extend `_youngest_division_age` to the same form.
   - In `discover_flights`, add two opt-in tournament keys. `skip_divisions`, a tuple of words, drops a
     division before parsing. `mixed_age_divisions` opens the `:402` gate alongside
     `age_from_name_prefix`.
   - Preserve every existing label form and the layout-row skip. Oregon, Utah and Hawaii set neither
     new key.

3. **Stop holding Hawaii's two-board games** (`_board_from_name_prefixes`)
   - Return the home team's reading when both names read, rather than `_same_board(readings)`. The
     row's age no longer decides a team, since step 4 reads each name.
   - Keep every other hold: no label, a label of the other gender, a name below u10, and a later age
     that vetoes the label.
   - `_same_board` stays for `_board_from_team_names`. Utah's hold is unchanged.

4. **Extract the shared base and give each team its own age**
   - New `src/models/affinity_state_league_matcher.py`, class
     `AffinityStateLeagueMatcher(AffinityUTGameMatcher)`. Move in, unchanged in behaviour, Hawaii's
     `_normalize_provider_name`, `_club_for`, `_club_words`, `_squad_words` and `_squads_conflict`.
   - Class attributes a state sets: `state_code`, `state_name`, `region`, its club map, and the words
     that are never a squad's own. Keep `_NOT_SQUAD_WORDS`' `NOISE_WORDS` part in the base.
   - Hook `_prepared(name)`: what a name becomes before its words are read. Hawaii drops the age label
     and writes Roman numerals as digits; Georgia respells (step 5).
   - Hook `_own_board(team_name)`: the board a team's own name states, else None.
   - Override `_match_team` with the same signature as `src/models/affinity_or_matcher.py:456`. It
     swaps in `self._own_board(team_name) or age_group`, then calls `super()._match_team`. A name that
     states no age keeps the row's age.
   - `src/models/affinity_hi_matcher.py` becomes a thin subclass holding `_HI_CLUBS`, `_AGE_LABEL` and
     the state attributes. `_own_board` reads the label: 18U and 19U both give `u19`, below 10 gives
     None. Its `_squads_conflict` docstring moves with the method.

5. **Add the Georgia matcher** (`src/models/affinity_ga_matcher.py`, `AffinityGAGameMatcher`)
   - `state_code = "GA"`, `state_name = "Georgia"`, `region = ("GA",)`.
   - `_prepared` respells before anything reads the name: `BA12U` and `BR14U` as `U12` and `U14`,
     `COS CREW14U` as `COS CREW U14` so `CREW` stays a squad word, and a bare `B14` as `U14`. All three
     bare forms (`B12`, `B14`, `B15`) sit in a division of that same number, and `B15` as a birth year
     would put a u12 team three years up in GPL. `B14U`, `U13B`, `13UG`, `Boys 13U`, `14/15B`, `2014B`
     and `07/09B` are read by `read_label` as written.
   - `_own_board` returns the single cohort `read_label` gives for the prepared name, else None.
   - Squad words: strike `GPL`, `CH`, `CF` and `PRE`, which are league tags that change by season. Do
     not strike `GA`: it is also Girls Academy, so a stored `GA` squad stays a different squad. Strike
     `GEORGIA` only through the club words.
   - Club map, each pairing read from stored rows on 2026-11-05: `BVB IA Georgia`; `Savannah United`;
     `Atlanta City FC`; `All-In FC Sugar Hill` to `All-IN FC Sugar Hill`; `AFC Lightning Griffin` to
     `AFC Lightning`; `Covered Bridge Soccer Club`; `Georgia Wolves` to `Georgia Wolves SC`;
     `Georgia Athletic SC` to `Georgia Athletic Soccer Club`; `Hinesville SA`, `Hinesville Soccer
     Association` and `Hinesville Waycross` to `Hinesville Soccer Association`; `TCSA United` and
     `TCSA Flames` to `Toombs County Soccer Association`; `Coastal Outre` and `Coastal Outreach` to
     `Coastal Outreach Soccer Prog.`; `Football Club OLeary` to `FC O'Leary`; `Path Academy FC` to
     `PATH ACADEMY FC`; `Piedmont SA`; `Alianza Soccer` to `Alianza Soccer Club`; `UMA FC`;
     `Bryson Park Soccer Club`, `Bryson Park Soccer` and `Bryson Park Flash Soccer` to `Bryson Park`;
     `Troup County Lions`; `Southern Cross FC`; `Atlanta Furious`; `BC Prime`.
   - `GUSA Rome` to `Georgia United SA`, read by hand in the dry run: one stored `Gusa Rome` row sits
     under `UMA FC`.
   - Left unmapped, so created new: `Champions FC`, `Statesboro Stars Soccer Club`, `BC Blazers` and
     `Sacred Heart Fusion`. Stored `RHSC Statesboro` is Richmond Hill and stored `Sacred Heart
     Crusaders` is a different name, so neither is linked by a map.
   - Branches stay apart: `South`, `West`, `Oconee`, `PTC`, `Waycross`, `Griffin` remain squad words.

6. **Add the scraper wrapper** (`scripts/scrape_affinity_ga_tournament.py`)
   - One tournament: name `Fall 26 Georgia Soccer Scheduling`, the GUID above, base_url
     `https://gs-fall26schedule.sportsaffinity.com`, provider `affinity_ga`, state `Georgia`,
     state_code `GA`, season_year 2026, `skip_divisions: ("RIAS",)`, `mixed_age_divisions: True`,
     `min_game_date: "2026-08-01"`.
   - Georgia sets neither `age_from_team_name` nor `age_from_name_prefix`, so the row carries the
     division's youngest age, which is the fallback for a name with no age.

7. **Wire the provider in**
   - `src/etl/enhanced_pipeline.py`: an `affinity_ga` branch passing `dry_run`, beside `affinity_hi` at
     `:332`.
   - `supabase/migrations/<next version>_seed_affinity_ga_provider.sql`, mirroring
     `20261105120000_seed_affinity_hi_provider.sql`, with base_url `https://gs.sportsaffinity.com`.
   - `.github/workflows/ga-scraper.yml`, a copy of `hi-scraper.yml`. Preserve the freeze gate, the
     stale-GUID check, the artifact upload and the dry-run input.
   - Cron `15 6 * * 1`: Sunday 11:15 PM Arizona, a free minute, with no DST guard. Sweep ages 10-19.
   - Registries, none derived: `AUTOCREATING_MATCHERS` and the create-helper list in
     `tests/unit/test_provider_matcher_dry_run.py`; `_SUBCLASS_PATHS` in
     `tests/unit/test_birth_year_guard_wiring.py`; `WRITER_WORKFLOWS` in
     `scripts/team_cleanup/apply_stage.py`; `EXEMPT_SCRIPTS` in
     `tests/unit/test_team_cleanup_apply_stage.py`; `SECONDARY_PROVIDERS` in
     `scripts/find_cross_provider_duplicates.py`. `PROVIDER_RULE_CODES` stays out, as with Hawaii.

8. **Update the records**
   - `CLAUDE.md`: provider row, workflow row, the count of provider imports that stamp a state, the
     state paragraph with new line anchors, and the freeze list.
   - `.claude/skills/scraper-patterns/SKILL.md`: Georgia's label forms, `read_label` as the reader to
     try first, and the rule that an Affinity team is matched at its own age.
   - `.turbo/plans/add-hawaii-oahu-league-affinity-provider.md` Known gaps: replace "half-match" with
     what the code does, and note the 26 games are lifted.
   - `.turbo/improvements.md`: Utah still holds two-age games (12 in its latest weekly run).

9. **Tests**
   - `tests/unit/test_scrape_affinity_ga.py`: every division label as a literal, `19U BOYS RIAS`
     skipped, a mixed division scraped once on its youngest age, a forfeit and a `0 CC` importing
     nothing, and no game held for pairing two ages.
   - `tests/unit/test_affinity_ga_matcher.py`, on the strict `_RecordingDB` double from
     `tests/unit/test_affinity_hi_matcher.py`: the board of each of the ten exception names plus one
     name per form, as literals; `B17U` reading u17; squad and club rules; `GA` left as a squad word.
   - Drive a two-age game through `match_game_history` for both matchers, asserting from what the
     double recorded that each team was looked up and created at its own age. A test of `_own_board`
     alone would pass with the override deleted.
   - `tests/unit/test_scrape_affinity_hi.py:185`: rewrite the two-board hold to assert the game is
     filed. `tests/unit/test_scrape_affinity_ut.py:147` must stay green unchanged.
   - Existing `tests/unit/test_affinity_hi_matcher.py` stays green unchanged, as the proof the
     extraction moved behaviour without altering it.

## Verification

- Live scrape of every age into a scratch folder: 18 divisions matched, `19U BOYS RIAS` absent, 322
  or more scored games filed, none held for age. Compare the `Matched flights` counts to the site.
- Offline check that no two Georgia teams share club, board, gender and squad words.
- Guarded production run of `AffinityGAGameMatcher` under the fail-closed write guard: all 110 teams,
  zero writes, every link read by hand, every candidate in GA, no stored team taken twice, and each
  team's board equal to the by-hand reading.
- Hawaii: re-scrape, confirming the 26 file and nothing new is held. Re-run the guarded matcher and
  compare against the 235-team result (89 linked, 146 to create).
- Oregon, Utah and Washington: output identical to `main` on the same pages.
- Mutation run, each killed by the new test by name: the `_match_team` swap, `_own_board`'s fallback,
  each respelling, `skip_divisions`, `mixed_age_divisions`, and the Hawaii return.
- Before merge, owner applies the provider row and repairs the ledger.
- After merge, dispatch `ga-scraper.yml` with `days_back` 90 and `hi-scraper.yml` with `days_back` 90,
  then verify from data: stored `affinity_ga` games since 2026-08-01 against the scraped count; every
  two-age game carrying both team ids; each created team in GA at the age its name states.

## As built

Built 2026-11-06 on `feat/affinity-ga-georgia-league`, after Hawaii merged as #1400. The steps above stand as
approved. The build differs from them in these ways. The first group came from reading the guarded production run
by hand, the second from a seven-reviewer round.

- **Club map keys stop short of a branch.** Step 5 lists `Hinesville Waycross` and `AFC Lightning Griffin` as
  spellings and also says Waycross and Griffin stay squad words. Every word of a written spelling is struck from
  the squad, so the two cannot both hold. The map uses `Hinesville` and `AFC Lightning`.
- **Georgia turns off OR's variant gate.** Not in the plan, and the largest finding: it refused 169 candidates.
  It reads league tags (`GPL`, `CH/CF`), the letter of `U15 B` and the `SC-` of `SC-U15B` as squads. The
  squad-word rule is stricter on real differences. Georgia only, so Hawaii's matching is unchanged.
- **Georgia takes the club's one live row under the league's exact name first.** Not in the plan. A stored duplicate
  can tie with the right row, and `refuse_tied_best` refuses a tie. Three teams would have been duplicated: two by
  ties between live rows (`Savannah United 12B West`, `Savannah United 12G Blue`) and one by a tie with a merged-away
  row, because OR's fuzzy candidates include deprecated rows.
- **`BVBIA` is struck, and `CF` is not listed.** Stored rows spell the club `BVBIA`, which blocked one real link.
  `CF` is already a generic club word, so its entry did nothing.
- **`AffinityStateLeagueMatcher` joined `_SUBCLASS_PATHS`.** The delegation guard reads a class's own body, so
  with the override on the base it skipped Hawaii and Georgia.
- **A name starting with its stored club is stored without it** (`Boys 13U` under `Champions FC`), by the shared
  create path, as in Oregon and Utah. Hawaii never met this because its names start with the age label.

From the review:

- **Georgia joined `SCHEDULE_ID_SUFFIX_PROVIDERS`.** Two doubleheaders in the league (Nov 7 and 8) would have lost
  their second games to the dedup key, with no count reporting it. Joining before the first import means no stored
  uid changes. A stored fixture keeps its uid, so its later score lands through the ordinary backfill (tested).
- **Ages ending in a U are respelled in `_prepared`** (`B14U`, `BA12U`, `13UG`, `G19U`, `16U`), so the UT club
  reader cuts the name at the age. That removed nine club entries, and the next club writing `B14U` no
  longer becomes its whole name. `Champions FC` and a few others still map to themselves, where the reader cuts wrongly.
- **Georgia's U-age check reads the respelled names**, so `COS CREW18U` conflicts with `COS CREW19U`. A stored bare
  `B14` is left alone there, because in a stored name it may be a birth year.
- **The exact-name lookup checks the club.** The create path makes short stored names such as `U13B`, which are not
  unique to one club.
- **`Pre-GPL` is respelled `GPL`, and `PRE` is not struck.** Striking it let `Pre-ECNL` link to `ECNL`.
- **Roman numerals stay out of Hawaii's club reading**, as on main: `_prepared` drops the label alone, and
  `_normalize_provider_name` adds the numerals. Sharing them had stored `Hawai'i Soccer` as `Hawai'1 Soccer`.
- **The base was simplified.** Its setup is a plain `__init__`, `region` comes from `state_code`, so no league can
  inherit Utah's six states, and `_match_team` holds the one board check. One `mixed_age_divisions` key opens the
  gate, so Hawaii sets it too, and the club spelling regex takes `re.ASCII` so a folded letter cannot raise `KeyError`.

Measured 2026-11-06, nothing written:

- **Scrape:** 18 divisions, no RIAS, 389 games (322 played, 67 upcoming), Sep 11 to Nov 21, none held. 104 teams
  against the survey's 110: the other six forfeited every game they had, so they import nothing.
- **Collisions:** no two of the 104 teams share club, board, gender and squad words.
- **Guarded matcher pass, all 104 teams, on the final code:** 28 linked, 76 new, no write attempted, no stored team
  taken twice, none outside GA, none at another age or gender. 28 teams match at an age other than their row's. The
  review's changes moved no link, club or board. Every link and every new team beside stored clubmates was read by
  hand. The full importer cannot run until the provider row exists.
- **Links to `B2009` and `2009B` from `B19U` names:** kept. Both stored rows have no games at all, so no history
  can fuse, and Georgia's 19U divisions field 2009 teams (`Savannah United 07/09B`, `Oconee 08/09`).
- **Still new, and left that way:** four teams whose stored row scores about 0.8 (`2011B`, `2013B`, `2015B`, `2012B`
  under the right club) go to review as new teams; stored duplicates that tie (`UMA FC 2014-15B` and `2014-15
  Boys`); and one-sided squad words (`Prem` against `Premier`).
- **Hawaii, on the final code:** re-scrape gives 993 games against 967, exactly the 26 held (17 `G15-19U`, 9 `B19U`),
  none lost, none held. Guarded matcher on main against the branch: no difference in link, club or board on the 235
  shared teams. Real importer dry run: 993 matched, 0 partial, 0 failed, 26 new, 967 already stored, 0 quarantined,
  one new team (`16UG - FC Hawaii Red`, seen only in held games).
- **Oregon and Utah:** 48 passes over 279 real flights, one cached copy of each page through both engines: no
  difference. The Washington, Oregon and Utah matcher files have no diff against main. The base matcher's only
  change adds `affinity_ga` to `SCHEDULE_ID_SUFFIX_PROVIDERS`.
- **Mutations:** 49 on the final code, each killed by a named test. Earlier runs exposed a test that never reproduced
  a tie and two boundary tests that stopped testing anything when their map entries were removed; all three were
  rebuilt.

Still to do after merge: the owner runs the provider SQL and repairs the ledger, then both catch-up dispatches and
the from-data checks above. A stored-games count should reach 389 for Georgia, doubleheaders included.

## Known gaps

- **Fall ends Nov 21.** Only three Sunday runs remain this season. Each season has its own GUID and
  subdomain, so spring 2027 needs a new `TOURNAMENTS` entry. The stale-GUID check catches a dead
  league, not a new one.
- **A rescan past an Aug 1 rollover** reads a name's birth year against the current season, because
  `read_label` takes the wall clock; a U-age does not move. Stored labels roll with it, and the freeze
  gate and the per-season GUID keep the weekly job clear of the gap.
- **Squad matching is strict.** A stored name that lacks a branch word will not link, so some Georgia
  teams will be created and left for the duplicate work. That is the safe direction.
- **A real import adds a pending review row per created team**, as Utah's and Hawaii's do (backlogged).
- **A bare `B14` meets the base birth-year guard as written.** The guard reads the raw name as born 2014, so a
  stored `2013` row of the same squad would be refused and a duplicate created, with a review row pointing at it. None
  of the three bare names has such a row today, and it fails in the safe direction.
- **A team that changes division gets a new provider id**, because `_team_hash` keys on the division's age, and a
  short stored name such as `U12B` may not be found again. No team plays in two divisions today.
- **Utah's hold is out of scope:** the owner approved this for Georgia and Hawaii.

## Context Files

- `src/models/affinity_hi_matcher.py`: the class being split.
- `src/models/affinity_ut_matcher.py`: `region`, `_club_states`, `_club_for`.
- `src/models/affinity_or_matcher.py`: `_match_team` and the create path.
- `src/models/game_matcher.py`: `match_game_history`, `_match_team`, `_match_by_provider_id`.
- `src/tournaments/cohort_labels.py`: `read_label`.
- `scripts/scrape_affinity_or_tournament.py`: labels, `discover_flights`, `_board_from_name_prefixes`.
- `tests/unit/test_affinity_hi_matcher.py`: the strict double to reuse.
- `.claude/skills/scraper-patterns/SKILL.md`: section "Sports Affinity Pages", in the worktree copy.
