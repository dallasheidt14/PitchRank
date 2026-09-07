# Two plan-level blockers in the scrape-activity change

Found during the post-implementation review of
`.turbo/plans/skip-inactive-teams-in-scrape-queue.md`. Both were raised by the correctness
reviewer and then verified independently against production on 2026-08-27. Neither is an
implementation slip — each invalidates a step of the plan as designed.

Code state: steps 1-9 implemented, staged, uncommitted, on branch
`skip-inactive-teams-in-scrape-queue`. Python CI gate green (ruff clean, 2,562 tests pass).

---

## Blocker 1 — the refresh RPC cannot finish; its timeout guard is inert

**Plan step 3.** `refresh_team_scrape_activity()` opens with
`SET LOCAL statement_timeout = '300s'`, mirroring `backfill_total_game_stats`
(`20260325100000:35`). That line does nothing.

PostgreSQL arms `statement_timeout` once, at the start of each top-level client command.
Statements executed inside a function never re-arm it, so changing the GUC mid-function
cannot extend the timer already running for the `SELECT refresh_team_scrape_activity(...)`
that PostgREST issued. The internal 10,000-row batching bounds nothing either — the whole
function is a single statement to that timer.

Verified by experiment:

| Test | Result |
|---|---|
| `DO $$ SET LOCAL statement_timeout='1s'; PERFORM pg_sleep(3); $$` | **succeeded** — slept 3s |
| `SET LOCAL statement_timeout='1s';` then `SELECT pg_sleep(3);` | **57014** statement timeout |

The timeout fires when armed before the statement and not when set inside it.

What is actually in force for a PostgREST call:

```
authenticated  = statement_timeout=8s
anon           = statement_timeout=3s
authenticator  = statement_timeout=8s, lock_timeout=8s
```

There is **no `service_role` entry** in `pg_db_role_setting`. PostgREST logs in as
`authenticator` (8s) and then `SET ROLE service_role`, which does not re-apply per-role
settings — so the refresh runs with an 8-second budget.

The work is far past 8s. `EXPLAIN` of the aggregate alone plans at ~851K cost over 3.03M
game rows and 2.50M scrape-log rows, and on the first run every one of the 211,401 `teams`
rows changes value (all four columns move off NULL), each write passing 16 indexes and a
per-row `update_teams_updated_at` trigger.

The repo already has this failure in production and mislabelled its cause.
`.turbo/backfill-review-2026-07-27.md` records that `backfill_total_game_stats`'s RPC branch
raises on every weekly run and `calculate_rankings.py`'s Python fallback takes over — the
report attributes that to the function outgrowing a 300s budget, but the budget was never
8 seconds' worth of in force. **Our refresh script has no fallback by design**, so the
workflow simply goes red, all four columns stay NULL, and — per the plan's own inertness
argument — the never-productive branch is TRUE for every row and the whole filter never
engages.

### Options

1. **Schedule it in-database with `pg_cron`**, as `refresh_homepage_stats` already is
   (`20260615200001_schedule_homepage_stats_refresh.sql`). A cron worker's session carries
   no `authenticator` timeout, so no timer is armed. Deletes the script, the workflow, and
   plan steps 8/11/13 — but also deletes the `--dry-run` gate and the log artifact.
2. **`ALTER ROLE service_role SET statement_timeout`.** One line, but it widens the budget
   for every service-role request in the project, not just this one.
3. **Drive the batching from Python.** Give the RPC a batch offset and have
   `refresh_team_scrape_activity.py` call it in a loop, each call comfortably under 8s.
   Keeps the script, the dry run and the workflow; costs ~22 round-trips at 10K rows.

---

## Blocker 2 — the predicate excludes nothing from either weekly producer

**Plan step 6.** The two functions the change was written to fix return exactly the same
teams after it as before.

Both order `last_scraped_at ASC NULLS FIRST`, and the re-probe branch opens with
`t.last_scraped_at IS NULL`. Never-scraped teams therefore sort to the front *and* pass the
filter unconditionally. Measured against production for `find_stale_teams`:

| Figure | Value |
|---|---:|
| Eligible pool | 13,518 |
| ...of which never scraped | 13,277 (98.2%) |
| **Rows the `LIMIT 500` actually returns that are never scraped** | **500 of 500** |
| Teams in the 90d-6mo band, where the predicate could ever bind | 235 |

So all 500 teams enqueued each Sunday still pass, and will keep passing for roughly 26
weeks (13,277 ÷ 500) — a pool continuously refilled by new team creation.
`find_discovery_teams` has the same shape: it orders `has_recent DESC` first (those teams
pass the recently-played branch) and then `last_scraped_at ASC NULLS FIRST` (those pass the
re-probe branch).

The plan's Verification asked for the wrong measurement. It says "the first two counts
should drop substantially", measured with `p_row_limit => 100000`. That is true of the
*pool* and false of the *output*: production calls these at `LIMIT 500` and `LIMIT 1000`,
and the filter never reaches the rows the limit keeps.

The plan did note that `last_scraped_at IS NULL` "admits all 23,302 never-scraped teams
unconditionally. Deliberate fail-open; the filter is not expected to reduce work there."
What it did not carry through is that the ordering makes those teams *the entire output*,
so the two producers get no benefit at all.

The change does real work in exactly one place: `find_topup_teams`, where the reviewer
measured 8,293 of 34,498 candidates excluded pool-wide — though only 1 of the first 2,000
rows in its `DESC` order, which is the end `drain_queue` consumes.

### Which branch is actually admitting them

**All 13,277 of those never-scraped teams have game rows. Zero have none.** So the
never-productive branch neither admits nor excludes any of them — the only thing keeping
them eligible is the `t.last_scraped_at IS NULL` half of the re-probe branch.

That exposes a circularity the plan did not resolve. The re-probe reads `last_scraped_at`,
which for a never-scraped team stays NULL forever *because nothing scrapes it* — so the
clock that is supposed to re-admit a filtered team can never start for this population.
The plan included `IS NULL` precisely to break that circle ("a never-scraped team with game
rows would otherwise match no branch and be excluded permanently"), and this is exactly the
cohort it was protecting. But including it is also what makes the filter a no-op on both
weekly producers.

Note the ordering matters as much as the branch: these teams sort first under
`NULLS FIRST`, so they occupy the entire `LIMIT 500` regardless of what the predicate says
about anyone else. `find_discovery_teams` is argued structurally here rather than measured
— a hand-written equivalent of its `team_flags` CTE exceeded a 2-minute session timeout.

### Options

1. **Re-scope to the top-up only.** Honest, small, and matches where the filter measurably
   binds. Drops the two `CREATE OR REPLACE`s and most of the drift test.
2. **Separate "never scraped" from "scraped long ago"** in the re-probe branch, and give
   never-scraped teams a bounded allowance instead of a permanent pass.
3. **Change the producers' ordering** so they do not return an all-never-scraped page —
   larger blast radius, and it changes what those jobs do independently of this filter.

---

## Everything else from the review

Six reviewers returned; the Codex peer review was still running when this was written.

- **Security: clean.** All five claims verified against the live catalog — the `REVOKE`
  covers `PUBLIC`/`anon`/`authenticated` (Supabase's `pg_default_acl` grants the latter two
  on top of PostgreSQL's implicit `PUBLIC`), and both replaced functions are live at
  identical signatures with `prosecdef = false` and null `proconfig`, so no overload is
  created and GRANTs survive. One operator note: apply each migration whole — pasted
  statement-by-statement and stopped after the `CREATE`, `find_topup_teams` would briefly be
  callable by `anon` as `SECURITY DEFINER`.
- **API usage: one P3.** `ROWS_CHANGED=$(grep ... | tail -1)` sits inside the step's
  `set -o pipefail` region, so a no-match `grep` exits 1 and Actions' default `bash -e` kills
  the step before `${ROWS_CHANGED:-0}` can apply. Same latent shape exists in
  `data-hygiene-weekly.yml`, which is where it was copied from. Fix is `|| true`.
- **Coverage: two real gaps in tests I wrote.** `test_refresh_only_writes_rows_whose_values_moved`
  asserts `"IS DISTINCT FROM" in <whole file>` and is satisfied by the migration's own header
  comment, so it cannot fail. And flipping the four top-level `OR`s to `AND` in all three
  predicate copies passes every predicate test while making the predicate unsatisfiable.
- **Consistency + coverage + correctness all converged** on the drift guard being pinned to
  hardcoded migration paths. Every one of these functions already has three definitions
  across migrations, so the guard stops covering them the moment one is redefined.
- **Consistency + simplicity converged** on `_flush_scrape_log` being a third copy of
  `_bulk_log_team_scrapes` (`scrape_games.py` and `drain_queue.py` already carry byte-identical
  bodies), with `src/etl/bulk_ops.py` as the existing shared home.
- **Simplicity refuted the plan's single-definition claim**: function inlining is genuinely
  blocked by the `EXISTS` sublink, but a `security_invoker` view is pulled up rather than
  inlined, so one definition is achievable at no planner cost.
- **Correctness P2, not yet decided**: `process_missing_games` scrapes only
  `[game_date-90, game_date+90]` but now stamps `last_scraped_at = now()`, and that column is
  the incremental watermark `drain_queue`/`scrape_games` pass as `since_date`. For a
  never-scraped team the pre-window history becomes unreachable.
- **CLAUDE.md is now factually wrong** — it states in bold that `process_missing_games.py`
  writes neither `team_scrape_log` nor `last_scraped_at`. That file is being edited by a
  concurrent session, so it was flagged rather than touched.

---

## Resolution (2026-08-27)

Direction chosen: ship with the chunking fix, keeping the never-scraped free pass so no
team is permanently excluded.

**Blocker 1 fixed.** `refresh_team_scrape_activity` now does one keyset page per call and
`refresh_team_scrape_activity.py` walks the table, feeding each page's last id back as
`p_after`. Measured on production: **289 ms for a 2,000-team page**, every join an index
scan, no sequential scan of `games`. That is ~31s total across ~106 pages, each call at
3.5% of the 8-second budget. The inert `SET LOCAL statement_timeout` is gone, and a test
asserts it does not come back.

**Blocker 2 accepted, not fixed.** The filter binds on the top-up today and on the two
weekly producers only as their backlogs drain. The plan's headline metric should be read
accordingly: expect movement in games-found-per-scrape on bulk drains, not on the weekly
cadence.

### Applied

- `|| true` on the workflow's row-count extraction. Demonstrated locally: without it the
  step exits 1 and never reaches the `$GITHUB_OUTPUT` write.
- Predicate guards now resolve functions by NAME across every migration and read the newest
  definition of each, so they cannot decay when a function is superseded.
- `IS DISTINCT FROM` is asserted against the extracted UPDATE statement (487 chars), not the
  whole file. Mutation-checked: removing the guard now fails.
- New assertion pinning the full five-branch disjunction. Mutation-checked: the OR→AND flip
  now fails, as does dropping a branch.
- Assertions on the two date aggregates, the merge expansion, the dry-run branch, and the
  keyset paging contract.
- Corrected the stale 40%-attrition figure and the `_is_scrapeable_team` rationale in
  `drain_queue.py`, plus a note that it may only read columns `_fetch_team_metadata` selects.
- Docstring notes on both enqueue callers, and a note in the shared-predicate migration that
  every table reference in the block must stay schema-qualified.
- Removed the `--self-test` / `PITCHRANK_SELF_TEST` scaffolding. Two reviewers flagged it:
  the stub returns before the real summary print, so it validated a literal it had written
  itself, and a leaked env var would have made a live run report `Updated: 0` and exit 0
  having done nothing. Thirteen unit tests now drive the real path, matching the workflow's
  exact grep pattern.

### Deferred — worth their own change

1. **`_flush_scrape_log` is a third copy of `_bulk_log_team_scrapes`.** `scrape_games.py` and
   `drain_queue.py` already carry byte-identical bodies; `src/etl/bulk_ops.py` is the shared
   home all three already import from. Lifting it needs `provider_id` per entry rather than
   per call.
2. **One definition of the predicate via a `security_invoker` view.** Function inlining is
   blocked by the `EXISTS` sublink, but a view is subquery-pulled-up rather than inlined, so
   the plan is unchanged. Needs an explicit `REVOKE SELECT ... FROM anon, authenticated`.
   Would retire three copies and most of the drift test.
3. **`find_discovery_teams`'s `team_flags` CTE is now redundant.** `has_future` and
   `has_recent` are exact rewrites of `last_fixture_at`, which this change materialises — and
   the column is more correct, since it resolves merges. Trade-off: up to a week stale.
4. **`process_missing_games` advances `last_scraped_at` after a window-limited scrape.** That
   column is also the incremental watermark `drain_queue`/`scrape_games` pass as `since_date`,
   but this path only covers `[game_date-90, game_date+90]`. For a never-scraped team the
   pre-window history becomes unreachable. Reachable only via the two manual-dispatch
   consumers today, which is why it was rated P2 — but those are the same surface where this
   change's benefit lands.
5. **CLAUDE.md's `team_scrape_log` section** needs its bold claim corrected.
