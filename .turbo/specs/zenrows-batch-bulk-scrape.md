# ZenRows Batch Bulk Scrape

## Overview

`scripts/drain_queue.py` (dispatched as "Help Clear Queue") scrapes GotSport with 20
in-runner threads. Measured throughput across twelve runs on 2026-08-31 → 2026-09-02 was
0.45–1.6 teams/sec: 5,900 teams took 61 min, 2,000 teams took 65 min. The eligible top-up
pool is **18,190 teams** (measured 2026-09-03 by paging `find_topup_teams`), which at the
best observed rate needs ~3.2 hours — past the workflow's 180-minute timeout. A killed run
never reaches auto-import, so everything it scraped is lost. A full sweep in one dispatch
has therefore never been possible, which is why the operator runs it in 2,000–5,900 team
chunks.

The run is latency-bound, not block-bound: the slowest run's log contains zero WAF or
CloudFront hits. The latency comes from a hidden asymmetry — only the match-list call
routes through ZenRows. `_extract_club_name` (`src/scrapers/gotsport.py:638`) and
`_fetch_club_name_for_team_id` (`:797`) both use `self.session` directly, so 1–31 requests
per team leave the runner's IP sequentially, inside the parse loop. Those lookups cannot
simply be dropped: `opponent_club_name` feeds `game_matcher.py:655` as the club field,
which carries 35% of the fuzzy-match weight, and losing it would create duplicate teams.

This project adds a second, independently dispatched bulk-scrape workflow that hands the
whole URL list to the ZenRows Batch API and lets ZenRows fan out on its own infrastructure,
covering **both** request kinds.

**Bounds.** One operator, manual dispatch only, never scheduled. Rigor tier: small-team
operational tooling — it must never corrupt game data, strand queue rows, or silently
under-report what it did, but it may fail loudly and be re-run.

**One concurrent writer, and it is not safe.** `process_missing_games.py` drains the same
queue every 15 minutes and does **not** use the atomic claim RPC: `:93` selects on
`status = 'pending'` and `:445` then writes `'processing'` with an unconditional update
carrying no expected-status predicate. A row it selected in the instant before this
workflow claims the same row can therefore be scraped by both. The exposure is bounded —
once a claim lands, those rows leave the drainer's `pending` view entirely, so only the ≤40
rows already in flight in that one cycle can collide — and games deduplicate on the
immutable `game_uid`, so the cost is duplicate `team_scrape_log` rows and wasted credits,
never corrupt game data. **This is accepted, not fixed** (R39). The overlap is also **not
measured**: `team_scrape_log` carries no run or workflow identifier (its columns are
`id, team_id, provider_id, scraped_at, games_found, status`), so no honest per-run
duplicate count is derivable without a migration.

**Scheduled enqueues run during a bulk run, and that constrains every release.**
`enqueue-yesterday-games` (`13 7 * * *`), `enqueue-active-teams` (`28 10 * * *`),
`enqueue-discovery` (`41 14 * * 0`) and `enqueue-safety-net` (`56 16 * * 0`) insert fresh
`pending` rows for teams this run may be holding in `processing` for up to two hours.
`idx_scrape_requests_pending_team` is `UNIQUE (team_id_master) WHERE status = 'pending'`
(`20260520001858_add_priority_to_scrape_requests.sql:16-18`), so releasing such a row back
to `pending` raises `23505`. R8 governs how.

## Users

**Operator (site owner).** Dispatches bulk scrapes by hand when the backlog needs clearing
or after a period of reduced scraping. Wants a full sweep to finish inside one run, wants to
know what it cost, and wants a failed run to leave nothing broken behind. Reads the workflow
summary, not the code.

## Requirements

### Selection

- **R1.** When dispatched with a team target N (default 5,000), the system shall claim up to
  N pending GotSport `scrape_requests` rows via the `claim_queue_items` RPC, then fill any
  shortfall from the `find_topup_teams` RPC — most-recently-scraped first, excluding teams
  scraped within the last 14 days.
- **R2.** The system shall apply the three scrape-eligibility rules of `_is_scrapeable_team`
  (`scripts/drain_queue.py:96-121`) — placeholder-unknown team, excluded age group, excluded
  birth year — to **claimed queue rows as well as** top-ups, after enriching claimed rows
  with `team_id_master`, `age_group`, `birth_year` and `last_scraped_at`. That function's own
  docstring records that claimed rows never pass through `find_topup_teams`, so "this is the
  only place they are checked at all."
- **R3.** When the system rejects a claimed row under R2, it shall transition that row to
  `failed` with an explanatory `error_message`, then drop it from the scrape list. `failed`
  is terminal, does not consume a revival enqueue the way `completed` does, and does not
  loop: `_is_scrapeable_team` is deterministic, so releasing to `pending` would have every
  future run re-claim, re-reject and re-release it forever.
- **R4.** The system shall not modify `scripts/drain_queue.py`,
  `.github/workflows/clear-queue.yml`, or `src/scrapers/gotsport.py`.

### Claim lifecycle

- **R5.** The system shall hold one in-memory set of outstanding claimed request ids and
  maintain this invariant at every exit: a row is written to its terminal state *before* its
  id leaves the set, and an id leaves the set immediately after any successful terminal
  transition. The outer `except BaseException` guard shall release only ids still in the set.
  Cancellation arrives as `KeyboardInterrupt`, which is not an `Exception`; R14's non-zero
  exit raises `SystemExit`, which the same guard catches — so the guard must never re-release
  rows already finalized, which the set makes impossible.
- **R6.** Terminal-state writers shall follow this precedence, top to bottom, with the first
  matching branch deciding every outstanding row:
  1. **Selection reject** (R3) — that row alone → `failed`.
  2. **Abort** — pass 2 failed wholesale (R23), or the club-resolution reserve expired (R15)
     → release *all* outstanding rows, write no `team_scrape_log` rows.
  3. **Import failure** (R27) → release *all* outstanding rows, write no `team_scrape_log`
     rows.
  4. **Normal completion** — classify outcomes, remove the block-pressure subset (R34), write
     log rows for the remainder (R30/R31), then finalize per the R34 mapping.
  5. **Guard** (R5) — release whatever is still outstanding.
- **R7.** SIGKILL and runner loss are out of scope. They strand rows in `processing`, and
  `scripts/retire_stranded_scrape_requests.py` is the existing manual recovery. No lease,
  reaper, or persistent claim ledger is introduced.
- **R8.** The system shall release rows to `pending` **one row per statement**, not in the
  100-id batches `_release_queue_items` uses (`drain_queue.py:340-362`), which swallow the
  exception as a warning and would strand the other 99 rows on a single conflict. When a
  release raises `23505` against `idx_scrape_requests_pending_team`, the team already carries
  a newer live pending row, so the system shall retire that redundant claim to `failed` with
  an explanatory message instead. This is a rule, not machinery.

### Fetching

- **R9.** The system shall route every GotSport HTTP request through the ZenRows Batch API,
  both match lists and team-details club lookups, so that no GotSport request originates
  from the runner's IP.
- **R10.** The system shall submit tasks with a proxy tier set by the `premium_proxy` input,
  and shall never send `mode: auto` — auto escalates on failure and billed 25 credits for a
  single dead team against 1 credit flat on defaults. The **default tier is unresolved**; see
  Open Questions.
- **R11.** The system shall set each task's `external_id` to the team's `provider_team_id`
  **as a string**, which is unique per team for GotSport (0 duplicate ids across
  `team_alias_map`).
- **R12.** The system shall keep every submission within **1,000 tasks**. ZenRows' prose
  documentation claims 10,000; its OpenAPI sets `maxItems: 1000` on both
  `SubmitJobRequest.tasks` and `AddTasksRequest.tasks`, and the schema governs. Runs up to
  1,000 teams create a `status: 'closed'` job with tasks inline; above that the system shall
  create the job `status: 'open'`, add tasks in ≤1,000-task batches via
  `POST /jobs/{job_id}/tasks`, then `POST /jobs/{job_id}/close`. Verified live 2026-09-03.
  An open run **begins fetching immediately** rather than waiting for the close, so later
  chunks may stream in while earlier ones are in flight. One job means one `run_id` and one
  cumulative `stats.spend`.
- **R13.** The system shall send a stable `Idempotency-Key` on **job creation**, derived
  from a per-process namespace and the submission index. A retry after an unknown outcome
  shall reuse the same key; an explicit `503` shall use a fresh one. Without this, a lost
  create response orphans a job that keeps billing while R37 captures no `job_id`.
  **`POST /jobs/{job_id}/tasks` carries no key and shall never be replayed on an unreadable
  outcome.** The vendor OpenAPI declares `Idempotency-Key` on `submitJob` and `rerunJob`
  only, so add-tasks has no dedupe guarantee: a retry after a lost response appends the
  chunk a second time and bills every task in it twice. Its `409` is the exception and is
  safe to retry, because it means the chunk was not accepted — the documented cause is task
  ingestion still in progress.
- **R14.** The whole-run ZenRows budget shall start when the **first create request is
  issued** — covering submission, the open-job period, the close call and all polling — and
  shall sit far enough below the workflow's `timeout-minutes` to leave import and claim
  cleanup time. `wait_cap_minutes` shall validate as a positive integer of at least 5. If the
  budget expires before every submission and the close call complete, the system shall stop
  the run and take the R6 abort branch; teams never submitted are released like any other
  outstanding row.
- **R15.** The budget shall reserve `club_reserve_minutes` (default 20) that pass 1 may not
  consume, so a pass-1 timeout can still fund club resolution. On a pass-1 timeout the system
  shall stop the run, collect what exists, run pass 2 within the reserve, then parse and
  import. If the reserve itself expires, the system shall take the R6 abort branch —
  importing with blank clubs is the degradation R23 rejects, and omitting sentinels would
  fall through to `self.session.get`, violating R9.
- **R16.** When stopping a run, the system shall not treat the immediate response as final.
  `POST /jobs/{job_id}/stop` returns `409` with `code: "run_not_stoppable"` once the run is
  terminal (verified live 2026-09-03) — on which the system shall re-fetch the run and treat
  it as completed — and after a successful stop, tasks already in flight may still finish and
  record results, so the system shall poll `stats.completed >= stats.total` on the run
  before taking its final spend snapshot. **Counting result rows is not equivalent**: a
  `TaskResult` exists from task creation and carries a `pending` or `processing` status, so
  a stopped run's listing reads as fully settled and reports a short spend as final.
  `RunStats` requires `total` and `completed`, and the vendor states `total` is correct from
  the first response. If a bound on that settle-wait is exceeded, the reported credits shall
  be labelled a lower bound alongside the logged `job_id`.

### Club resolution

- **R17.** The system shall apply the newest-first sort and 30-match cap **before** collecting
  club ids. The cap is the first of several filters, not the only one: `_parse_api_match`
  additionally discards matches where neither side is the scraped team, U20+ matches by
  `age_group` or `birth_year`, matches with empty or unparseable dates, and matches older
  than `since_date`. Collecting from the capped set is conservative rather than exact.
- **R18.** The system shall apply a side-effect-free pre-filter mirroring the parser's
  team-membership, age, valid-date and `since_date` checks before scheduling club lookups.
- **R19.** From the surviving matches, the system shall collect every team id still needing a
  club name: each scraped team itself, and each opponent whose match payload carried no
  inline `club.name`.
- **R20.** The system shall resolve as many of those ids as possible from the database before
  submitting job 2: `teams.provider_team_id` scoped to the GotSport `provider_id` first, then
  `team_alias_map(provider_id, provider_team_id, team_id_master)` → `teams.club_name` for
  alias-backed teams whose canonical row carries a different `provider_team_id`. The alias leg
  shall filter `review_status = 'approved'`, matching `process_missing_games.py:169`: the
  column's CHECK admits `pending`, `rejected` and `new_team` too
  (`20240101000000_initial_schema.sql:112`), and an unapproved association would feed a wrong
  club into a 0.35-weighted match and into immutable game rows. Both lookups shall batch at
  ≤100 ids per `.in_()` call per CLAUDE.md's URI-length rule and paginate past the 1,000-row
  limit.
- **R21.** The remainder becomes job 2 against `team_ranking_data/team_details`, chunked under
  R12 like any other submission. Opponents repeat heavily across teams and 92.5% of `teams`
  rows already carry a club name (199,880 of 216,039, measured 2026-09-03), so the remainder
  is expected to be a small fraction of the theoretical team × 30 ceiling.
- **R22.** Before parsing, the system shall pre-populate `scraper.club_cache` with the
  **union** of three sources: every club name job 2 resolved, every club name R20 resolved
  from the database, and an empty-string sentinel for every remaining id — including any id
  job 2 returned a body for that carried no `club_name` field. Keys shall be strings matching
  `gotsport.py:745`'s `str(opponent.get("team_id", ""))`, because the guard at `:805` is an
  exact `in` membership test: an integer key, or an id omitted because R20 already resolved
  it, falls straight through to `self.session.get` on the runner's IP.
- **R23.** If job 2 fails wholesale, the system shall take the R6 abort branch. Degrading to
  sentinels would be strictly worse than today's behaviour, where a cache miss triggers a real
  lookup; a blank club feeds `game_matcher.py:682` at 0.35 weight, and games are immutable
  once imported, so a run's worth of degraded matching becomes manual team merges.

### Parsing and output

- **R24.** The system shall parse result bodies with `json.loads` regardless of the `type`
  ZenRows reports, which is `html` even for JSON payloads.
- **R25.** The system shall pass `_parse_api_match` an **integer** team id, normalized
  `int(float(str(provider_team_id)))` exactly as `scrape_team_games:409` does, and a **`date`**
  object as the `since_date` cutoff. `gotsport.py:671` tests
  `home_team.get("team_id") == team_id` by strict equality against the payload's integer id,
  and `:728` compares `game_date < since_date` — so a string id matches nothing and a raw
  timestamp raises a caught `TypeError`, both yielding **zero games with no error**. String
  ids remain correct for `external_id` (R11) and `club_cache` keys (R22); only the parser
  boundary converts.
- **R26.** The system shall reuse `GotSportScraper._parse_api_match` and `_game_data_to_dict`,
  mirroring `scrape_team_games`' newest-first sort and 30-match cap, and shall write
  `data/raw/scraped_games_*.jsonl` in the existing shape for
  `scripts/import_games_enhanced.py`.
- **R27.** If `import_games_enhanced.py` exits non-zero, the system shall release every
  outstanding claim to `pending` under R8, write no `team_scrape_log` rows, preserve the JSONL
  as a workflow artifact, and exit non-zero. This diverges from **both** existing scripts —
  `drain_queue.py:835-854` warns and finalizes regardless, and `process_missing_games.py:676-679`
  marks the request `failed` — because a 5,000-team run must stay retryable, and leaving rows
  in `processing` is not retryable either, since `claim_queue_items` selects only `pending`.

### Bookkeeping

- **R28.** The system shall determine each pass-1 team's outcome from that team's own per-task
  `error` field, never from run-level `failure_reasons`, which is a rollup and cannot identify
  which team failed. The documented buckets are `bad_target` (bad host, 404, 410, too large)
  and `blocked` (anti-bot / policy denials); no per-task error code means "target returned
  403" — `RESP002` is 404-specific and `AUTH009`/`BLK0001` are ZenRows-side.
- **R29.** The system shall classify every pass-1 outcome **before** writing any
  `team_scrape_log` row, so R34's block-pressure subset can be excluded from logging entirely.
- **R30.** For each pass-1 team not excluded by R34, the system shall write a
  `team_scrape_log` row: a task that reached GotSport and returned games or an empty list logs
  `success`/`partial` and advances `teams.last_scraped_at`; a task blocked or failed in transit
  logs `error` and shall not advance it.
- **R31.** A per-task `error` with `status` 404 shall log as `error` **with**
  `last_scraped_at` advanced — matching `drain_queue.py:483-502` and deliberately diverging
  from R30's general rule, because a 404 is a permanent answer and re-probing a dead id every
  run buys nothing. `team_scrape_log.status` is CHECK-constrained to
  `('success','error','partial')` (`20240101000000_initial_schema.sql:212`), so "not found" is
  a run-summary counter, not a fourth status.
- **R32.** A **job-2** task outcome shall produce only a club name or a sentinel — never a
  `team_scrape_log` row, never a `last_scraped_at` advance, never a queue transition. R20
  guarantees job 2's set is precisely the ids *not* resolvable from the database, i.e. real
  team rows; applying R30/R31 to them would log an opponent lookup as a team scrape, reset its
  re-probe clock, and push it outside `find_topup_teams`' 14-day window.
- **R33.** The system shall finalize claimed rows by the same mapping `_finalize_queue_items`
  uses (`drain_queue.py:365-392`): a row whose log entry is `error` becomes `failed`, every
  other row becomes `completed` with its game count.
- **R34.** When the `blocked` bucket exceeds `block_abort_pct` (default 20) of pass-1 tasks,
  the system shall release **only the blocked subset** to `pending` and write no log rows for
  those teams; every other team follows R30–R33 normally. Teams whose failure is a 404 (R31)
  are never released — that answer is permanent, not retryable. Releasing only the blocked
  subset matters in both directions: `_finalize_queue_items` fails only rows carrying an
  `error` entry, so a wholesale release would return the majority that were successfully
  scraped *and already imported* back to `pending` for a redundant re-scrape; and a released
  team that had already been logged `success`/`partial` would be counted again by
  `refresh_team_scrape_activity` (`WHERE l.status <> 'error'`, `20260827100100:86-97`) into
  the `scrape_attempts < 10` gate `find_topup_teams` reads.
- **R35.** The system shall print `job_id` and `run_id` for every job to the workflow log and
  upload them as an artifact, so a cancelled run can be recovered inside ZenRows' 14-day
  result retention.
- **R36.** The system shall report teams attempted, games written, tasks failed by reason,
  teams not found, and credits spent — on **every** exit that created a job, including the R6
  abort and guard branches, marked as an aborted run.

### Safety

- **R37.** The system shall support `--dry-run`, which selects teams and reports the planned
  task count and credit estimate without creating a ZenRows job or writing to the database.
  Because `claim_queue_items` writes, the dry run shall preview queue order with a read-only
  select rather than claiming.
- **R38.** The system shall never write the ZenRows API key to a log line, an error message,
  or an artifact, reusing `_redact(text, secret)` from `src/scrapers/_zenrows.py:39`.
- **R39.** The system shall not introduce cross-workflow exclusion against
  `process-missing-games.yml`, and shall not claim a duplicate-scrape count it cannot derive.

## Design

### Architecture

Two new production files — `scripts/batch_drain_queue.py` and
`.github/workflows/batch-clear-queue.yml` — plus `tests/unit/test_batch_drain_queue.py` and
fixtures under `tests/fixtures/zenrows_batch/`. Nothing else is edited, in particular none of
the three files named in R4.

**Workflow inputs.** Its own contract, not `clear-queue.yml`'s — that workflow's
`use_zenrows` and `concurrency` are meaningless here, since this workflow is Batch-only and
ZenRows owns the fan-out.

| Input | Type | Default | Notes |
|---|---|---|---|
| `team_limit` | string | `'5000'` | Total scrape target (R1). Validated `^[0-9]+$`. |
| `premium_proxy` | boolean | *unresolved* | R10; see Open Questions. |
| `wait_cap_minutes` | string | `'120'` | Whole-run ZenRows budget (R14). Positive integer ≥5. |
| `club_reserve_minutes` | string | `'20'` | Reserved for pass 2 (R15). Positive integer. |
| `block_abort_pct` | string | `'20'` | R34's release threshold. |

`timeout-minutes: 180`, leaving ~60 minutes beyond the budget for import, bookkeeping and
claim cleanup.

**Transport.** Raw `requests`, not the `zenrows` SDK — every other ZenRows caller here
(`src/scrapers/_zenrows.py`, `src/scrapers/gotsport.py`,
`scrapers/outreach_scraper/outreach_scraper/zenrows.py`) uses raw `requests`, and the SDK is
in neither `requirements.txt` nor `requirements.lock`.

**Batch API contract.** Base `https://async.api.zenrows.com/v1`, header `X-API-Key`. All
rows verified live 2026-09-03.

| Step | Call |
|---|---|
| Create (closed, ≤1,000 tasks inline) | `POST /jobs` → `{job_id, latest_run:{run_id, status, stats}, accepted_tasks}` |
| Create open → add → close | `POST /jobs` (`status:'open'`) → `POST /jobs/{job_id}/tasks` → `POST /jobs/{job_id}/close` |
| Poll | `GET /jobs/{job_id}/runs/{run_id}` |
| Results | `GET /jobs/{job_id}/runs/{run_id}/results` → `{results:[…], next_cursor}` |
| Body | `GET result_url` — either a **24-hour** presigned link (no auth header) or a relative `/v1/jobs/<id>/runs/<run>/tasks/<tid>/content` path, which **requires** `X-API-Key` |
| Stop | `POST /jobs/{job_id}/stop` — 409 `run_not_stoppable` once terminal |

`result_url` is empty for non-successful tasks and `error` is present on failed ones — exclusive
across the two *terminal* states, which is what R28's per-team classification rests on. A
`pending` or `processing` row has neither, so per-task outcome is read from `TaskResult.status`
rather than inferred from an empty `result_url`; a run stopped at its deadline leaves such rows
behind, and counting them as failures misreports a budget overrun as a scrape blocked at source.

Verified against the vendor OpenAPI (`ZenRows/zenrows-python-sdk`, `docs/openapi.yaml`) on
2026-09-03. Where that schema and the prose documentation disagree, the schema governs — it is
what caught the poll-response shape, the `Spend` object, the add-tasks idempotency scope and
both `result_url` forms, each of which the prose had wrong.

### Key flow

1. Claim rows, top up to N, filter through R2, fail rejects per R3. Populate the R5
   outstanding set.
2. Pass 1: one task per surviving team, `url` = `/api/v1/teams/{provider_team_id}/matches`
   plus R25's date params, `external_id` = the string `provider_team_id`, chunked ≤1,000 with
   R13 idempotency keys. Poll until complete or the R14/R15 budget bites.
3. Download bodies, `json.loads` (R24), sort newest-first, cap at 30 (R17), apply R18's
   pre-filter.
4. Collect ids needing clubs (R19); resolve what the database can answer (R20).
5. Pass 2 within the R15 reserve. On wholesale failure or reserve expiry → R6 abort.
6. Pre-fill `club_cache` with the three-source union, string-keyed (R22).
7. Per team: `_parse_api_match` with an **integer** id and a **`date`** cutoff (R25), then
   `_game_data_to_dict`; append to the JSONL.
8. Import (R26). Non-zero → R6 branch 3: release all, no log rows, exit non-zero (R27).
9. Classify outcomes (R29) → set aside R34's blocked subset → write log rows for the
   remainder (R30/R31, pass-1 teams only per R32) → finalize per R33 → release the blocked
   subset under R8 → clear the outstanding set → print the R36 summary.

R6 is the single precedence order over all of these; R5's set is what makes it enforceable.

### Why the parser needs no refactor

`_fetch_club_name_for_team_id` consults `club_cache` before any network call
(`gotsport.py:805`). Pre-filling that cache makes the existing parser network-free at the
point of use — but only if the fill is complete and correctly keyed, which is why R22 is a
union over three sources. The two ways to get it wrong both fail silently, falling through to
a direct request from the runner's IP: **omitting the ids R20 resolves from the database**
(92.5% of teams already carry `club_name`, so job 2 is deliberately not asked about most
opponents), and **keying by integer** (`:805` is `if team_id in self.club_cache`; `:745`
passes `str(...)`).

R25 is the mirror-image trap at the same boundary and fails just as silently in the opposite
direction: the cache wants strings, the parser wants an int.

The batch path never calls `scrape_team_games`, so `_extract_club_name` — which does *not*
check the cache first — is never reached. The cost is that the script calls two private
methods on `GotSportScraper`, a deliberate trade against R4: reaching into internals is far
less risky than refactoring a module the every-15-minute production drainer runs through.

### Cost model

Measured, 11 identical tasks, plus a 4-task confirmation on 2026-09-03:

| Configuration | Credits | Wall clock |
|---|---|---|
| Current production (`premium_proxy=true`) | 110 | — |
| Batch, `zenrows_params:{mode:'auto'}` | 35 | 18s |
| Batch, default params (datacenter) | **11** | **7s** |

The 1-vs-10 credit difference is real and reproduced three times. What is **not** established
is that datacenter proxies survive production volume — see Open Questions. If they do not, the
cost model reverts to 10 credits/team and the project's value is the ~5x speed-up alone, which
still makes an 18,190-team sweep fit inside one run for the first time.

### Error handling

- R6 is the precedence order; R5's outstanding set makes it enforceable; R8 governs the
  mechanics of every release.
- A task carrying an `error` and no `result_url` never reached GotSport usefully; R28/R31 map
  `error.status` 404 to "not found" and everything else to `error`.
- Failed body downloads (expired presign, S3 error) are retried once, then counted as `error`.
- A duplicate scrape from the accepted `process_missing_games.py` overlap is neither prevented
  nor counted (R39).

### Testing

- Unit: task-list construction, chunking at the **1,000** boundary, `external_id` round-trip,
  per-task outcome classification (404 vs blocked vs success), idempotency-key derivation and
  its reuse-on-timeout / fresh-on-503 split, and the R22 union — including an id R20 resolved
  from the database, a job-2 body with no `club_name`, and an int-keyed entry treated as a miss.
- **A test asserting a non-zero game count** for a fixture team through the batch path. This is
  what catches R25's type trap; every assertion that only checks "no exception" passes while
  the parser returns zero games.
- A test asserting `session.get` is never called during parsing (R22's completeness).
- A test asserting the generated club-task ids after R18's pre-filter — the characterization
  test cannot detect over-collection, since the parser discards those games anyway.
- **Claim-lifecycle tests, one per R6 branch:** R3 selection reject, R23 abort, R15 reserve
  expiry, R27 import failure, R34 block-pressure partial release, R33 normal finalize, and the
  R5 guard. Each asserts no row ends in two terminal states and none is left outstanding.
- An R8 test: a release that raises `23505` retires that one claim to `failed` and leaves its
  neighbours released, proving the row-by-row rule.
- Characterization: parse a captured body through both `scrape_team_games` and the batch path,
  asserting identical `_game_data_to_dict` output. The fixture must hold more than 30 matches
  spanning the `since_date` cutoff.
- Contract: recorded fixtures of closed-create, open-create, add-tasks, close, poll, results,
  and stop's 409 `run_not_stoppable`.
- All HTTP mocked; no test spends credits.

## MVP Scope

**Ships:** both passes, queue claim plus top-up with R2 filtering, the R5/R6/R8 claim
lifecycle, dry run, auto-import with R27's failure gate, bookkeeping, job-id logging, and the
five-input workflow.

**Deferred:** webhook result delivery; automated resume from a logged `job_id`; promoting the
batch client into `src/scrapers/`; retiring `clear-queue.yml`.

**Rollout.** Blocked on the proxy-tier test in Open Questions, which sets `premium_proxy`'s
default. Once that is known, the first dispatch runs ~500 teams — one submission, no chunking
— and R36's summary is read for the `blocked` bucket before scaling to 5,000. The open →
add-tasks → close path is exercised for the first time only above 1,000 teams, so the
5,000-team run is also its first real test.

## Open Questions

- **Does the datacenter proxy tier survive production volume?** The measured 1-vs-10 credit
  saving rests on it, but the only supporting evidence is 10- and 11-URL probes, and the
  operator reports that running without ZenRows usually trips the WAF — so the residential
  tier is the known-good configuration. **Resolution:** the operator runs the existing
  `clear-queue.yml` on ~300 teams with `zenrows_premium_proxy: false`; a clean run sets
  `premium_proxy`'s default to false, CloudFront 403s set it to true and the cost model
  reverts to 10 credits/team. Until then R10's default is unresolved and the workflow input
  has no default value.
- **Should `clear-queue.yml` eventually be retired?** Deferred by the operator until both
  have real numbers side by side.
