# Top-up: prefer recently-scraped teams over the stalest ones

**Date:** 2026-08-11
**Status:** Draft for implementation planning
**Affects:** `scripts/drain_queue.py` only. No migration, no database function, no
change visible to any other caller.

## Purpose

The "Help Clear Queue" top-up fills a short batch from the `teams` table, and it
picks the teams we have neglected longest. Those turn out to be the teams that
stopped playing.

Measured against production 2026-08-11: of the 2,000 teams the top-up would pick
right now, **5.6% have played a game in the last 90 days**. Run 31438229008
(9,999 teams, 2026-08-10) returned 11,288 games, **1.1 per team**. Run
31427617530 the same evening (2,000 teams, queue-fed) returned 14,304 games,
**7.2 per team**.

Selecting on the same column in the opposite direction picks teams that are
still playing. A live query with the proposed ordering returned **99.2% active**.

## Why last-scraped predicts activity

Activity rate by how long ago a team was last scraped. 600-team samples per band,
"active" meaning at least one game in the last 90 days, measured 2026-08-11:

| Last scraped | Active |
|---|---|
| 0-7 days ago | 94.8% |
| 14-30 days ago | 79.7% |
| 30-60 days ago | 93.2% |
| 60-75 days ago | 85.8% |
| 75-90 days ago | 6.2% |
| 90+ days ago | 0.0% |

Actively-playing teams are continuously re-enqueued by the automated pipeline
(`enqueue_yesterday_games` and `enqueue_active_teams`, both daily, both priority
2), so they always carry a recent `last_scraped_at`. A team sinks to the bottom
of an ascending sort precisely because nothing in the pipeline has had reason to
touch it. Ascending order is not merely uncorrelated with activity — it is
anti-correlated.

Descending order does not need to know where the cliff sits. It walks from the
freshest eligible team backwards and exhausts the high-yield bands first.

## Approach

Replace the `get_teams_to_scrape_limited` RPC call inside `_fetch_topup_teams`
with a direct PostgREST query against `teams`.

This is the whole reason there is no migration. The RPC is shared with
`scripts/scrape_games.py`; changing its ordering or its parameter list would
require dropping and recreating a function two scripts depend on, re-granting
permissions, and risking a "function is not unique" overload error at runtime.
The top-up does not need that function. It needs an ordinary query, and an
ordinary query cannot affect anything else.

### The query

```
teams
  where provider_id = <gotsport>
    and last_scraped_at < now() - 14 days
    and (birth_year is null or birth_year not in (yr-21, yr-20, yr-9, yr-8, yr-7))
  order by last_scraped_at desc
```

Verified live: 2,000 rows in 0.55s, ordering confirmed descending, 99.2% of the
result active within 90 days.

The birth-year exclusions are computed in Python from the current year, matching
the dynamic `extract(year from now())` list the SQL functions use, so they roll
over annually without edits.

### Filtering and the fetch loop

Two eligibility rules cannot be expressed in a PostgREST filter:

- placeholder teams, where `team_name = 'unknown_' || provider_team_id` (a
  column-to-column comparison)
- `age_group` in U8/U-8/U9/U-9, which the SQL functions compare via
  `upper(trim(...))` while the stored values are lowercase

`drain_queue.py` already applies both, in Python, to every queue team. Top-up
teams currently skip that filter because the RPC pre-filtered them in SQL.

**Measured drop rate: 39.5%** (of 3,000 fetched rows, 988 placeholder and 198
U8/U9). A fixed over-fetch multiplier is therefore not safe. Instead, page
through the query 1,000 rows at a time — PostgREST caps a single response at
1,000 — applying the filter to each page and stopping once `shortfall` teams
have survived or the pages run out. Returning fewer than `shortfall` when supply
is exhausted is acceptable and already handled by the call site.

### Extract the filter, do not copy it

The U8/U9 and birth-year checks currently live inline in `drain_queue()`'s filter
loop. Extract them, with `_is_placeholder_unknown_team`, into one
`_is_scrapeable_team(team) -> bool` helper used by both the existing loop and the
new top-up path. This removes the duplication the change would otherwise
introduce rather than adding a second copy that can drift.

### Never-scraped teams

`last_scraped_at < cutoff` is NULL for a never-scraped team, so PostgREST
excludes them. There are 7,724 such teams, but `get_scrape_eligibility_counts`
reports `never_count = 0` — every one of them fails the age, birth-year, or
placeholder filters anyway. So the exclusion costs nothing real today.

It is also the correct behavior on the merits: a never-scraped team carries no
evidence of activity, and this change is built on last-scraped-date as an
activity signal. Should genuinely eligible never-scraped teams appear later,
`enqueue_safety_net` already targets teams "never scraped or not scraped in 90+
days" and feeds them through the queue at priority 4, which the drain claims
before it reaches the top-up.

## Scope

- **In scope:** `_fetch_topup_teams` and the filter extraction, both in
  `scripts/drain_queue.py`.
- **Out of scope:** `get_teams_to_scrape_limited`. Untouched, so `scrape_games.py`
  is byte-for-byte unaffected.
- **Out of scope:** `get_scrape_eligibility_counts` and the dashboard. It mirrors
  what `scrape_games` would pick, which remains true.
- **Out of scope:** `scripts/enqueue_active_teams.py` and its daily workflow.
  That is the automated, hands-off pipeline; "Help Clear Queue" is a manual tool,
  and improving the manual tool must not perturb the automation.
- **Out of scope:** the stale docstring in four `enqueue_*.py` scripts claiming
  `process_missing_games` drains "200/run" when
  `.github/workflows/process-missing-games.yml:42` runs `--limit 40`. Real, and
  unrelated.

## The trade-off

Teams last scraped 75+ days ago will no longer be selected by the top-up, where
today they are selected first. That is the intent — they yield nothing — but it
means the top-up stops doing discovery.

Discovery is not the top-up's job. `scripts/enqueue_discovery_teams.py` runs
weekly (`enqueue-discovery.yml`, `cron: '0 14 * * 0'`), selects teams with no
future games on record, and enqueues them at priority 3. The drain claims queue
rows before it ever calls the top-up, so dormant teams still get scraped — via
the automation rather than the manual button.

## Failure behavior

The current implementation calls the RPC through `call_rpc_with_fallback`, which
returns `[]` only on SQLSTATE 42883 ("function does not exist") and re-raises
every other error. A direct table query has no 42883 case: `teams` always
exists.

So errors propagate, matching today's semantics for every non-42883 failure.
That is deliberate: swallowing an error would hand back a batch of 300 when
10,000 was requested, with nothing in the output saying why. The claim-release
guard added in `035ff0fc0` catches the propagating exception, returns the
claimed rows to `pending`, and the run fails visibly.

Removing the RPC call leaves `call_rpc_with_fallback` unused in this module; its
import must be dropped or `ruff` will fail on F401.

Removing the RPC call leaves `call_rpc_with_fallback` unused in this module; its
import must be dropped or `ruff` will fail on F401.

## Testing

Extend `tests/unit/test_drain_queue_topup.py`. The existing tests assert RPC
parameters that will no longer exist and must be rewritten against the new query
builder, not deleted.

1. The query applies the 14-day cutoff, provider filter, and
   `order(last_scraped_at, desc=True)`.
2. Birth-year exclusions are computed from the current year, not hardcoded.
3. Paging continues while pages come back full and stops once `shortfall` teams
   survive filtering.
4. Placeholder and U8/U9 rows are dropped, and paging fetches further to make up
   the difference rather than returning short.
5. Teams already in `exclude_ids` are dropped.
6. Supply exhaustion returns fewer than `shortfall` without raising.
7. `shortfall <= 0` issues no query at all.
8. A PostgREST error propagates rather than being swallowed, so the caller's
   claim-release guard runs and the failure is visible.
9. `_is_scrapeable_team` rejects placeholder, U8, U9, and out-of-range birth
   years, and accepts a normal team and one with NULL age/birth-year.

## Verification

`ruff check`, then `python -m pytest tests/unit/test_drain_queue_topup.py`.

Then `python scripts/drain_queue.py --dry-run --limit 200` against production and
confirm: the previewed teams' `last_scraped_at` values are descending and start
around 14 days back, the claimed rows are released, and the `processing` count
returns to baseline.

Finally, sample the previewed set for games in the last 90 days. Expect roughly
99%, against the 5.6% baseline.
