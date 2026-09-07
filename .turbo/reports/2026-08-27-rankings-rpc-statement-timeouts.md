# Rankings statement timeouts (57014)

**Date:** 2026-08-27 (revised after systematic investigation)
**Status:** root cause confirmed, not fixed

> **This report was rewritten.** The first version blamed
> `get_national_rankings` and recommended removing a `LEFT JOIN
> current_rankings` as the primary fix. That was wrong on the path that
> matters. Superseded findings are listed at the bottom so the earlier
> claims are not silently reused.

## Root cause

`api.getTeam` (`frontend/lib/api.ts:307`) queries `state_rankings_view`
filtered by `team_id_master`.

That view computes

```sql
ROW_NUMBER() OVER (PARTITION BY state, age, gender ORDER BY power_score_final DESC, team_id_master)
```

in a CTE, then joins it. **A filter cannot be pushed below a window
function**, so Postgres must compute the window over the whole set and then
discard everything but the requested row:

```
->  Subquery Scan on asr  (actual rows=1)
      Filter: (asr.team_id_master = '0c31...')
      Rows Removed by Filter: 60220
      ->  WindowAgg  (actual rows=60221)
```

To return one team's state rank it ranks **60,221 teams**, via parallel
sequential scans of `teams`, `rankings_full` and `current_rankings`, plus a
60k-row sort whose key is a nested `CASE`/`regexp_replace` age expression.

**398 ms warm on an idle connection**, CPU bound, and it takes a parallel
worker with it. Concurrent copies contend for CPU, so under load it crosses
the 3 second `anon` statement timeout and is cancelled as 57014.

## It accounts for essentially all of the timeouts

Postgres 57014 events grouped by statement, 2026-08-27 UTC:

| Hour | Total | `state_rankings_view` by `team_id_master` |
|---|---:|---:|
| 22:00 | 1032 | **1009** |
| 20:00 | 821 | **803** |
| 18:00 | 338 | **327** |
| 15:00 | 106 | **103** |

971 distinct URLs for 991 failures at 22:00, i.e. many different teams, not
one hot row. The national rankings RPCs are a minority of the remainder.

## The failure is designed for, which is why it hid

`frontend/lib/api.ts:341` already says the quiet part out loud:

> state_rankings_view commonly times out because its ROW_NUMBER window
> function requires scanning all rows.

When the view returns nothing, `getTeam` falls back to the
`get_team_state_rank` RPC. So the page still renders correct data. The cost
is invisible from the outside and severe from the inside: **every team page
spends up to 3 seconds of CPU and a parallel worker on a query whose result
is thrown away.** The more of them run at once, the slower each becomes, and
the more of them time out. That is a positive feedback loop, and it explains
why the timeout rate scales faster than traffic (22:00 had half of 18:00's
requests but 6x the timeout rate).

Corroborating: **1032 Postgres timeouts against 1 HTTP 500.** The failures
are swallowed and served as 200s, so nothing ever paged anyone.

## The fix is already written

`get_team_state_rank(p_team_id)` computes the same rank by counting better
teams in the cohort, using `idx_rankings_full_state` and
`idx_rankings_full_age_gender`:

| Path | Time | Work |
|---|---:|---|
| `state_rankings_view` filtered by team | 398 ms | ranks 60,221 rows, discards 60,220 |
| `get_team_state_rank` RPC | **6.5 ms** | index scans, 766 buffers |

**61x cheaper, same answer, already deployed and already called.**

Change: drop `state_rankings_view` from the `Promise.all` in `getTeam` and
call `get_team_state_rank` unconditionally instead of only as a fallback.
Small diff, removes the doomed query entirely.

Check the other two callers before assuming they are safe:
`app/api/watchlist/route.ts:224` and `lib/matchPredictionService.ts:209`.
`app/api/infographic/spotlight/route.tsx:43` also reads the view.

## Amplifier: a crawler collapsing the cache hit rate

Request volume at peak was not higher than during quiet hours. The **cache
miss rate** was, roughly 9x:

| Window | MISS | HIT |
|---|---:|---:|
| Burst 22:01 | 36% | 62% |
| Quiet 23:08 | 4% | 96% |

A client walks the state x age x gender cross product alphabetically, 9
distinct `ia/*` routes all MISS inside 2 seconds, then `ok/*`, then `il/*`.
**3,049 distinct paths in 75 minutes** versus 1,250 in 59 quiet minutes. It
requests `u18` routes (`ca/u18/male`, `national/u18/male`), a cohort that per
project rules holds no teams, which is conclusive that it is enumerating
blindly rather than following links. Those routes still render, normalising
18 to 19, so they burn full query work to produce duplicate u19 data and
occupy their own cache entries.

The same client is behind the `/upgrade` volume: 4,898 hits in 75 minutes,
essentially all of the 4,723 `307`s, from crawling premium `/teams/*` pages
and being redirected.

## Suggested order of work

1. **Stop querying `state_rankings_view` per team in `getTeam`.** Removes
   ~97% of the timeouts. 61x cheaper, fallback already exists.
2. **Lengthen and jitter revalidation** on the state x age x gender routes so
   expiries do not hand a crawler a fresh wall of misses. Consider not
   generating `u18` permutations at all, since they duplicate u19.
3. **Rate limit or exclude the enumerating client.** It is not a user.
4. Drop the inert `LEFT JOIN current_rankings` from `get_national_rankings`.
   Real but secondary: 284 ms -> 72 ms on the age filtered path, ~8 ms on the
   unfiltered path.
5. Make the national sort key indexable, or use keyset pagination, if
   `/rankings/national` is still slow after the above.
6. **Do not** raise the `anon` timeout. It hides the next regression.
7. **Do not** bother with `VACUUM FULL`. Both hot tables carry ~1.7x
   free space bloat, but it is a constant factor and refills at the next
   weekly rewrite.

## Hypotheses tested

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | Dead tuple bloat inflates scans | **Refuted** (mechanism) | `rankings_full` holds 0 dead tuples after 18.6M updates, 648 autovacuums. Physical free space bloat ~1.7x is real but a constant factor. |
| H2 | Instance wide saturation | **Refuted** | Zero occurrences of `too many clients`, lock waits, temp files, OOM in 8 hours. No auth, profile or lookup query timed out even once. 18:00 had 2x the traffic of 22:00 and one sixth the timeout rate. |
| H3 | ISR/prerender amplification | **Confirmed** (mechanism) | Cache miss rate 36% vs 4%; 3,049 distinct paths in 75 min; alphabetical state x age x gender sweep including nonexistent u18 routes. |
| H4 | Removing the inert join restores headroom | **Refuted** | On the unfiltered path the join runs *after* the LIMIT as a nested loop over 1,000 rows, ~8 ms of ~300 ms. `teams` was never seq scanned there. |
| H5 | `state_rankings_view` per team is the real cost | **Confirmed** | 1009 of 1032 timeouts at 22:00. 398 ms warm, ranks 60,221 rows to return 1. |

## External review findings (Codex), evaluated

| Location | Issue | Severity | Verdict | Challenged |
|---|---|---|---|---|
| `get_national_rankings` + `team_alias_map` RLS | `has_modular11_alias` is always `false` on public pages: the table has `deny_all USING (false)` for `anon`/`authenticated` and the function is not `SECURITY DEFINER`. Correctness, not performance. | Medium | **Escalate** | Confirmed via `pg_policies` + `prosecdef=false` |
| `get_national_rankings`, `get_state_rankings`, `get_team_state_rank` | All `EXECUTE`-granted to `anon`, none `SECURITY DEFINER`, and `p_limit`/`p_offset` are unclamped. Anyone can request `OFFSET 500000`; cost grows linearly (measured 540 ms / 100k buffers at OFFSET 20,000). A crawler is already confirmed present. | High (was Medium) | **Apply** | Confirmed via `proacl` |
| `frontend/lib/api.ts` `getRankings` | Claimed uncapped `OFFSET` loop, ~103 sequential RPCs per national render. | — | **Skip** | Refuted: all 6 call sites pass an explicit `limit`; the 2 matches without one are JSDoc examples |
| `teams.idx_teams_active` | Partial index `WHERE is_deprecated = false` cannot serve `IS NOT TRUE` filters. Reviewer called it "the cheapest high-value lead". | Low (was High) | **Skip** | Disputed. Mechanism real, conclusion wrong: **0 rows are NULL**, so the predicates are identical today. It is a consistency issue (35 `IS NOT TRUE` vs 28 `= false` sites), not a lever. |
| `get_national_rankings_count` + `get_national_active_count` | Collapse into one `COUNT(*) FILTER`. | Low | **Skip** | Disputed: they are never called on the same render (different routes), so consolidation saves zero scans |
| `frontend/app/rankings/age/[ageGroup]/page.tsx:116-117` | **New, found while disputing the above.** The same count RPC is called twice on one render, differing only by gender. A genuine duplicated ~257 ms scan that `COUNT(*) FILTER (WHERE gender = ...)` collapses. | Low-Medium | **Apply** | Found by the challenge pass |

Codex's primary answer ranked mechanisms for `get_national_rankings`, which is
not the dominant query. It was briefed before `state_rankings_view` was
identified, so treat that ranking as superseded rather than wrong. It also
cited a comment about "~8 concurrent RPCs per build page" as live evidence;
that comment describes a past SSG build incident, not the current SSR path.
Its one clean negative result: there is no retry amplification, because the
only fallback branch in `getRankings` fires on `PGRST202` (missing RPC), and a
57014 is thrown immediately.

Correction to this report's own earlier reasoning: `idx_teams_active` was
described as dead weight with "no read benefit". That was wrong. It carries
94.3M scans and the highest `idx_tup_read` on the table, and at 94.7% row
qualification it is 11 MB against 10 MB for the full index, so it is larger
rather than smaller. The conclusion (not a performance lever) stands; the
rationale did not.

## Superseded claims from the first version of this report

- "Drop the `current_rankings` join, biggest win." It is worth doing for the
  age filtered pages, but it is fix #4, not #1, and it does almost nothing
  for `/rankings/national`.
- "`get_national_rankings` unfiltered costs 680 ms / 28,122 buffers,
  materialising 102,958 rows." Did not reproduce; the same query ran at
  296 ms / 24,331 buffers with a nested loop plan. Do not use 680 ms as a
  baseline.
- "Seq scan of `teams` (200k rows) on every call." True for the age filtered
  plan, false for the unfiltered plan, which uses an index scan.

## Caveats

- All timings are warm cache, single connection. They are floors.
- `pg_stat_statements` is not installed, so there is no per statement call
  count to rank real production load. Installing it would sharpen any
  follow up.
- Cache MISS/HIT ratios come from capped log samples taken identically in
  both windows, not full counts.
- Postgres `log_connections` is off, so concurrent session counts could not
  be measured directly.
