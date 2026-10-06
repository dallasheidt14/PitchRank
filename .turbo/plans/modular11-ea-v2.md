# Modular11 EA v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EA matching trustworthy enough to import from. This means season-keyed EA ids, a
pre-match cleanup that feeds the merge and state skills, and a branch-safe matcher that uses
region states and schedules.

**Architecture:**
- A small `src/models/modular11_ea_keys.py` owns the season key and the region→state table.
- The step-1 matcher (`scripts/match_modular11_ea_teams.py`) gains the new rules as pure
  functions, plus one database read for schedule evidence.
- A new `scripts/prepare_modular11_ea_cleanup.py` builds the candidate pool and writes the
  inputs the merge and state skills take.
- The step-2 linker and builder switch to season keys.
- A one-off migration re-keys the U17 rows already in production.

**Tech Stack:** Python 3.11, supabase-py, pytest.

**Spec:** `.turbo/specs/modular11-ea-v2.md` (earlier: `modular11-ea-scraper.md`,
`modular11-ea-import.md`).

## Global Constraints

- Season key format: `f"{uid}:{season_start_year}"`, e.g. `3432:2026`. Build it only through
  `ea_key()`.
- Season start year: `today.year if today.month >= 8 else today.year - 1`. Reuse
  `scripts.scrape_modular11_ea.season_bounds` logic; do not re-derive it inline.
- Game rows are never updated except `is_excluded`. Migrations touch `team_alias_map` and `teams`
  only.
- Every writing script defaults to a dry run, takes `--execute`, logs every write, and offers
  `--undo LOG`.
- MLS NEXT (`modular11`) code, rows and workflows are untouched.
- The merge and state skills are called, not changed. Every merge and every state write goes
  through them with their gates.
- Lint: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`. Tests:
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`. Never run whole-file
  `ruff format`; hand-apply `ruff format --diff`.

## Review Focus

1. **A season key going through the real importer.** `import_games_enhanced.stream_games_csv`
   wraps id and score conversion in one `try`, so a non-numeric id skips the score conversion. A
   `3432:2026` row must still import with integer scores and no failure. Pinned in Task 2 by
   driving `stream_games_csv` on a real CSV.
2. **A re-run of the migration.** It must find nothing left to change and must not double-suffix
   `3432:2026:2026`. Pinned in Task 2.
3. **Branch words that are also generic words.** "Surf" is a club word in "LA Surf SC" but a
   branch in "Santa Monica Surf"; "Academy" is generic. The branch rule must use the
   difference between names, never a blacklist of single words. Pinned in Task 3 with the real
   pairs.
4. **A candidate with no state.** It must never be confident, and its reason string must say
   "no state". Pinned in Task 4.
5. **A region missing from the table.** A new EA region that appears on the page must fail the
   matcher run loudly, never pass every state. Pinned in Task 1.

## Branch

Continue on `feat/ea-scraper` in `C:\pitchrank-ea-scraper`. Merge `origin/main` before Task 1
(`git fetch && git merge origin/main`; never rebase).

---

### Task 1: Season key and region→state table

**Files:**
- Create: `src/models/modular11_ea_keys.py`
- Create: `config/modular11_ea_regions.json`
- Test: `tests/unit/test_modular11_ea_keys.py`

**Interfaces:**
- Produces:
  - `ea_key(uid: str, season: int) -> str`
  - `split_ea_key(key: str) -> tuple[str, int]`, which raises `ValueError` on a key without a
    season
  - `season_start_year(today: date) -> int`
  - `REGION_STATES: dict[str, frozenset[str]]`, loaded from the JSON
  - `allowed_states(regions: Iterable[str]) -> frozenset[str]`, which raises
    `UnknownRegionError(KeyError)` for an unmapped region

- [ ] **Step 1: Draft the table from the data, then STOP for the owner.** Write a read-only
  scratch script that, for each of the 19 regions in
  `tests/fixtures/modular11_ea/ea_page.html` (Florida, LA North, LA South, Mid-America, Nor Cal,
  North, Northeast (East), Northeast (West), Oregon, PACNW, SD / OC / IE, South, Southeast,
  Southwest, Southwest (North), Southwest (South), Southwest Desert, Southwest EA, Texas), lists
  the `state_code` values of PitchRank teams already linked through `modular11_ea` aliases whose
  EA team plays in that region. Use `data/modular11_ea/u17/teams.csv` for regions. Write the
  draft JSON (`{"Florida": ["FL"], ...}`), adding obvious neighbours by hand and marking anything
  guessed. Send the table to the owner in plain English and wait for corrections. **Do not continue
  past Step 1 until the owner has answered.**

- [ ] **Step 2: Failing tests**

```python
from datetime import date

import pytest

from src.models.modular11_ea_keys import (
    REGION_STATES, UnknownRegionError, allowed_states, ea_key, season_start_year, split_ea_key,
)


def test_key_round_trip():
    assert ea_key("3432", 2026) == "3432:2026"
    assert split_ea_key("3432:2026") == ("3432", 2026)


def test_unkeyed_id_is_refused():
    with pytest.raises(ValueError):
        split_ea_key("3432")


def test_season_turns_on_aug_1():
    assert season_start_year(date(2027, 7, 31)) == 2026
    assert season_start_year(date(2027, 8, 1)) == 2027


def test_every_page_region_is_mapped():
    assert len(REGION_STATES) == 19 and all(REGION_STATES.values())


def test_union_of_regions():
    assert allowed_states(["LA North", "Texas"]) == frozenset({"CA", "TX"})


def test_unknown_region_fails_loudly():
    with pytest.raises(UnknownRegionError):
        allowed_states(["Atlantis"])
```

Adjust `test_union_of_regions` to the owner-approved table's literal values.

- [ ] **Step 3: Run, confirm failure, implement.**

```python
"""EA season keys and the region -> state table.

An EA team id names an age slot (club, age, tier) that keeps its id every season while the
players move up, so a link is only true for one season: PitchRank stores `<uid>:<season>`.
"""

import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

REGION_STATES: dict[str, frozenset[str]] = {
    region: frozenset(states)
    for region, states in json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "modular11_ea_regions.json").read_text(encoding="utf-8")
    ).items()
}


class UnknownRegionError(KeyError):
    """An EA region the table does not map; the page added one and the table must be extended."""


def ea_key(uid: str, season: int) -> str:
    return f"{uid}:{season}"


def split_ea_key(key: str) -> tuple[str, int]:
    uid, sep, season = key.partition(":")
    if not sep or not uid.isdigit() or not season.isdigit():
        raise ValueError(f"not a season-keyed EA id: {key!r}")
    return uid, int(season)


def season_start_year(today: date) -> int:
    return today.year if today.month >= 8 else today.year - 1


def allowed_states(regions: Iterable[str]) -> frozenset[str]:
    states: set[str] = set()
    for region in regions:
        if region not in REGION_STATES:
            raise UnknownRegionError(region)
        states |= REGION_STATES[region]
    return frozenset(states)
```

Then make `scripts/scrape_modular11_ea.season_bounds` call `season_start_year`, so the rule lives
in one place.

- [ ] **Step 4: Run and confirm the tests pass.** Mutation check: drop the `if region not in`
  guard (so `REGION_STATES[region]` raises a plain `KeyError`) and confirm that
  `test_unknown_region_fails_loudly` still catches it, because `UnknownRegionError` subclasses
  `KeyError`. Then make the guard return an empty set and confirm the test fails.
- [ ] **Step 5: Commit** — `git commit -m "Add EA season keys and the region-to-state table"`.

---

### Task 2: Season keys through scraper, linker, builder; migrate U17

**Files:**
- Modify: `scripts/scrape_modular11_ea.py` (add a `season` column to `teams.csv`; add
  `home_key` and `away_key` columns to `games.csv`)
- Modify: `scripts/link_modular11_ea_teams.py` (aliases and created teams use
  `ea_key(provider_team_id, season)`; the decisions file keeps raw uids)
- Modify: `scripts/build_modular11_ea_games_csv.py` (links keyed by season key; importer
  `team_id` and `opponent_id` are season keys)
- Modify: `scripts/match_modular11_ea_teams.py` (the "already linked" exclusion reads season keys)
- Create: `scripts/migrate_modular11_ea_season_keys.py`
- Test: extend the four existing test files; create `tests/unit/test_migrate_modular11_ea_season_keys.py`

**Interfaces:**
- Consumes: `ea_key`, `split_ea_key`, `season_start_year`.
- Produces: `teams.csv` gains a `season` column (int). `link_plan.csv` gains a `key` column.
  `migrate(sb, provider_id, season, log_path, execute) -> dict[str, int]` with keys
  `aliases, teams, already_keyed`.

- [ ] **Step 1: Failing tests.**
  - Linker: an executed create writes the `teams.provider_team_id` and alias `provider_team_id`
    as `"7155:2026"`, and a decision keyed by the raw `"7155"` still applies.
  - Builder: importer rows carry `team_id == "7155:2026"`, and `live_links` keys are season
    keys.
  - **Importer:** write an `import.csv` with one season-keyed row pair and call
    `scripts.import_games_enhanced.stream_games_csv(path)`. Assert that `team_id == "7155:2026"`,
    `goals_for == 3` (an int) and `goals_against == 1`. Expect this to fail today, because the
    shared `try` skips score conversion after the id conversion raises.
  - **Migration:** with a `_Db` double (pattern from `tests/unit/test_link_modular11_ea_teams.py`)
    holding a raw alias `3432` and a raw team `7155`, an executed `migrate(..., season=2026)`
    rewrites both to `:2026`. A second run reports `already_keyed=2` and writes nothing. A dry
    run writes nothing, and `--undo` restores the raw ids.
- [ ] **Step 2: Fix the importer finding with the smallest change.** Split the conversion in
  `stream_games_csv` and `load_games_csv` so that ids and scores each get their own `try`. Do not
  convert ids that contain `:`. Mirror the change in both loaders. Add a regression test for an
  existing numeric provider (`"3432.0"` still becomes `"3432"`). This changes a shared importer:
  name it in the PR description.
- [ ] **Step 3: Implement the key plumbing and the migration.** The migration updates guarded on
  the current value, `.eq("provider_team_id", raw)`, skips ids that already contain `:`, and logs
  `{"table", "id or team_id_master", "old", "new"}` lines.
- [ ] **Step 4: Run the tests, then mutation-check.** Remove the `:` skip and confirm the
  double-suffix test fails. Merge the importer `try` blocks back and confirm the importer test
  fails.
- [ ] **Step 5: Commit** — `git commit -m "Key EA ids by season, including through the shared importer"`.

---

### Task 3: Branch-safe club test and tier markers

**Files:**
- Modify: `scripts/match_modular11_ea_teams.py`
- Test: `tests/unit/test_match_modular11_ea_rules.py`

**Interfaces:**
- Produces:
  - `club_relation(ea_club: str, candidate_club: str | None, candidate_name: str) -> str`,
    returning `"same"`, `"branch"` or `"other"`
  - `tier_marker` now reads `EA1` as `"EA"`

**Rule:**
1. Compare normalised token lists. Normalising lowercases, splits on non-alphanumerics, and drops
   `GENERIC = {"sc","fc","soccer","club","futbol","football","academy","youth","the","de","cf","ac","sa","united"}`.
2. `"same"`:
   - the EA club's and the candidate club's token sets are equal, **or**
   - the candidate name opens with the EA club followed by an age token (keep
     `_name_led_by_club`).
3. `"branch"`: one token set strictly contains the other, or they share their first token and
   differ in at least one non-generic token, e.g. `albion santa ana` vs `albion santa monica`,
   `tfa oc` vs `tfa sgv`, `la surf lc` vs `la surf futures`, `albion atlanta` vs
   `albion atlanta metro`, `albion san diego` vs `albion san diego ec`.
4. Otherwise `"other"`.

`are_same_club` is no longer used for acceptance.

- [ ] **Step 1: Failing tests from the real pairs.** Each asserts a literal:

```python
@pytest.mark.parametrize(
    "ea_club,cand_club,cand_name,expected",
    [
        ("ALBION SC Santa Ana", "Albion SC Santa Monica", "BU17 EA", "branch"),
        ("Total Futbol Academy - OC", "Total Futbol Academy (TFA-SGV)", "TFA-SGV 2010 EA", "branch"),
        ("LA Surf LC", "LA Surf Futures", "Futures EA BU16", "branch"),
        ("ALBION SC Atlanta", "ALBION SC Atlanta Metro", "ALBION SC ATLANTA METRO B10 EA", "branch"),
        ("ALBION SC San Diego", "Albion SC San Diego", "ALBION SC San Diego EC B10 EA2", "same"),
        ("California Football Academy", "California Football Academy", "CFA OC BU17 EA", "same"),
        ("ALBION SC Boulder County", "Albion SC Colorado", "ALBION SC Boulder County B10 EA", "same"),
        ("Emerald City FC", "Sparta Tacoma", "Sparta 2010 EA", "other"),
    ],
)
def test_club_relation(ea_club, cand_club, cand_name, expected):
    assert club_relation(ea_club, cand_club, cand_name) == expected


def test_ea1_reads_as_ea():
    assert tier_marker("AC Brea EA1") == "EA"
```

San Diego vs San Diego EC is `"same"` at club level. The `EC` sub-site is caught by Task 4's
qualifier rule, and a test there pins it.

- [ ] **Step 2: Run, confirm failure, implement, run and confirm the tests pass.** Then mutation:
  drop the shared-first-token branch rule (the Santa Ana row fails), and drop the generic-word
  removal (the Boulder County row or the CFA row fails).
- [ ] **Step 3: Commit** — `git commit -m "Tell EA club branches apart and read EA1 as EA"`.

---

### Task 4: State agreement, one claim per team, squad qualifiers

**Files:**
- Modify: `scripts/match_modular11_ea_teams.py` (`classify` signature and buckets)
- Test: `tests/unit/test_match_modular11_ea_rules.py`

**Interfaces:**
- Consumes: `club_relation`, `allowed_states`.
- Produces: `EaTeam` gains `regions: frozenset[str]`. `classify(ea_teams, db_teams)` reasons now
  include `different branch`, `state outside region`, `no state`, `squad qualifier`, and
  `claimed by another EA team`.

**Rules, applied in order to each candidate:**
1. `club_relation == "other"` → not a candidate.
2. `club_relation == "branch"` → review only, reason `different branch`.
3. The candidate's `state_code` is not in `allowed_states(ea.regions)` → not a candidate.
4. No `state_code` → can never be confident, reason `no state`.
5. **Squad qualifier.** A candidate name token after its tier marker that is not an age token,
   not a word of the EA team's own display name, and not in
   `{"boys","b","premier","academy","elite"}` → can never be confident, reason
   `squad qualifier: <token>`. Tests: `B10 EA Mora`, `BU17 EA Brimicombe`, `U16 EA | Ramirez`,
   `B10 EA Coachella`, `B09/10 Red EA` (colour before the marker: also catch the colour set
   `{"red","blue","white","black","gold","silver","orange","navy","green","grey","purple"}`
   anywhere), and `San Diego EC B10 EA2` (`ec`).
6. **One claim.** A candidate tagged for two EA teams → both review, reason
   `claimed by another EA team` (keep the existing rule). A candidate that already holds a
   `modular11_ea` alias for a different key of the **same season** is not a candidate.

- [ ] **Step 1: Failing tests**, one fixture per rule with literal expected buckets and reasons.
- [ ] **Step 2: Implement, run and confirm the tests pass, then mutate each rule's condition and
  confirm its own test (by name) fails.**
- [ ] **Step 3: Commit** — `git commit -m "Hold EA matches whose state, claim or squad name disagrees"`.

---

### Task 5: Schedule evidence and lineage

**Files:**
- Modify: `scripts/match_modular11_ea_teams.py` (new `fetch_candidate_games(sb, ids, season)` and
  pure `schedule_conflict(ea_games, cand_games) -> bool`, plus `lineage_target(...)`)
- Test: `tests/unit/test_match_modular11_ea_schedule.py`

**Interfaces:**
- Consumes: `games.csv` rows (`game_date`, `home_key`, `away_key`, `home_name`, `away_name`), and
  the live `modular11_ea` aliases.
- Produces:
  - `schedule_conflict(ea_games: list[dict], cand_games: list[dict], ea_club: str) -> bool` is
    true when the candidate played on a date when the EA team played a scored league game, and
    the candidate's opponent belongs to a different club (`club_relation(...) == "other"`) from
    the EA team's opponent that day.
  - `lineage_target(age_minus_one_uid: str, season: int, links: dict[str, str]) -> str | None`
    returns `links.get(ea_key(uid, season - 1))`.

**Use in `classify`:**
- A conflicting candidate is not a candidate.
- A lineage target that is among the candidates becomes the only tagged candidate, so the bucket
  is `confident` with reason `last season's age-below team`.
- Lineage never adds a candidate the club, state and tier tests rejected.

- [ ] **Step 1: Failing tests.**
  - Conflict: the EA team plays Sparta on 2026-09-12; the candidate played "Pacific FC 2010" on
    2026-09-12, so the result is `True`.
  - Same fixture: the candidate's opponent is "Sparta Tacoma B10 EA", so the result is `False`.
  - Lineage: `links = {"9001:2025": "T1"}`, so `lineage_target("9001", 2026, links) == "T1"`.
  - Classify integration: a two-candidate review becomes confident when lineage names one of them.
- [ ] **Step 2: Implement.** `fetch_candidate_games` pages `games` for the candidate ids (≤100 per
  `.in_()`, ordered by `id`) within `season_bounds`, excluding `is_excluded`, and resolves
  opponents through `team_merge_map`. Drive it in one test through a `_Db` double that records at
  `execute()`.
- [ ] **Step 3: Run, mutate (flip the opponent-club comparison; drop the lineage branch), confirm
  the named tests fail.**
- [ ] **Step 4: Commit** — `git commit -m "Use schedules and last season's link when matching EA teams"`.

---

### Task 6: Cleanup runner for the merge and state skills

**Files:**
- Create: `scripts/prepare_modular11_ea_cleanup.py`
- Test: `tests/unit/test_prepare_modular11_ea_cleanup.py`

**Interfaces:**
- Consumes: `teams.csv` for the age, `club_relation`, `tier_marker`, and live `teams` (the same
  paged read as `fetch_db_teams`).
- Produces, all read-only, in `data/modular11_ea/<age>/cleanup/`:
  - `candidate_pool.csv`: every live team of the age and gender whose `club_relation` to any EA
    club in the roster is `"same"` or `"branch"`.
  - `duplicate_pairs.json`: pairs inside the pool with the same `club_relation == "same"` club,
    the same tier marker, no squad qualifier on either side, zero head-to-head and zero shared
    dates. These are in the `apply_vetted_team_merges.py` shape
    (`merge_id, keep_id, merge_name, keep_name`) plus an `evidence` object. The survivor is chosen
    by the merge skill's Step 6 order (two-year band or current U-age > bare year > no age > stale
    U-age; then games; then last played).
  - `stateless.csv`: pool teams with no `state_code`.
  - `--state-snapshot RUN.json`: keep only the snapshot decisions whose `team_id` is in the pool,
    and write `state_pool.json` in the snapshot's own shape.

- [ ] **Step 1: Failing tests** from this week's data:
  - California Football Academy ×3 → 2 pairs into the GotSport `BU17 EA` row.
  - Albion SC Atlanta vs Atlanta Metro → no pair (a branch).
  - Rangers `EA 2010` vs `Rangers FC U17 EA` → a pair is proposed, but the evidence shows no
    current-season games on the merge side. The skill's review is what holds it; the runner only
    proposes.
  - The snapshot filter keeps 2 of 3 decisions.
- [ ] **Step 2: Implement, run, mutate (drop the head-to-head screen; drop the qualifier screen),
  confirm the named tests fail.**
- [ ] **Step 3: Commit** — `git commit -m "Prepare per-age EA cleanup inputs for the merge and state skills"`.

---

### Task 7: Full gate and review

- [ ] Run the full CI gate (the ruff path list, then pytest in the CI form). Expected: green, or
  only the frontend-runtime pair when the junction is absent.
- [ ] Run one fresh whole-branch reviewer (opus) with this plan's Review Focus. Fix Critical and
  Important findings with TDD, and ledger the minors.

---

### Task 8: Migrate U17, then run the new flow (owner-gated)

Each step that writes stops for the owner's yes.

- [ ] **Migration:** run `migrate_modular11_ea_season_keys.py --season 2026` as a dry run, then
  `--execute` after the owner says yes. Verify from the database that all 98 aliases and 36 teams
  are keyed and that nothing raw remains.
- [ ] **U17 cleanup:**
  - Run `prepare_modular11_ea_cleanup.py --age u17`.
  - Invoke the `merging-duplicate-teams` skill on `duplicate_pairs.json`, with its review,
    owner page, apply and doubled-game steps.
  - Invoke `assigning-team-states` (dry run, then `--state-snapshot`, hold split, apply), and send
    `stateless.csv` to the owner.
- [ ] **U17 rematch:** re-run the match report on the cleaned pool. Report the counts by bucket
  next to the old 41/90/36. Apply new confident links through the linker as a dry run, then
  execute on the owner's word, then build and import.
- [ ] **U16:** scrape, then cleanup (both skills), then match, then the owner's spreadsheet, then
  import. This is the success measure: no confident link the owner rejects, no shared targets,
  and under a third of teams left for review.
