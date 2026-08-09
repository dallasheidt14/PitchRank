# Clear Queue — top up short batches from the teams table

**Date:** 2026-08-09
**Status:** Draft for implementation planning
**Affects:** `.github/workflows/clear-queue.yml` ("Help Clear Queue"), `scripts/drain_queue.py`

## Purpose

Today, dispatching "Help Clear Queue" with `queue_limit = 4000` scrapes 4000 teams only if
`scrape_requests` happens to hold 4000 pending rows. When the queue is empty the run prints
"Queue is empty — nothing to drain" and exits having done nothing; when the queue is short it
scrapes only what was there.

The operator's intent when typing a number is "scrape this many teams." Make `--limit` mean
exactly that: queue work first, then fill the remainder from the teams table.

## Scope

- **In scope:** GotSport only (`drain_queue.py` is hardcoded to `provider = "gotsport"`).
- **In scope:** Raising the ZenRows concurrency default so large batches fit the job timeout.
- **Out of scope:** The direct-mode (`use_zenrows=false`) concurrency default of 30, which is
  3x the per-IP WAF limit documented in `scrape-games.yml:306-320`. Real bug, unrelated
  feature, separate fix.
- **Out of scope:** Parallel-safety of the top-up (see Non-goals).
- **Out of scope:** The absent stale-claim reaper — rows stranded in `processing` by a killed
  run are never reclaimed. Pre-existing; one such row has been stuck since 2026-06-22.

## Behavior

`--limit N` changes meaning from "claim N queue items" to "scrape N teams".

```
claim up to N from scrape_requests          (unchanged — claim_queue_items, SKIP LOCKED)
  |
filter junk: placeholder unknown_*, U8/U9,  (unchanged — drain_queue.py:462-492)
             birth_year in {2005,2006,2017,2018,2019}
  |
shortfall = N - len(surviving teams)
  |
if shortfall > 0:
    get_teams_to_scrape_limited(provider, shortfall + len(batch))
    drop any team_id_master already in the batch
    append up to `shortfall`
  |
scrape / auto-import / finalize             (unchanged)
```

### Which teams the top-up picks

`get_teams_to_scrape_limited` (`supabase/migrations/20260422010000_*.sql`) already applies every
filter this path needs, in SQL:

- `provider_id` match
- excludes `age_group` in U8/U-8/U9/U-9
- excludes `birth_year` in `{yr-21, yr-20, yr-9, yr-8, yr-7}` (dynamic per current year)
- excludes placeholder `unknown_<provider_team_id>` teams
- with `p_include_recent = false`, excludes anything scraped in the last 7 days
- orders `last_scraped_at ASC NULLS FIRST` — never-scraped teams first, then longest-stale

It returns `SETOF public.teams`, which carries every field `drain_queue.py` puts in its team
dicts (`team_id_master`, `team_name`, `provider_id`, `provider_team_id`, `age_group`,
`birth_year`, `last_scraped_at`). Verified against production 2026-08-09.

### Two intended consequences

**Consecutive runs walk the backlog.** Scraped teams get a fresh `last_scraped_at` via the
existing `_bulk_log_team_scrapes` call, so the next run's 7-day filter skips them and selects
the next tranche. As of 2026-08-09 there are 130,369 stale and 924 never-scraped GotSport
teams, so the top-up will not run dry.

**The junk-filter waste disappears.** Historically a 500-item run scraped 104 teams (run
30944721235, 2026-08-04: 345 placeholder + 51 out-of-range filtered). Under this design that
run still claims 500 queue rows but tops up to 500 real scrapes.

### Empty-queue case

`Queue is empty — nothing to drain` and its early `return` are removed. With `N` set the run
always scrapes `N`, or everything eligible if fewer than `N` teams remain — a short batch, not
an error.

## Non-goals

**The top-up is not parallel-safe, by decision.** Queue claims use `FOR UPDATE SKIP LOCKED`, so
concurrent dispatches get disjoint batches. The teams table has no equivalent claim, so two
simultaneous runs would both select the same oldest-scraped teams and scrape them twice.
`get_teams_to_scrape_limited` supports hash sharding via `p_shard_index` / `p_shard_count`, but
exposing those as workflow inputs adds two boxes an operator must get right every dispatch, and
getting them wrong causes silent overlap or silent gaps. Chosen mitigation: document it in the
`queue_limit` input description. Run one at a time when the queue is short.

## Batch size and the job timeout

Measured from run 27104427792 (2026-06-07, `--limit 5400 --concurrency 10`, ZenRows):

| Phase | Window | Duration |
|---|---|---|
| Scrape 4984 teams | 20:52:39 → 21:37:45 | 45m06s (**1.84 teams/sec**) |
| Auto-import 12,175 games | 21:37:45 → 21:46:23 | 8m38s |
| Finalize 5396 queue rows | 21:46:23 → 21:52:27 | 6m04s |

At that rate, against the 180-minute `timeout-minutes`:

| Limit | Scrape @ conc. 8-10 | Total | Fits? |
|---|---|---|---|
| 5,000 | ~45 min | ~60 min | yes |
| 10,000 | ~91 min | ~115 min | yes |
| 20,000 | ~181 min | ~230 min | **no** |

A run killed at 180 minutes never reaches auto-import, so every game scraped that run is lost
to Supabase. The JSONL artifact still uploads (`if: always()`), so it is recoverable by hand.

**Resolution:** raise the ZenRows concurrency default from 8 to 20, putting 20,000 at roughly
75 minutes of scraping. One run at 20 uses 40% of the ZenRows Startup-tier 50-slot parallel
ceiling — the 8 default exists because `scrape-games.yml` runs 5 shards through one API key
(5 x 8 = 40), a constraint this single-runner workflow does not have.

## Implementation

### `scripts/drain_queue.py`

One new helper:

```python
def _fetch_topup_teams(supabase, provider_id, shortfall, exclude_ids) -> List[Dict]:
    """Pull oldest-scraped eligible teams to fill out a short queue batch."""
```

- Returns `[]` immediately when `shortfall <= 0`.
- Calls `get_teams_to_scrape_limited` through `call_rpc_with_fallback`
  (`src/etl/bulk_ops.py:32`, already imported in this module for
  `bulk_update_last_scraped_at`) with `p_include_recent=False`, `p_null_only=False`,
  `p_shard_index=0`, `p_shard_count=1`.
- Passes `p_limit = shortfall + len(exclude_ids)`. The padding covers the exact worst case:
  every claimed queue team is also top-up-eligible and could appear in the RPC result.
- Drops rows whose `team_id_master` is in `exclude_ids`, then truncates to `shortfall`.
- On SQLSTATE 42883 the fallback logs and returns `[]`, so a rolling deploy where the migration
  has not landed degrades to today's queue-only behavior instead of crashing a drain.

**Call site:** immediately after `teams = filtered_teams` (`drain_queue.py:488`) and its two
filter-count prints, before the `Scraping games for N teams` banner. Appended teams flow through
the rest of the function untouched:

- `queue_map` has no entry for them, so `_finalize_queue_items` ignores them — correct, they
  have no `scrape_requests` row.
- `_bulk_log_team_scrapes` writes their `team_scrape_log` entry and `last_scraped_at`, which is
  what makes consecutive runs advance.
- They are already SQL-filtered, so they bypass the Python filter loop without needing to.

**Console output** distinguishes the two sources, e.g.
`Topping up with 3,896 teams from the teams table (oldest-scraped first)`.

**Dry-run** currently early-returns at `drain_queue.py:438-458`, before the filter loop — so as
written it would never see the top-up. Move that block to sit *after* the top-up call site so it
previews what would actually be scraped. It prints both sources separately and still releases
only the claimed queue rows back to `pending`; top-up teams have no rows to release.

This makes the dry-run path do real work it previously skipped (the filter loop and one RPC
call). Both are read-only against Supabase, so the guarantee that `--dry-run` writes nothing
except the release-back-to-`pending` update is preserved.

### `.github/workflows/clear-queue.yml`

No new inputs. Two edits:

1. ZenRows concurrency default `8` → `20`, with a comment recording the arithmetic above
   (measured rate, the 180-min cap, and why this workflow is not bound by the 5-shard
   constraint that justifies 8 in `scrape-games.yml`).
2. `queue_limit` description rewritten: it is now a total scrape target, not a claim count, and
   the top-up portion is not safe to run from concurrent dispatches.

## Testing

New `tests/unit/test_drain_queue_topup.py`, mirroring the existing enqueue-script tests
(`tests/unit/test_enqueue_discovery_teams.py`, `test_enqueue_safety_net.py`) with a stubbed
Supabase client. Cases:

1. `shortfall <= 0` — RPC is never called.
2. Shortfall math — 920 claimed, 300 survive filtering, limit 4000 → shortfall is 4000-300 = 3700.
3. Over-fetch — that same case passes `p_limit = 3700 + 300 = 4000` to the RPC.
4. Overlap dedup — a team present in both the queue batch and the RPC result appears once, and
   the result is truncated to exactly `shortfall`.
5. Short supply — RPC returns fewer rows than `shortfall`; the run proceeds with a smaller batch
   and does not raise.
6. RPC missing (42883) — returns `[]`, run continues queue-only.
7. Top-up teams are absent from `queue_map`, so `_finalize_queue_items` does not try to complete
   a nonexistent `scrape_requests` row.
8. Dry-run — top-up teams are listed in the preview, and only the claimed queue rows are
   released back to `pending`.

No network in tests; the GotSport scraper and the auto-import subprocess are stubbed.

## Verification

`ruff check` on the changed Python, then `python -m pytest tests/unit/test_drain_queue_topup.py`.
Manual confirmation via `python scripts/drain_queue.py --dry-run --limit 50` against production,
which claims, prints both sources, and releases the claimed rows back to `pending`.
