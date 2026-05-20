# Schedule-Driven Scraping

**Date:** 2026-05-19
**Status:** Draft (pending implementation)
**Slug:** `schedule-driven-scraping`

## Scope

GotSport teams only. PlayMetrics is explicitly out of scope.

## Problem

Every weekly scrape pulls each GotSport team's full schedule (past + future games), but `enhanced_pipeline.py` discards every row with a missing score. Future-dated games — which are *scheduled* and therefore necessarily scoreless — get caught in this filter and never reach the database.

Consequences:

- The weekly chain brute-forces ~150K team-scrapes/week (6 links × 25K) regardless of whether teams have games to fetch. Most calls return nothing useful.
- We have no record of upcoming fixtures, so we can't target scrapes at the day-after-game window where scores are most likely to be available.
- The Sunday-night concentrated burst triggers GotSport WAF limits.

We currently use `teams.last_scraped_at` as the only signal for what to scrape next, and it's not tied to whether the team actually has games.

## Goal

Persist future-dated games as NULL-score rows in `games`. Use them as triggers for an automated workflow that enqueues per-team scrape requests into the existing `scrape_requests` queue. The existing `process_missing_games` workflow drains that queue at a fixed rate (200 teams every 15 minutes, ~19,200/day), staying well below GotSport WAF limits regardless of how many games happen on any given day.

The existing `scrape-games.yml` workflow is repurposed: scheduled cron removed, manual dispatch retained for ZenRows-powered bulk operations (bootstrap, large one-offs, queue-recovery).

## Non-goals

- No new tables for scheduled games. NULL scores in `games` are the representation.
- No retry-window logic. NULL-score rows persist; the team's next scheduled game re-triggers a scrape, and the 90-day safety net catches everything else.
- No ranking-engine changes. Consumers that already filter scoreless rows are left alone; consumers that don't get audited and patched.
- No UI feature work for showing scheduled games.

## Architecture

### Storage model

Future games live in the existing `games` table:

- `home_score = NULL`, `away_score = NULL`, `result = NULL`
- `game_date > CURRENT_DATE` at insert time
- `is_immutable = false` (must be UPDATE-able when scores arrive)
- `scraped_at` set as usual

When a score is later scraped, the row UPDATES via the existing `game_uid`-based dedup. `game_uid` is symmetric on `(team_a, team_b, game_date)` and score-independent (confirmed by inline comment at `src/etl/enhanced_pipeline.py:396`).

`games.scraped_at` is the row-level freshness marker. No new `updated_at` column needed.

### Pipeline change

Two filter sites in `src/etl/enhanced_pipeline.py` drop scoreless rows. Both need a future-date carveout:

**Site 1: `_validate_and_dedup` (pre-dedup), line 1063-1072.** Current behavior: increments `skipped_empty_scores` and continues. Change: if both scores empty AND `game_date > today`, fall through. Past-dated scoreless rows still skip.

**Site 2: `_has_valid_scores` filter (post-match), line 885-909.** Current behavior: `_has_valid_scores(g)` rejects scoreless. Change: wrap call site in a new `_should_accept_for_insert(g)` helper that allows scoreless rows when `game_date > today`. `_has_valid_scores` itself unchanged.

A new private helper `_is_future_game(game)` (near `_is_empty_score` at line 1038) encapsulates the date check.

### Queue model

ONE queue (`scrape_requests`), ONE drain workflow (`process-missing-games`), MANY thin enqueue sources.

**Schema change on `scrape_requests`:**

```sql
ALTER TABLE scrape_requests
  ADD COLUMN IF NOT EXISTS priority smallint NOT NULL DEFAULT 5;

CREATE UNIQUE INDEX IF NOT EXISTS idx_scrape_requests_pending_team
  ON scrape_requests (team_id_master)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_scrape_requests_priority_pending
  ON scrape_requests (priority ASC, requested_at ASC)
  WHERE status = 'pending';
```

Priority convention (lower number = higher priority):

| Priority | Source | Why |
|---|---|---|
| 1 | User-clicked "process missing games" | A real person is waiting |
| 2 | Daily yesterday-game enqueue | Stale score collection; older `requested_at` drains first within priority |
| 3 | Weekly discovery enqueue | Find newly-published schedules |
| 4 | Weekly safety-net enqueue | 90-day stale catch-all |
| 5 | Default | Fallback |

**Enqueue semantics: UPSERT with priority promotion.**

```sql
INSERT INTO scrape_requests (team_id_master, priority, request_type, status, requested_at)
VALUES (...)
ON CONFLICT (team_id_master) WHERE status = 'pending'
DO UPDATE SET
  priority = LEAST(scrape_requests.priority, EXCLUDED.priority);
```

This keeps one pending request per team. If a higher-priority enqueue arrives later, it bumps the priority (toward 1) without resetting `requested_at` — so a request that's been waiting maintains its FIFO position within its new priority tier.

### Enqueue sources

All are tiny cron scripts (~30-50 lines) that run a SELECT and INSERT into `scrape_requests`. None of them scrape anything.

**Daily yesterday-game enqueue** (`scripts/enqueue_yesterday_games.py`, daily cron):

```sql
SELECT DISTINCT t.team_id_master
FROM teams t
JOIN games g ON (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
WHERE t.is_deprecated = false
  AND t.provider_id = '<gotsport_provider_id>'
  AND g.game_date = CURRENT_DATE - 1
  AND g.home_score IS NULL
```

Enqueues at priority 2. Volume: ~5-22K/day depending on what played the day before.

**Weekly discovery enqueue** (`scripts/enqueue_discovery_teams.py`, weekly cron):

```sql
SELECT t.team_id_master
FROM teams t
WHERE t.is_deprecated = false
  AND t.provider_id = '<gotsport_provider_id>'
  AND NOT EXISTS (
    SELECT 1 FROM games g
    WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
      AND g.game_date > CURRENT_DATE
  )
ORDER BY t.last_scraped_at ASC NULLS FIRST
LIMIT 1000;
```

Enqueues 1,000 teams at priority 3. Slowly chips through teams with no visible future games — about 1,000/week sustained, ~50K teams covered per year.

**Weekly safety-net enqueue** (`scripts/enqueue_safety_net.py`, weekly cron):

```sql
SELECT t.team_id_master
FROM teams t
WHERE t.is_deprecated = false
  AND t.provider_id = '<gotsport_provider_id>'
  AND (t.last_scraped_at IS NULL OR t.last_scraped_at < NOW() - INTERVAL '90 days')
LIMIT 500;
```

Enqueues at priority 4. Backstop for stragglers.

**New-team hook** (existing — verify, fix gaps): when `teams` gets a row inserted, an INSERT into `scrape_requests` should fire. Audit and patch if missing.

**User-clicked "process missing games":** existing flow, unchanged — UI inserts into `scrape_requests`. New: set priority=1 explicitly so user requests jump the queue.

### Drain processor

`scripts/process_missing_games.py` and `.github/workflows/process-missing-games.yml`:

- **Frequency:** every 15 minutes (currently hourly).
- **Per-run cap:** 200 teams max.
- **Ordering:** `ORDER BY priority ASC, requested_at ASC`.
- **Capacity:** 200 × 4/hr × 24hr = **19,200 teams/day**.
- **Method:** direct GotSport scrapes (no ZenRows), same as current `process_missing_games`.

**Peak-load math (worst case, tournament weekend):**

- Saturday: ~22K teams play.
- Sunday morning enqueue: 22K rows into queue at priority 2.
- Drain rate: 19,200/day.
- Sunday's leftovers drain by Monday evening; Monday's enqueue (Sunday games) drains by Tuesday evening. Queue clears mid-week.
- WAF risk: 200 req/15 min ≈ 0.22 req/sec sustained. Well below burst limits.

### Repurposed `scrape-games.yml`

The existing weekly chain workflow is **kept but neutered for automation**:

- **Remove:** `schedule:` block (no more Sunday-night auto-trigger).
- **Keep:** all `workflow_dispatch` inputs (limit_teams, null_teams_only, since_date, concurrency, batch_size, delay_min, delay_max, chain_remaining).
- **Keep:** ZenRows integration.
- **Use case:** manual operator tool for:
  - Bootstrap (one-shot scrape of all teams to seed future schedules)
  - Bulk one-offs (new state, large tournament results, recovery from queue backlog)
  - Anything where direct scrapes via the queue would be too slow

### Bootstrap (one-time)

After the Phase 1 pipeline patch deploys:

1. Manually dispatch `scrape-games.yml` with `null_teams_only=true` and a generous limit (or run the chain as today).
2. Monitor sanity-check stats: % teams returning future games, % rows future-dated.
3. Bootstrap is idempotent — `game_uid` dedup means re-runs are safe.

No new bootstrap script. The repurposed `scrape-games.yml` IS the bootstrap mechanism.

## Consumer audit

Same risks as before; verify each consumer tolerates NULL-score rows:

| Consumer | Expected behavior | Risk |
|---|---|---|
| Ranking engine (Glicko-2 input) | Must filter `home_score IS NULL OR away_score IS NULL` | High |
| `rankings_view` / `rankings_full` | Should filter via score predicate | Medium |
| `frontend/lib/api.ts` game history | NULL rows render as blank/scheduled | Low (cosmetic) |
| `GameHistoryTable` (premium-gated) | NULL rows don't crash | Low |
| Existing dedup logic | UPDATE-on-uid-collision must not skip scheduled rows | High |
| `is_immutable` enforcement | Scheduled rows must be `false` | High |
| `result` column derivation | NULL for NULL scores | Medium |
| Analytics / exports | `count(*) from games` may need a score filter | Low |

Each row is a verification task in the plan.

## Rollout

Phases ship sequentially, each as its own PR:

1. **Pipeline patch** — `enhanced_pipeline.py` filter sites + tests + consumer audit + ranking guard.
2. **Bootstrap** — manual dispatch of `scrape-games.yml`. No code change; operational only.
3. **Queue infrastructure** — `scrape_requests` schema migration (priority column, unique index), `process_missing_games` bumps (15-min cron, 200 cap, priority ordering). User-click handler updated to set priority=1.
4. **Daily yesterday enqueue** — new script + workflow.
5. **Discovery enqueue** — new script + weekly workflow.
6. **Safety-net enqueue** — new script + weekly workflow.
7. **Deprecate `scrape-games.yml` automation** — remove `schedule:` block, leave `workflow_dispatch` for manual use.
8. **New-team hook** — audit + patch if gap.

Phase 2 (bootstrap) depends on Phase 1 deploy. Phases 4-6 depend on Phase 3 (priority column exists). Phase 7 depends on Phases 4-6 stabilizing.

## Open questions

1. **Daily enqueue script timezone.** Run at 12:00 UTC so East Coast Sunday-night games have had time to post scores. Confirm at implementation.
2. **`games.result` derivation.** Generated column? Trigger? Pipeline-set? Verify NULL handling.
3. **New-team hook audit.** Does `teams` INSERT already trigger a `scrape_requests` INSERT anywhere? Likely yes via frontend or import path — verify.
4. **Priority column on existing rows.** Backfill existing pending requests to priority=5? Or treat the new column as opt-in via DEFAULT?
5. **Discovery cadence empirical check.** 1,000/week may be too slow or too fast. Tune after one cycle.

## Risks

- **Silent NULL leak into rankings.** Mitigation: hard assertion at ranking input entrypoint.
- **`game_uid` symmetry assumption.** Mitigation: integration test in Phase 1 that proves scheduled-then-played dedups to one row.
- **Unique-on-pending index conflicts with existing data.** Mitigation: pre-flight check for duplicate pending rows; resolve before applying the index.
- **Process-missing-games at 15min cadence hits GitHub Actions concurrency limits.** Mitigation: workflow `concurrency:` block to ensure overlap doesn't stack.
- **Bootstrap reveals low future-game density.** Not catastrophic; means daily enqueue is small and discovery does more work. Visible immediately from Phase 2 sanity-check logs.

## Out of scope (follow-ups)

- UI for "scheduled" games in team history.
- Push notifications when a scheduled game posts a result.
- Adaptive priority cap (e.g., bump per-run cap to 400 when queue depth > 5K).
- Sharded enqueue scripts (currently all run as single processes).
- PlayMetrics extension of this model.
