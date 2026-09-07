---
status: done
note: Steps 1-9 shipped in d03775c2d. Step 3's mechanism CHANGED during
  implementation and steps 10-13 (rollout) are outstanding - read
  .turbo/reports/2026-08-27-scrape-activity-review-blockers.md before acting on this plan.
---

# Plan: Retarget the Scrape Queue Away From Inactive Teams

## Context

PitchRank's scrape queue spends its fixed weekly quota re-checking teams that have stopped
playing, or that have never produced a game at all. Measured against production on
2026-08-27:

- **2,001,882 of 2,508,929** scrape-log rows (80%) found zero games.
- Over the last 90 days, **15,574 of 172,468 scrapes (9.0%)** went to teams with no
  completed game since 2024.
- **12,732 teams have no game rows whatsoever** yet have been scraped 10+ times each —
  **313,226 scrapes burned**, averaging 25 attempts over ~9 months apiece.

Two producers cause this by construction. `find_stale_teams` selects on "never scraped or
90d+ stale", which a dormant team satisfies permanently, so it is re-enqueued every Sunday
forever. `find_discovery_teams` selects on "no future games", which a dormant team also
satisfies by definition.

### What this change actually buys — read this before writing the PR description

**It retargets scrapes. It does not reduce scrape volume, and it will not lower the ZenRows
bill.** Every surface this plan gates is a fixed-N selector:

| Site | Cap | Set where |
|---|---:|---|
| `enqueue_safety_net.py` | 500 | `:48` `DEFAULT_LIMIT`; `enqueue-safety-net.yml:36` leaves `LIMIT_FLAG` empty on schedule |
| `enqueue_discovery_teams.py` | 1000 | `:47` `DEFAULT_LIMIT`; `enqueue-discovery.yml:35` likewise |
| `process_missing_games.py` | 40/run | `process-missing-games.yml:42` `--limit 40` |
| `drain_queue.py` top-up | pages **until** `shortfall` survivors | `:279-315` |

The producers enqueue *up to* their quota and the eligible pool stays far above it — the
re-probe branch alone admits all 23,302 NULL-`last_scraped_at` teams — so after this change
they will still enqueue ~1,500/week, aimed at better targets. A stricter top-up RPC just
pages deeper and still returns N.

So the measured figures above are evidence of **mistargeting**, not of recoverable spend.
The payoff is games-found-per-scrape, and the same budget covering teams that might actually
have played. **If lowering spend is the goal, the lever is the producer limits or the drainer
cadence — one-line changes, deliberately out of scope here.**

An earlier investigation (`.turbo/reports/2026-08-27-inactive-teams-since-2024.md`)
established that these team rows must **not** be deleted: they are opponents in 11,509 games
belonging to 6,451 still-active teams. `teams` carries 18 inbound foreign keys, so a delete
either **errors** — `games` references it `ON DELETE NO ACTION`, and every one of these
teams has games — or, for a team without games, **cascade-deletes its `rankings_full` and
`ranking_history` rows**. This plan changes only what we *scrape*, never what we store.

### Decisions already made (do not re-litigate)

| Decision | Choice | Rationale |
|---|---|---|
| Mechanism | Persisted columns on `teams`, weekly refresh | Live computation from `games` timed out repeatedly against prod |
| Dormancy cutoff | **12 months** | User's call |
| Scope | Dormancy rule **and** never-productive rule | The never-productive branch is 13,711 scrapes/90d vs the dormancy branch's 1,863 |
| Ranked-team exemption | Ranked in any `ranking_history` snapshot in the last 30 days | Verified to strictly contain the current `rankings_full` set (0 exceptions) |
| Fixture exemption | A fixture in the future or within the last 30 days | Gives a late-posted score or a scraper outage time to resolve |
| Re-probe | Any filtered team is re-admitted for one scrape every 6 months | Removes the permanent-exclusion risk. **Depends on step 5** |
| **Expected outcome** | **Enqueue volume unchanged (~1,500/week); games-found-per-scrape up** | Every gated site is fixed-N — see above. Unchanged volume is success, not failure |

#### Why not `rankings_full` for the ranked exemption

`rankings_full` is built from a 365-day game window and the cutoff is also 365 days, so it
structurally covers only the ~28-day grace taper plus merge skew. It is also actively pruned:
`scripts/calculate_rankings.py:540-547` computes `stale_ids = existing_ids - new_team_ids` and
DELETEs them each run. Measured protection of the 35,457 teams the 12-month rule catches:

| Exemption source | Teams protected |
|---|---:|
| `rankings_full` (current only) | 3,578 |
| `ranking_history`, last 14 days | 4,236 |
| **`ranking_history`, last 30 days** | **5,445** |
| `ranking_history`, last 60 days | 10,966 |
| `ranking_history`, last 90 days | 19,143 |

`idx_ranking_history_team_date (team_id, snapshot_date DESC)` exists, so the `EXISTS` is an
index lookup against the 12.7M-row table.

### The one-way-door question, answered

**Dormancy is mostly self-healing, but not entirely — hence the 6-month re-probe.**

When a revived team plays anyone we still scrape, the opponent's scrape writes a game row
carrying the revived team's master id (`src/models/game_matcher.py:596-613`, `:636-649`,
`:696-701`), and `find_recently_active_teams` picks it up within a day. The TGS, PlayMetrics,
and Affinity-WA importers are scheduled weekly and import games for teams they do not own,
ignoring scrape eligibility entirely — a genuine second recovery path.

But recovery begins only *after* a game row exists, and if both opponents are filtered —
or a whole local competition is — nothing creates one. GotSport event import is manual-only
(`auto-gotsport-event-scrape.yml` is `workflow_dispatch`), and
`scripts/scrape_upcoming_gotsport_events.py` explicitly does not import games. So an
all-GotSport dormant pocket could stay excluded permanently.

The re-probe closes this by reusing `teams.last_scraped_at`, which stops advancing precisely
because the team is filtered.

> **The re-probe is inert without step 5.** `scripts/process_missing_games.py` — the
> every-15-minute drainer that consumes these enqueues — contains **zero** references to
> `last_scraped_at` (grep-verified) and writes no `team_scrape_log` row.
> `src/scrapers/base.py:171-179` `_log_team_scrape` is the only place pairing the two, and
> that script bypasses it; `EnhancedETLPipeline._update_team_scrape_dates`
> (`src/etl/enhanced_pipeline.py:2401-2465`) derives its team set from successfully
> **inserted** game records, and `process_request` only queues an import when games is
> non-empty (`:487-497`). So today a probe that finds nothing bumps nothing, and the team
> would be re-admitted the *next* Sunday and every Sunday after — ~52 probes/year rather
> than ~2. Step 5 fixes that; the re-probe must not be considered working until it ships.

**The filter must still NOT be added to `find_recently_active_teams` or
`find_yesterday_null_score_teams`.** They are already immune to dormant teams *and* are the
only automated producers that can re-enqueue a revived one.

## Pattern Survey

### Analogous Features

- **`scripts/backfill_team_distinction.py` — the script skeleton to mirror.** The only script
  that writes a derived column onto `teams`, already in `data-hygiene-weekly.yml` (Step 1b,
  `:163`). argparse `:112-128` (`--dry-run` opt-in, defaults LIVE); `rich` `:36,:47` for
  humans, bare `print` for the machine line; summary `:231`/`:268`; docstring `:15-22`
  declares a **LOAD-BEARING INVARIANT** — exactly one stdout line matching
  `(Would update|Updated):\s*\d+`, self-tested by `_self_test()` `:80-108`; exits non-zero on
  partial failure `:266-274`.
- **`scripts/drain_queue.py:113-153` `_bulk_log_team_scrapes` — the exact helper step 5 should
  mirror.** Batches log inserts 500 at a time, calls
  `bulk_update_last_scraped_at(supabase, update_payload)` at `:151`, honours a per-entry
  `update_last_scraped_at` flag at `:137`, and swallows insert failures with a warning.
- **`scripts/find_inactive_teams.sql`** (untracked) has the merge-resolving aggregation, but
  its final `SELECT` at `:47` is `FROM teams t JOIN activity a` — an **inner** join that
  cannot see a zero-game team. **Do not copy that join shape.**
- **`rankings_full.last_game`** cannot be the source: the ranking run uses a 365-day window
  and `rankings_full` is a subset, so dormant teams are exactly the ones absent from it.

### Reusable Utilities

- **`supabase/migrations/20260325100000_batch_backfill_game_stats.sql:13-130`** —
  `backfill_total_game_stats()`, **no payload**: temp table then cursor-driven 10,000-row
  batches with `SET LOCAL statement_timeout = '300s'` `:35`. `LANGUAGE plpgsql`,
  `SECURITY DEFINER` `:15-16`, but **no function-level `search_path`**.
- **`supabase/migrations/20260615200000_homepage_stats_cache.sql:32-64`** — the security
  precedent: `SECURITY DEFINER`, `SET search_path = ''` `:33`,
  `REVOKE EXECUTE ... FROM PUBLIC, anon, authenticated` `:64`. PostgreSQL grants EXECUTE to
  PUBLIC by default (`20260602000000_add_batch_backfill_null_scores.sql:72-77`).
- **`scripts/calculate_rankings.py:1006-1016`** — the client-timeout precedent:
  `create_client(url, key, options=SyncClientOptions(postgrest_client_timeout=360))`, with
  the comment that the default 120s kills the RPC mid-flight. Runs weekly in production, so
  the long-running-RPC-through-the-client pattern demonstrably works here.
- **Do not use `.upsert()` on `teams`** — zero precedent; NOT NULL `provider_team_id`,
  `team_name`, `age_group`, `gender` make clobber risk real.
- `CREATE TRIGGER update_teams_updated_at BEFORE UPDATE ON teams`
  (`20240101000000_initial_schema.sql:376`) fires per row — hence step 3's
  `IS DISTINCT FROM` guard.
- **`scripts/drain_queue.py:245-316`** — `_fetch_topup_teams`. `_TOPUP_STALE_DAYS = 14`
  `:232`, `_TOPUP_PAGE_SIZE = 1000` `:233`, `_TEAM_KEYS` `:234-242`. It computes `cutoff`
  **once** at `:278` before the loop, then OFFSET-pages (`offset += _TOPUP_PAGE_SIZE`,
  breaking only on an empty or short page, `:311-314`). Both facts are load-bearing for
  steps 4 and 7. `_is_scrapeable_team` is defined `:96-110` and called at **both** `:305`
  (top-up) and `:610` (queue-claimed rows). PostgREST errors are allowed to propagate —
  pinned by `test_postgrest_errors_propagate` (`tests/unit/test_drain_queue_topup.py:229`) —
  and the caller's `except` at `:671-675` releases claimed rows and re-raises.

### Convention Anchors

- **Column-add migration to mirror: `20260502043821_add_teams_distinction.sql`.**
  `ALTER TABLE teams ADD COLUMN IF NOT EXISTS` on unqualified `teams`;
  `CREATE INDEX IF NOT EXISTS`, **never `CONCURRENTLY`** (Supabase wraps each migration in a
  transaction); `COMMENT ON COLUMN` style at `:8-11` with explicit NULL semantics.
- **Eligibility functions**, all in
  `supabase/migrations/20260824120000_scrape_eligibility_uses_season_year.sql`. All share a
  season-year CTE and three filters (age_group not in `('U8','U-8','U9','U-9')`,
  `birth_year not in (yr-21,yr-20,yr-8,yr-7,yr-6)`, `not (t.team_name = 'unknown_' || t.provider_team_id)`),
  and all have a `t` alias in scope (`find_discovery_teams` has `FROM teams t` at `:137`).

  | Function | Signature / location | Sole caller | Gates production? |
  |---|---|---|---|
  | `get_teams_to_scrape_limited` | `:17-68` | `scrape_games.py:351-362` | **No** — manual `scrape-games.yml` only |
  | `find_stale_teams` | `(p_provider_id uuid, p_row_limit integer DEFAULT 500)`, `:157-177` | `enqueue_safety_net.py:60-63` | **YES — priority 4**, cron `0 16 * * 0` |
  | `find_discovery_teams` | `(p_provider_id uuid, p_row_limit integer DEFAULT 1000)`, `:113-154` | `enqueue_discovery_teams.py:59-62` | **YES — priority 3**, cron `0 14 * * 0` |
  | `find_recently_active_teams` | `(p_provider_id uuid, p_active_window_days int DEFAULT 3, p_cooldown_hours int DEFAULT 20, p_row_limit int DEFAULT 2000)`, `:180-229` | `enqueue_active_teams.py:71-79` | Immune — **DO NOT TOUCH** |

  Modify in place with `CREATE OR REPLACE` **at an identical signature** — `20260824120000`
  did exactly that and its header `:12-13` records that this preserves GRANTs. **Adding a
  parameter creates an overload** and every existing call then fails with "function is not
  unique".
- **`scripts/process_missing_games.py`** — the every-15-min drainer. Reads `scrape_requests`
  with no teams-table filter (`:81-97`), writes `processing` **unconditionally** after
  fetching (`:434`), treats `team_id_master` as optional (`:465`), carries `self.dry_run`
  honoured by every other write (`:101`, `:316`, `:339`), and breaks/flushes on
  `WAFBlockedError`.
- **Migrations are hand-applied.** Nothing in `.github/workflows/` runs `supabase db push`
  (verified across all 42 workflow files); CLAUDE.md:463-464 documents the manual push plus
  ledger repair. This drives step 10's ordering.
- **Tests.** `test_age_rollover_freeze_coverage.py` matches writing steps by hardcoded script
  filename (`:29-33`, `:39-48`, decision `:108-112`) — **a new hygiene script does NOT fail
  it**. A new *workflow file* with a `cron:` **does** trip
  `tests/unit/test_agent_doc_references.py:367-379` until CLAUDE.md's workflow table lists it.
  - `find_stale_teams`, `find_discovery_teams`, `get_teams_to_scrape_limited` have **no tests
    by name**. `find_recently_active_teams` has its RPC name and full `p_*` payload pinned at
    `tests/unit/test_enqueue_active_teams.py:45-55`.
  - **`tests/unit/test_drain_queue_topup.py`.** `_supabase_paging(pages)` `:36-69` records
    builder-chain calls; `:224-226` asserts `set(team) == TEAM_KEYS` against a duplicated
    literal at `:11-19`; `test_query_excludes_birth_years_dynamically:104` reads
    `supabase._calls["or_"][0][0][0]`; `:99-110` documents the unique-tiebreaker requirement
    **because OFFSET paging is in use**; `test_postgrest_errors_propagate:229`;
    `_is_scrapeable_team` cases `:394-435`.
  - `.github/workflows/ci.yml:20-43` **does not apply migrations** — nothing in CI executes
    the changed SQL. This is why the migration-content assertions are mandatory and why the
    step-12 live gate is the only behavioral check.
- **Workflow conventions (`data-hygiene-weekly.yml`, cron `0 11 * * 1`).** Job-level `env:`
  `:63-101`. **No step uses `continue-on-error`**; every step sets `set -o pipefail` because
  `tee` returns 0 and hid a 12-week outage. Steps write `logs/step*.log` (uploaded `:283-291`)
  and a `$GITHUB_OUTPUT` row consumed by the summary `:294-327`. Representative step `:161-183`.

### Proposed Alignment

Mirror `backfill_team_distinction.py` for the script skeleton, `_bulk_log_team_scrapes` for
the hot-path write, `backfill_total_game_stats()` for the batching, and
`homepage_stats_cache.sql` for the security posture. Express the eligibility rule **once**, in
SQL, shared across all three gating surfaces — which is why `drain_queue.py`'s top-up moves
from a hand-built PostgREST query to a dedicated RPC.

## The canonical eligibility predicate

This exact block appears in **three** places: `find_stale_teams`, `find_discovery_teams`, and
`find_topup_teams`. It is the single definition of the rule, and step 9's drift test asserts
all three copies are identical.

```sql
AND ( -- canonical-eligibility-v1
      -- a fixture in the future, or within the last 30 days (late scores, outages)
      (t.last_fixture_at IS NOT NULL AND t.last_fixture_at >= CURRENT_DATE - 30)
      -- ranked in any snapshot in the last 30 days
   OR EXISTS (SELECT 1 FROM public.ranking_history h
               WHERE h.team_id = t.team_id_master
                 AND h.snapshot_date >= CURRENT_DATE - 30)
      -- played recently enough
   OR (t.last_played_at IS NOT NULL
       AND t.last_played_at > CURRENT_DATE - INTERVAL '12 months')
      -- never produced a game, but not yet proven futile
   OR (COALESCE(t.game_row_count, 0) = 0 AND COALESCE(t.scrape_attempts, 0) < 10)
      -- six-month re-probe: nothing filtered stays filtered forever
   OR (t.last_scraped_at IS NULL
       OR t.last_scraped_at < NOW() - INTERVAL '6 months')
)
```

The `-- canonical-eligibility-v1` anchor on the opening line is **required**: it is how the
drift test locates the block. Bump the version suffix if the rule ever changes.

Branch notes:

1. **`last_fixture_at >= CURRENT_DATE - 30`** — one column covers both the future-fixture
   exemption and the 30-day grace, because `last_fixture_at` is `MAX(game_date)` over *all*
   rows.
2. **`ranking_history` within 30 days** — see "Why not `rankings_full`".
3. **Strict `>`** on the dormancy boundary, in every copy.
4. **`game_row_count = 0`, NOT `last_played_at IS NULL`.** The latter means "no *scored*
   game" and would also capture the 13,867-team cohort with unscored or future rows.
5. **Re-probe** reads `last_scraped_at`. `IS NULL` is included deliberately: a never-scraped
   team with game rows would otherwise match no branch and be excluded permanently.

#### Why there is no fourth, negated copy

An earlier draft added a `cancel_ineligible_pending_requests` RPC to purge already-queued
rows, carrying a negated fourth copy. **Dropped deliberately — do not re-add it.** Measured
2026-08-27, `scrape_requests` holds only **279 pending** rows in total (against 160,550
completed, 2,690 failed, 6,482 processing), and the queue drains continuously, so stale
pending rows clear on their own within hours. A destructive cleanup RPC plus a wrapper
script, plus a negated copy that no text assertion can reliably distinguish from an
un-negated one — where a missing `NOT` silently inverts the UPDATE from "cancel ineligible"
to "cancel everything eligible" — is wildly disproportionate to that. The filter alone
prevents refills.

Separately, and **out of scope for this plan**: 6,482 rows sit permanently in `processing`
because nothing ever reclaims them — no lease, expiry, or reaper, as CLAUDE.md documents.
That is roughly 4% of all requests ever created and is a pre-existing bug deserving its own
ticket.

## Implementation Steps

Steps 1-9 are code that lands and passes CI together. Steps 10-13 are the rollout, in order.
The Sunday cron is **not** enabled until step 12's gate passes.

1. **Branch from the right baseline**
   - Re-verified during planning: a parallel worker committed previously-staged frontend work
     as `b68328f09` on `show-team-name-in-rankings`, so HEAD is **1 commit ahead of
     `origin/main`**, and the tree holds only `scripts/backfill_unknown_team_names.py`
     (modified) plus untracked files.
   - `git fetch --all --prune`, then
     `git checkout -b skip-inactive-teams-in-scrape-queue origin/main`.
   - **Re-run `git status` first anyway** — this checkout demonstrably changes under parallel
     workers mid-session. If staged work has reappeared, isolate via a worktree off
     `origin/main`, and never `git stash` (it drops the index).
   - Confirm `git diff --merge-base origin/main --stat` is empty before the first edit.

2. **Migration: four derived columns on `teams`**
   - `supabase/migrations/<ts>_add_teams_scrape_activity_columns.sql`, mirroring
     `20260502043821_add_teams_distinction.sql`.
   - `last_played_at DATE`, `last_fixture_at DATE`, `game_row_count INTEGER`,
     `scrape_attempts INTEGER`, each `ADD COLUMN IF NOT EXISTS`.
   - `COMMENT ON COLUMN` for each. **NULL means one thing only, for all four: the refresh has
     not run for this team yet.** Everything else is materialized as a value (step 3
     coalesces), so the predicate's `COALESCE` guards cover the pre-first-refresh state, not
     ordinary rows.
     - `last_played_at` — most recent game with both scores set, merge-resolved. (The one
       column where NULL is also a real value post-refresh: no scored game. Branch 4 does not
       read it, so this is safe.)
     - `last_fixture_at` — most recent game date of any kind, past or future, scored or not.
     - `game_row_count` — count of game rows of any kind. **0, not NULL, for a team with no
       games.**
     - `scrape_attempts` — count of non-error `team_scrape_log` rows **since 2025-11-03**,
       when that table begins. A ~9-month counter, not lifetime. **0, not NULL.** It
       undercounts the automatic drainer until step 5 has soaked (step 10) — which fails safe,
       toward scraping.
   - **No new index.** No query ANDs a predicate on `last_played_at` — the rule is a
     five-branch OR containing a non-indexable `EXISTS`, so Postgres applies it as a post-scan
     filter. Any such index degrades to a `provider_id` prefix already served by
     `teams_provider_scrape_priority_idx (provider_id, last_scraped_at ASC NULLS FIRST)`
     (`20260422000002:74-75`), which additionally serves `find_stale_teams`'s
     `ORDER BY last_scraped_at ASC NULLS FIRST` and the top-up's descending order — while
     costing HOT-update suppression on ~137K rows every refresh.

3. **Migration: `refresh_team_scrape_activity()` RPC**
   - Batching from `20260325100000:13-130`; security from `20260615200000:32-64`.
   - `refresh_team_scrape_activity(p_dry_run boolean DEFAULT false) RETURNS integer`.
   - `LANGUAGE plpgsql`, `SECURITY DEFINER`, `SET search_path = ''` (schema-qualify
     everything), then `REVOKE EXECUTE ... FROM PUBLIC, anon, authenticated;` and
     `GRANT EXECUTE ... TO service_role;`
   - `SET LOCAL statement_timeout = '300s'`.
   - **Key the temp table off `teams`:**
     `public.teams t LEFT JOIN <games agg> g ON ... LEFT JOIN <log agg> l ON ...`. A
     `games`-driven union cannot emit a row for the zero-game teams that are the whole target
     of the futility rule, and a teams-driven key set also prevents stale values, since rows
     absent from the temp table are never UPDATEd.
   - **Project with explicit coalesce and cast:**
     - `last_played_at = g.last_played_at`
     - `last_fixture_at = g.last_fixture_at`
     - `game_row_count = COALESCE(g.game_row_count, 0)::integer`
     - `scrape_attempts = COALESCE(l.non_error_attempts, 0)::integer`
   - Games aggregate, per `team_id_master` after resolving merges
     (`LEFT JOIN public.team_merge_map m ON m.deprecated_team_id = tid`, take
     `COALESCE(m.canonical_team_id, tid)`; one hop, no chained merges exist):
     - `last_played_at = MAX(game_date) FILTER (WHERE home_score IS NOT NULL AND away_score IS NOT NULL)`
     - `last_fixture_at = MAX(game_date)` — all rows, no date filter
     - `game_row_count = COUNT(*)`
     - Games join `public.teams.team_id_master`, **never `teams.id`**.
     - **Do not filter `is_excluded`.** The repo is split, and every verification figure here
       was measured **without** it. An implementer who mirrors `20260325100000:49`, which does
       filter, will not reproduce those numbers.
   - Scrape-log aggregate: `non_error_attempts = COUNT(*)` over `public.team_scrape_log`
     **excluding `status = 'error'`**, grouped by `team_id` **resolved through
     `team_merge_map` the same way**. Verified reasons: bulk consumers persist WAF blocks and
     404s as `status='error'` (`scripts/drain_queue.py:499`, `:515`), so counting them lets
     transient failures retire a live team; and merging deprecates a team without repointing
     its scrape logs (`20251230000001:177-187`), so unresolved grouping undercounts the
     canonical team.
   - Update `public.teams` in cursor-driven 10,000-row batches, guarded:
     `WHERE (t.last_played_at, t.last_fixture_at, t.game_row_count, t.scrape_attempts) IS DISTINCT FROM (b....)`.
     This updates `teams` — ~137K rows, 16 indexes, per-row `update_teams_updated_at` trigger
     — unlike the prior art which updates `rankings_full`.
   - `p_dry_run = true` returns the same guarded count without the UPDATE.

4. **Migration: `find_topup_teams`**
   - `find_topup_teams(p_provider_id uuid, p_cutoff timestamptz, p_row_limit integer DEFAULT 1000, p_offset integer DEFAULT 0)`
     returning the columns in `_TEAM_KEYS` (`drain_queue.py:234-242`), carrying the canonical
     predicate plus `last_scraped_at < p_cutoff` and the birth-year/age/unknown-name filters,
     ordered `last_scraped_at DESC, team_id_master`. Same security posture as step 3.
   - **`p_cutoff` is an absolute timestamp, not a relative window.** `_fetch_topup_teams`
     computes `cutoff` once at `drain_queue.py:278` before the loop, which is what makes
     OFFSET paging over `last_scraped_at DESC` coherent. A `now() - p_stale_days` gate inside
     the function would re-evaluate per call, so teams crossing the boundary mid-run would
     insert at the **head** of the descending order and push later rows to higher offsets,
     skipping them.
   - **The body must contain `OFFSET find_topup_teams.p_offset`.** PostgreSQL permits a
     declared-but-unused parameter and CI applies no migrations, so an omitted `OFFSET` clause
     would pass every test while returning the same page forever, hanging the caller's loop.
   - The `ORDER BY` tiebreaker on `team_id_master` is load-bearing for pagination stability,
     not just determinism — `tests/unit/test_drain_queue_topup.py:99-110` documents exactly
     this, because OFFSET paging is in use.

5. **Log scrape attempts and advance `last_scraped_at` in `process_missing_games.py`**
   - **Prerequisite for both the futility counter and the re-probe.** Verified: the script
     writes neither `team_scrape_log` nor `last_scraped_at`.
   - Mirror `scripts/drain_queue.py:113-153` `_bulk_log_team_scrapes`: batch log inserts,
     call `bulk_update_last_scraped_at` for the timestamps, swallow insert errors with a
     warning. **Buffer the run's 40 attempts and flush once**, not 40 extra round-trips on a
     15-minute path.
   - **Status mapping and the timestamp flag, mirroring the drainer exactly** — these two go
     together, per outcome:

     | Outcome | `status` | `update_last_scraped_at` | Drainer anchor |
     |---|---|---|---|
     | games found | `success` | **True** | `:452` |
     | zero games, scrape succeeded | `partial` | **True** | `:452`, default at `:126` |
     | `TeamNotFoundError` | `error` | **True** | `:478` |
     | WAF blocked | `error` | **False** | `:499` |
     | unexpected failure | `error` | **False** | `:515` |

   - **Do not advance the timestamp on WAF or unexpected failures.** Stamping it after a
     scrape that never reached the provider restarts the load-bearing 6-month re-probe clock
     and drops the team out of `find_stale_teams` for 90 days on a probe that did not happen.
     `process_missing_games.process_all` breaks and flushes on `WAFBlockedError`, so this
     fires exactly on the runs where it matters most.
   - The `status='error'` mapping is what keeps transient failures out of `scrape_attempts`
     (step 3 excludes them), so mapping everything to `partial` would let ten WAF blocks
     retire a live team.
   - **Honor `self.dry_run`** (`:101`, `:316`, `:339`) on both writes.
   - **Skip the log row when `team_id_master` is absent.** `process_request` treats it as
     optional (`:465`) but `team_scrape_log.team_id` is
     `NOT NULL REFERENCES teams(team_id_master)` (`20240101000000:206-209`).
   - **Both writes are best-effort**: a bookkeeping failure is logged and swallowed, never
     aborting an otherwise successful scrape.

6. **Add the predicate to the two gating functions**
   - One migration, `CREATE OR REPLACE` at **identical signatures**, for `find_stale_teams`
     (`20260824120000:157-177`) and `find_discovery_teams` (`:113-154`). Preserve each body
     entirely; add only the canonical block, anchor comment included.
   - Keep `find_stale_teams`'s existing lack of `SET search_path`/SECURITY clause.
   - **Do not** add a parameter to either. **Do not touch** `find_recently_active_teams` or
     `find_yesterday_null_score_teams`. `get_teams_to_scrape_limited` is manual-dispatch only
     and out of scope — say so in the header.

7. **Rewire `drain_queue.py`'s top-up to `find_topup_teams`**
   - Replace the PostgREST query at `:285-296` with an RPC call passing the `cutoff` already
     computed at `:278` as `p_cutoff`, the loop's running `offset` as `p_offset`, and
     `_TOPUP_PAGE_SIZE` as `p_row_limit`. Keep the loop, the `seen` set, the empty/short-page
     breaks, and the `_is_scrapeable_team` post-filter at `:305`.
   - `exclude_ids` stays a **client-side** filter, as today; the RPC over-fetches slightly,
     which the post-filter already accounts for.
   - **Do not add the new columns to `_TEAM_KEYS`**, and **do not add a dormancy check to
     `_is_scrapeable_team`.** It is not top-up-only: `:610` runs it over **queue-claimed**
     rows, whose metadata from `_fetch_team_metadata` (`:215-229`) selects only
     `team_id_master, age_group, birth_year, last_scraped_at`. The new columns would be
     absent, `.get()` would return None, and the branch would reject every queued team — and
     a rejected team is dropped from `teams` but stays in `queue_map`, so
     `_finalize_queue_items` (`:355-371`) marks its request `completed` with `games_found=0`,
     silently consuming a revival enqueue without scraping it.

8. **Refresh script `scripts/refresh_team_scrape_activity.py`**
   - Mirror `backfill_team_distinction.py`: argparse `:112-128` (`--dry-run` opt-in, defaults
     LIVE); `rich` for humans, bare `print` for the machine line; **exactly one** stdout line
     matching `(Would update|Updated):\s*\d+`, with a `_self_test()` per `:80-108`; exit
     non-zero on partial failure per `:266-274`.
   - **Build a dedicated client with a 360s timeout**, exactly as
     `calculate_rankings.py:1006-1016`. The default 120s would kill the RPC mid-flight.
   - **No Python fallback** — the equivalent would page ~3M game rows plus 2.5M log rows over
     PostgREST, which is why the work is in Postgres. Fail loudly and let the workflow retry;
     say so in the docstring so the omission reads as deliberate.
   - A direct-Postgres alternative is unavailable: `DATABASE_URL` is set only in CI and direct
     Postgres is firewalled from local sessions.

9. **Tests** (land with steps 1-8, not after)
   - `tests/unit/test_refresh_team_scrape_activity.py`: the `(Would update|Updated): N` stdout
     contract; `--dry-run` passing `p_dry_run: true`; the client built with
     `postgrest_client_timeout=360`. Bare `Mock()` + `.rpc.call_args`, per
     `test_enqueue_active_teams.py:45-55`.
   - `tests/unit/test_process_missing_games_scrape_log.py`: the step-5 writer — the full
     status/timestamp table above, including **`last_scraped_at` advancing on a zero-result
     attempt** and **NOT advancing on a WAF-blocked one** (the two load-bearing cases);
     `dry_run` suppressing both writes; the missing `team_id_master` skip; a swallowed insert
     failure not aborting the request.
   - **`tests/unit/test_scrape_activity_predicate.py` — mandatory.** `ci.yml:20-43` applies no
     migrations, so these text assertions stand in for execution and the step-12 live gate is
     the only behavioral check.
     - One regex **per branch** of the canonical predicate, against each of the three copies.
     - Drift check: locate each block by the `-- canonical-eligibility-v1` anchor and extract
       to its matching parenthesis using a **balanced-parenthesis scanner**, not a
       first-closing-paren regex — the block contains nested parens in the `EXISTS`
       subquery, the `COALESCE` calls and the `INTERVAL` expressions. Normalize trailing
       whitespace only, then assert all three are identical.
     - Strip **only** `/* */` comments. `tests/unit/test_age_rollover_migration_map.py`
       is the model for block-comment stripping, but **adapt it — its second statement
       (`live = "\n".join(line for line in live.splitlines() if not line.lstrip().startswith("--"))`)
       strips `--` lines and would erase the anchor the extraction depends on.**
     - **Name the exact migration files** the test reads; `find_stale_teams` and
       `find_discovery_teams` bodies appear in several historical migrations and a glob would
       match superseded copies.
     - Assert `OFFSET find_topup_teams.p_offset` is present in the `find_topup_teams` body.
     - Assert the refresh migration contains: the teams-driven `LEFT JOIN`, both
       `COALESCE(...)::integer` projections, both `team_merge_map` resolutions, the
       `status <> 'error'` exclusion, the `IS DISTINCT FROM` guard, and the REVOKE/GRANT lines.
     - Assert neither `find_recently_active_teams` nor `find_yesterday_null_score_teams`
       contains `canonical-eligibility-v1`.
   - `tests/unit/test_drain_queue_topup.py`: step 7 replaces the query this file asserts
     against, so rewrite rather than extend. `:81-96`, `:99-110`, `:113-122` and
     `test_query_excludes_birth_years_dynamically:104` no longer describe the code; replace
     with assertions on the `find_topup_teams` RPC name and payload, **including that
     `p_offset` advances between pages and `p_cutoff` does not**. `:224-226`
     (`set(team) == TEAM_KEYS`) stays valid only if the RPC returns exactly those columns.
     Keep `test_postgrest_errors_propagate:229` and `_is_scrapeable_team` `:394-435`.

10. **Ship, push the migrations, and let step 5 soak**
    - Merge with CI green.
    - **Push the migrations to production by hand and repair the ledger.** Nothing in
      `.github/workflows/` runs `supabase db push` (verified across all 42 workflow files);
      CLAUDE.md:463-464 documents the manual procedure.
    - **The push must land before any `clear-queue.yml` run.** Step 7's `drain_queue.py`
      rewrite hard-depends on `find_topup_teams` existing: `_fetch_topup_teams` lets PostgREST
      errors propagate (pinned by `test_postgrest_errors_propagate`), and the caller's
      `except` at `drain_queue.py:671-675` releases claimed rows and re-raises — so code
      without the migration breaks "Help Clear Queue" outright rather than degrading.
    - The predicate is **inert** at this point: with the four columns NULL, branch 4
      (`COALESCE(game_row_count,0)=0 AND COALESCE(scrape_attempts,0)<10`) is TRUE for every
      row and short-circuits the OR.
    - **Wait at least one full week** before step 11, so `scrape_attempts` reflects the
      automatic drainer.

11. **Dry-run the refresh, and capture baselines**
    - `python scripts/refresh_team_scrape_activity.py --dry-run`. Confirm exactly one
      `Would update: N` line and that the four columns are still NULL in the database — per
      CLAUDE.md a dry run is proven against the database, not its own output.
    - Capture baselines **with named arguments**. Positional arguments are a trap:
      `find_recently_active_teams`'s second parameter is `p_active_window_days`, not a row
      limit, and its `p_row_limit` defaults to 2000, so a naive count saturates.
      ```sql
      SELECT COUNT(*) FROM find_stale_teams(p_provider_id => '<gotsport_id>', p_row_limit => 100000);
      SELECT COUNT(*) FROM find_discovery_teams(p_provider_id => '<gotsport_id>', p_row_limit => 100000);
      SELECT COUNT(*) FROM find_recently_active_teams(p_provider_id => '<gotsport_id>', p_row_limit => 100000);
      ```
    - Seed one controlled regression row: a team with an old `last_played_at` plus a game
      dated today.

12. **Live backfill, then check the gate**
    - Run the refresh live once by hand, then re-run the three counts.
    - **Primary gate (static, cannot drift or saturate):** neither `find_recently_active_teams`
      nor `find_yesterday_null_score_teams` contains `canonical-eligibility-v1`, and the
      seeded regression row appears in `find_recently_active_teams`.
    - **Secondary (sanity, tolerant):** the first two counts should drop substantially. The
      third should be broadly stable — but do **not** demand exact equality. The 15-minute
      drainer keeps importing games and, after step 5, updating `last_scraped_at`, both of
      which feed that RPC while the baseline, the up-to-300s refresh and the follow-up count
      run. Investigate only a drop beyond ~5%.
    - **Rollback:**
      `UPDATE teams SET last_played_at = NULL, last_fixture_at = NULL, game_row_count = NULL, scrape_attempts = NULL;`
      This restores inertness because branch 4 coalesces to TRUE for every row and
      short-circuits the OR. It is **not** because "every branch fails open on NULL" — the
      re-probe branch reads `last_scraped_at`, which the rollback does not reset and which may
      well be FALSE. Do not "simplify" the rollback to null fewer columns.
    - Spot-check the cohort figures in Verification before accepting the run.

13. **Enable the schedule**
    - Only now add the `schedule:` block. `.github/workflows/refresh-team-scrape-activity.yml`
      ships in step 8 with **`workflow_dispatch:` only**; the cron `0 12 * * 0` (Sunday 12:00
      UTC, two hours before discovery at 14:00 and four before safety-net at 16:00) is a
      one-line follow-up commit.
    - Mirror `data-hygiene-weekly.yml`: job-level `env:` for the Supabase keys and
      `PYTHONUNBUFFERED`, `set -o pipefail`, `tee` to `logs/refresh_scrape_activity.log`, grep
      the `(Would update|Updated)` count into `$GITHUB_OUTPUT` defaulting with `${VAR:-0}`
      (never `|| echo 0`), log artifact upload, no `continue-on-error`.
    - **No `AGE_ROLLOVER_FREEZE` gate** — this writes no age groups, and Steps 1/1b set the
      precedent of ungated writers.
    - **Add the workflow to CLAUDE.md's GitHub Actions table in the same commit** —
      `tests/unit/test_agent_doc_references.py:367-379` fails on a new `cron:` workflow until
      that table lists it.

## Verification

- `python -m pytest tests/unit/test_refresh_team_scrape_activity.py tests/unit/test_process_missing_games_scrape_log.py tests/unit/test_scrape_activity_predicate.py tests/unit/test_drain_queue_topup.py -v`
- Full CI gate: `python -m ruff check src/ scripts/ config/ tournament_intake.py dashboard.py`
  and `python -m pytest tests/ --ignore=tests/test_enhanced_pipeline.py`.
- **Enqueue volume is expected to stay at 500 and 1000 per Sunday. Unchanged volume is
  success, not failure** — every gated site is a fixed-N selector (see Context). The metric
  that should move is the share of scrapes returning games: compare
  `team_scrape_log.games_found > 0` as a fraction of rows, for the 30 days before the cron is
  enabled versus the 30 days after. **Baseline measured 2026-08-27: 35,095 of 140,275 scrapes
  in the trailing 30 days returned games — 25.0%.** That is the number to beat, and it is the
  single headline result for this change. Note the baseline covers only the logged bulk and
  manual paths; once step 5 ships, the automatic drainer starts logging too, so the
  denominator grows. Compare like with like by restricting both windows to the same
  `provider_id` set, or re-baseline after step 5 has soaked.
- After the live backfill, spot-check against the figures this plan was sized on (all measured
  **without** an `is_excluded` filter, using this plan's own final definitions):
  - `last_played_at < CURRENT_DATE - 365` — the **dormancy** cohort: expect ~35,457.
  - Of the dormancy cohort, protected by the 30-day `ranking_history` exemption: ~5,445.
  - Of the dormancy cohort, `last_fixture_at >= CURRENT_DATE`: expect **~461**, all of which
    must remain scrapable. Do not use the figure 182 from earlier drafts — it was measured
    against a third population and belongs to neither cohort.
  - `game_row_count = 0 AND scrape_attempts >= 10` — the **futility** cohort: expect
    **~11,640**. Earlier drafts carried 12,927 (loose `last_played_at IS NULL`), 12,732 (raw
    `team_id` log grouping) and 11,983 (`NOT EXISTS` against `games`); all three used
    definitions this plan does not. 11,640 is what merge-resolved `game_row_count` plus
    merge-resolved non-error `scrape_attempts` produces.
  - Of the futility cohort, `last_fixture_at >= CURRENT_DATE`: expect **0** — verified, and
    true by construction, since a zero-game team has no game rows. A non-zero count means the
    games aggregate is wrong. (Deliberate contrast with the ~461 above; do not transpose them.)
  - Excluding `status = 'error'` changes the cohort by nothing today — it is a guard that
    costs nothing now and prevents transient WAF blocks from retiring a live team later.
- Revival-path regression: a team whose `last_played_at` is older than the cutoff still
  appears in `find_recently_active_teams` the moment a game row dated within 3 days exists.
- **Re-probe regression (load-bearing):** after step 5 ships, one probe of a team that returns
  zero games must leave `teams.last_scraped_at` **advanced**; a WAF-blocked probe must leave
  it **unchanged**. Without the first the 6-month clock never restarts; without the second a
  scrape that never reached the provider buys six months of silence.
- Re-probe eligibility: a team with `last_scraped_at` older than 6 months appears in
  `find_stale_teams` despite failing every other branch. **Expect this to be nearly inert on
  day one** — only 2,415 non-deprecated teams have `last_scraped_at` older than 6 months, and
  3 are in the futility cohort. Construct the case by backdating `last_scraped_at` on a
  scratch row rather than hunting for a natural one.
- The `last_scraped_at IS NULL` half of the re-probe branch admits all 23,302 never-scraped
  teams unconditionally. Deliberate fail-open; the filter is not expected to reduce work there.

## Context Files

- `scripts/backfill_team_distinction.py` — the script skeleton and its greppable-summary invariant.
- `scripts/drain_queue.py` (`:96-110`, `:113-153`, `:215-229`, `:245-316`, `:355-371`, `:452`, `:478`, `:499`, `:515`, `:610`, `:671-675`) — `_bulk_log_team_scrapes` models step 5 including the per-outcome timestamp flag; the top-up rewrite is step 7; the dual `_is_scrapeable_team` call site is why it must not be extended.
- `scripts/process_missing_games.py` — the hot path step 5 changes.
- `scripts/calculate_rankings.py` (`:1006-1016`, `:540-547`) — the 360s client precedent, and the `rankings_full` pruning behind the `ranking_history` exemption.
- `supabase/migrations/20260824120000_scrape_eligibility_uses_season_year.sql` — current bodies of the eligibility functions.
- `supabase/migrations/20260325100000_batch_backfill_game_stats.sql` — the batched, no-payload refresh shape.
- `supabase/migrations/20260615200000_homepage_stats_cache.sql` (`:32-64`) — the security posture for both new RPCs.
- `supabase/migrations/20260502043821_add_teams_distinction.sql` — column-add conventions.
- `src/models/game_matcher.py` (`:596-613`, `:636-649`, `:696-701`) — why dormancy is mostly self-healing.
- `tests/unit/test_drain_queue_topup.py` — the tests step 7 invalidates and step 9 rewrites.
- `.github/workflows/data-hygiene-weekly.yml` (`:161-183`) — step conventions for the new workflow.
- `.turbo/reports/2026-08-27-inactive-teams-since-2024.md` — the measurements this plan is sized against.
