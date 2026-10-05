# Modular11 EA Import (Step 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For one EA age group per run, link the confident EA teams to existing PitchRank teams,
create the no-match teams, import the played games between linked teams through the standard
pipeline, and hand the user a spreadsheet of the created and review teams.

**Architecture:** Mirror the Athletes2Events and Soccer Events Group providers. A link script is
the only thing that writes aliases and creates teams, and it is a dry run unless `--execute` is
passed. A games builder turns step 1's `games.csv` into the importer's two-rows-per-game CSV for
linked teams only, and reports the ranking impact. `scripts/import_games_enhanced.py <csv>
modular11_ea` then imports through an alias-only matcher that never fuzzy-matches or creates.

**Tech Stack:** Python 3.11, supabase-py, the existing `EnhancedETLPipeline`, pytest, and GitHub
Actions.

**Spec:** `.turbo/specs/modular11-ea-import.md` (step 1:
`.turbo/specs/modular11-ea-scraper.md`)

## Global Constraints

- Provider code `modular11_ea`. Never touch `modular11` (MLS NEXT) code, data or workflows.
- Inputs are step 1's per-age files in `data/modular11_ea/<age>/`: `teams.csv`, `games.csv`,
  `match_report.csv`.
- New teams: `gender` `Male`, `state_code` NULL, `provider_id` = modular11_ea,
  `provider_team_id` = the EA team id.
- Alias methods and confidences: created team → `direct_id` 1.0; confident report link →
  `fuzzy_auto` 0.95; user pick from the decisions spreadsheet → `manual` 1.0. Every alias is
  written through `src.tournaments.alias_writer.upsert_team_alias`, which keeps human rows and
  queues conflicts.
- Played games only (`status == "played"`), and both teams must be linked.
- Game ids are made by the pipeline (`{provider}:{date}:{master}:{master}`), so re-running a game is
  a no-op. Do not invent a match-number uid (this corrects the spec's wording).
- Every script that writes takes `--execute`. The default is a dry run that writes nothing to the
  database.
- Every write is appended to a JSONL log, and `--undo <log>` reverses it.
- Lint: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`. Tests:
  `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.

## Review Focus

1. **An EA team the user marked `skip`, or a review team with no pick**, must get no alias, and
   its games must be held back, not imported against a guessed team. Pinned in Task 2 and Task 3.
2. **A re-run after a partial or complete `--execute`** must reuse existing aliases and teams, not
   create a second team for the same EA id. Pinned in Task 2.
3. **`--undo` on a created team that already has games** must refuse that team rather than delete
   it, because games reference it. Pinned in Task 2.
4. **A game where only one side is linked** is held back and counted, never imported half-matched.
   Pinned in Task 3.
5. **A dry run writes nothing at any layer** (linker, matcher, pipeline). This is checked against
   the database in Task 6, not only in the summary.

## Branch

Continue on `feat/ea-scraper` in `C:\pitchrank-ea-scraper`. It already has `origin/main` merged in
(72345de). One PR covers step 1 and step 2. Run `git branch --unset-upstream` before the first push.

---

### Task 1: Provider row, alias-only matcher, pipeline wiring

**Files:**
- Create: `supabase/migrations/20261005120000_seed_modular11_ea_provider.sql`
- Create: `src/models/modular11_ea_matcher.py`
- Modify: `src/etl/enhanced_pipeline.py` (matcher selection chain, beside `athletes2events` at `:309`)
- Test: `tests/unit/test_modular11_ea_matcher.py`

**Interfaces:**
- Produces: `PROVIDER_CODE = "modular11_ea"` (in the matcher module) and
  `Modular11EaGameMatcher(GameHistoryMatcher)`, whose `_match_team(...)` returns the base
  `direct_id`/`provider_id` result, or `{"matched": False, "team_id": None, "method": None,
  "confidence": 0.0}`.

- [ ] **Step 1: Migration** (mirror `20260919120000_seed_athletes2events_provider.sql`)

```sql
-- EnhancedETLPipeline raises ValueError when this row is absent. Elite Academy League
-- (Modular11 tournament 27) is its own provider, separate from MLS NEXT's `modular11`:
-- its team ids are Modular11 UID_team values, never the MLS NEXT club-age keys.
INSERT INTO providers (code, name, base_url)
VALUES ('modular11_ea', 'Modular11 Elite Academy League', 'https://www.modular11.com')
ON CONFLICT (code) DO NOTHING;
```

- [ ] **Step 2: Failing tests**

```python
"""The EA matcher resolves teams only through modular11_ea aliases."""

from unittest.mock import MagicMock

from src.models.modular11_ea_matcher import Modular11EaGameMatcher

PROVIDER = "prov-ea"


def _matcher(cache=None):
    m = Modular11EaGameMatcher(MagicMock(), provider_id=PROVIDER, alias_cache=cache or {}, dry_run=True)
    m._validate_team_age_group = lambda *a, **k: True
    return m


def test_cached_alias_resolves():
    m = _matcher({"7155": {"team_id_master": "T1", "match_method": "direct_id", "review_status": "approved"}})
    result = m._match_team(PROVIDER, "7155", "Emerald City FC", "u17", "Male")
    assert (result["matched"], result["team_id"]) == (True, "T1")


def test_unlinked_team_never_fuzzy_matches_or_creates():
    m = _matcher()
    m._match_by_provider_id = lambda *a, **k: None
    m._fuzzy_match_team = MagicMock(side_effect=AssertionError("fuzzy must not run"))
    m._create_alias = MagicMock(side_effect=AssertionError("must not write"))
    result = m._match_team(PROVIDER, "999", "Emerald City FC", "u17", "Male")
    assert result == {"matched": False, "team_id": None, "method": None, "confidence": 0.0}


def test_pipeline_selects_ea_matcher():
    import inspect

    from src.etl import enhanced_pipeline

    source = inspect.getsource(enhanced_pipeline)
    assert 'elif self.provider_code.lower() == "modular11_ea":' in source
    assert "Modular11EaGameMatcher(" in source
```

The third test is a source check because constructing `EnhancedETLPipeline` needs a live provider
row. Then run `tests/unit/test_birth_year_guard_wiring.py` and
`tests/unit/test_provider_matcher_dry_run.py`. If either derives its matcher list by discovery and
fails on the new class, add the class to the explicit exemption set that test keeps, with the reason
"alias-only: never fuzzy-matches or creates". Ledger it as a Ruling.

- [ ] **Step 3: Run and confirm failure** (`ModuleNotFoundError`).

- [ ] **Step 4: Implement**

```python
"""Modular11 Elite Academy League game matcher: alias-only.

``scripts/link_modular11_ea_teams.py`` is the only thing that links or creates EA
teams. The game import resolves an EA team id through the alias that script wrote,
and a team without one stays unmatched -- its games were already held back by
``scripts/build_modular11_ea_games_csv.py``, so this is a backstop, not a path.
"""

from typing import Dict, Optional

from src.models.game_matcher import GameHistoryMatcher

PROVIDER_CODE = "modular11_ea"
UNMATCHED = {"matched": False, "team_id": None, "method": None, "confidence": 0.0}


class Modular11EaGameMatcher(GameHistoryMatcher):
    def _match_team(
        self,
        provider_id: str,
        provider_team_id: Optional[str],
        team_name: Optional[str],
        age_group: Optional[str],
        gender: Optional[str],
        club_name: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Dict:
        if not provider_team_id:
            return dict(UNMATCHED)
        alias = self._match_by_provider_id(provider_id, str(provider_team_id), age_group, gender)
        if not alias:
            return dict(UNMATCHED)
        method = "direct_id" if alias.get("match_method") == "direct_id" else "provider_id"
        return {"matched": True, "team_id": alias["team_id_master"], "method": method, "confidence": 1.0}
```

Pipeline branch, inserted after the `athletes2events` branch:

```python
        elif self.provider_code.lower() == "modular11_ea":
            from src.models.modular11_ea_matcher import Modular11EaGameMatcher

            logger.info("Using Modular11EaGameMatcher (alias-only; teams come from link_modular11_ea_teams.py)")
            self.matcher = Modular11EaGameMatcher(
                self.supabase,
                provider_id=self.provider_id,
                alias_cache=self.alias_cache,
                dry_run=self.dry_run,
            )
```

- [ ] **Step 5: Run and confirm the tests pass**, including the two registry tests. Mutation check:
  make `_match_team` fall through to `super()._match_team(...)` when there is no alias, and confirm
  that `test_unlinked_team_never_fuzzy_matches_or_creates` fails.
- [ ] **Step 6: Commit**: `git commit -m "Add the modular11_ea provider with an alias-only game matcher"`.

---

### Task 2: Link script (plan, execute, undo, hand-back)

**Files:**
- Create: `scripts/link_modular11_ea_teams.py`
- Test: `tests/unit/test_link_modular11_ea_teams.py`

**Interfaces:**
- Consumes: `data/modular11_ea/<age>/teams.csv` (columns `provider_team_id, academy_id,
  club_name, display_name, age_group, name_tier, tiers, regions, gender`) and
  `match_report.csv` (`provider_team_id, bucket, candidate_ids, candidate_names, ...`). Also
  `PROVIDER_CODE` from Task 1.
- Produces:
  - `LinkAction` (frozen dataclass: `provider_team_id, action, team_id_master, match_method,
    display_name, club_name, age_group, reason`), where `action` is one of `link`, `create`,
    `hold`.
  - `plan_links(teams: list[dict], report: list[dict], decisions: dict[str, str]) ->
    list[LinkAction]`.
  - `apply_plan(sb, provider_id: str, plan: list[LinkAction], log_path: Path) -> dict[str, int]`.
  - `undo(sb, provider_id: str, log_path: Path) -> dict[str, int]`.
  - `write_handback(path: Path, plan, report) -> None`.
  - `main(argv=None) -> int`.
  - Files: `link_plan.csv` (every run) and `handback.csv` plus `handback_legend.txt` (every run).
    Executed runs also write `link_log_<UTC timestamp>.jsonl`.

**Rules (`plan_links`), for each EA team:**
- A decision for its id wins: a `team_id_master` → `link` (`manual`), `new` → `create`,
  `skip` → `hold`.
- Otherwise the bucket decides: `confident` → `link` to its single `candidate_ids` (`fuzzy_auto`);
  `no_match` → `create`; `review` → `hold`.

- [ ] **Step 1: Failing tests.** Build the Supabase double from `_Db` in
  `tests/unit/test_playmetrics_matcher_row_state.py`. It records `insert`, `delete` and selects
  **at `execute()`**, and a zero-row `.single().execute()` raises
  `APIError({"code": "PGRST116"})`. Patch `scripts.link_modular11_ea_teams.upsert_team_alias` with
  a recorder that returns `{"action": "created"}`, or `{"action": "updated"}` for an id already
  recorded.

```python
def test_plan_follows_buckets():                      # confident→link fuzzy_auto, no_match→create, review→hold
def test_decisions_override_buckets():                # id→link manual, "new"→create, "skip"→hold (incl. on a confident row)
def test_dry_run_writes_nothing(tmp_path):            # main([... no --execute]) → db.executed has no insert/delete; link_plan.csv written
def test_execute_creates_team_and_direct_id_alias():  # team row fields per Global Constraints; alias method direct_id; log lines for both
def test_rerun_reuses_existing_team():                # teams row with provider_id+provider_team_id exists → no second insert; alias upsert still called
def test_hold_writes_nothing():                       # a hold action produces no alias and no team
def test_undo_removes_aliases_and_empty_teams():      # deletes logged alias rows and created teams with zero games
def test_undo_refuses_team_with_games():              # created team referenced by a game → kept, reported as refused
def test_handback_lists_created_and_review_teams():   # one row per created team (with its new id) and per review team (with candidates); empty your_pick column
```

Write each test body out before running it. Every assertion must name its expected value as a
literal: for example, the inserted team dict equals
`{"team_name": "Emerald City FC", "club_name": "Emerald City FC", "age_group": "u17",
"gender": "Male", "state_code": None, "provider_id": "prov-ea", "provider_team_id": "7155", ...}`.
Mutation checks for Step 4: drop the existing-team lookup (kills `test_rerun_reuses_existing_team`),
drop the games check in undo (kills `test_undo_refuses_team_with_games`), and make `skip` fall
through to the bucket (kills `test_decisions_override_buckets`).

- [ ] **Step 2: Run and confirm failure.**

- [ ] **Step 3: Implement.** Key code:

```python
def plan_links(teams, report, decisions):
    by_id = {r["provider_team_id"]: r for r in report}
    plan = []
    for team in teams:
        tid = team["provider_team_id"]
        row = by_id.get(tid, {"bucket": "no_match", "candidate_ids": ""})
        pick = (decisions.get(tid) or "").strip()
        base = dict(provider_team_id=tid, display_name=team["display_name"], club_name=team["club_name"],
                    age_group=team["age_group"])
        if pick.lower() == "skip":
            plan.append(LinkAction(**base, action="hold", team_id_master="", match_method="", reason="your pick: skip"))
        elif pick.lower() == "new":
            plan.append(LinkAction(**base, action="create", team_id_master="", match_method="direct_id", reason="your pick: new"))
        elif pick:
            plan.append(LinkAction(**base, action="link", team_id_master=pick, match_method="manual", reason="your pick"))
        elif row["bucket"] == "confident":
            plan.append(LinkAction(**base, action="link", team_id_master=row["candidate_ids"], match_method="fuzzy_auto", reason="confident"))
        elif row["bucket"] == "no_match":
            plan.append(LinkAction(**base, action="create", team_id_master="", match_method="direct_id", reason="no match"))
        else:
            plan.append(LinkAction(**base, action="hold", team_id_master="", match_method="", reason="needs review"))
    return plan
```

`apply_plan`:
- **`create`:** look up `teams` by `provider_id` + `provider_team_id` with `.single()`. A
  `PGRST116` miss means insert a new row: `team_id_master=str(uuid4())`, `team_name=display_name`,
  `club_name`, `age_group`, `gender="Male"`, `state_code=None`, `state=None`, `provider_id`,
  `provider_team_id`, and `distinction=resolve_distinction(display_name, club_name, None)`
  (import from `src.utils.team_name_utils`, as `src/models/athletes2events_matcher.py` does).
  Log `{"kind": "team", "team_id_master": ...}` only for a team created this run.
- **Every `create` and `link`:** call `upsert_team_alias(sb, provider_uuid=provider_id,
  provider_team_id=..., team_id_master=..., provider_team_name=display_name, confidence=(1.0, 0.95
  or 1.0), match_method=..., priority_score=same)`. Log `{"kind": "alias", "provider_team_id": ...,
  "team_id_master": ..., "result": action}`. Any result other than `created`/`updated` is counted
  as a conflict and printed.
- **Returns** counts: `teams_created, teams_reused, aliases_written, conflicts, held`.

`undo`:
- For each logged alias, delete the `team_alias_map` row by `provider_id` + `provider_team_id`.
- For each logged team, count the games that reference it (two `.select("id",
  count="exact").eq("home_team_master_id"|"away_team_master_id", id).limit(1)` queries). Delete it
  if both counts are 0; otherwise report it as refused.
- Deleting the aliases first is safe: an alias whose team stays is simply re-linked by a re-run.

`main` arguments: `--age` (required), `--in-dir` (default `data/modular11_ea`), `--decisions
PATH` (CSV with `provider_team_id,your_pick`), `--execute`, `--undo LOG`. Client setup follows
`scripts/match_modular11_ea_teams.py` (the `sys.path` insert and env lookup). Look up the provider
id with `providers` `.eq("code", PROVIDER_CODE).single()` and fail with a clear message ("apply
migration 20261005120000 first") when it is missing. Print the counts per action, and in a dry run
also print `DRY RUN — nothing written`.

`write_handback`:
- Columns: `provider_team_id, ea_team_name, club, status, pitchrank_team_id, candidates,
  your_pick`.
- `status` is `created` (or `would create` in a dry run) or `needs review`.
- `candidates` is `name (id)` joined with ` | `.
- `handback_legend.txt` explains `your_pick`: paste a PitchRank team id to link (or, for a created
  team, to merge into), `new` to create, `skip` to leave out. It shows one real example row per
  status, taken from the run.

- [ ] **Step 4: Run and confirm the tests pass, then run the three mutation checks above.**
- [ ] **Step 5: Commit**: `git commit -m "Link or create EA teams from the match report, dry run by default, with undo"`.

---

### Task 3: Games CSV builder with ranking-impact report

**Files:**
- Create: `scripts/build_modular11_ea_games_csv.py`
- Test: `tests/unit/test_build_modular11_ea_games_csv.py`

**Interfaces:**
- Consumes: `games.csv` and `teams.csv` from step 1; `link_plan.csv` from Task 2 (for
  `--planned`); live `team_alias_map` rows for `modular11_ea` (the default).
- Produces:
  - `build_rows(games: list[dict], teams: dict[str, dict], links: dict[str, str]) ->
    tuple[list[dict], list[dict]]`, which returns `(importer_rows, held_games)`.
  - `impact(sb, importer_rows, links) -> dict`.
  - `main(argv=None) -> int`, which writes `data/modular11_ea/<age>/import.csv` and
    `held_games.csv` and prints the impact.

**Rules:**
- Only `status == "played"` games are used.
- A game is held when either `home_team_id` or `away_team_id` is blank or has no link.
- Each kept game becomes two rows (H and A perspective), shaped like
  `scripts/import_athletes2events_event.py:build_csv_rows`: `provider=modular11_ea`, `team_id`,
  `team_id_source`, `team_name`, `club_name`, `opponent_*`, `age_group`, `gender="Boys"`,
  `game_date`, `home_away`, `goals_for`, `goals_against`, `result` (W/L/D), `event_name=
  "Elite Academy League - <bracket>"`, `competition=<bracket>`, `division_name=<region>`,
  `source_url=MATCHES_URL`, and `scraped_at`.
- Every column must be one that both loaders in `scripts/import_games_enhanced.py` admit (`:83-110`
  and `:153-180`). Assert that in a test by parsing those whitelists, not by listing them by hand.

**Impact:** for every `team_id_master` in the rows, count the games already stored in the last
365 days (two count queries, ≤100 ids per `.in_()`), add the new games, and report:
- `games_added`
- `teams_touched` (existing / new)
- `crossing_up`: the teams that go from below 12 to 12 or more games (`MIN_GAMES_PROVISIONAL`,
  imported from `src/rankings/constants.py`, never hard-coded)

New teams start from 0.

- [ ] **Step 1: Failing tests**

```python
def test_played_game_with_both_linked_becomes_two_rows():   # literal H and A rows, goals swapped, result W/L
def test_scheduled_game_is_dropped():
def test_one_unlinked_side_is_held():                        # held_games has it; no importer rows
def test_rows_use_only_columns_both_loaders_admit():         # parse both whitelists from the importer source
def test_impact_counts_crossing_provisional_threshold():     # team at 10 stored + 3 new → crossing_up == 1; at 13 → 0
def test_planned_mode_reads_link_plan_not_database(tmp_path) # --planned uses link_plan.csv links; db double asserts no team_alias_map read
```

Mutation checks: drop the `played` filter; make held games emit rows; hard-code 12 instead of the
constant and change the constant in a monkeypatch (the threshold test must follow the constant).

- [ ] **Step 2–4:** Watch them fail, implement, watch them pass, run the mutation checks.
- [ ] **Step 5: Commit**: `git commit -m "Build the EA import CSV for linked teams and report the ranking impact"`.

---

### Task 4: Workflow import switch and the age-rollover gate

**Files:**
- Modify: `.github/workflows/ea-scraper.yml`
- Modify: `tests/unit/test_age_rollover_freeze_coverage.py` (add `link_modular11_ea_teams.py` to
  `AGE_DERIVING_SCRIPTS`, because it writes only with `--execute`)
- Modify: `CLAUDE.md` (the `AGE_ROLLOVER_FREEZE` re-arm list: add `ea-scraper.yml`, and "ten"
  becomes "eleven")

- [ ] **Step 1:** Add the workflow-level env `AGE_ROLLOVER_FREEZE: 'false'`, with the comment block
  copied from `or-scraper.yml`. Add the boolean input `execute` (default `false`, description
  "Write links, new teams and games to PitchRank").
- [ ] **Step 2:** Add the steps after "Build match report". Each is gated by
  `if: ${{ inputs.execute && env.AGE_ROLLOVER_FREEZE == 'false' }}` and carries the
  Supabase env vars of the match step:

```yaml
      - name: Link EA teams
        run: |
          set -euo pipefail
          python scripts/link_modular11_ea_teams.py --age "$AGE" --execute | tee link_counts.txt

      - name: Build EA import CSV
        run: |
          set -euo pipefail
          python scripts/build_modular11_ea_games_csv.py --age "$AGE" | tee impact.txt

      - name: Import EA games
        run: |
          set -euo pipefail
          python scripts/import_games_enhanced.py "data/modular11_ea/$AGE/import.csv" modular11_ea
```

  Without `execute`, also run the link script and the builder as dry runs (`--planned`), so every
  run's artifact carries `link_plan.csv`, `handback.csv` and the impact numbers. Add both counts
  files to the summary step.
- [ ] **Step 3:** Run the workflow guard tests:
  `python -m pytest tests/ -k "workflow or pipefail or rollover or zenrows" -q`. Expected: pass,
  with the new step detected as gated.
- [ ] **Step 4: Commit**: `git commit -m "Let EA Scraper import an age when asked, behind the rollover freeze"`.

---

### Task 5: Full gate and review

- [ ] Run the full CI gate (ruff path list, then pytest with the CI form). Expected: green.
- [ ] Run one fresh whole-branch reviewer over Tasks 1–4, with this plan's Review Focus, and fix the
  Critical and Important findings with TDD. A second review round happens only if the user asks
  (per the memory note).

---

### Task 6: U17 dry run and impact numbers → STOP for the user

- [ ] **Step 1:** Ask the user to apply the migration (`supabase db push`, or by hand followed by
  `supabase migration repair --status applied 20261005120000`). This is a write to production, so
  it happens on the user's word only.
- [ ] **Step 2:** Re-scrape U17, so the data is current:
  `python scripts/scrape_modular11_ea.py --age u17 && python scripts/match_modular11_ea_teams.py --age u17`.
- [ ] **Step 3:** Run the link dry run, then the games builder in `--planned` mode. Read 10 real
  rows of `link_plan.csv` and of `import.csv`.
- [ ] **Step 4:** Confirm from the database that the dry run wrote nothing: `team_alias_map` and
  `teams` counts for provider `modular11_ea` are both 0.
- [ ] **Step 5: STOP.** Send the user, in plain English: how many teams would be linked, created
  and held; how many games would go in; how many teams cross the 12-game line; and
  `handback.csv` with its legend. Wait for an explicit go-ahead.

### Task 7: U17 real import (only after the user's go-ahead)

- [ ] Link `--execute`, then build the CSV (live links), then run
  `import_games_enhanced.py ... modular11_ea --dry-run`, read its summary, and only then run it
  for real.
- [ ] Verify from the data: the `modular11_ea` aliases equal the link count, the created teams equal
  the create count, and the games for the age's linked teams went up by the imported count. Report
  this to the user together with the hand-back spreadsheet, and keep the `link_log_*.jsonl` path for
  undo.
