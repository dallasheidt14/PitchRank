---
status: done
---

# Plan: One cohort and gender label reader for the seeding tools

## Context

The MatchBalance seeding tools read a division's age group and gender from its label in two places. Each place has its own grammar, and both get common labels wrong. The 2026-09-23 audit confirmed three defects:

- **C5, the paste box.** `roster_paste.py` recognises a heading only when it has a full gender word and a U-age. These all fail to read: "Boys 2012", "B2013", "BU14", "U14B", "Under 15", "Coed U14" and tab-padded "Female U14\t\t". The rows below an unread heading silently keep the previous section's cohort. "Boys/Girls U13" is filed Male.
- **C10, the event walker, bands.** `gotsport_event_roster.py` reads a two-year band ("B2013/2014", "B13/14", "2014-2015 Girls", "G2015/2016") as two cohorts and assigns none. The repo's band rule, a band named by its younger year, is already implemented in `team_utils` and used by the TGS and PlayMetrics parsers. Because U9 bands and "U8/U9" labels read as nothing, they are not filtered out. Their team pages are bought, and they count as the probe's "U10+" samples.
- **C11, the event walker, gender.** A gender letter standing apart from the age ("U13 B D1", "U13 G") reads blank. Glued "U14M" / "U12F" lose both age and gender. A bracket token ("U13 Gold B2") is taken as a birth year and sets the gender to Male.

The owner scoped the fix on 2026-09-24:

- It covers the seeding tools only, and both MatchBalance tabs (Seeding and Backtest), because they share the walker.
- `src/scrapers/gotsport.py` `_parse_division_gender` feeds the scheduled imports and stays unchanged. Moving it onto the shared reader goes to the backlog.
- A standing rule applies: the director's roster heading decides a team's cohort, with no age-eligibility check.

The intended outcome is one reader both tools call, which:

- reads every label above correctly;
- withholds rather than guesses when a label names two ages or two genders;
- sends a row whose cohort it cannot read to cohort review instead of the previous section.

## Pattern Survey

### Analogous Features

- **The paste parser.**
  - `src/tournaments/roster_paste.py:31-38` defines `_GENDER_WORDS`, and `:40` defines `_HEADING_GENDER`, which accepts words only: no letters, no "coed".
  - `:80-87` `_parse_heading` needs a gender word plus `published_u_ages(line)`.
    - `.search` takes the first gender, so "Boys/Girls U13" returns Male.
    - A mixed-age heading returns `age=""` and stores the line as `listed_division` (`:126`).
    - It normalises through `seeding_optimizer.normalize_age_group`, which keeps `u9` literally. `test_seeding_assessment.py:27` relies on that.
  - `:118-134`: heading detection runs only on tabless lines (`:122`).
    - A tabless non-heading line becomes a row with `intake_issue="Confirm this line is a team, or exclude it."` (`:130-131`).
    - The carried `age_group`/`gender` is never reset.
- **The event walker.**
  - `src/tournaments/gotsport_event_roster.py:114-121` defines `_AGE_RUN`, which allows only a lead or tail `[BG]` letter. `:127-135` duplicates the gender word map and adds `_GENDER_LETTERS` (B, G).
  - `:308-329` `resolve_cohort` withholds anything outside `AGE_GROUPS`.
    - `:349-360` `_named_cohort`: U-age runs win over birth-year runs.
    - `:370-404` `_read_run`: `:380` handles birth years of 1990 or later, `:382` the compact `14B` form (where "B2" also matches), and `:393` U-ages through `normalize_age`.
    - `:407-422` `_birth_year_cohorts` maps each year separately, so a band counts as two cohorts.
  - `:454-462` `_gender_of` / `_genders_named` return a gender only when exactly one is named.
  - `:555-565` `names_no_gender`.
  - `:568-586` `parse_header_gender`, the page header fallback.
  - `:1672-1677` is the per-division use of those two.
  - `:332-346` `names_cohort_outside` separates "unwanted" from "unreadable". It depends on `_named_cohort` returning out-of-board literals.
  - `:1716-1762` `_read_until_wanted_limit` (the probe) and `:1765-1793` `_wanted_divisions` (team pages) drop only a division naming exactly one unwanted cohort. "U8/U9" and a U9 band are therefore kept and paid for.
- **Reference grammars (read-only).**
  - `scripts/scrape_tgs_event.py:167-201` `extract_age_group` checks, in order: a U-age, then a band via `extract_band_birth_year` → `calculate_age_group_from_band`, then single years that must all agree. It passes an explicit season.
  - `scripts/scrape_playmetrics_league.py:259-292` `derive_team_age_group` follows the same shape.
  - `src/scrapers/gotsport.py:1070-1114` `_parse_division_gender` checks the gender word first, then a B/G/M/F letter glued to or standing beside the age. It is the spec for the letter rule and stays untouched.

### Reusable Utilities

- **`src/utils/team_utils.py`.**
  - `:92` `extract_band_birth_year(name, current_year=None)` returns the younger year of exactly one two-year band. It already allows a B/G/M/F letter glued to either side, and refuses "U13/14" and "13/14U". It handles only `/`, `-` and `–`, so fold dashes before calling it.
  - `:120` `calculate_age_group_from_band(younger, current_year=None)` returns "U7".."U17" or "U19", uppercase.
  - `:134` `calculate_age_group_from_birth_year(birth_year, current_year=CURRENT_YEAR)` binds its default at import time, so pass the season explicitly.
- **`src/scrapers/_age_normalization.py:20`** `normalize_age(int)` returns `u6`..`u19`, folding U18 into U19.
- **`src/tournaments/gotsport_event_roster.py:425-447`** `_ascii_dashes` folds every Unicode dash.
- **`config/settings.py:94-95`** `AGE_GROUPS` is the board set. `tournament_intake.py:3606` wraps it as `_RANKED_COHORTS`.

### Convention Anchors

- **Dependency direction.** `roster_paste` imports `gotsport_event_roster`, and `seeding_assessment` imports both. A reader shared by both must sit below the walker, in a pure-parsing module. The precedent is `src/tournaments/gotsport_event_structure.py`, whose docstring reads "Pure parsing: no HTTP, no Supabase, no Streamlit".
- **How rows reach cohort review.**
  - `seeding_assessment.py:139-140` sends a row to `cohort_review` when it has no age number, a gender other than Male/Female, or any `intake_issue`.
  - `:39-40` `package_roster` drops ages 1-9 but keeps a row with no age.
- **Test pins.**
  - `tests/unit/test_gotsport_event_roster.py:263-322` `TestResolveCohort`. `:306-307` pins "B2017/18" and "G2015/2016" as withheld, which is the C10 defect.
  - `:63-103` `CAPTURED_LABEL_COHORTS` and `:112-154` `CAPTURED_PAGE_COHORTS` are real-page corpora with every answer pinned.
  - `:1928-1963` `TestNamesCohortOutside`, plus the probe and skip tests at `:1965-2115`.
  - `tests/unit/test_roster_paste.py` covers heading carry-down, the U18 fold, the row before any heading, and the flagged tabless line.
  - `tests/unit/test_extract_band_birth_year.py:19-22` pins the season with an autouse monkeypatch. The walker's tests pin no season.

### Proposed Alignment

- Follow the TGS/PlayMetrics reading order and the walker's withhold-rather-than-guess stance.
- Put the reader in one pure module below the walker.
- Take the gender-letter rule from `gotsport.py` as a spec only.
- Keep the out-of-board literal distinct from "unreadable".

## Implementation Steps

Work in worktree `C:/pitchrank-seeding-labels`, on branch `fix/seeding-cohort-labels`, created from `origin/main` at `e5cb92b46`. Before editing, confirm that `git -C C:/pitchrank-seeding-labels status --short` shows only this plan file. If anything else is modified, another writer is using the tree: stop.

1. **Add the shared reader `src/tournaments/cohort_labels.py`.** It is pure parsing (stdlib and `src.utils.team_utils` / `src.scrapers._age_normalization` only), and it must not import `gotsport_event_roster`.
   - `read_label(label: str, *, season: int | None = None) -> LabelReading`, a frozen dataclass with these fields:
     - `cohorts: frozenset[str]`: every cohort the label names, as `uNN` literals, including off-board ones such as `u9` and `u20`.
     - `genders: frozenset[str]`: a subset of {"Male", "Female"}. "Coed" and "mixed" add both.
     - `cohort: str | None`: the single cohort when exactly one is named, else None.
     - `gender: str | None`: the single gender when exactly one is named, else None.
     - `season` defaults to `team_utils._soccer_season_year()` and is passed explicitly to every `team_utils` call.
   - **Reading order** (TGS/PlayMetrics shape). First fold every dash with the same rule as `_ascii_dashes`, moved into this module and re-imported by the walker so there is one copy. Then collapse whitespace and strip tabs.
     1. **U-ages.** Accept "U14", "u 14", "14U", "Under 15" and glued letters: "BU14", "GU12", "U14B", "U14G", "U14M", "U12F". Also accept a B/G/M/F letter standing alone as the next token after an age ("U13 B", "13U B Gold"). A U-age run that names two ages ("U15/16", "13/14U", "U13-U19") names both. Fold U18 into U19 through `normalize_age`.
     2. **A two-year birth-year band.** Use `extract_band_birth_year(label, current_year=season)` → `calculate_age_group_from_band(..., current_year=season).lower()`. This covers "B2013/2014", "B13/14", "2014/2015 Boys", "2014-2015 Girls" and "G2015/2016". A band's glued letter (B/G/M/F) adds its gender.
     3. **Single birth years**, only when steps 1 and 2 named nothing:
        - four-digit years from 1990 on;
        - the compact two-digit forms "14B", "B13" and "G12", which need **two** digits, so "B2" and "G1" are not years.
        - Map each through `calculate_age_group_from_birth_year(year, current_year=season)`, lowercased. A glued letter adds its gender.
     4. **Gender words.** male/males, female/females, boy/boys, girl/girls, men/women, coed/co-ed/mixed. Take them from the walker's current map at `gotsport_event_roster.py:127-135`, which already matches `roster_paste.py:31-38`, and give one copy to both.
   - Letters count as gender only in the positions above: glued to an age or band, standing after an age, or prefixing a birth year. A letter anywhere else, such as a bracket "B2" or a division "Gold B", is not a gender.
2. **Move the walker onto the reader.** In `src/tournaments/gotsport_event_roster.py`, keep these public names and signatures, because callers and tests import them: `resolve_cohort`, `names_cohort_outside`, `names_no_gender`, `parse_header_gender`, `published_u_ages`.
   - `resolve_cohort(label)` returns `(reading.cohort, reading.gender)`, and still withholds a cohort not in `AGE_GROUPS` (returns None for it).
   - `names_cohort_outside(label, wanted)` becomes True when `reading.cohorts` is non-empty and **every** named cohort is outside `wanted`. That makes "U8/U9", "B2017/2018" (U9) and "GU6-GU7" unwanted. "U9/U10" and "U13-U19" stay wanted, because they name a boarded cohort.
     - Check this against the existing pins in `TestNamesCohortOutside` (`:1928-1963`), which pin "U13-14 Boys" and "U18/U19/20" as "will not judge".
     - Both name boarded cohorts, so they stay wanted. Keep those pins.
   - `names_no_gender(label)` becomes `not reading.genders`. Keep the "names none" vs "names several" distinction: a two-gender label is **not** "no gender", so the header fallback does not override it.
   - Delete `_AGE_RUN`, `_read_run`, `_birth_year_cohorts`, `_named_cohort`, `_gender_of`, `_genders_named` and the duplicate `_GENDER_WORDS` / `_GENDER_LETTERS` once nothing references them.
     - `git grep` each name first.
     - `published_u_ages` (`:1002-1019`) still uses `_AGE_RUN`. Move its U-age tokenising onto the reader's U-age step, and keep its return type and `expand_ranges` behaviour.
     - Its callers are `roster_paste.py:82`, `seeding_assessment.py:50` and the Backtest helpers at `:1022-1071`, and their tests must pass unchanged.
   - `_historical_lookup_age` (`:1074-1086`) calls `_read_run`. Point it at `read_label(...).cohort`.
3. **Move the paste parser onto the reader.** In `src/tournaments/roster_paste.py`:
   - **Strip trailing tabs and whitespace first.** Take `line.rstrip()` before the tab test at `:122`, so "Female U14\t\t" is tabless.
   - **What counts as a heading.** A tabless line is a heading when `read_label` names at least one cohort or at least one gender, **and** every remaining word is one of these:
     - a small filler set: "division", "div", "bracket", "group", "flight", "age", "and", "&", "the";
     - a bare number;
     - a known tier word (Gold, Silver, Bronze, Premier, Elite, Select, Classic, Red, White, Blue, Black).
     - The tier words keep lines like "U14 Boys Gold" as headings.
     - Any other word, such as a club name, makes the line a team line, which is today's `intake_issue` row. A one-column team line such as "Tyler FC Boys U14" is therefore never swallowed as a heading.
   - **A heading replaces both carried fields, even when one is unreadable.**
     - `age_group` becomes `reading.cohort`, or `""` when the heading names none or several.
     - `gender` becomes `reading.gender`, or `""` when it names none or both.
     - Rows below "Boys/Girls U13" or "Coed U14" therefore carry `u13`/`u14` and a blank gender, and reach cohort review through `seeding_assessment.py:139-140`.
     - A heading naming two ages keeps today's behaviour: `age=""` with the line as `listed_division`.
   - Keep `u9` and other off-board literals exactly as today. `package_roster` excludes ages 1-9 by reading them.
   - Delete `_GENDER_WORDS` / `_HEADING_GENDER` here once unused.
4. **Fix the tests that pin the old behaviour, and add a single season pin.**
   - In `tests/unit/test_gotsport_event_roster.py` `:306-307`, move "B2017/18" and "G2015/2016" out of the withheld parametrization. Pin them as literals: "B2017/18" is `(None, "Male")` and "unwanted" (it names U9), and "G2015/2016" is `("u11", "Female")`. Checked against the label key in CLAUDE.md: the band's younger year is 2018 → U9, and 2016 → U11.
   - Pin the season to 2026 for every new test, and for the corpus tests at `:325-374`, with an autouse fixture that passes the season or monkeypatches `team_utils._soccer_season_year`, mirroring `test_extract_band_birth_year.py:19-22`.
     - Re-run the corpora. If an answer changes, check that label by hand against CLAUDE.md's table before re-pinning it, and list each changed label in the PR.

## As built (2026-09-24)

The code departs from the steps above as follows. Read this section, not those steps, for what the code does; line numbers in the survey and Context Files are from `e5cb92b46`, before the change.

- **The grammar lives in the reader.** `src/tournaments/cohort_labels.py` owns the age-run pattern, dash folding, accent composition and the gender words. `published_u_ages` imports `AGE_RUN`, `RUN_NUMBER` and `normalize_label`; `_published_age` and `_historical_lookup_age` call `read_label`.
- **Readings return `""`, not None,** for a cohort or gender that is withheld, from `LabelReading.cohort` / `.gender` and from `resolve_cohort`. That matches every existing caller.
- **Two tiers, not three.** U-ages win; otherwise every birth year counts, a band counting as its younger year. A pair too young to be a band (`2025-2026`) names no cohort.
- **Gender letters.**
  - A letter counts only on a run that reads as an age, and a compact year needs two digits, so a bracket such as "B2" names nothing.
  - A letter standing after a U-age is a gender only when no word or glued letter names one, and it is not firm: the page header overrides it, and a header naming both genders withholds.
  - Two letters (`B/G`, standing or glued) name both genders firmly.
- **Paste headings (owner decision, 2026-09-24): age and gender, one extra word at most.**
  - The extra word is allowed only when the age is a U-age and the gender is a word ("Girls U9/U10 Mexico", "U14 Boys Gold"). Every other shape takes none, so "Solar 14G", "Arsenal 2013 Girls" and "Barca U13 B" stay team rows.
  - Numbers and filler words ("division", "group", "flight" and similar) never count.
  - A heading naming several cohorts keeps its label for the operator, and `could_belong` bounds its rows by those cohorts, read as years when the heading names no U-age.
- **Backtest published age** reads years through `read_label`: flight tokens ("F1", "M2") are not years, a band gives its younger year, and the literal off-board age (`u21`) is still produced.

## Verification

- **New `tests/unit/test_cohort_labels.py`.** Parametrize literal label → literal `(cohort, gender)` pairs at season 2026:
  - "U14 Boys" → `(u14, Male)`
  - "BU14" → `(u14, Male)`
  - "U14B" → `(u14, Male)`
  - "U14M" → `(u14, Male)`
  - "U12F" → `(u12, Female)`
  - "U13 B D1" → `(u13, Male)`
  - "U13 G" → `(u13, Female)`
  - "13U B Gold" → `(u13, Male)`
  - "U 15 Boys" → `(u15, Male)`
  - "Under 15 Girls" → `(u15, Female)`
  - "B2013/2014" → `(u13, Male)`
  - "B13/14" → `(u13, Male)`
  - "2014/2015 Boys" → `(u12, Male)`
  - "2014-2015 Girls" → `(u12, Female)`
  - "G2015/2016" → `(u11, Female)`
  - "B2013" → `(u14, Male)`
  - "14B" → `(u13, Male)`
  - "Boys 2012" → `(u15, Male)`
  - "U13 Gold B2" → `(u13, None)`, where "B2" is not a year and not a gender
  - "Boys/Girls U13" → `(u13, None)` with both genders named
  - "Coed U14" → `(u14, None)`
  - "U15/16" → `(None, …)` with cohorts {u15, u16}
  - "U18" → `(u19, …)`
  - "U8/U9" → cohorts {u8, u9}
  - Every expected value is a literal. None is computed from the helper under test.
- **`tests/unit/test_roster_paste.py`.** One test per C5 heading form checks that the rows below it carry the read cohort and gender:
  - "Boys 2012", "B2013", "BU14", "U14B", "Under 15 Boys" and tab-padded "Female U14\t\t".
  - "Boys/Girls U13" gives blank gender and reaches cohort review.
  - "Coed U14" gives blank gender.
  - "Tyler FC Boys U14" stays a flagged team row and does not change the carried cohort.
  - A heading naming no cohort and no gender is not a heading.
- **`tests/unit/test_gotsport_event_roster.py`.**
  - The re-pinned band cases.
  - C11 cases through `resolve_cohort`.
  - A probe over an event whose first two divisions are "B2017/2018" and "U8/U9" does not count them. Assert `divisions_walked` and that neither division's team pages were fetched.
  - `_wanted_divisions` drops them.
  - "U9/U10" is still kept.
- Mutate each rule on its own and check that a named new test fails:
  - the glued-letter U-age
  - the standing letter after an age
  - the band step
  - the two-digit compact-year rule
  - "every cohort unwanted"
  - the paste heading shape test
  - the carried-cohort reset
  - the exactly-one-gender rule
- The full CI gate passes.
- In a browser smoke run of a scratch copy of the app, paste a list using "Boys 2012", "BU14" and "Boys/Girls U13" headings. The preview's Age/Gender columns should show u15/Male, u14/Male, and u13 with blank gender.

## Context Files

- `src/tournaments/gotsport_event_roster.py`: `resolve_cohort` through `_genders_named` (`:308-462`), `names_no_gender`/`parse_header_gender` (`:555-586`), `published_u_ages` (`:1002-1086`), and the probe/team-page filters (`:1716-1793`).
- `src/tournaments/roster_paste.py`: the whole file, which is short.
- `src/utils/team_utils.py:70-150`: the band and birth-year helpers.
- `src/tournaments/seeding_assessment.py:29-53,139-140`: how rows reach cohort review and how `u9` is excluded.
- `scripts/scrape_tgs_event.py:167-201`: the reading order to mirror.
- `src/scrapers/gotsport.py:1070-1114`: the gender-letter spec (read only).
- `tests/unit/test_gotsport_event_roster.py:63-154,263-374,1928-2115` and `tests/unit/test_roster_paste.py`: the existing pins.
