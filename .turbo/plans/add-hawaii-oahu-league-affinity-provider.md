---
status: done
---

# Plan: Add Hawaii Oahu League Affinity provider

## As built

Where the build departed from the steps below, and why:

- **Range divisions.** `G15-19U` parses to no cohort, by the same rule as Utah's two-age labels
  (now the shared `_pair_cohort`). `discover_flights` schedules it on its youngest age's pass
  (`_youngest_division_age`), and only for a league that sets `age_from_name_prefix`, so Oregon
  and Utah never take a range label as a cohort.
- **A pre-existing engine bug, fixed here.** On every Affinity accepted list, the division
  rows sit inside a layout table. The layout row's first link belongs to the first division,
  and `discover_flights` marked that link seen before reading the row's label. The real row was
  then skipped, so the first division of each boys/girls list never scraped.
  - Hawaii lost `B19U` and `G15-19U` this way.
  - Oregon has been losing `BU11 SCL` and `GU11 SCL` every week: 79 games in the 90 days to
    2026-11-05, none of them stored.
  - Utah's first divisions are U9, which has no board, so it lost nothing.
  - Washington's scraper has its own copy of the loop and the same layout rows. Its first
    divisions are U8 and U9, which its ages loop never scrapes, so it loses nothing today. It
    was left alone and logged in the backlog.
  - Layout rows (rows holding a table) are now skipped. The OR test page builder now wraps its
    rows the way the live page does, which is why the bug had stayed invisible.
- **A squad-word rule in `AffinityHIGameMatcher._squads_conflict`.** The first production dry
  run linked 11 stored teams to two or three league squads each. Stored names that named no
  squad (`Hawaii Rush 2016`) were matched by `RUSH Azul`, `RUSH Nero` and `RUSH Lightning Salt
  Lake`. Stored rows such as `WND BU12 Academy`, which carry no club, had their branch mark read
  as the club. So two names of one club are now one squad only when the same words remain after
  the club (both spellings), the ages and generic club words (the shared `NOISE_WORDS`) are
  struck out. This replaces Utah's `_squads_conflict` for Hawaii rather than adding to it:
  coach initials and squad numbers are words too, and Utah's lane reader wrongly refused a
  number written before a year (`Hawaii Surf Academy 1 2014`).
- **A stated U-age rule in the same method.** Review found that U18 and U19 squads of one club
  merge: both file on `u19`, and their words agree once ages are struck out. Two names that both
  state a U-age (`label_numbers` from `scripts/decide_team_merges.py`) and share none are now two
  squads. The first attempt used `cohorts_compatible`, which refused `19UB - Leahi Na Koa 08/09
  Blue` against its own stored row because it reads the `08/09` band as U18. HYSA labels that
  band either 18UB or 19UB, so bands are left out of this rule.
- **`refuse_tied_best` is inherited, and the only Utah matcher change is `region`.** The
  not-initials set, `_is_initials` and `_club_words` hooks tried during the build were removed
  once nothing needed them.
- **Club map** also maps `BI Rush` to itself, so a stored Big Island Rush row is never read as
  Hawaii Rush, and adds `Ballistic`, `Hoomau` and `Arsenal FC`, whose stored names (`Ballistic
  Soccer Hawaii`, `Ho'omau FC`, `Arsenal FC Hawaii`) the smoke run showed were being missed: the
  six Ballistic teams would otherwise have become six clubs.
- **`scripts/full_club_analysis.py` `PROVIDER_RULE_CODES` was not joined.** Utah joined it in a
  later club re-casing change, not in the change that added the provider.
  `SECONDARY_PROVIDERS` was joined as planned.
- **Verification, 2026-11-05:**
  - **Live scrape:** 17 flights (3 of them empty), 745 games filed, 26 held, dated
    Aug 15 – Oct 31. The held games are 17 in `G15-19U` and 9 in `B19U`, each pairing teams on
    two different boards.
  - **Production matcher dry run** (writes refused by a transport guard), over 235 teams:
    - 89 linked, every link read by hand;
    - 146 to be created, none with an exact stored twin;
    - no stored team taken twice, nothing outside HI, zero writes attempted.
    - A dry run creates nothing, so it cannot show a league squad linking to a team created
      earlier in the same import. Measured instead: none of the 235 teams shares its club,
      board, gender and squad words with another, so no two can link to each other this season.
  - **Mutations:** 26, each killed by the intended test.

## Context

The owner asked for 2026 Affinity leagues PitchRank does not ingest. A census on 2026-11-05 found
the HYSA **2026/27 Oahu League Season** to be the largest competitive one: 287 club teams (Albion SC
Hawaii, Hawaii Rush, Surf Hawaii, BVB IA, HSC Bulls, Leahi, FC Hawaii, Inter Ohana CF, Hawaii United
FC, 808 FC, Ballistic), with 910 scored games played Aug 15 – Oct 31 2026. PitchRank holds only about
2,400 Hawaii team-games for the whole past year, so this roughly doubles Hawaii's evidence. No game
from this league is stored under any provider (checked by event name).

Owner decisions (2026-11-05):
- Import only games on or after **2026-08-01**.
- Run weekly, plus a one-time catch-up covering Aug 15 onward.
- Each team's age comes from the age label at the **start of its own name** (`13UB - HSC Bulls
  13/14B - II`). This label is per team, not the division's: division `B19U` holds `17UB`, `18UB`
  and `19UB` teams, and `G15-19U` holds `15UG` … `19UG`.
  - Of 287 teams, 195 carry a second age later in the name, and it agrees with the label every time.
  - 90 carry only the label.
  - 2 Albion names carry two U-ages (`15UB - ALBION SC Hawaii HNL BU14/U15 Academy`) and use the
    label too.
- U9 teams are skipped, because there is no board.
- Matching is Hawaii-only, and new teams are created with state HI.
- Run a matcher dry run against production, with every write blocked and every link read by hand,
  before anything is written.
- Applying the provider-row migration is the owner's call.

Out of scope:
- the Big Island and Maui leagues (rec);
- the spring 2026 Oahu season (before Aug 1);
- Fall League Washington (rec; dropped 2026-11-05);
- the separate WA scraper (`scripts/scrape_affinity_wa_tournament.py`).

## Pattern Survey

Surveyed against `origin/main` at cac9226f4, in the worktree this plan lives in.

### Analogous Features

- **Utah, `affinity_ut`** (`.turbo/plans/affinity-ut-uysa-provider.md`) is the template. It consists
  of:
  - a thin wrapper, `scripts/scrape_affinity_ut_tournament.py:20,24-39,43`, which defines
    `TOURNAMENTS` and calls the shared `main`;
  - a matcher subclass, `src/models/affinity_ut_matcher.py:138`;
  - a pipeline branch, `src/etl/enhanced_pipeline.py:322-326`;
  - a seed migration, `supabase/migrations/20261001120000_seed_affinity_ut_provider.sql`;
  - a workflow, `.github/workflows/ut-scraper.yml`.
- **Shared scraper engine, `scripts/scrape_affinity_or_tournament.py`:**
  - `TOURNAMENTS` entry keys (`:46-61`): `name`, `tournament_guid`, `base_url`, `provider`,
    `state`, `state_code`, `season_year` (required, never the wall clock). `age_from_team_name` is
    opt-in (`:458`).
  - `_extract_age_gender_from_division` (`:172-210`) reads `^[BG]U\d`, `<Boys|Girls> n[/m]U`, and
    a gender word plus `Under n` / `\bU\d`. **It returns `(None, None)` for every Hawaii label**
    (`B19U`, `B14U R1`, `G15-19U`, `G09U R2`), so `discover_flights` (`:292-356`, skip at
    `:339-340`) matches no flight. The workflow's stale-GUID check would then fail the run.
  - `discover_flights` keeps a flight only when the division's U-number equals `--age` (`:341`).
  - `scrape_flight_games` (`:362-523`):
    - reads names from `cell_text[5]`/`[8]` and scores from `[6]`/`[9]` (`:407-418`);
    - filters on the window at `:399`;
    - skips a past blank pair and keeps a future blank as a fixture (`:420-435`);
    - skips any non-numeric score (`:437`);
    - takes the age group from the division (`:449-456`), unless `age_from_team_name` hands the
      game to `_board_from_team_names` (`:236-257`, applied `:458-463`). A game that function
      rejects is held and counted in `held_by_name` (`:521-522`).
  - `_team_hash(provider, name, source_age_u, gender)` is at `:110-129`.
  - `main(tournaments)` (`:529-593`): window `now ± days` (`:551-553`), the
    `FLIGHTS_MATCHED:<n>:<name>` line (`:566`), and a header-only CSV when the result is empty.
  - **Forfeits are already dropped.** Hawaii writes the mark onto a score (`&nbsp;2<font
    color="red">F</font>` → `2F`) and appends `Forfeited Game` to the forfeiting team's cell, so the
    `isdigit` test at `:437` skips the row. Checked live on four `B14U R1` forfeits, 2026-11-05. The
    survey's guess that forfeits import as played does not hold for this markup.
- **Oregon matcher, `src/models/affinity_or_matcher.py:84-571`:**
  - class attributes `state_code` / `state_name` / `refuse_tied_best` (`:107-111`);
  - hooks `_normalize_provider_name` (`:141`), `_same_club_as_candidate` (`:145`) and
    `_squads_conflict` (`:149`);
  - `_state_for_new_team` (`:153-183`), plus national club-state lookups (`:185-243`);
  - `_fuzzy_match_team`, which filters by `state_code` (`:273-281`) and gates club → variant →
    tier → lane → `_squads_conflict` (`:330-368`);
  - `_match_team`, which creates through `_create_new_affinity_or_team` (`:473-480`) and then
    writes the alias with `self._create_alias` (`:482-492`).
  - The create helper (`:505-571`) strips a leading club from the team name, stores
    `club_name or clean_team_name`, resolves the state via `_state_for_new_team`, and gates the
    insert on `if not self.dry_run` (`:569-570`).
- **Utah matcher, `src/models/affinity_ut_matcher.py`:**
  - `_REGION` is a **module constant**, `("UT","ID","WY","NV","CO","AZ")` (`:47`), read directly by
    `_club_states` (`:149-168`, query `:160`).
  - `_NOT_INITIALS` (`:63-71`) is Utah-tuned: it carries `UT` and lacks `CF`/`IA`/`HSC`/`BVB`.
  - `_squad_key_match` (`:195-239`) runs before the OR fuzzy match (`:187-193`).
  - `_club_for` (`:241-246`) is `_club_before_age` or `_without_coach_initials`.
  - `_squad_marks` / `_squads_conflict` (`:266-280`) treat coach initials and squad numbers as
    marks; a squad number on one side only counts as a conflict.
  - **Read verbatim, it gets Hawaii wrong:**
    - `_club_for("17UB - RUSH East 09/10B")` gives `"17UB - RUSH East"`.
    - `_club_for("18UB - Inter Ohana CF Blanco")` gives the whole name.
    - The create then stores the team name as `09/10B`.
    - The lane reader does not read `I`/`II`/`III`.
- **Date-floor prior art:** `scripts/scrape_playmetrics_league.py:306` (`is_before_min_date`,
  per-league `min_game_date`) and Demosphere's `--since` (`scripts/import_demosphere.py`). Nothing
  in the Affinity engine floors dates today.

### Reusable Utilities

- `scripts/import_athletes2events_event.py`:
  - `respell_ages` (`:541`) rewrites `13UB` → `U13B`. It is opt-in per provider: Oregon must not
    call it.
  - `age_from_name(team_name, division_birth_year, event_season)` (`:552-610`): with no division,
    nothing bounds the name. It returns `None` for two U-ages.
  - `board_cohort` (`:613-622`) gives u10–u19, folds U18 into u19, and returns `None` below u10.
- `src/models/yssl_matcher.py:48`, `roman_to_digits`: `PREMIER II` → `PREMIER 2`, so the shared
  lane reader (`squad_name_gates.extract_lane_number`) can compare squad numbers.
- `scripts/find_squad_key_duplicates.py`: `squad_key` / `cohorts_compatible`, already used by the
  Utah matcher. Its `read_name` reads `17UB` as a U-age.
- `src/utils/us_states.py:27`: `STATE_CODE_TO_NAME["HI"] = "Hawaii"`.
- Test helpers:
  - `tests/unit/test_scrape_affinity_or.py:127-162`: `_schedule_html`, `PLAYED`, `FUTURE_HEADER`,
    `WIDE_WINDOW`.
  - `tests/unit/test_scrape_affinity_ut.py:163-218`: a filter-applying PostgREST double that
    records at `execute()`.

### Convention Anchors

- **Hand-written registries.** Omitting the new provider from any of these stays green:
  - `AUTOCREATING_MATCHERS` and the `(provider, cls, create)` list in
    `tests/unit/test_provider_matcher_dry_run.py` (`:34-47`, `:89-101`). The pipeline checks there
    split source text on a literal `== "affinity_hi"` (`:71-86`).
  - `_SUBCLASS_PATHS` in `tests/unit/test_birth_year_guard_wiring.py:55-68`.
- **Derived checks that fail until updated:**
  - `scripts/team_cleanup/apply_stage.py:203-227` `WRITER_WORKFLOWS`, which must name
    `hi-scraper.yml`.
  - `tests/unit/test_team_cleanup_apply_stage.py` `EXEMPT_SCRIPTS` (`:935-936`), which must name
    `scrape_affinity_hi_tournament.py`, a git-tracked file.
  - The writer-cron hard stop (`apply_stage.py:192-198`): no writer cron between Wednesday's
    propose and Monday 05:00 UTC.
  - `tests/unit/test_agent_doc_references.py:387-399`: a scheduled workflow needs a CLAUDE.md
    workflow-table row, and backticked paths must resolve.
  - `tests/unit/test_age_rollover_freeze_coverage.py` globs workflows and covers the new one once
    its import step carries the gate.
- **Optional registries Utah also joined:**
  - `scripts/find_cross_provider_duplicates.py:96` `SECONDARY_PROVIDERS`;
  - `scripts/full_club_analysis.py:42` `PROVIDER_RULE_CODES`.
- **CLAUDE.md** names Utah at `:403` (provider table), `:682` (workflow table), `:742-761`
  (state-stamping paragraphs) and `:785-792` (the `AGE_ROLLOVER_FREEZE` re-arm list). Also
  `.claude/skills/scraper-patterns/SKILL.md:964`.
- **Layout:**
  - `scripts/scrape_affinity_<st>_tournament.py`
  - `src/models/affinity_<st>_matcher.py`
  - `supabase/migrations/YYYYMMDD120000_seed_affinity_<st>_provider.sql`
  - `.github/workflows/<st>-scraper.yml`
  - output under `data/raw/affinity_<st>/`

### Proposed Alignment

Follow Utah's shape and subclass the Utah matcher. Extend the shared engine only through opt-in
tournament keys, so Oregon and Utah output is unchanged. Hawaii needs four things neither has:
- a gender-first division label;
- a per-team prefix age reader;
- a date floor;
- a Hawaii club-spelling map with Roman-numeral squad numbers.

## Implementation Steps

0. **Work in the existing worktree.** `C:/pitchrank-affinity-hi` is on branch
   `feat/affinity-hi-oahu-league`, cut from `origin/main` cac9226f4, with its upstream unset.
   - Do not work in `C:/PitchRank`. It is a detached HEAD 176 commits behind, with another session's
     uncommitted edits, and it is shared with other sessions.
   - Before editing, `git -C C:/pitchrank-affinity-hi status --porcelain` should list only this plan
     file. If `origin/main` has moved, `git merge origin/main` (never rebase: force-push is blocked).
   - Database scripts there need the main checkout's env:
     `python -m dotenv -f C:\PitchRank\.env run -- python ...`.

1. **Engine: read Hawaii's division labels.** In
   `scripts/scrape_affinity_or_tournament.py` `_extract_age_gender_from_division` (`:172-210`):
   - Add a branch ahead of the word search for the gender-first compact form
     `^([BG])(\d{1,2})(?:-(\d{1,2}))?U\b`, which covers `B12U`, `B14U R1` and `G15-19U`.
   - Return the gender and the **lowest** age. That age only decides which `--age` pass scrapes the
     flight; with step 2 on, every game's board comes from the team names.
   - Every existing Oregon and Utah label must parse exactly as before. Pin that with a test over
     the label samples already in the OR/UT tests.

2. **Engine: per-team age from the name prefix (opt-in `age_from_name_prefix`).**
   - Add `_board_from_name_prefixes(home_name, away_name, flight_gender, season_year)` next to
     `_board_from_team_names` (`:236-257`), lazily importing `age_from_name`, `respell_ages` and
     `board_cohort` from `scripts.import_athletes2events_event` the same way. For each name:
     - Match `^\s*(\d{1,2})U([BG])\s*-\s*`. Allow the dash with no space after it: `12UB -RUSH
       Cinza 14/15B` and `16UB -10/11B Surf…` occur.
     - No prefix means hold.
     - The letter must agree with `flight_gender`; otherwise hold.
     - Birth year = `season_year - age + 1`. Board = `board_cohort(birth_year, season_year)`; a
       `None` board (U9 and younger) means hold.
     - **Veto:** run `age_from_name(respell_ages(rest), None, season_year)` on the rest of the name.
       If it yields a birth year whose board differs from the prefix's, hold. A `None` result (two
       U-ages, nothing readable) is no veto, so both Albion two-age names use their prefix as the
       owner decided.
   - Return `(birth_year, age_group)` when both names land on the same board, else `None`.
   - Wire it into `scrape_flight_games` as an `elif tournament.get("age_from_name_prefix")` beside
     the `age_from_team_name` branch (`:458-463`), reusing `held_by_name` and its printed count.
   - The CSV keeps the raw team name, prefix included. Some stored GotSport Hawaii teams carry the
     identical name, e.g. `10UB - HSC Bulls 16/17B - I`.

3. **Engine: an opt-in date floor (`min_game_date`).**
   - In `scrape_flight_games`, skip any date header before the tournament's `min_game_date`,
     alongside the window check at `:399`. Compare dates, not datetimes.
   - Print the floor in `main`'s window line when it is set.
   - Oregon and Utah set no floor and behave as before.

4. **Wrapper: `scripts/scrape_affinity_hi_tournament.py`.** Mirror
   `scripts/scrape_affinity_ut_tournament.py` (docstring, `from scripts.scrape_affinity_or_tournament
   import main`, `main(TOURNAMENTS)`). The single entry:
   - `name: "2026/27 Oahu League Season"`
   - `tournament_guid: "B52D16EC-4B82-4251-AD18-8E5C35567EC2"`
   - `base_url: "https://ol-fall-26-27.sportsaffinity.com"`
   - `provider: "affinity_hi"`, `state: "Hawaii"`, `state_code: "HI"`
   - `season_year: 2026`, `age_from_name_prefix: True`, `min_game_date: "2026-08-01"`

   The docstring should say why each key is set, and that `B09U`/`G09U` are never scraped (the
   workflow's ages loop starts at 10).

5. **Make two Utah internals overridable, keeping Utah's behaviour unchanged.** In
   `src/models/affinity_ut_matcher.py`:
   - Add a class attribute `region = _REGION` and have `_club_states` (`:160`) read `self.region`.
   - Have `_squad_marks` (`:266-273`) call a method `self._is_initials(token)`, which defaults to the
     module `_is_coach_initials`, so a subclass can supply its own not-initials set.
   - The existing Utah tests must stay green unchanged.

6. **Matcher: `src/models/affinity_hi_matcher.py`, `AffinityHIGameMatcher(AffinityUTGameMatcher)`.**
   - Class attributes: `state_code = "HI"`, `state_name = "Hawaii"`, `region = ("HI",)`,
     `refuse_tied_best = True`.
   - **Club spellings.** A module `_HI_CLUBS` maps each written spelling to the stored club name.
     Each pairing is evidenced by stored HI rows (2026-11-05):

     | Written | Stored |
     |---|---|
     | `HSC Bulls` | `Honolulu Bulls Soccer Club` |
     | `RUSH` | `Hawaii Rush` |
     | `Surf Hawaii` | `Hawaii Surf Soccer Club` |
     | `Leahi Na Koa`, `Leahi` | `Leahi Soccer Club` |
     | `BVB IA Hawaii` | `BVB International Academy Hawaii` |
     | `808 FC`, `808FC` | `808 Futbol Club` |
     | `Universal SC` | `Universal Soccer League` |
     | `ALBION SC Hawaii`, `FC Hawaii`, `Inter Ohana CF`, `Hawaii United FC` | themselves |

     Longest spelling first, matched case-insensitively on word boundaries anywhere after the prefix
     (`13/14B Surf Hawaii Academy II` puts the club after the band).
   - **`_club_for`:** strip the prefix, then take the first `_HI_CLUBS` hit. Otherwise use Utah's
     `_club_before_age` on the stripped name, then `_without_coach_initials`. Clubs with no stored
     rows (`Ballistic`, `Hoomau`, `Ka oi SC`, `Ke Ahi O Pele FC`, `Arsenal FC`, `Inter Hawaii`)
     keep their written form. Returning the stored club means the OR create helper (`:540-546`)
     never strips the name, so a new team stores its full provider name.
   - **`_normalize_provider_name`:**
     - drop the prefix;
     - write Roman squad numbers as digits with `yssl_matcher.roman_to_digits`, so `- II` reads as
       squad 2 and `Academy I` as squad 1;
     - then apply Utah's normalizer.
   - **`_is_initials`:** Hawaii's not-initials set is Utah's less `UT`, plus `HI`, `CF`, `IA`, `BVB`,
     `HSC`, `RUSH` and `ALBION`. `HNL` and `WND` (Albion's Honolulu and Windward branches) stay
     readable as marks, so `HNL` against `WND` is two squads.
   - **`_squad_marks`:** exclude the words of both the written spelling and the stored club. Copy
     the Athletes2Events rule: stripping only one side leaves club words that read as squad marks.
     Squad numbers then come from the Roman-converted text. Utah's one-sided rule makes `Academy`
     against `Academy I` two squads.
   - **Inherited unchanged:** `_create_new_affinity_or_team`, `_match_team` (the alias write),
     `_state_for_new_team` (now limited to HI, falling back to HI), and `_squad_key_match`.

7. **Pipeline branch.** In `src/etl/enhanced_pipeline.py`, add an `affinity_hi` branch after
   `affinity_ut` (`:322-326`): lazy import, then `AffinityHIGameMatcher(..., dry_run=self.dry_run)`.

8. **Migration: `supabase/migrations/20261105120000_seed_affinity_hi_provider.sql`.**
   - Mirror the Utah seed: `INSERT INTO providers (code, name, base_url) VALUES ('affinity_hi',
     'Affinity Sports HI', 'https://hysa.sportsaffinity.com') ON CONFLICT (code) DO NOTHING`, with a
     header comment.
   - The owner hand-applies it, then runs `supabase migration repair --status applied
     20261105120000`.

9. **Workflow: `.github/workflows/hi-scraper.yml`.** Copy `ut-scraper.yml`.
   - **Change:**
     - name `Affinity HI Scraper`;
     - one cron, `30 9 * * 1` (Sunday 23:30 HST; Hawaii has no DST);
     - **remove the schedule-guard step** and every `steps.guard.outputs.should_run` condition and
       reference, including the report step's `SHOULD_RUN` branch;
     - output dir `data/raw/affinity_hi`, file prefix `affinity_hi_`;
     - script `scripts/scrape_affinity_hi_tournament.py`;
     - import provider `affinity_hi`.
   - **Preserve from the Utah file:**
     - dispatch inputs `days_back` (7), `days_forward` (30) and `dry_run`;
     - `AGE_ROLLOVER_FREEZE: 'false'` with its comment;
     - the ages `10..19` × male/female loop;
     - the merge step;
     - the per-tournament `FLIGHTS_MATCHED` stale-GUID check;
     - artifact upload;
     - the import step's `--batch-size 500` and its `env.AGE_ROLLOVER_FREEZE == 'false'` gate;
     - the secrets block;
     - `timeout-minutes`.

10. **Registries.**
    - `AffinityHIGameMatcher` joins `AUTOCREATING_MATCHERS` and the `(provider, cls, create)` list
      (`"_create_new_affinity_or_team"`) in `tests/unit/test_provider_matcher_dry_run.py`, and
      `_SUBCLASS_PATHS` in `tests/unit/test_birth_year_guard_wiring.py`.
    - `hi-scraper.yml` joins `WRITER_WORKFLOWS` in `scripts/team_cleanup/apply_stage.py`.
    - `scrape_affinity_hi_tournament.py` joins `EXEMPT_SCRIPTS` in
      `tests/unit/test_team_cleanup_apply_stage.py`, with Utah's reason text. Add a cron pin beside
      Utah's (`:1018`).
    - `affinity_hi` joins `SECONDARY_PROVIDERS` (`scripts/find_cross_provider_duplicates.py`) and
      `PROVIDER_RULE_CODES` (`scripts/full_club_analysis.py`), as Utah did. No Hawaii club overrides.

11. **Tests.**
    - **`tests/unit/test_scrape_affinity_hi.py`**, built on `_schedule_html` from the OR tests:
      - Hawaii division labels, including `G15-19U` → (Female, 15) and `B14U R1` → (Male, 14).
      - Every OR/UT sample label is unchanged.
      - The prefix reader:
        - `12UB -RUSH Cinza 14/15B` → u12;
        - `17UB - 10B Surf Hawaii Academy I` → u17;
        - `18UB` and `19UB` both → u19;
        - the two-U-age Albion name uses its prefix;
        - a `09UG` team is held;
        - a gender letter disagreeing with the flight is held;
        - a name whose later age disagrees with its prefix is held;
        - `17UB` against `18UB` is held and counted.
      - A forfeit row (`2F` score, `Forfeited Game` cell) imports nothing.
      - `min_game_date` drops a July date header and keeps Aug 1.
      - The wrapper's `TOURNAMENTS` keys are literal values. Assert literals, not module constants
        read back.
    - **`tests/unit/test_affinity_hi_matcher.py`**, using the filter-applying double from
      `test_scrape_affinity_ut.py:163-218`, with `.single()` raising `PGRST116` on zero rows as in
      `tests/unit/test_athletes2events_matcher.py`:
      - `_club_for` for each `_HI_CLUBS` spelling and one unmapped club;
      - `HSC Bulls 16/17B - I` against `- II`, `Academy` against `Academy I`, and `HNL` against
        `WND` each conflict, while identical names link;
      - club-state lookups query HI only;
      - a new team is created with `state_code` HI and its full provider name;
      - `dry_run=True` inserts nothing.

12. **Docs.**
    - CLAUDE.md:
      - provider table (`:401-403`): an `Affinity HI` / `affinity_hi` row;
      - workflow table (`:680-682`): `hi-scraper.yml`, Mon 9:30 AM UTC;
      - the state-stamping paragraphs (`:742-761`): Hawaii stamps HI on creation, resolved from the
        club's HI rows and falling back to HI. Correct the off-by-one `:154` / `:553` anchors in the
        same paragraph;
      - the `AGE_ROLLOVER_FREEZE` re-arm list (`:785-792`): add `hi-scraper.yml` and update the count.
    - `.claude/skills/scraper-patterns/SKILL.md:964`: name Hawaii beside Utah.
    - This plan: `status: done` and an "As built" section before the commit.

## Verification

- **CI gate, run the way CI runs it:**
  `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py` and
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`. Both must exit 0.
- **Mutation checks** on the new guards. Revert each half on its own and confirm a *new* test is
  among the failures:
  - the prefix gender check;
  - the veto;
  - the board-equality hold;
  - the date floor;
  - the Roman-numeral conversion;
  - the HI region.
- **Live scrape** of every age and gender with `--days-back 90`, writing CSVs to a scratch dir.
  Expect:
  - every flight but `B09U`/`G09U`/the empty `R2` divisions matched;
  - about 745 games filed and about 26 held (17U against 18U/19U in `B19U`);
  - no game dated before 2026-08-15;
  - no forfeit row;
  - a non-zero `FLIGHTS_MATCHED` sum.
- **Matcher dry run against production**, with every database write blocked and recorded: all
  distinct teams in that CSV through `AffinityHIGameMatcher(dry_run=True)` with a provider id that
  has no aliases.
  - Report linked, created and refused counts.
  - Confirm zero attempted writes and no candidate or new team outside HI.
  - Read every link by hand. Squads differing only by I/II/III, HNL/WND or a colour must never
    share a stored team.
- **After the owner applies the migration:**
  - `python scripts/import_games_enhanced.py <csv> affinity_hi --dry-run` against production. Then
    confirm by query that no `affinity_hi` game, team or alias exists.
  - After the real catch-up (workflow dispatch, `days_back` 90): count stored `affinity_hi` games
    since 2026-08-01 against the scraped count, and confirm every team the run created carries
    `state_code` HI.

## Known gaps

- **26 games are held**: 17 in `G15-19U` and 9 in `B19U`, each between teams on two different
  boards. The importer looks both teams up at one age group, so the team on the other board would
  miss its stored row and be created as a duplicate on the wrong board. The Georgia change matches
  each team at its own label, which lifts this hold and brings these 26 in.
- **Some clubs have no stored rows** (`Ka oi SC`, `Ke Ahi O Pele FC`, `Inter Hawaii`). Their teams
  will mostly be created new.
- **A real import adds a pending review row for each team it creates** (read from the code; the
  guarded run's fresh provider id stopped at the provider lookup, so it did not observe them).
  Oregon and Utah inherit the same path; Utah has 674 such rows pending.
- **Uncertain matches become new teams.** As in Oregon and Utah, a review-range fuzzy match creates
  a team rather than a review item.

## Context Files

- `.turbo/plans/affinity-ut-uysa-provider.md`: the change this mirrors.
- `scripts/scrape_affinity_or_tournament.py`: the shared engine (steps 1–3).
- `scripts/scrape_affinity_ut_tournament.py`: the wrapper to mirror.
- `src/models/affinity_ut_matcher.py` and `src/models/affinity_or_matcher.py`: the matcher chain
  (steps 5–6).
- `scripts/import_athletes2events_event.py:537-622`: `respell_ages`, `age_from_name`,
  `board_cohort`.
- `src/models/yssl_matcher.py:44-50`: `roman_to_digits`.
- `.github/workflows/ut-scraper.yml`: the workflow to copy.
- `tests/unit/test_scrape_affinity_ut.py` and `tests/unit/test_provider_matcher_dry_run.py`: test
  patterns and the registries.
- `.claude/skills/scraper-patterns/SKILL.md` § Provider Matcher Name Parsing: the matcher gate
  rules.
