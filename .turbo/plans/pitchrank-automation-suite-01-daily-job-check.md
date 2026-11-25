---
status: done
spec: .turbo/specs/pitchrank-automation-suite.md
---

# Plan: Daily Job Check

## As built

Implemented on `feat/scheduled-jobs-check` on 2026-11-25. Where the code differs from the steps
below:

- **The SQL ran locally after all.** PostgreSQL 16 and 17 are installed under
  `C:\Program Files\PostgreSQL\`, though not on PATH. The integration tests and all four SQL
  mutations ran against a throwaway PostgreSQL 17 cluster in the scratchpad, so the four
  temporary CI commits in Verification were not needed to prove them.
- **Mutation checks: all 19 killed their named test.** That covers the 11 unit mutations and 4 SQL
  mutations listed, plus four half-condition mutations added during implementation: the queue
  stall rule's age and `completed_recently` halves, a counted run's job conclusion, and the
  failure flag's clearing.
- **A templated step `name:` gives no display name**, instead of `Run <uses>`. GitHub evaluates
  such a name, so neither spelling would match.
- **"Frequent" is "fires more than once a day".** For one cron, that is the same test as a gap
  under 24 hours between due times.
- **A dry run exits 1 when a check is incomplete**, matching the live run, so the pre-merge dry
  run exits 1 on the checker's own missing workflow entry.
- **The count line reads `checks 5, ...`**, one per check: rankings, imports, quiet imports, scrape
  queue and scheduled jobs.
- **The heartbeat stops at the first counted run, newest first.** Checking every run of the
  15-minute drainer would cost one jobs call per run.
- **GitHub's state list unreadable** gives one incomplete line, which says the schedule and import
  checks did not run. The rankings and queue checks still run.
- **The local dry run on 2026-11-25** matched the expected list in Verification line for line, and
  made 78 GitHub reads.

Review round 1 (seven reviewers) changed these:

- **Only a finished run counts.** The TGS chain's `prepare` job ("Compute shard gate") succeeds
  before its scrape starts, so an unfinished link used to clear an earlier red link.
- **Paged lists are reconciled with `total_count`.** Runs and jobs share one pager. It keeps a
  record that appears on two pages once, and treats fewer records than the first page's total as
  unreadable.
- **A workflow with a problem has its run list read again** before the problem is reported. The
  `github-actions-debug` skill records that a filtered list sometimes comes back empty or stale.
- **Shapes the checker cannot judge are reported incomplete, not half-checked:**
  - a cron restricting the day of month or the month (it can go more than 15 days between due
    times);
  - a schedule entry with no `cron` or with a non-UTC `timezone`;
  - two series that cannot be told apart by start time, meaning a daylight-saving pair beside
    another cron, a more-than-daily cron beside another, or two daily crons.
- **Malformed records are incomplete, not a pass:** a non-text workflow state, a step with no
  name, a provider row missing a count, or a non-list jsonb column.
- **Two-series lines** say "no counted run for the one due D", and give the last counted run
  before D.
- **Accepted limit (the owner, 2026-11-25).** On `compare-live-monitoring.yml` and on this checker's
  own daily-plus-Tuesday schedules, a weekly run that never fires is not reported as such. The
  next daily run fills its slot, so the miss shows only as a one-day false alarm on the daily
  line. The run list does not say which cron started a run, and no timing rule tells a late daily
  run from an on-time weekly one. The rule that fixes this case hides the Monday 18:17 /
  Tuesday 17:00 / Wednesday 10:00 case the slots were built for. Build 2 separately checks that
  this checker ran.

Review round 2 changed these:

- **The re-read merges both reads by run id**, keeping the later copy. A stale second read used to
  replace the first, which could hide a failure the first read had seen.
- **Values from GitHub and the database pass through `text_of`, `count_of` and `records_of`**, so a
  blank state, a boolean count, a non-list column or a null id makes its check incomplete instead
  of reading as valid. The workflow list now uses the same pager as runs and jobs.
- **Schedule shapes:** two series that share more than one weekday, or share one at the same time
  of day, are refused as "schedules this check cannot tell apart". This also covers two daily
  crons. A present but empty `schedule:` is refused. A non-UTC timezone gets its own reason. A
  `jobs:` or `steps:` that cannot be iterated is reported for that file alone rather than stopping
  the run. A shape that can be iterated, such as a mapping under `steps:`, is skipped instead;
  GitHub refuses such a file anyway.
- **Two-series lines** with nothing counted before the missed slot say "no earlier counted run in
  15 days".
- **Superseded step text.** These signatures in the steps below changed:
  - `build_series(crons)` takes the cron strings, and `Workflow.series` replaces `Workflow.crons`;
  - `missed_due(series, due, assignment, counted) -> bool`;
  - `failure_flag(runs, counted, bad=FAILED)`, which the chain links call directly, with no stand-in
    series.

  Other step text that no longer matches:
  - `Cron` keeps only minutes, hours and weekdays;
  - the SQL quoted in Step 3 now names this week's Monday 12:30 once, in a `this_week` CTE;
  - `CHECK_ERRORS` also includes `AttributeError`;
  - the workflow list is read as `workflows?per_page=100&page=N`;
  - the email lines quoted in Steps 2-4 are paraphrases. The code's strings are authoritative, for
    example "the scheduled run started 2026-11-23 ended cancelled", "… stuck in processing for over
    6 hours; oldest stuck request claimed …" and "N daily-or-weekly schedules on time".

Review round 3 changed these:

- **The merge keeps a finished run.** A stale second-read copy of the same attempt, still in
  progress, no longer replaces it. A rerun, which is a higher attempt, still does.
- **The remaining database values are validated:** the `complete` and `completed_recently` flags
  (`flag_of`), the snapshot date, and the snapshot count, all checked before a verdict is chosen.
- **The loader refuses an `on:` list or string that names `schedule` with no entries.** A non-UTF-8
  file gets its own reason.

## Context

Scheduled jobs on this repo fail quietly. GitHub skips and delays scheduled runs, an import can go
green while importing nothing, and the weekly ranking run ends `cancelled` at the 6-hour runner cap
after saving rankings. Today the owner finds these by hand, days later.

This plan adds a daily GitHub Actions check (build 1 of the spec). It reads the data each job
should have changed, and the GitHub run history, and emails the owner only when something did not
do its work. A separate weekly trigger sends a Tuesday all-clear, so silence never hides a dead
checker.

It is stateless and public-repo safe:
- Every date in an email is labelled with what it measures, and is derived from the data on each
  run.
- Actions logs print counts only.
- An unreadable source or a rejected email fails the run (R31). The after-ranking follow-up
  (build 2) relies on that to tell a working checker from a dead one.

It covers spec requirements R1–R10 and R31.

### Decisions made at expansion

- **Every database read goes through the Supabase Management API's read-only query endpoint.**
  The endpoint is `POST https://api.supabase.com/v1/projects/<ref>/database/query/read-only`,
  authorized by the `SUPABASE_ACCESS_TOKEN` repo secret, which already exists and is used by
  `compare-weekend-tuning.yml`. Its pattern is `src/predictions/archive_inputs.registered_inventory`.
  - It is the only path from a runner that can run the shared SQL file verbatim. No
    `exec_sql`-style RPC exists in any migration. The database host is IPv6-only, so runners cannot
    connect directly (`update-missing-club-and-state.yml:45-48`).
  - It is the same file the follow-up skill (build 2) runs through the read-only MCP
    `execute_sql`.
  - Every response is checked for `transaction_read_only = on`.
  - Because every check uses this endpoint, the job holds no service-role key.
- **GitHub reads use `gh api` in a subprocess with `GH_TOKEN: ${{ github.token }}`.** This mirrors
  `scripts/catch_up_compare_forecasts.github`, and the new code is GET-only. Jobs and steps are
  fetched lazily, once per run, and only for runs a decision needs, which keeps the call count well
  under the token's rate limit.
  - **One failure stops all GitHub reads.** After the first read that fails all three attempts,
    every later read fails at once. One GitHub outage therefore costs about 3 minutes, not one
    retry cycle per workflow, and the incomplete-check email still goes out inside the 20-minute
    job.
- **The daily cron is `41 6 * * *`.** GitHub fires daily crons 7–12 hours late (spec R6), so the
  email usually lands in the Arizona morning. The all-clear cron is exactly `0 19 * * 2`.
- **The cadence rule, made exact.** For each series, let D be its latest due time with
  D + grace ≤ now, where grace is 24 hours (25 for a daylight-saving pair, below). The series is
  flagged when no counted run of that series started at or after D.
  - This is R6's "interval plus 24 hours" measured from the previous due time. A missed Monday
    import alerts from Tuesday at its due minute.
  - Tuesday-and-Friday gaps of 3 and 4 days come out of the actual due times.
  - **Due times before a workflow existed are dropped.** The cut-off is the workflow's
    `created_at` in GitHub's workflow list, so a newly merged workflow, the checker included, is
    not reported as missed before its first slot has had its grace. `enqueue-opponent-frontier.yml`
    was created 2026-11-24, after that day's 08:43 UTC slot.
  - **A daylight-saving pair gets 25 hours of grace.** Runs count from the earlier hour, which
    the summer slot needs, while the deadline allows for the later hour, which the winter slot
    needs.
- **The rankings baseline is the newest snapshot dated before the day of this week's ranking
  start.** The calculator fixes the snapshot's date when the run starts (`src/rankings/calculator.py:2722`,
  `today = resolve_as_of(today)`), and stamps `last_calculated` when it publishes.
  - A scheduled run starts 7–12 hours late, often on Monday evening UTC, and publishes on Tuesday.
    A baseline of "before the publication's own date" would then be the run's own snapshot.
  - The 2026-11-23 scheduled run started 11-24 00:08 UTC.
  - On 2026-11-25 this compares 150,056 rows with 150,562 for 2026-11-19 (99.7%). R2's example
    compared with the 2026-11-23 snapshot, which a run started on 11-23 wrote, so under this rule
    it is not earlier than the week's start.
- **The mode comes from the environment.** The workflow sets
  `WEEKLY: ${{ github.event.schedule == '0 19 * * 2' }}`, and the script runs in weekly mode when
  `--weekly` is passed or `WEEKLY` is `true`. No shell conditional can drop the flag.
- **Local configuration.** `main()` loads `C:\PitchRank\.env`, then `.env.local` with override,
  exactly as `scripts/find_cross_provider_duplicates.py:63-68` does. A dry run on the owner's PC
  therefore finds `SUPABASE_URL`; `SUPABASE_ACCESS_TOKEN` comes from the user environment.
- **No separate secrets step.** The script checks its own configuration.
  - A missing database setting makes each database check "check incomplete".
  - A missing `RESEND_API_KEY` is checked up front, so it fails a live run even on a quiet day
    with nothing to send.
  - Either way the run exits 1, and the count line names the missing setting (its name, never its
    value).
- **Productive steps are matched by display name.** The match uses a step's literal `name:`, else
  `Run <uses>`, else `Run <first line of run>`. Verified on run 45215524977: GitHub lists every YAML
  step in order, skipped ones included, under its YAML name.
- **More-than-daily series in the all-clear** show "fired N of M scheduled times in the last 7 days
  (K succeeded)". This needs no jobs calls.

### Risks found at expansion

- **A season wind-down alerts daily for about four weeks, not once.** R4's baseline is weeks 3–6
  back, so the last busy week keeps the average at or above 50 until it leaves the baseline.
  - A provider that drops from 465 games a week to about 5 is flagged every day for four weeks,
    because R9 repeats persisting problems daily.
  - On 2026-11-25 the rule already flags `affinity_ga` (1 and 4 new games against a 98.5 average)
    and `demosphere` (1 and 15 against 464.5).
  - This plan implements R4 as written. The spec's "can still alert once" understates it.
- **`rankings_full.last_calculated` is a naive timestamp** (`scripts/calculate_rankings.py`,
  `pd.Timestamp.now()`). It is UTC on a runner, but a run on the owner's PC stamps Arizona time,
  and the timestamp column reads it as UTC, 7 hours early.
  - A PC publication on Monday before 12:30 PM Arizona therefore reads as older than the 12:30 UTC
    cutoff, and the check reports it stale once the 30 hours pass. The grace does not change that
    comparison.
  - The weekly publication runs on Actions, so this needs a hand-run PC publish, and the owner
    will recognise the alert.
- **`build_logs.started_at` is rewritten on every update** (`src/etl/enhanced_pipeline.py`,
  `_log_build_metrics`). The heartbeat therefore reads it as "last logged", which is what a
  heartbeat needs.
- **A job gated off by a repo variable reads as a missed run.** The five `compare-*` and
  `weekly-prospective-refresh` workflows gate their job on a `vars.*` value, and all five ran their
  job on 2026-11-24. Switched off, their runs end with conclusion `skipped`, which GitHub gives a
  run whose only job a job-level `if:` turned off (`claude.yml`'s runs show it). That is not a
  counted run. The line says "ran but skipped its work", so the cause is clear.
- **Series assignment is a heuristic.** The REST API does not say which cron started a run.
  - For the one workflow with two series, `compare-live-monitoring.yml`, runs are matched to due
    slots in order (Step 2), the owner's choice on 2026-11-25. R7's "most recent due time" rule
    would have filed the Monday daily run of 2026-11-23, which started 18:17 UTC, under the Monday
    series, and reported the daily run missed the next day.
  - A missing run is still flagged, though it can be named under the other series.
- **Only scheduled runs clear a line** (the owner's choice, 2026-11-25). A job fixed by hand
  keeps its line in the daily email until its next scheduled counted run, up to 6 days for a
  weekly job.
  - The reason: a manual run of a guarded scraper with `dry_run` set still runs its scrape step.
    Its guard is skipped on `workflow_dispatch`, so `should_run` is empty and `!= 'false'` holds.
    It would count, and would clear a real failure with nothing imported.
  - Human-started and `workflow_run` runs are therefore never listed. The one listed dispatch
    event is the TGS chain's own bot-dispatched links (Step 2, Chains).
- **The access token is account-wide.** Adding it to a second workflow widens where it is exposed.
  It is passed only to the check step's env, and the workflow's permissions are read-only.
- **The follow-up (build 2) depends on three things here:**
  - the SQL file's path;
  - its output column names, documented in the file's header;
  - this workflow ending `success` only when every source was read and every required email was
    accepted.

  Renaming any of them breaks build 2.

## Pattern Survey

All citations are against `origin/main` @ 908e90c85.

### Analogous Features
- **`scripts/investigate_missing_game_requests.py:807-843`.** The closest analogue: an Actions job
  that emails the owner.
  - It gets its client from `get_client()` in `find_cross_provider_duplicates`.
  - `--dry-run` prints `render_text` and returns 0 (`:831-834`). It sends nothing and writes
    nothing.
  - It returns 1 when `send_email` returns `False` (`:838-840`).
  - `ALERT_EMAIL = os.environ.get("ALERT_EMAIL", ...)` is at `:82`.
  - Logging is `logging.basicConfig(INFO, "%(message)s")`, with
    `getLogger("httpx").setLevel(WARNING)` (`:78-80`).
  - The docstring (`:21-22`) says "A live run logs counts only, because Actions logs are public."
  - The HTML is inline-styled: Arial, `#0B5345` headings, a muted footer and `#fff4d6` caveat
    boxes (`render_html` `:733-786`).
- **`.github/workflows/investigate-missing-game-requests.yml`.**
  - Its cron is `'50 */3 * * *'` (`:10`).
  - The comment at `:18` reads "No dry-run input … Actions logs are public", enforced by
    `tests/unit/test_investigate_missing_game_requests.py:640-648`.
  - It has `concurrency` with `queue: max` (`:22-25`).
  - Its workflow-level env carries `SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}`
    and `RESEND_API_KEY` (`:27-31`).
  - Its steps: `checkout@v5` with `ref: main` (`:40-43`); `setup-python@v6`, Python 3.11 with pip
    cache (`:45-49`); `pip install -r requirements.lock` (`:51-54`); a "Verify secrets" step that
    echoes yes or no (`:56-64`).
  - It sets `timeout-minutes: 20` (`:37`) and has **no `permissions:` block**.
- **`scripts/check_stuck_signups.py:203-238`.**
  - It imports `send_email` (`:45`) but uses it only for buyer reminders (`:267`).
  - The admin digest goes through its **own** `requests.post` to Resend, which logs the full
    `resp.text` (`:234`).
  - `ALERT_EMAIL` has the same default (`:55`).
  - Addresses are kept out of stdout because the logs are public (`:311-314`).
  - A dry run exits 1 to mean "action needed" (`:330-332`), and a failed send exits 1 (`:336-338`).
- **`scripts/reconcile_stripe_subscriptions.py:225-245`.** Its own `requests.post` to Resend, with
  no `send_email`, logs the full `resp.text` (`:243`). A failed send does **not** fail the run.
  `ALERT_EMAIL` is at `:45`.
- **`scripts/team_cleanup/advance.py:247-257`.** `email()` calls `send_email` to
  `CLEANUP_OWNER_EMAIL`. Without `--execute`, it prints "DRY RUN -- would email".
- **`scripts/catch_up_compare_forecasts.py:93-150`.** The only reader of GitHub jobs and steps.
  - `github()` shells out to
    `gh api -H "X-GitHub-Api-Version: 2026-03-10" repos/$GITHUB_REPOSITORY/actions/<path>`. It
    retries a GET 3 times and never retries a POST.
  - It reads `workflows/{wf}/runs?branch=main&per_page=100` (`:113`), with no pagination.
  - It reads `runs/{id}/jobs`, then `jobs[0]["steps"]` as name → conclusion (`:143-150`).
  - Its workflow, `compare-forecast-catchup.yml`, sets job-level
    `permissions: contents: read, actions: write` (`:22-24`) and `GH_TOKEN: ${{ github.token }}`
    (`:36`).
  - The module imports prospective-prediction code (`:10-11`), so the new script mirrors
    `github()` rather than importing it.
- **`scripts/team_cleanup/apply_stage.py:283,418-430`.** `gh_runs()` calls
  `gh api -X GET repos/{owner}/{repo}/actions/runs -f status=… -f per_page=100`, and **refuses a
  full page** rather than paging.
- **`scripts/pr_wait.py:86-94`.** `gh_pages()` uses `gh api --paginate --slurp` and flattens a list
  of lists. `/actions/runs` pages are objects, not lists.
- **`.claude/hooks/session-start.sh:46-75`.** The existing scheduled-run health check.
  - It queries each scheduled workflow separately, because one 15-minute job failing in a loop
    floods any shared window (`:34-38`).
  - The awk chain detector (`:70-75`) marks a file whose uncommented `gh workflow run` line names
    the file itself.
  - A chain seed counts as failing on any finished result but success (`:49-53`).
  - It reads chain links with `--branch main --user 'github-actions[bot]' --event workflow_dispatch`
    over 8 days (`:59-64`).
  - For non-chain workflows it flags failure only, because "frequent jobs end cancelled routinely"
    (`:66-68`).
  - It is tested in `tests/unit/test_claude_hooks.py:682-714`.
- **`.claude/skills/github-actions-debug/SKILL.md:45-62`.** GitHub skips most scheduled runs here:
  16 of about 42 for the missing-game report, 11-18 to 11-23. Runs start 1–3 hours late. The file
  shows how to count runs against cron slots.
- **`scripts/marketing_pipeline.py:327-352`.** The existing rankings-freshness check:
  `fetch_rankings_last_calculated` takes the max via `.order(desc).limit(1)`, and
  `rankings_are_stale` uses 8 days.
- **`scripts/enqueue_opponent_frontier.py:598,609-615`.** It lists IDs only when
  `GITHUB_ACTIONS != "true"`. A count of rows stuck in processing for over 24 hours (`:506`) exits
  1.
- **`scripts/retire_stranded_scrape_requests.py:61,68-92`.** Its stranded-row query is
  `status='processing'`, `processed_at < cutoff`, ordered by `processed_at,id`. Ties are huge: one
  bulk claim stamped 5,981 rows with a single timestamp. Its default floor is 24 hours.
- **`src/predictions/archive_inputs.py:82-121` and `scripts/benchmark_compare_form.py:111-132`.**
  The only precedent for raw SQL from Python.
  - They POST to `https://api.supabase.com/v1/projects/{ref}/database/query/read-only` with
    `SUPABASE_ACCESS_TOKEN` and `allow_redirects=False`.
  - The query selects `current_setting('transaction_read_only') AS read_only`, and the code refuses
    any result that is not `"on"`.
  - The response is a JSON list of row dicts.
  - It runs on Actions in `compare-weekend-tuning.yml:30`.
  - `gh secret list` shows `SUPABASE_ACCESS_TOKEN` exists. There is **no `ALERT_EMAIL` secret**.
- **`.github/workflows/or-scraper.yml:4-9,56-79`** (likewise `ut-scraper.yml:57` and
  `wa-scraper.yml:53`). The daylight-saving pair.
  - Two crons sit one hour apart.
  - A step with `id: guard` and `if: github.event_name == 'schedule'` compares
    `github.event.schedule` against `TZ=America/Los_Angeles` and writes `should_run`.
  - The productive steps carry `if: steps.guard.outputs.should_run != 'false' …` (`:82`, `:178`).
  - A skipped run therefore still ends with the job `success` and the scrape and import steps
    `skipped`.
  - These three files are the only ones with a guard.
- **`.github/workflows/compare-live-monitoring.yml:32`.** One job tells two crons apart with
  `github.event.schedule == '30 17 * * 1'`.
- **`tests/unit/test_team_cleanup_apply_stage.py:996-1037`.** The only cron parser in the repo, and
  it is test-only.
  - `_crons()` uses `doc.get("on", doc.get(True))`.
  - `_cron_values()` handles `*`, lists, ranges and steps.
  - `_fires_after_propose()` maps weekdays into Arizona's UTC-7 (cron Sunday is 0 or 7).
- **`dashboard.py:101-140`.** Import stats count `games` by `created_at` with
  `select('id', count='exact', head=True)`, and read `build_logs` ordered by `started_at`.
- **`tests/unit/test_age_rollover_freeze_coverage.py:102-135` and
  `tests/unit/test_gotsport_event_scrape_zenrows_coverage.py:93-139`.** Guards that derive their
  list from the workflow YAML.
  - Each one globs `*.yml`, loads it with `safe_load`, walks jobs → steps → `run` and matches
    `scripts/<name>` substrings.
  - Each has an anti-vacuity test, "the scan finds known members".

### Reusable Utilities
- **`src/utils/resend_email.py:17-37`, `send_email(to, subject, html) -> bool`.**
  - Its logger is `logging.getLogger(__name__)` (`:10`), i.e. `src.utils.resend_email`.
  - It emits three warnings: no key (`:21`), the exception type only (`:32`), and
    `"Resend answered %s: %s", status, resp.text[:300]` (`:36`).
  - **No caller filters or re-levels that logger.**
  - Its tests (`tests/unit/test_resend_email.py:19-73`) monkeypatch `resend_email.requests.post`
    and use `caplog`.
- **`scripts/find_cross_provider_duplicates.py:146-151`, `get_client()`.** It builds
  `create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY)` and raises `SystemExit`
  when either is unset. At `:154-166`, `page(build, order_col, size)` is an ordered paginator.
- **`src/outreach/_db.py:18-31`, `get_client()`.** It loads `.env.local`, then `.env`.
- **`scripts/enqueue_helpers.py:21,41,62`.** `_paged`, `_keyset(query, key="id")` and `_chunks`
  (at most 100 for `.in_`).
- **`scripts/skill_check_offline.py:554-562`.** `workflow_steps(doc)` and `step_is_off(job, step)`.
  **Importing the module has a side effect:** `sys.addaudithook(_audit)` runs at import (`:398`).
- **`scripts/skill_check_offline.py:77-130,165-215`, `Database`.** A shared in-memory Supabase that
  records at `execute()`. It refuses any `select()` option, so `count="exact"` and `head=True` are
  not modelled.
- **`tests/unit/test_investigate_missing_game_requests.py:84-185,1094-1115`.** The closest Supabase
  double.
  - It checks columns and refuses `range()` without `order()`.
  - It applies `update()` only in `execute()`.
  - Its fixtures monkeypatch `img.get_client`, `img.send_email` and `img.datetime`.
- **`tests/unit/test_batch_drain_queue.py:81-201`.** The fullest `requests` double.
  - `FakeResponse` treats `content` as the truth and decodes `text` from it.
  - `FakeSession` routes by method plus path with query, honours `allow_redirects` and records
    every call.
  - Its JSON fixtures live in `tests/fixtures/zenrows_batch/`.
- **`scripts/investigate_missing_game_requests.py:86,195-217`.** The date helpers:
  `ARIZONA = timezone(timedelta(hours=-7))`, `plural`, `nice_date` and `window_label`. Importing
  this module pulls in heavy dependencies (`:49-76`).
- **`.claude/skills/review-workflows/scripts/audit_workflows.py:49-106,160,286`.** `WorkflowFile`,
  `load_workflows`, `iter_jobs`, `iter_steps`, and the `CRON_LINE` and `SCRIPT_REF` regexes.
  - It is skill-local: nothing in `scripts/`, `tests/` or `.github/` imports it, and it has no
    tests.
  - It never reads triggers.
- **`src/etl/enhanced_pipeline.py:3219-3260`, `_log_build_metrics`.** It writes:
  - `stage='game_import'`, `provider_id`, and `parameters={provider_code, batch_size, dry_run}`;
  - naive `started_at` and `completed_at` values, rewritten on every update.

  It writes on dry runs too.
- **`PROVIDER_CODE` constants.**
  - `scripts/import_athletes2events_event.py:90` "athletes2events"
  - `scripts/import_demosphere.py:105` "demosphere"
  - `scripts/import_heartland.py:116` "heartland"
  - `scripts/import_htgsports_event.py:125` "htgsports"
  - `scripts/import_soccereventsgroup_event.py:79` "soccereventsgroup"
  - `scripts/import_tourneycentral_event.py:121` "tourneycentral"
  - `scripts/import_yssl.py:102` "yssl"

  `import_demosphere.py`, `import_heartland.py` and `import_yssl.py` shell out to
  `import_games_enhanced.py <csv> PROVIDER_CODE` only when there are records and the run is not a
  dry run (yssl `:1384-1389`), so a week with no games writes no `build_logs` row.

### Convention Anchors
- **Scheduled import workflows and their providers.** Every provider argument is a literal. Matrix
  workflows run several jobs.
  - `ea-scraper` (matrix) → `modular11_ea`
  - `ga-scraper` → `affinity_ga`
  - `hi-scraper` → `affinity_hi`
  - `mlsnext-kitman-scraper` → `mlsnext_kitman`
  - `or-scraper` (guard) → `affinity_or`
  - `ut-scraper` (guard) → `affinity_ut`
  - `wa-scraper` (guard) → `affinity_wa`
  - `playmetrics-scrape-import` → `playmetrics`
  - `tgs-event-scrape-import` (the only chain) → `tgs`
  - `demosphere-scraper` → `import_demosphere.py`
  - `heartland-scraper` → `import_heartland.py`
  - `yssl-scraper` → `import_yssl.py`
  - `process-missing-games` → `process_missing_games.py`
  - `tgs-event-scrape-import.yml:262` runs `scripts/extract_and_import_tgs_teams.py`, which is not
    a `scripts/import_*.py` path.
  - Not scheduled: the two Modular11 workflows and `playmetrics-tournament-scrape-import`.
- **Other crons that matter.**
  - `calculate-rankings` `30 12 * * 1`. It also runs on `workflow_run` and has no
    `timeout-minutes`.
  - `tgs-score-reconcile` `23 5 * * 2,5`, which already declares `actions: read`.
  - `compare-live-monitoring` has two series: `20 6 * * *` and `30 17 * * 1`.
  - More often than daily: `process-missing-games`, `backfill-unknown-team-names`,
    `check-stuck-signups`, `reconcile-stripe-daily`, `compare-forecast-catchup` and
    `investigate-missing-game-requests`.
- **Disabled in GitHub now:** `data-hygiene-weekly.yml` and `auto-merge-queue.yml`, both
  `disabled_manually`.
- **YAML loading.** Every workflow spells `on:` bare. Tests use `safe_load` with
  `doc.get("on", doc.get(True))`, or `[True]`, or `yaml.BaseLoader`. There is no shared YAML helper
  under `tests/`.
- **Rankings facts.**
  - `last_calculated = pd.Timestamp.now()` is naive, and one stamp is shared per run.
  - Stale-row cleanup only warns on failure.
  - `ranking_history` is `UNIQUE(team_id, snapshot_date)`. Its `snapshot_date` defaults to
    `date.today()` (`src/rankings/ranking_history.py:74-75`), and it is upserted inside the
    calculator before `rankings_full` is published.
  - Indexes exist on `rankings_full.last_calculated`, `games.created_at`, `build_logs.started_at`
    and `ranking_history.snapshot_date`.
- **`scrape_requests` facts.**
  - The statuses written are exactly `pending`, `processing`, `completed` and `failed`.
  - `processed_at` is stamped on claim.
  - `completed_at` is stamped on both completed and failed rows.
- **No raw-SQL path besides the Management API.** There is no `exec_sql` RPC, runners cannot reach
  the database directly, and no Python reads a `.sql` file at runtime.
- **No cron library is installed.** `requirements.lock` has `pyyaml==6.0.2` and no `tzdata`.
- **Guard tests a new scheduled workflow must satisfy.**
  - A CLAUDE.md workflow-table row (`tests/unit/test_agent_doc_references.py:387-399`).
  - A `NOT_A_WRITER` entry (`tests/unit/test_team_cleanup_apply_stage.py:948,1040-1046`).
  - No `gh workflow run`, `/dispatches` or `createWorkflowDispatch` text anywhere in the file,
    comments included (`tests/unit/test_claude_hooks.py:703-714`).
  - Any piped `$(…)` under pipefail needs `||` (`tests/unit/test_workflow_pipefail_substitutions.py`).
- **Code layout.**
  - `scripts/<name>.py` with `sys.path.insert(0, ROOT)`, packaged imports, a Usage docstring, and
    `main() -> int` with `raise SystemExit(main())`.
  - Tests are `tests/unit/test_<script>.py`, with fixtures under `tests/fixtures/<topic>/`.
  - CI runs `pytest tests/ --ignore=tests/test_enhanced_pipeline.py` on Linux with a `postgres:17`
    service and `PROSPECTIVE_TEST_DATABASE_URL` (`ci.yml:34-45`). The `postgres_database` fixture
    in `tests/integration/conftest.py` creates a throwaway database per module.

### Proposed Alignment
- **Script, email and workflow shape:** follow `investigate_missing_game_requests.py` and its
  workflow.
- **GitHub reads:** mirror `catch_up_compare_forecasts.github()` and the `session-start.sh`
  semantics (branch `main`, bot-dispatched chain links, failure-only for frequent jobs).
- **YAML and cron model:** build it fresh in `scripts/`, with `safe_load` and
  `doc.get("on", doc.get(True))`.
- **SQL:** run every query through the Management API read-only endpoint, as
  `archive_inputs.registered_inventory` does.
- **The Resend body log:** mute it at the `src.utils.resend_email` logger.

## Implementation Steps

1. **Workflow schedule model** (`scripts/check_scheduled_jobs.py`, a new script laid out like
   `scripts/investigate_missing_game_requests.py`).
   - **Loading.** `load_workflows(root: Path) -> tuple[list[Workflow], dict[str, str]]` reads
     `.github/workflows/*.y*ml` with `yaml.safe_load`, matching both extensions as
     `tests/unit/test_team_cleanup_apply_stage.py`'s `_workflows()` does. It takes triggers from
     `doc.get("on", doc.get(True))` and keeps the files whose triggers include `schedule`.
     - Each file is parsed inside its own `try`. Any of these leaves the file out of the first
       list and records basename → reason in the second:
       - a `yaml.YAMLError`;
       - a `ValueError` from `parse_cron`;
       - an `UnmappedImporter` from the provider mapping;
       - an `OSError` from reading an importer script, for example `FileNotFoundError` when a
         workflow still names a renamed importer.
     - Those parse errors become findings only after `workflow_states()` is read. A file GitHub
       reports as not `active` is listed only among the switched-off workflows; any other file
       gets one "check incomplete: <file>" finding.
     - The other workflows load and are checked normally.

     A frozen `Workflow` dataclass carries:
     - `file` (the basename);
     - `name`;
     - `crons` (strings, in YAML order);
     - `guarded` (any step in any job has `id: guard`);
     - `chain`;
     - `productive_names` and `setup_names` (below);
     - `importer_steps` (below).
   - **Cron parsing.** `parse_cron(expr: str) -> Cron` takes the five fields.
     - It accepts `*`, `N`, `a-b`, `*/n`, `a-b/n` and comma lists. Day of week runs 0–7, and 7 is
       Sunday.
     - It raises `ValueError` on names (`MON`), `L`, `W` or `#`, and on an expression that
       restricts both day of month and day of week. No workflow on main uses those forms.
     - `load_workflows` turns that error into the workflow's "check incomplete" finding (R31)
       rather than guessing.
   - **Due times.** `due_times(cron, start, end) -> list[datetime]` expands day by day in UTC, from
     each matching day's hours × minutes.
   - **Series.** `build_series(wf) -> list[Series]` applies R6.
     - It merges two entries only when minute, day of month, month and day of week are identical,
       and both hour fields are single integers exactly 1 apart.
     - A merged series takes the **earlier** hour's due times, because both crons fire every week
       and the guard runs only one of them.
     - A merged series also has `Series.grace = timedelta(hours=25)`, so the deadline allows for
       the later hour. Every other series has 24 hours.
     - Every other entry is its own series.
     - `Series.frequent` is true when the shortest gap between consecutive due times is under
       24 hours.
     - `Series.label` is the cron text, or both crons joined with " / ".
     - Today, `or-scraper.yml`, `ut-scraper.yml` and `wa-scraper.yml` each yield one merged series,
       and `compare-live-monitoring.yml` yields two.
   - **Chains.** `chain` mirrors the awk test in `.claude/hooks/session-start.sh`: some line that
     is not a comment contains `gh workflow run` and a whitespace-separated word naming the file
     itself, with quotes and any leading path stripped. On main only `tgs-event-scrape-import.yml`
     matches.
   - **Step display names.** `display_name(step) -> str | None` returns:
     - the literal `name:` when it has no `${{`;
     - else `"Run " + uses`;
     - else `"Run " + first line of run`;
     - else `None`.
   - **Productive and setup names.**
     - For a guarded workflow, `productive_names` holds the display names of steps whose `if:`
       string contains `steps.guard.outputs`.
     - `setup_names` holds the display names of three kinds of step:
       - steps whose `uses` starts with `actions/checkout`, `actions/setup-` or `actions/cache`;
       - steps whose literal `name:` starts with `Install`, case-insensitive. There are 55
         `Install dependencies` steps across `.github/workflows/`, plus `Install deps` and
         `Install frontend dependencies`. Some carry retry loops, comments and `echo` lines, for
         example `calculate-rankings.yml:92` and `tgs-score-reconcile.yml:59`;
       - unnamed `run` steps whose every non-empty, non-comment line starts with `pip install`,
         `pip3 install`, `python -m pip install`, `npm ci`, `npm install` or `mkdir`.
     - `GITHUB_OWN_STEP_NAMES = {"Set up job", "Complete job", "Initialize containers",
       "Stop containers"}`, and any name starting with `"Post "` also counts as GitHub's own.
   - **Provider mapping (R3).** `importer_providers(run_text: str, root: Path) -> set[str]`
     splits each non-comment line of a step's `run` into invocations at `&&`, `||`, `;` and `|`,
     and maps each invocation on its own:
     - `scripts/import_games_enhanced\.py\s+("[^"]*"|'[^']*'|\S+)\s+([a-z0-9_]+)(?=\s|$)` gives
       group 2. The look-ahead means the whole provider argument must be literal:
       `affinity_${STATE}` maps to nothing and raises, instead of mapping to `affinity_`;
     - any other `scripts/(import_[a-z0-9_]+)\.py` is resolved by reading
       `scripts/<that>.py` as text, without importing it, and matching
       `^PROVIDER_CODE\s*(?::\s*str\s*)?=\s*["']([a-z0-9_]+)["']` (multiline);
     - `scripts/process_missing_games\.py` gives `gotsport`.

     An invocation that runs `scripts/import_*.py` or the drainer but yields no code raises
     `UnmappedImporter(line)`. `load_workflows` catches it and records it against the workflow's
     file. `importer_steps` is the list of (step display name, provider
     codes) for every step whose `run` matches. The pattern is anchored on `scripts/import_`, so
     `scripts/extract_and_import_tgs_teams.py` is not an importer.

2. **GitHub run evaluation** (same script).
   - **The GitHub reader.** `github(path: str) -> dict` mirrors
     `scripts/catch_up_compare_forecasts.github`, GET only.
     - It runs `["gh", "api", "-H", "X-GitHub-Api-Version: 2026-03-10", f"repos/{REPO}/actions/{path}"]`
       with `capture_output=True, text=True, check=True, timeout=60`.
     - It makes 3 attempts, sleeping 5 s and then 10 s between them, and returns
       `json.loads(stdout)`.
     - `REPO = os.environ.get("GITHUB_REPOSITORY", "dallasheidt14/PitchRank")`, so a local dry run
       works.
     - The final failure raises `SourceUnreadable("GitHub")`. Neither stderr nor stdout is logged.
   - **One failure stops all GitHub reads.** A module-level flag is set when `github()` raises
     after its third attempt. While it is set, `github()` raises `SourceUnreadable("GitHub")` at
     once, without calling `gh`.
   - **Workflow states.** `workflow_states() -> dict[str, WorkflowState]` reads
     `workflows?per_page=100` for **every** workflow, scheduled or not.
     - It maps each path's basename to its `state` and its `created_at`, parsed with
       `datetime.fromisoformat`; GitHub returns `-07:00` offsets.
     - It raises `SourceUnreadable` when `total_count` exceeds the rows returned. There are 65
       workflows today.
     - The weekly list of switched-off workflows is every entry whose state is not `active`. Today
       that is `data-hygiene-weekly.yml` and `auto-merge-queue.yml`; the second has no schedule.
     - A scheduled YAML file with no entry in the response gets one "check incomplete" line, and
       its other checks are skipped.
   - **Run lists.** `list_runs(file, query) -> list[dict]` pages `workflows/{file}/runs?{query}&per_page=100&page=N`
     until a page is short. Past 10 pages it raises `SourceUnreadable`, rather than truncating
     silently.
     - Both query strings come from one helper, `runs_query(event: str, since: datetime, *, bot:
       bool = False) -> str`. It formats `since` as `%Y-%m-%d` in UTC and builds the string with
       `urllib.parse.urlencode`, so `>=` and `[bot]` are always percent-encoded the same way.
     - The scheduled-run query decodes to `branch=main&event=schedule&created=>=YYYY-MM-DD`.
     - The chain-link query decodes to
       `branch=main&event=workflow_dispatch&actor=github-actions[bot]&created=>=YYYY-MM-DD`.
     - `RUN_HISTORY_DAYS = 15` sets `since`.
     - Both filters were verified live on 2026-11-25. `ut-scraper.yml` returned 4 scheduled runs
       since 11-10, and `tgs-event-scrape-import.yml` returned 14 bot links, all with actor
       `github-actions[bot]`.
   - **Counted runs (R7).** `is_counted(run, wf, jobs_cache) -> bool` fetches
     `runs/{id}/jobs?per_page=100` once per run, paging while `total_count` exceeds the jobs
     returned.
     - A run is counted when `head_branch == "main"` and some job has `conclusion == "success"`
       with a step of `conclusion == "success"` that is productive.
     - For a guarded workflow, productive means the step's `name` is in `wf.productive_names`.
     - Otherwise, productive means the step is not GitHub's own and its name is not in
       `wf.setup_names`.
     - Run 45215524977 (`ut-scraper.yml`, 2026-11-23 16:21 UTC) is the acceptance case: its job is
       `success`, and steps 6–8 (scrape, upload, import) are `skipped`, so it is not counted.
   - **Series assignment.** A workflow with one series files every scheduled run there; that
     includes the daylight-saving pairs, whose two weekly runs share one series. For a workflow
     with more than one series,
     `assign_runs(series_list, runs, created_at, since, now) -> Assignment` matches runs to due
     slots in order. `Assignment` is a small frozen dataclass with `runs: dict[Series, list[dict]]`
     and `slots: dict[tuple[Series, datetime], dict]`, the run that filled each slot. A
     single-series workflow gets an `Assignment` whose `runs` holds every run and whose `slots` is
     empty. The owner chose this on 2026-11-25, over R7's "most recent
     due time" rule.
     - The slots are every (series, due time) from 8 days before the run window's `since` up to
       now, at or after the workflow's `created_at`, sorted by due time.
     - Starting 8 days early gives the window's first run its predecessor slots. Eight days is
       the longest gap, a week, plus the grace; for example the Tuesday 03:25 run sits right after
       a window that begins Tuesday.
     - A run with no due time at or before its start is dropped from series evaluation. That only
       happens when `created_at` excludes every earlier slot.
     - Slots before `since` have no listed runs, so they look empty. That can misfile a run in
       the window's first day. It never reaches a cadence decision: D lies within the last 8 days
       (a week plus the grace), and `since` is 15 days back.
     - A slot is open to a run when `due ≤ run_started_at < due + series.grace` and no run has
       filled it yet.
     - Each scheduled run, taken in `run_started_at` order, fills the earliest-due open slot and is
       filed under that slot's series.
     - A run that finds no open slot falls back to the series with the latest due time at or before
       its start.
     - Example, `compare-live-monitoring.yml` on 2026-11-23:
       - the 18:17 UTC run fills the daily 06:20 slot;
       - the 03:25 UTC Tuesday run fills the Monday 17:30 slot;
       - Tuesday's 17:51 run fills the daily Tuesday slot.

       So no false "daily run missed" line appears. R7's rule would have filed both Monday runs
       under the Monday series.
     - `Assignment.slots` records the slot each run filled. The cadence rule reads it for
       multi-series workflows, which is what keeps a missing run flagged (below). When the Monday
       review is missing, the line can name the daily series instead.
   - **Cadence (R6).** For each series that is not frequent, in an active workflow:
     - `missed_due(series, assignment, counted, created_at, now) -> datetime | None` takes
       `counted`, a one-argument callable wrapping `is_counted(run, wf, jobs_cache)`. It considers
       only due times at or after the workflow's `created_at`. Let D be the latest such due time
       with D + `series.grace` ≤ now.
     - **One series:** it returns D when no run in `assignment.runs[series]` that started at or
       after D is counted.
     - **More than one series:** it returns D when `assignment.slots` has no run for
       `(series, D)`, or its run is not counted. It does not use start times there. A start-time test would let
       Wednesday's daily run satisfy Tuesday's empty daily slot after Tuesday's run had filled the
       Monday review's slot. Simulated on 2026-11-25: Monday 18:17, Tuesday 17:00 and Wednesday
       10:00 runs with no review gave an all-clear on Wednesday under start times. Under slots, the
       Tuesday daily slot is flagged from Wednesday 06:20.
     - It returns `None` otherwise, or when no due time qualifies. In that last case the weekly
       email shows the series as "awaiting its first run".
     - The line carries "last counted run YYYY-MM-DD", or "no counted run in 15 days".
     - The line adds "ran on YYYY-MM-DD but skipped its work" only when a run of the series since
       D did no work without failing. That covers a run that ended `success` without counting
       (the inactive-guard runs) and one that ended `skipped` (a job turned off by a job-level
       `if:`, as the `vars`-gated workflows' would be). Failed, cancelled and timed-out runs are
       described by the failure half of the line instead.
     - Runs are checked newest first, and the check stops at the first counted run, so most series
       cost one jobs call.
   - **Failures (R7).** `failure_flag(series, runs, counted) -> dict | None` takes the same
     `counted` callable as `missed_due`, so both share one jobs cache. It finds the newest run of
     the series whose
     `conclusion` is in `{"failure", "cancelled", "timed_out"}`, or `{"failure"}` for a frequent
     series.
     - It flags that run unless a later run of the same series is counted.
     - Runs still in progress (`conclusion is None`) are ignored.
     - Example: in the daylight-saving pair, a failed active run followed by a successful inactive
       run stays flagged, because the inactive run is not counted.
   - **Chains.** The chain links of a chain workflow form one extra daily-or-less series, and
     `failure_flag` runs over them.
     - A failed link is cleared by a later counted link, as R7's chain rule says.
     - These links are the chain's own automatic dispatches, listed with
       `actor=github-actions[bot]`. They are not the human-started runs the owner's
       scheduled-only rule excludes, and a person's dispatch of the workflow is never listed.
     - On `tgs-event-scrape-import.yml`, the week's last link ends red when it still finds games.
       That red link stays flagged until the next week's chain produces a counted link.
   - **Disabled workflows.** A workflow whose state is not `active` gets no findings. The weekly
     email lists every such workflow from `workflow_states()`, whether or not it has a schedule.
   - **Frequent series in the all-clear.**
     `frequent_counts(series, runs, created_at, now) -> (fired, expected, succeeded)` covers the
     last 7 days, starting at the later of `now - 7 days` and `created_at`. `expected` is the number
     of due times in that span. Neither count needs a jobs call.
   - **One line per series.** The series' failure and cadence findings merge into one line, for
     example "Calculate rankings: the latest scheduled run (started 2026-11-23) ended cancelled; no
     counted run since the one due 2026-11-23", linked to that run's `html_url`.

3. **Data checks** (`scripts/sql/rankings_publication_complete.sql` plus the same script).
   - **The shared SQL file** is a single `SELECT` with no trailing statement.
     - Its header comment names its two consumers (this script, and the follow-up skill through
       MCP `execute_sql`).
     - The header also lists the output columns: `read_only`, `ranking_start`, `row_count`,
       `stale_rows`, `newest_calculated`, `previous_snapshot_date`, `previous_snapshot_rows`,
       `complete`.
     - It documents the test override `SET pitchrank.ranking_start = '<timestamptz>'`.
   - **The SQL file's body.** It is the query below, verified against production on 2026-11-25
     through read-only MCP. It returned `read_only on`, `ranking_start 2026-11-23 12:30:00+00`,
     `row_count 150056`, `stale_rows 0`, `previous_snapshot_date 2026-11-19`,
     `previous_snapshot_rows 150562` and `complete true`.

     ```sql
     WITH params AS (
       SELECT coalesce(
                nullif(current_setting('pitchrank.ranking_start', true), '')::timestamptz,
                (CASE WHEN date_trunc('week', now() AT TIME ZONE 'UTC') + interval '12 hours 30 minutes'
                           <= now() AT TIME ZONE 'UTC'
                      THEN date_trunc('week', now() AT TIME ZONE 'UTC') + interval '12 hours 30 minutes'
                      ELSE date_trunc('week', now() AT TIME ZONE 'UTC') + interval '12 hours 30 minutes' - interval '7 days'
                 END) AT TIME ZONE 'UTC'
              ) AS ranking_start
     ),
     published AS (
       SELECT count(*) AS row_count,
              count(*) FILTER (WHERE r.last_calculated IS NULL OR r.last_calculated < p.ranking_start) AS stale_rows,
              max(r.last_calculated) AS newest_calculated
       FROM public.rankings_full r CROSS JOIN params p
     ),
     previous AS (
       SELECT h.snapshot_date, count(*) AS snapshot_rows
       FROM public.ranking_history h
       WHERE h.snapshot_date = (
         SELECT max(snapshot_date) FROM public.ranking_history
         WHERE snapshot_date < (SELECT (ranking_start AT TIME ZONE 'UTC')::date FROM params)
       )
       GROUP BY h.snapshot_date
     )
     SELECT current_setting('transaction_read_only') AS read_only,
            p.ranking_start, pub.row_count, pub.stale_rows, pub.newest_calculated,
            prev.snapshot_date AS previous_snapshot_date, prev.snapshot_rows AS previous_snapshot_rows,
            (pub.row_count > 0 AND pub.stale_rows = 0 AND prev.snapshot_rows IS NOT NULL
             AND pub.row_count >= 0.95 * prev.snapshot_rows) AS complete
     FROM params p CROSS JOIN published pub LEFT JOIN previous prev ON true
     ```

     - "Newest earlier snapshot" means the newest `snapshot_date` before the UTC date of
       `ranking_start`. The calculator dates its own snapshot when the run starts and writes it
       before publishing, so the current run's snapshot is never its own baseline, even when the
       run crosses midnight UTC (see Decisions).
     - With no earlier snapshot, `complete` is false.
   - **The SQL reader.**
     `read_only_query(sql: str, *, source: str, columns: tuple[str, ...]) -> dict` mirrors
     `src/predictions/archive_inputs.registered_inventory`.
     - It derives the project ref from `SUPABASE_URL`, requiring `https` and a `.supabase.co`
       hostname. A missing or malformed URL, or a missing `SUPABASE_ACCESS_TOKEN`, raises
       `SourceUnreadable(source)`.
     - It POSTs `{"query": sql}` with `Authorization: Bearer <SUPABASE_ACCESS_TOKEN>`,
       `timeout=60` and `allow_redirects=False`.
     - It catches `requests.RequestException` and a JSON decode error, and raises
       `SourceUnreadable(source)` for either.
     - It requires a JSON list of exactly one row, whose `read_only == "on"` and which holds every
       name in `columns` (a key that is present with a `null` value passes, because
       `previous_snapshot_date` and `oldest_stuck_claimed` are legitimately null). It returns that
       row.
     - Anything else raises `SourceUnreadable(source)`, whose message carries only the HTTP status.
     - `PUBLICATION_SQL` holds the file's contents, read with
       `(ROOT / "scripts/sql/rankings_publication_complete.sql").read_text(encoding="utf-8")`.
   - **Rankings (R2).** `rankings_finding(row, now) -> Finding`:
     - `complete` → ok;
     - not complete, with `now - ranking_start` > 30 hours → problem;
     - otherwise → "awaiting this week's run".

     The problem text distinguishes five cases, checked in this order, and each carries a
     labelled date:
     - an empty table, with "expected from the run starting YYYY-MM-DD" (`ranking_start`);
     - every row lacking a refresh time (`newest_calculated` null), with "no row has a refresh
       time; expected from the run starting YYYY-MM-DD";
     - `stale_rows > 0`, with "newest refresh YYYY-MM-DD", which names both causes: "this week's
       run did not refresh every row, or teams it removed were not cleaned up";
     - no earlier snapshot to compare with (`previous_snapshot_rows` null), with "no ranking
       snapshot before the run starting YYYY-MM-DD to compare with";
     - a row count under 95% of the earlier snapshot, giving both numbers and "snapshot of
       YYYY-MM-DD".

     The line links to `calculate-rankings.yml`.
   - **The other three queries** are module constants, each returning one row that includes
     `current_setting('transaction_read_only') AS read_only`. All three were verified against
     production on 2026-11-25.
     - `BUILD_HEARTBEAT_QUERY` gives the newest `build_logs.started_at` per `providers.code`. It
       joins on `build_logs.provider_id = providers.id`, covers the last 15 days, and keeps only
       rows where `coalesce(b.parameters->>'dry_run', 'false') <> 'true'`. Rows come back as a
       jsonb array.
     - `GAME_WINDOWS_QUERY` gives `games` counts per `providers.code`, joined on
       `games.provider_id = providers.id`, by `created_at` in three windows:
       `[now-7d, now)`, `[now-14d, now-7d)` and `[now-42d, now-14d)`. It uses
       `idx_games_created_at`. Rows come back as a jsonb array.
     - `SCRAPE_QUEUE_QUERY` gives four values:
       - `stuck_processing`, the count of `status = 'processing'` rows with `processed_at` older
         than 6 hours;
       - `oldest_stuck_claimed`, the oldest such `processed_at`;
       - `oldest_pending_requested`, the oldest `requested_at` among `pending` rows;
       - `completed_recently`, an `EXISTS` over `status = 'completed'` rows with `completed_at`
         in the last 6 hours.
   - **Provider heartbeat (R3).** `expected_providers(workflows, states)` maps provider code →
     mapped workflows, using active scheduled workflows only. Today that is 13 codes: the nine
     Affinity/EA/Kitman/PlayMetrics/TGS literals, plus `demosphere`, `heartland`, `yssl` and
     `gotsport`. D is the latest due time across the mapped workflow's series that is at or after
     the workflow's `created_at`, with D + that series' grace ≤ now. A provider with no such D is
     not checked yet. Otherwise it is flagged when two things both hold:
     - its newest heartbeat is before D, or it has none;
     - it has no counted scheduled run of the mapped workflow starting at or after D.

     The line carries "last import logged YYYY-MM-DD" and the last counted run's date. When it has
     neither in the 15 days, it carries "import due YYYY-MM-DD" (D). It links to the mapped
     workflow's page.
   - **Quiet imports (R4).** For each expected provider, flag it when
     `baseline_4_weeks / 4 >= 50` and both `last_week` and `week_before` are under
     `0.1 * baseline_4_weeks / 4`. The text gives both weekly counts, the usual weekly average,
     and "in the two weeks to YYYY-MM-DD" (today). It links to the mapped workflow's page.
   - **Scrape queue (R5).** There are two possible lines, both linked to
     `process-missing-games.yml`:
     - `stuck_processing > 0` gives "N scrape requests stuck in processing; oldest claimed
       YYYY-MM-DD";
     - an oldest pending request older than 2 hours, with `completed_recently` false, gives "the
       drainer has stalled: oldest waiting request queued …; nothing completed in the last
       6 hours".
   - **Unreadable sources (R31).** Each source is caught separately. The four queries, the
     workflow states, each workflow's run list, and a jobs call each map to their own failure.
     `SourceUnreadable`, `ValueError`, `KeyError` or `TypeError` turns the affected check into a
     "check incomplete: <check>" finding, never a pass, and the other checks still run. The last
     two catch a malformed field inside a row that `read_only_query` accepted. An incomplete
     finding is dated "checked YYYY-MM-DD" and links to the checker's own run.
   - **The `columns` passed per query:**
     - the publication file: all eight output columns;
     - `BUILD_HEARTBEAT_QUERY`: `heartbeats`;
     - `GAME_WINDOWS_QUERY`: `game_windows`;
     - `SCRAPE_QUEUE_QUERY`: `stuck_processing`, `oldest_stuck_claimed`,
       `oldest_pending_requested` and `completed_recently`.

4. **Email composition and sending** (same script).
   - **Findings.** A frozen `Finding` dataclass carries `check` (one of `rankings`, `imports`,
     `quiet`, `queue`, `schedules`, `incomplete`), `text`, `date_label`, `link` and `kind`
     (`problem`, `ok` or `awaiting`).
   - **Dates.** `az_date(dt) -> str` renders a `YYYY-MM-DD` date in
     `ARIZONA = timezone(timedelta(hours=-7))`, mirroring
     `scripts/investigate_missing_game_requests.py:86`. Every date in a line is labelled ("last
     counted run", "oldest stuck request claimed", "run started"), and the footer says the dates
     are in Arizona time (R9).
   - **Links.**
     - Workflow page: `https://github.com/{REPO}/actions/workflows/{file}`.
     - A run: its `html_url`.
     - A "check incomplete" finding on Actions: the checker's own run,
       `{GITHUB_SERVER_URL}/{GITHUB_REPOSITORY}/actions/runs/{GITHUB_RUN_ID}`. Off Actions, where
       `GITHUB_RUN_ID` is unset, it links to the checker's workflow page,
       `https://github.com/{REPO}/actions/workflows/scheduled-jobs-check.yml`.
   - **Rendering.** `render_html(findings, weekly, now) -> (subject, html)` and
     `render_text(...)` follow `render_html`'s inline style in
     `scripts/investigate_missing_game_requests.py`.
     - The daily email lists only problem and incomplete lines. The subject is "PitchRank job
       check: N problem(s)".
     - The weekly email (R8) always sends, under "PitchRank weekly job check: all clear" or "…: N
       problem(s)". It carries one line per check:
       - rankings;
       - imports ("all 13 scheduled providers on time", or the problem lines);
       - quiet imports;
       - scrape queue;
       - scheduled jobs ("N daily-or-weekly series on time", or problem lines);
       - one "fired N of M" line per frequent series;
       - the workflows switched off in GitHub;
       - any "awaiting" or "check incomplete" lines.
   - **Sending.** The recipient is resolved inside `main()`, after `.env` and `.env.local` load,
     as `os.environ.get("ALERT_EMAIL", DEFAULT_ALERT_EMAIL)`. `DEFAULT_ALERT_EMAIL` is the default
     used at `scripts/investigate_missing_game_requests.py:82`. No module-level `ALERT_EMAIL`
     exists, so a value from either file reaches the sender. Sending goes through
     `src.utils.resend_email.send_email(recipient, subject, html)`.
   - **Hiding the Resend body (R10).** `hide_resend_body()` runs when
     `os.environ.get("GITHUB_ACTIONS") == "true"`. It adds a `logging.Filter` to
     `logging.getLogger("src.utils.resend_email")`, and does not edit
     `src/utils/resend_email.py`.
     - For a record whose `msg` is `"Resend answered %s: %s"`, the filter replaces `record.args`
       with `(record.args[0], "(body hidden on Actions)")` and keeps the record.
     - The helper's other two warnings, "no key" and the exception type, carry no response text
       and pass unchanged.
   - **Every problem line carries a labelled date and a link (R9).** `Finding` has `date_label`
     and `link` fields, and every builder above fills both for a `problem`. The rendering test
     builds its findings through those builders (Step 5).
   - **`main(argv=None) -> int`** takes `--dry-run` and `--weekly`.
     - Its first action loads `ROOT / ".env"`, then `ROOT / ".env.local"` with `override=True`,
       through `dotenv.load_dotenv`, as `scripts/find_cross_provider_duplicates.py:63-68` does.
       Variables already set in the environment win over `.env`.
     - It is in weekly mode when `--weekly` is passed or `os.environ.get("WEEKLY") == "true"`.
     - `--dry-run` under `GITHUB_ACTIONS == "true"` prints a refusal and returns 2 (R10). There is
       no dry-run input.
     - A dry run prints `render_text` and never calls `send_email`.
     - A live run logs one count line, for example
       `checks 6, problems 2, incomplete 0, email accepted`.
       - When a setting is missing, the line adds its name, for example `missing RESEND_API_KEY`.
       - The only other output a live run can produce is the Resend helper's own warning when a
         send fails, with the body hidden on Actions (above).
     - **The mail key is checked up front.** A live run without `RESEND_API_KEY` returns 1, even
       on a quiet daily run that has nothing to send. A dry run does not need the key.
     - It returns 1 when any check is incomplete, when the mail key is missing, or when a required
       send returned `False`, after attempting the send (R31). Otherwise it returns 0.
     - A daily run with no problems and the key present sends nothing and returns 0.
     - It ends with `raise SystemExit(main())`.

5. **Workflow, docs and tests.**
   - **`.github/workflows/scheduled-jobs-check.yml`.** One job, `check`, laid out like
     `investigate-missing-game-requests.yml`.
     - Two `schedule` entries:
       - `'41 6 * * *'`, with a comment: offset minute; GitHub fires daily crons 7–12 hours late;
       - `'0 19 * * 2'`, with a comment: the Tuesday all-clear, after R2's 30-hour mark at Tuesday
         18:30 UTC.
     - `workflow_dispatch` with no inputs, and the comment "No dry-run input: … Actions logs are
       public". A manual run is a real daily check.
     - `permissions: contents: read` and `actions: read`.
     - No `concurrency`, because two overlapping checks only duplicate an email.
     - `timeout-minutes: 20`.
     - Steps: `actions/checkout@v5` with `ref: main`; `actions/setup-python@v6` with Python 3.11
       and pip cache; `pip install -r requirements.lock`.
     - There is no "Verify secrets" step. The script checks its own configuration (see Decisions),
       so a missing database secret still produces an incomplete-check email.
     - The step "Check scheduled jobs" has env `GH_TOKEN: ${{ github.token }}`,
       `SUPABASE_URL: ${{ secrets.SUPABASE_URL }}`,
       `SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}`,
       `RESEND_API_KEY: ${{ secrets.RESEND_API_KEY }}`, `PYTHONUNBUFFERED: '1'` and
       `WEEKLY: ${{ github.event.schedule == '0 19 * * 2' }}`. Its `run` is exactly
       `python scripts/check_scheduled_jobs.py`.
     - The file must not contain `gh workflow run`, `/dispatches` or `createWorkflowDispatch`,
       even in a comment, because `tests/unit/test_claude_hooks.py` checks for them.
   - **`CLAUDE.md` workflow table.** Add a row: `scheduled-jobs-check.yml` | Daily 06:41 UTC +
     Tue 7:00 PM UTC | Check from the data and the run history that each scheduled job did its
     work; email the owner only when one did not, plus a Tuesday all-clear.
     `tests/unit/test_agent_doc_references.py::test_every_scheduled_workflow_is_documented`
     requires this row.
   - **`tests/unit/test_team_cleanup_apply_stage.py`.** Add
     `"scheduled-jobs-check.yml": "reads the database and run history and emails the owner; writes nothing"`
     to `NOT_A_WRITER`. `test_every_workflow_is_checked_or_named_as_left_out` requires it.
   - **`tests/fixtures/scheduled_jobs_check/`.** JSON fixtures with only the fields the script
     reads, and made-up IDs throughout, as the spec's Safety section requires:
     - `run_inactive_guard.json` and `jobs_inactive_guard.json` copy the shape of run 45215524977
       (the inactive UT run of 2026-11-23, the R7 acceptance case) under a made-up run ID. That
       shape is one `scrape-ut-games` job ending `success`, with steps 1–5 and 9 `success`, steps
       6–8 (`Scrape UT Affinity games (ranked source divisions, male+female, window)`,
       `Upload UT scraper output`, `Import scraped UT games`) `skipped`, and the GitHub-added
       `Post …` and `Complete job` steps. The fields kept are `id`, `event`, `head_branch`,
       `status`, `conclusion`, `run_started_at` and `html_url`, plus
       `jobs[].name/conclusion/steps[].number/name/conclusion`.
     - Further made-up runs cover the other cases.
   - **`tests/unit/test_check_scheduled_jobs.py`** (`from scripts import check_scheduled_jobs as
     job`).
     - **An autouse fixture** replaces `job.subprocess.run` with a refusal unless the test installs
       a fake, and replaces `job.requests.post` likewise, so no test reaches the real `gh` or
       Supabase.
       - It also deletes `GITHUB_ACTIONS`, `GITHUB_RUN_ID`, `GITHUB_SERVER_URL`, `WEEKLY`,
         `SUPABASE_URL`, `SUPABASE_ACCESS_TOKEN` and `RESEND_API_KEY`, as
         `tests/unit/test_enqueue_opponent_frontier.py:425` does for `GITHUB_ACTIONS`. CI's pytest
         runs on Actions with `GITHUB_ACTIONS=true`, so without this the dry-run tests return 2 on
         CI only. Tests that need a variable set it themselves.
       - It replaces `job.load_dotenv` with a no-op, so the developer's real `.env` never leaks
         into a test.
       - It resets the GitHub-failure flag, and replaces `job.time.sleep` with a no-op so the
         retry back-off costs nothing.
       - On teardown it removes every filter `hide_resend_body()` added to the
         `src.utils.resend_email` logger.
     - **The GitHub fake** routes by the exact `actions/...` path with its query string, and
       records each call.
     - **One `requests.post` fake routes by host.** `job.requests` and
       `src.utils.resend_email.requests` are the same imported module, so a second patch would
       replace the first. The fake is installed once, on that module's `post`.
       - Requests to `api.supabase.com` go to the Supabase side. It asserts the URL, the
         `Authorization` header, `json["query"]`, `timeout` and `allow_redirects is False`, and
         answers per query from the test's fixture.
       - Requests to `api.resend.com` go to the Resend side, which answers 200 or the status the
         test sets.
       - Every response's `.json()` parses its `content` bytes. Each call is recorded under its
         host, so a test can assert, for example, four Supabase calls answered 200 and one Resend
         call.
     - **Cron:**
       - `23 5 * * 2,5` gives alternating 3- and 4-day gaps;
       - `7,22,37,52 * * * *` is frequent;
       - day of week 7 equals 0;
       - `MON` raises, and so do a restricted day of month and day of week together.
     - **Series:**
       - the real `or-scraper.yml` yields one merged series at the earlier hour;
       - `compare-live-monitoring.yml` yields two;
       - a synthetic `0 6 * * 1` plus `0 7 * * 2` stays as two.
     - **R3, derived from the files:**
       - the test picks importer steps with its own, broader pattern,
         `(?<!\w)import_\w+\.py|-m\s*scripts\.import_\w+|process_missing_games`, over every
         non-comment `run` line of every scheduled workflow in `.github/workflows/`. It does not
         use the script's pattern, so an importer form the script misses fails the test instead of
         dropping out of both. `extract_and_import_tgs_teams.py` does not match, because `_`
         precedes `import_`;
       - every **invocation** that pattern matches, one per match on a line, maps through
         `importer_providers` on that line alone to a code matching `^[a-z0-9_]+$`. The check is
         per invocation, not per step, so a step that also runs a mapped importer cannot hide an
         unmapped one;
       - a `tmp_path` step running `python scripts/import_yssl.py` and
         `python -m scripts.import_newthing` on separate lines fails the coverage assertion for the
         second line. So does the same pair joined by `&&` on one line, because the test splits
         invocations the way `importer_providers` does;
       - `python scripts/import_games_enhanced.py "$F" affinity_${STATE}` raises
         `UnmappedImporter`, rather than mapping to `affinity_`;
       - a `tmp_path` workflow naming `scripts/import_gone.py`, a file that does not exist, gives
         one "check incomplete" finding through `main()`. A neighbouring valid workflow is still
         checked, the email is attempted, and the exit code is 1;
       - the test's scan, like `load_workflows`, globs `*.y*ml`. A scheduled `tmp_path` workflow
         saved as `.yaml` reaches both;
       - anti-vacuity pairs: `yssl-scraper.yml→yssl`, `process-missing-games.yml→gotsport`,
         `or-scraper.yml→affinity_or`, `ea-scraper.yml→modular11_ea`,
         `demosphere-scraper.yml→demosphere`, `tgs-event-scrape-import.yml→tgs`;
       - a `tmp_path` workflow running `python scripts/import_newthing.py`, beside a
         `scripts/import_newthing.py` with no `PROVIDER_CODE`, raises `UnmappedImporter`;
       - `extract_and_import_tgs_teams.py` is not an importer.
     - **Guard names:** in every guarded workflow, each step whose `if:` references
       `steps.guard.outputs` has a literal `name:` with no `${{`. Without one, the name match can
       never succeed.
     - **Setup classification, from real files:** the `Install dependencies` steps of
       `calculate-rankings.yml` and `tgs-score-reconcile.yml`, and `yssl-scraper.yml`'s, which
       ends in `mkdir`, are all in `setup_names`.
     - **Counted runs:**
       - the inactive-guard fixture (run 45215524977's shape) is not counted;
       - the same jobs payload with step 8 `success` is counted;
       - a non-guarded job ending `success` whose only successful steps are setup and GitHub's
         own is not counted. The fixture uses `calculate-rankings.yml`'s real step names, with
         `Install dependencies` `success` and the ranking steps `skipped`;
       - a job ending `failure` is not counted;
       - a matrix run with one `success` job holding a productive `success` step is counted.
     - **Cadence:**
       - a weekly series whose counted run started 12 hours after its due time is not flagged;
       - with no counted run 25 hours after the due time, it is flagged with the last counted date;
       - on the Tuesday-and-Friday series, Saturday with Friday's run missing is flagged;
       - on Thursday, with Tuesday's run present, it is not flagged;
       - a frequent series is never flagged on timing;
       - a workflow whose `created_at` is after its latest due time is not flagged, and its first
         qualifying slot is flagged only once its grace passes. This covers the checker's own
         first deployment;
       - a merged daylight-saving series with no counted run since its earlier-hour due time is not
         flagged when checked 24.5 hours after that due time, and is flagged at 25.5 hours;
       - a series whose run since D ended `cancelled` gets the failure text and not "skipped its
         work". One that ended `success` with every productive step skipped gets "skipped its
         work", and so does one whose run conclusion is `skipped`;
       - `frequent_counts` for a 15-minute series whose `created_at` falls between two slots
         yesterday counts expected slots only from `created_at`, not 672;
       - `runs_query` output, URL-decoded, has `created` equal to `>=` plus the `%Y-%m-%d` date and,
         for chain links, `actor` equal to `github-actions[bot]`. The test passes a timezone-aware
         `since` with a time of day.
     - **Slot matching** (two-series workflow, made-up run IDs, real timings):
       - with `compare-live-monitoring.yml`'s series, `created_at` 2026-11-20 and runs at Monday
         2026-11-23 18:17 and Tuesday 03:25 UTC, a check at Tuesday 15:00 UTC flags neither series.
         - The daily D is Monday 06:20, filled by 18:17.
         - The review series has no qualifying D yet: Monday 17:30's grace runs to Tuesday 17:30,
           and the slot a week earlier predates `created_at`.
         - R7's most-recent-due rule would have filed 18:17 under the review series and flagged
           the daily one.
         - No run in the fixture starts after the check time. This case was prototyped at review;
       - with the Tuesday 03:25 run removed (the Monday review missing), a check at Wednesday
         18:00 UTC flags exactly one series;
       - with runs at Monday 18:17, Tuesday 17:00 and Wednesday 10:00 UTC and no review, a check at
         Wednesday 12:00 UTC flags the daily series. Tuesday 17:00 fills the review slot, leaving
         Tuesday's daily slot empty. This is the case a start-time test would pass;
       - with the run list starting at Tuesday 03:25, so the window's `since` falls on Tuesday, that
         run is not dropped and nothing raises. It fills the daily Monday slot, because Monday's
         18:17 run falls before `since` and is not listed, and the slots generated 8 days early
         give it a predecessor;
       - a run more than 24 hours after every open slot's due time falls back to the series with
         the latest due time before it.
     - **Failures:**
       - a failed active run of the daylight-saving pair followed by an inactive `success` is
         still flagged, and a later counted run clears it;
       - a frequent series' `cancelled` run is not flagged, but its `failure` is;
       - the newest failed chain link is flagged, and a later counted bot link clears it;
       - a `disabled_manually` scheduled workflow yields no finding and appears in the weekly list;
       - a `disabled_manually` workflow with no schedule also appears in the weekly list;
       - a `disabled_manually` workflow with an unsupported cron appears only in the weekly
         switched-off list. The same file reported `active` gives one "check incomplete" finding;
       - a scheduled YAML file missing from the workflow-state response yields one "check
         incomplete" line.
     - **Data rules:**
       - rankings: `complete` passes; not complete at 29 hours is awaiting. At 31 hours each of the
         five problem cases renders its own text, including no earlier snapshot with every row
         fresh, and every refresh time null. The stale-rows text names both causes;
       - heartbeat, one fixture per condition: a heartbeat at or after D clears; a heartbeat before
         D, with a counted run at or after D, does not flag (YSSL's no-records case); a heartbeat
         before D with no counted run flags;
       - quiet imports, one fixture per condition: a baseline total of 200 with weeks of 4 and 4
         flags; 200 with 5 and 4 does not (5 is not under 5); 200 with 4 and 5 does not; a
         baseline of 196 with 4 and 4 does not;
       - queue, one fixture per condition, on the rule Python computes. A pending row 2 h 1 min
         old with `completed_recently` false flags; the same row with `completed_recently` true
         does not; a pending row 1 h 59 min old with `completed_recently` false does not.
         `stuck_processing > 0` flags. The two 6-hour thresholds are computed in SQL, so the
         integration test covers them.
     - **R31:**
       - an HTTP 500 from the Supabase fake makes only its check incomplete; the email still sends,
         and the exit code is 1;
       - `read_only` other than `"on"` makes the check incomplete;
       - a `requests.post` fake raising `requests.ConnectionError` makes only its check
         incomplete;
       - a row missing a required column makes only its check incomplete, and the email still
         sends;
       - with `SUPABASE_ACCESS_TOKEN` unset, all four database checks are incomplete, the email
         still sends, and the count line names the setting;
       - with `RESEND_API_KEY` unset, healthy sources and daily mode: no email is attempted, the
         count line names `RESEND_API_KEY`, and the exit code is 1;
       - the GitHub-failure flag, after the inventory succeeds. The `gh` fake answers
         `workflows?per_page=100` with two active scheduled workflows and fails every later call.
         `subprocess.run` is called exactly 4 times: 1 inventory plus 3 attempts on the first
         run list. Both workflows' schedule checks are incomplete, the email is attempted, and the
         exit code is 1. Without the flag, the second workflow's run list would add 3 more calls;
       - a `gh` fake that fails one run-list read once and then succeeds leaves later reads
         enabled; the flag is set only after a third failed attempt;
       - one workflow file with an unsupported cron (`0 6 * * MON`) beside one valid scheduled
         workflow, driven through `main()`: the valid workflow's checks run, the malformed one gives
         one "check incomplete" line, the email is attempted, and the exit code is 1;
       - a `send_email` fake returning `False` gives exit 1;
       - a daily run with no problems and the mail key set makes no send and exits 0;
       - with `WEEKLY=true` in the environment and no problems, exactly one email is sent, its
         subject says "all clear", and the exit code is 0.
     - **R10:**
       - `--dry-run` prints the email, and a `send_email` fake that raises is never called;
       - `--dry-run` with `GITHUB_ACTIONS=true` returns 2;
       - a healthy live run's whole stdout plus captured log is exactly the count line;
       - through `main()`, with `GITHUB_ACTIONS=true`, `--weekly` and the `gh` fake healthy. The
         host-routed fake answers four Supabase calls with healthy rows and the Resend call with
         422 and the body `BODY-MARKER`.
         - The test asserts four Supabase calls answered 200, zero incomplete checks, and exit 1.
         - It asserts the whole output is the count line plus the one helper warning reading
           `Resend answered 422: (body hidden on Actions)`, with `BODY-MARKER` nowhere.
         - Deleting the `hide_resend_body()` call from `main()` fails this test.
     - **Rendering (R9):** each problem finding is produced by its real builder from fixtures, not
       constructed by hand. The builders are `rankings_finding` (each of its five cases), the
       merged cadence and failure line, heartbeat, quiet, queue and incomplete. For each one, the
       test asserts:
       - `date_label` matches a labelled date, a phrase followed by `\d{4}-\d{2}-\d{2}`, and
         appears in the rendered HTML;
       - `link` starts with `https://` and appears in the HTML as an `href`.

       An empty `date_label` or `link` therefore fails, because `"" in html` would always pass. The
       incomplete finding is built off Actions and must carry the workflow-page link.
     - **Configuration**, with `job.load_dotenv` restored for these tests:
       - For every variable the files set, the test calls `monkeypatch.setenv(name, "")` and then
         `monkeypatch.delenv(name)`.
         - The `setenv` records the variable's original absence, so teardown removes whatever
           `load_dotenv` writes.
         - The `delenv` makes it absent again before `main()` runs. That matters because
           `load_dotenv` without override skips a key already present, even an empty one.
         - A bare `delenv` of an absent variable records nothing, and the value would leak into
           later test modules. Verified with python-dotenv 1.1.1, the version in
           `requirements.lock`.
       - A `tmp_path` `.env` holds a made-up `SUPABASE_URL=https://abcdefgh.supabase.co` and
         `ALERT_EMAIL=env@example.com`; a `.env.local` holds `ALERT_EMAIL=local@example.com`. A
         token is set in the environment, and `job.ROOT` is pointed at `tmp_path`.
       - The Supabase side of the fake sees
         `https://api.supabase.com/v1/projects/abcdefgh/database/query/read-only`.
       - A problem email goes to `local@example.com`.
     - **The workflow file:**
       - its crons are exactly `41 6 * * *` and `0 19 * * 2`;
       - the check step's `env.WEEKLY` is `${{ github.event.schedule == '0 19 * * 2' }}`;
       - the check step's `run`, stripped, is exactly `python scripts/check_scheduled_jobs.py`;
       - the check step's env names `GH_TOKEN`, `SUPABASE_URL`, `SUPABASE_ACCESS_TOKEN` and
         `RESEND_API_KEY`;
       - `permissions.actions == "read"`;
       - `workflow_dispatch` has no `inputs`.
   - **`tests/integration/test_scheduled_jobs_check_sql.py`.** It uses the `postgres_database`
     fixture from `tests/integration/conftest.py`, and CI runs it against `postgres:17`.
     - It creates minimal `public.rankings_full(team_id uuid, last_calculated timestamptz)`,
       `public.ranking_history(team_id uuid, snapshot_date date)`,
       `public.providers(id uuid, code text)`, `public.build_logs(provider_id uuid,
       started_at timestamptz, parameters jsonb)`, `public.games(provider_id uuid,
       created_at timestamptz)` and `public.scrape_requests(status text, processed_at timestamptz,
       requested_at timestamptz, completed_at timestamptz)`.
     - It executes the real `PUBLICATION_SQL` and the three query constants exactly as the script
       sends them.
     - **One transaction per case.** The fixture's connection is `autocommit=True`. Each case
       therefore runs `BEGIN`, its inserts, any `SET LOCAL pitchrank.ranking_start = …`, the query,
       and `ROLLBACK`, all on one cursor.
       - PostgreSQL's `now()` is then the same for the inserts and the query, so a row inserted at
         exactly `now() - interval '7 days'` (and at 14 and 42 days) tests which window owns the
         boundary.
       - The override ends with the transaction and cannot leak into the no-override case. A
         plain `SET` would last the whole autocommit session, and the no-override assertion would
         start failing after 2026-11-30.
     - **Publication file**, each case run with `SET LOCAL pitchrank.ranking_start =
       '2026-11-23 12:30+00'`:
       - every row fresh, at 99.7% of the earlier snapshot, is `complete`;
       - one row before the start gives `stale_rows 1` and not complete;
       - one `NULL` row is not complete;
       - an empty table is not complete;
       - 94% of the earlier snapshot is not complete;
       - a run crossing midnight UTC is not complete: 90,000 rows published at Tuesday 03:00 UTC,
         the run's own snapshot of 90,000 dated Monday, and the previous week's snapshot of
         150,000. Comparing with the Monday snapshot would have passed it.
     - **Publication file, without the override:** `ranking_start` is a Monday 12:30 UTC no later
       than `now()` and later than `now() - 7 days`.
     - **The other queries:**
       - a `dry_run: true` `build_logs` row is ignored;
       - game windows land in the right buckets at their edges. Rows sit at exactly
         `now() - 7 days`, `now() - 14 days` and `now() - 42 days`, inside the same transaction as
         the query: the 7-day row is in `last_week`, the 14-day row in `week_before`, and the
         42-day row in `baseline_4_weeks`, because each lower bound is inclusive;
       - `SCRAPE_QUEUE_QUERY`, with rows inserted relative to `now()`:
         - a `processing` row claimed 6 h 1 min ago counts in `stuck_processing` and sets
           `oldest_stuck_claimed`; one claimed 5 h 59 min ago does not;
         - a `completed` row with `completed_at` 5 h 59 min ago sets `completed_recently` true;
           with only a `completed` row at 6 h 1 min, it is false;
         - a `failed` row with a recent `completed_at` does not set `completed_recently`;
         - `oldest_pending_requested` is the oldest `pending` row's `requested_at`.

## Verification

- **Unit suite.** `python -m pytest tests/unit/test_check_scheduled_jobs.py -q` → all pass.
- **The SQL tests.** `python -m pytest tests/integration/test_scheduled_jobs_check_sql.py -q`
  skips locally, because this PC has no PostgreSQL (no `docker`, `psql` or `pg_ctl` on PATH,
  checked 2026-11-25) and `PROSPECTIVE_TEST_DATABASE_URL` is unset. It runs in CI's Python Tests
  (Linux) job. Confirm on the PR that it ran rather than skipped:
  - `pyproject.toml` sets `addopts = "-ra --tb=short"`, so pytest's short test summary lists every
    skipped test with a `SKIPPED` line.
  - In the job log, that summary must hold no `SKIPPED` line naming
    `test_scheduled_jobs_check_sql.py`.
  - The module's progress line must show dots, not `s`.
- **Mutation checks.** Each mutation must fail the named new test, not merely redden the suite.
  Collect the failing test names.
  - **Run locally**, each failing its named unit test:
    - drop the guard rule from `is_counted`, so any non-setup step counts → the inactive-guard
      counted-run test fails;
    - remove the daylight-saving merge → the `or-scraper.yml` series test fails;
    - put `cancelled` in the frequent failure set → the frequent-cancelled test fails;
    - drop the `PROVIDER_CODE` lookup → the R3 anti-vacuity test fails for `yssl-scraper.yml`;
    - drop the `created_at` cut-off → the first-deployment cadence test fails;
    - drop the counted-run condition from the heartbeat rule → the YSSL no-records heartbeat test
      fails;
    - drop the `week_before` condition from the quiet rule → the 200/4/5 test fails;
    - delete the `hide_resend_body()` call from `main()` → the `main()`-level R10 test fails;
    - drop the GitHub-failure flag → the "4 calls in total" test fails;
    - switch the multi-series cadence back to a start-time test → the Monday 18:17 / Tuesday
      17:00 / Wednesday 10:00 slot test fails;
    - drop the `Install` name rule from `setup_names` → the real-file setup classification test
      fails.
  - **The SQL mutations run in CI**, because the integration tests skip locally:
    - remove the `dry_run` filter from `BUILD_HEARTBEAT_QUERY` → the integration dry-run test
      fails;
    - change the baseline back to "before the UTC date of `newest_calculated`" → the
      midnight-crossing test fails;
    - drop `stale_rows = 0` from `complete` → the integration stale-row test fails;
    - change `SCRAPE_QUEUE_QUERY`'s processing interval from 6 hours to 60 → the 6 h 1 min
      processing test fails.
  - **How to run the CI mutations.** Push each one as its own temporary commit on the PR branch,
    one at a time. Wait for that commit's Python Tests (Linux) run, read its failing test names,
    then revert it before pushing the next.
    - Separate commits keep the attribution clean: two of the four edit the same SQL file.
    - Afterwards, confirm the next CI run is green.
    - The squash merge drops every temporary commit.
- **The CI gate, locally:**
  - `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
  - `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`

  These cover `test_agent_doc_references.py`, `test_team_cleanup_apply_stage.py`,
  `test_claude_hooks.py` and `test_workflow_pipefail_substitutions.py` for the new workflow.
- **Workflow audit.**
  `python .claude/skills/review-workflows/scripts/audit_workflows.py --repo-root . --fail-on never --format markdown`
  → no finding names `scheduled-jobs-check.yml`.
- **Local dry run on the owner's PC.** Run `python scripts/check_scheduled_jobs.py --dry-run` and
  `--dry-run --weekly` from a checkout of the branch.
  - It needs `SUPABASE_URL` in `.env` and `SUPABASE_ACCESS_TOKEN` in the user environment (both
    present on 2026-11-25), and `gh` logged in.
  - Re-derive each line independently before trusting it: the MCP queries above and
    `gh run list --workflow <file> --event schedule`.
  - Expected from the data on 2026-11-25. Re-derive each line on the day you run it; the queue and
    run history move.
    - **rankings:** complete (150,056 rows, 99.7% of the 2026-11-19 snapshot of 150,562);
    - **scrape queue:** 1 request stuck in processing, oldest claimed 2026-10-05;
    - **quiet imports:** `affinity_ga` and `demosphere` (the wind-down risk above);
    - **YSSL:** flagged twice, a failed latest scheduled run and no import logged since
      2026-11-18, matching the session-start hook's "scheduled workflows failing: YSSL Scraper";
    - **Calculate rankings:** its latest scheduled run (started 2026-11-24 00:08 UTC) ended
      `cancelled`, and there is no counted run since the one due 2026-11-23. The 2026-11-16 run
      ended `failure` too;
    - **Heartland scraper:** its latest scheduled run (2026-11-23 20:33 UTC) ended `failure`. Its
      heartbeat is fine (import logged 2026-11-23), so only the schedule line appears;
    - **UT:** not flagged, because its 2026-11-23 18:38 UTC run is counted even though run
      45215524977 is not;
    - **`enqueue-opponent-frontier.yml`:** not flagged. It was created 2026-11-24 at 15:24 UTC,
      after that day's 08:43 UTC slot, and its first qualifying slot's grace has not passed;
    - **switched off in GitHub, in the weekly list:** `data-hygiene-weekly.yml` and
      `auto-merge-queue.yml`, the second from the full workflow list since it has no schedule;
    - **the checker itself:** one "check incomplete: scheduled-jobs-check.yml" line. GitHub
      registers a workflow only when it reaches `main`; `enqueue-opponent-frontier.yml`'s
      `created_at` matches its PR's merge to the second. The branch's YAML therefore has no entry
      in the workflow list, so before merge the dry run exits 1. That is expected;
    - **the GitHub reads** stay well under the rate limit. Log the call count in the dry run.
- **After merge** (the owner's call, since it sends a real email): dispatch
  `scheduled-jobs-check.yml` once from the Actions page. A manual run is a daily check. Then
  confirm:
  - the check step's log shows only the one count line;
  - with today's problems (above), one email arrives at `ALERT_EMAIL`, with labelled dates and
    working links;
  - the run ends `success` when every check was read and the email was accepted. It ends
    `failure` when any check was incomplete, even though the email still went out, or when the
    send was refused.

  The next Tuesday's all-clear should arrive after 19:00 UTC, allowing for GitHub's delay. Its
  subject says "all clear" or names the problem count. A healthy daily run sends nothing and ends
  `success`; the unit tests cover that case.

## Context Files

- `.turbo/specs/pitchrank-automation-suite.md`: R1–R10 and R31, Design → Key flows (Daily check),
  and Safety ("What leaves this PC").
- `scripts/investigate_missing_game_requests.py`: the script, email and dry-run shape to mirror
  (`main`, `render_html`, `render_text`, `ALERT_EMAIL`, logging setup).
- `.github/workflows/investigate-missing-game-requests.yml`: the workflow shape to mirror.
- `src/predictions/archive_inputs.py`: `registered_inventory`, the read-only Management API call
  to mirror.
- `scripts/catch_up_compare_forecasts.py`: `github()`, the `gh api` reader to mirror, and the
  jobs/steps reading.
- `.claude/hooks/session-start.sh` (lines 34–75): chain detection and the failure semantics R7
  mirrors.
- `src/utils/resend_email.py`: `send_email` and the log line to hide on Actions.
- `.github/workflows/ut-scraper.yml`: the guard step and the guarded step names (run 45215524977's
  workflow).
- `tests/integration/conftest.py`: the `postgres_database` fixture.
- `tests/unit/test_investigate_missing_game_requests.py`: the test layout and fixtures to mirror.
- `tests/unit/test_team_cleanup_apply_stage.py` (`NOT_A_WRITER`) and
  `tests/unit/test_agent_doc_references.py`: the two guard lists the new workflow joins.
