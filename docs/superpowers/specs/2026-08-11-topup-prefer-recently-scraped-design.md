# Top-up: prefer recently-scraped teams over the stalest ones

**Date:** 2026-08-11
**Status:** Draft for implementation planning
**Affects:** `supabase/migrations/` (new migration), `scripts/drain_queue.py`

## Purpose

The "Help Clear Queue" top-up fills a short batch from the `teams` table using
`get_teams_to_scrape_limited`, which orders `last_scraped_at ASC NULLS FIRST`.
That picks the teams we have neglected longest, which turn out to be the teams
that are no longer playing.

Measured 2026-08-11 against production: of the 2,000 teams the top-up would
select right now, **5.6% have played a game in the last 90 days**. The 9,999-team
run on 2026-08-10 (run 31438229008) returned 11,288 games, or **1.1 games per
team**. The 2,000-team run the same evening (run 31427617530) returned 14,304
games, **7.2 per team**.

Sorting the same column the other way selects teams that are still playing.

## The measurement this rests on

Activity rate by how long ago a team was last scraped. Samples of 600 teams per
band, "active" meaning at least one game in the last 90 days, taken 2026-08-11:

| Last scraped | Active | Eligible pool |
|---|---|---|
| 0-7 days ago | 94.8% | (excluded by any gate) |
| 14-30 days ago | 79.7% | 3,787 |
| 30-60 days ago | 93.2% | ~12,700 |
| 60-75 days ago | 85.8% | large |
| 75-90 days ago | 6.2% | large |
| 90+ days ago | 0.0% | 721 |

The cliff sits between 75 and 90 days. Descending order does not need to know
where it is: it walks from the freshest eligible team backwards and exhausts the
high-yield bands before reaching the dead ones.

**Why the correlation is this strong.** Actively-playing teams are continuously
re-enqueued by the automated pipeline (`enqueue_yesterday_games` daily at
priority 2, `enqueue_active_teams` daily at priority 2), so they always carry a
recent `last_scraped_at`. A team sinks to the bottom of the ascending sort
precisely because nothing in the pipeline has had a reason to touch it. Ascending
order is therefore not merely uncorrelated with activity, it is
anti-correlated.

## Behavior

Two new parameters on `get_teams_to_scrape_limited`, both defaulting to today's
behavior:

- `p_stale_days int default 7` — replaces the hardcoded `interval '7 days'`
- `p_oldest_first boolean default true` — when false, order
  `last_scraped_at DESC`

`drain_queue.py`'s `_fetch_topup_teams` passes `p_stale_days => 14` and
`p_oldest_first => false`. Every other caller is unchanged and unaffected.

Expected effect on a 10,000-team run: draws from the 14-30d and 30-60d bands, so
roughly 90% of picks are active, against 5.6% today.

### NULL last_scraped_at

`NULLS FIRST` in the ascending order exists to prioritize never-scraped teams.
Under descending order they must sort **last** (`DESC NULLS LAST`), not first:
a never-scraped team carries no evidence of activity, and putting the unknown
bucket ahead of the 93%-active bucket would defeat the change. As of 2026-08-11
`get_scrape_eligibility_counts` reports `never_count = 0`, so this affects
nothing today, but the ordering must be explicit rather than left to the
Postgres default.

## Scope

- **In scope:** the two RPC parameters and the single call site in
  `_fetch_topup_teams`.
- **Out of scope:** `scripts/enqueue_active_teams.py` and its daily workflow.
  It is part of the automated, hands-off pipeline; "Help Clear Queue" is a
  manual tool. Improving the manual tool must not perturb the automation.
- **Out of scope:** `scripts/scrape_games.py`. It keeps calling the RPC without
  the new parameters and gets byte-identical behavior from the defaults.
- **Out of scope:** the stale docstring in four `enqueue_*.py` scripts claiming
  `process_missing_games` drains "200/run" when
  `.github/workflows/process-missing-games.yml:42` runs `--limit 40`. Real and
  worth fixing, unrelated to this change.

## The trade-off

Teams last scraped 75+ days ago will never be selected by the top-up, where
today they are selected first. That is the intent, since they yield nothing, but
it means the top-up stops performing discovery.

That is acceptable because discovery is not the top-up's job.
`scripts/enqueue_discovery_teams.py` runs weekly (`enqueue-discovery.yml`,
`cron: '0 14 * * 0'`), selects teams with no future games on record — exactly
the dormant set — and enqueues them at priority 3. The drain claims queue rows
before it ever calls the top-up, so dormant teams still get scraped; they arrive
through the automated path instead of the manual one.

## Alternative considered and rejected

Joining `games` to order by "has a game in the last 90 days" first, mirroring
the CTE in `find_discovery_teams`. It targets the same teams but requires a new
aggregation over a games table that made the naive form of that very query time
out at 137K teams (`20260520054454_find_discovery_teams.sql`, and `teams` now
holds 152,918 rows). `last_scraped_at` already delivers 80-93% activity on its
own, and the RPC that reads it returns 10,000 rows in 0.45s today. The join buys
nothing the sort direction does not already provide.

## Implementation

### Migration

New migration adding the two parameters via `CREATE OR REPLACE FUNCTION`.
Because Postgres treats a changed parameter list as a new signature, the
migration must `DROP FUNCTION` the existing 6-argument version explicitly, then
create the 8-argument one, and re-issue the `GRANT` (grants do not survive a
drop). The existing body is otherwise preserved verbatim, including the
Euclidean-modulo shard filter from
`20260422010000_fix_get_teams_to_scrape_limited_signed_modulo.sql`.

Ordering clause becomes:

```sql
order by
  case when p_oldest_first then t.last_scraped_at end asc nulls first,
  case when not p_oldest_first then t.last_scraped_at end desc nulls last
```

Whichever branch is inactive evaluates to NULL for every row and contributes no
ordering, leaving the active branch to decide. Ordering on a `CASE` expression
cannot use an index, but no index on `teams.last_scraped_at` appears anywhere in
`supabase/migrations/`, so the current ascending order is already an unindexed
sort — and it returns 10,000 rows in 0.45s and 2,000 in 0.29s (measured against
production 2026-08-11). The expression therefore costs nothing relative to
today. If an index is added later, this clause would need revisiting.

Staleness clause becomes:

```sql
and (p_include_recent
     or t.last_scraped_at is null
     or t.last_scraped_at < now() - (p_stale_days || ' days')::interval)
```

### `scripts/drain_queue.py`

`_fetch_topup_teams` adds the two keys to its RPC params dict. Its docstring
currently states the RPC skips teams "scraped in the last 7 days" and returns
them oldest-first; both claims change and must be corrected in the same edit.

The `call_rpc_with_fallback` fallback currently returns `[]` on SQLSTATE 42883.
That still applies, and now also covers the window where the migration has not
yet been applied and the 8-argument signature does not exist: the top-up
degrades to queue-only rather than crashing a drain.

## Testing

Extend `tests/unit/test_drain_queue_topup.py`:

1. `_fetch_topup_teams` passes `p_stale_days=14` and `p_oldest_first=False`.
2. The existing parameter assertions still hold for the other six arguments.
3. Signature-missing (42883) still degrades to `[]`.

The ordering itself is SQL behavior and is verified against production rather
than in a unit test, since the stub returns whatever rows the test supplies.

## Verification

`ruff check`, then `python -m pytest tests/unit/test_drain_queue_topup.py`.

Apply the migration, then confirm the ordering flipped by calling the RPC
directly with `p_oldest_first => false, p_stale_days => 14` and checking that
the returned teams' `last_scraped_at` values are descending and start roughly 14
days back. Then sample the returned set for games in the last 90 days: expect
roughly 80-93% active, against the 5.6% baseline measured on the current
ascending order.

Finally `python scripts/drain_queue.py --dry-run --limit 200` to confirm the
call site works end to end and releases its claimed rows.
