# Schedule-Driven Scraping

**Date:** 2026-05-19
**Status:** Draft (pending user review)
**Slug:** `schedule-driven-scraping`

## Scope

GotSport teams only. PlayMetrics is explicitly out of scope for this spec — same idea may extend to it later, but no PlayMetrics wiring or testing in this work.

## Problem

Every weekly scrape pulls each GotSport team's full schedule (past + future games), but `enhanced_pipeline.py` discards every row with a missing score. Future-dated games — which are *scheduled* and therefore necessarily scoreless — get caught in this filter and never reach the database.

Consequences:

- We re-pay the scrape cost for the same teams every week, without using the data we already have to decide *which* teams need scraping.
- Teams without recent games still get scraped on the same cadence as active teams, wasting ZenRows quota and adding WAF risk.
- We have no record of upcoming fixtures, so we can't schedule scrapes against the day-after-game window where scores are most likely to be available.

Currently `teams.last_scraped_at` is the only signal we have for what to scrape next, and it isn't tied to whether the team actually has games to fetch.

## Goal

Persist future-dated games in the `games` table as NULL-score rows. Use those rows as the trigger for a per-team, day-after-game scrape so we collect scores precisely when they become available, instead of running broad weekly chains. ZenRows is reserved for the one-time bootstrap and the periodic safety-net rescrape; the daily ongoing work runs as direct provider hits, sized like `process_missing_games.py`.

## Non-goals

- No new tables, RPCs, or storage abstractions for scheduled games. NULL scores in the existing `games` table are the representation.
- No retry-window logic. If a score isn't posted by the day-after scrape, the row stays NULL; the team's next scheduled game will pull it eventually, and the discovery pass + 90-day safety net catch everything else.
- No changes to the ranking engine, Glicko-2 inputs, or any consumer that already filters out scoreless rows. Consumers that don't filter are surfaced and patched, but no behavior change for scored games.
- No UI feature work for showing scheduled games to users. (A `result IS NULL` row in game history will display as blank or "scheduled" — that's worth a follow-up but is out of scope here.)

## Design

### Storage model

Future games live in the existing `games` table with:

- `home_score = NULL`, `away_score = NULL`
- `result = NULL`
- `game_date > CURRENT_DATE` at insert time
- `is_immutable = false` (scheduled rows must be UPDATE-able when scores arrive)
- `scraped_at` set as usual

When the score is later scraped, the row UPDATES via the existing `game_uid`-based dedup path. `game_uid` is symmetric on `(team_a, team_b, game_date)` and does not include scores (confirmed by inline comment at `src/etl/enhanced_pipeline.py:396`), so the scheduled row and the played row collide on the same uid and the played row's scores overwrite the NULLs.

`games.scraped_at` serves as the row-level freshness marker; no new `updated_at` column is needed.

### Pipeline change

`src/etl/enhanced_pipeline.py` has two filter sites that both drop scoreless rows. Both need the same carveout for future-dated games:

**Site 1: `_validate_and_dedup` (pre-dedup), line 1063-1072.**
Currently increments `skipped_empty_scores` and `continue`s when both scores are empty. Change: if both scores are empty AND `parse_game_date(game_date) > CURRENT_DATE`, let the row through (do not increment, do not continue). Else, existing behavior (skip past-dated scoreless rows as data quality issues).

**Site 2: `_has_valid_scores` filter (post-match), line 885-909.**
Currently filters rows by `self._has_valid_scores(g)` and shuffles failures into `skipped_games`. Change: extend the predicate so a row with `game_date > CURRENT_DATE` and NULL scores passes through to insertion. Past-dated rows with invalid scores continue to fail and get logged as data quality issues.

The `_is_empty_score` helper (line 1038-1039) and `_has_valid_scores` (line 271) themselves do not change; only the call sites that branch on them. This keeps the helpers honest — "this score is empty" remains a true statement about the score — while the carveout becomes an explicit policy at the call sites.

### Bootstrap (Phase 2)

One-shot scrape of every team in DB, using the existing ZenRows path, after the pipeline patch is deployed.

- Trigger: manual script invocation (`scripts/bootstrap_schedule_scrape.py`, new).
- Source: `teams` table, all rows where `is_deprecated = false`.
- Order: ascending `last_scraped_at` (oldest first, nulls first). Highest-value coverage gain comes from teams we haven't touched recently.
- Chunking: ~500 teams per batch with a between-batch sanity check that logs (a) how many teams returned at least one future-dated game and (b) what fraction of all returned rows are future-dated. Early batches validate the premise before the full quota is burned.
- Idempotency: bootstrap re-runs are safe. Scheduled rows dedup via `game_uid`; `last_scraped_at` updates each pass.

### Daily cron (Phase 3)

New script (`scripts/scrape_yesterdays_games.py`) and accompanying GitHub Actions workflow. Runs daily at 7am local (TBD what timezone — `America/Phoenix`/`UTC`, see Open Questions).

**Trigger query:**

```sql
SELECT DISTINCT g.home_team_master_id AS team_id_master
FROM games g
JOIN teams t ON t.team_id_master = g.home_team_master_id
WHERE g.game_date = CURRENT_DATE - 1
  AND g.home_score IS NULL
  AND t.is_deprecated = false
  AND (t.last_scraped_at IS NULL OR t.last_scraped_at < CURRENT_DATE)

UNION

SELECT DISTINCT g.away_team_master_id AS team_id_master
FROM games g
JOIN teams t ON t.team_id_master = g.away_team_master_id
WHERE g.game_date = CURRENT_DATE - 1
  AND g.home_score IS NULL
  AND t.is_deprecated = false
  AND (t.last_scraped_at IS NULL OR t.last_scraped_at < CURRENT_DATE)
```

Both teams in the matchup need to be scraped (each will return the same game with the score, but one team may have additional games we haven't seen). DISTINCT + the `last_scraped_at < CURRENT_DATE` gate prevents double-scrapes when a team plays multiple games in a tournament weekend.

**Per-team work:**

1. Direct scrape of the team's full GotSport schedule via `GotSportScraper` (same scraper class `process_missing_games.py` already uses).
2. Push results through the existing `enhanced_pipeline` import path (same code as the weekly chain — no parallel path).
3. The pipeline's existing dedup will UPDATE the scheduled NULL-score row with the played score, INSERT any new future games, and ignore already-stored past games.
4. Update `teams.last_scraped_at = NOW()`.

**No retries.** If yesterday's score isn't posted yet, the row stays NULL. The team's next game will re-trigger the cron in a future window; that scrape will pick up the now-posted late score as a side effect of fetching the full schedule.

**Volume estimate:** GotSport team count × ~1 game/week ÷ 7 days, smooth across the morning. Direct hits, no ZenRows. Actual number to confirm via `SELECT count(*) FROM teams WHERE provider = gotsport AND NOT is_deprecated` during plan-drafting.

### Schedule-discovery pass (Phase 4)

The daily cron only triggers on teams that already have future-dated rows in `games`. Teams with empty future schedules — either because their season is between sessions, the club hasn't published yet, or they were genuinely inactive at bootstrap time — drop out of daily-cron eligibility entirely. The 90-day safety net is too coarse to catch them in a useful window; a club that publishes a fall schedule in late August would have games slip by for weeks before the safety net touched them.

This phase repurposes the existing weekly chain as a **discovery pass** for exactly this set of teams. Instead of scraping every team every week (current behavior), the weekly chain narrows to teams without visible future games:

```sql
-- "Teams without visible future schedules"
SELECT t.team_id_master
FROM teams t
WHERE t.is_deprecated = false
  AND t.provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
  AND NOT EXISTS (
    SELECT 1 FROM games g
    WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
      AND g.game_date > CURRENT_DATE
  )
```

Direct scrape (or ZenRows if volume is high — TBD), same import path. Once the discovery pass finds future games for a team, the daily cron picks them up automatically from there.

This is a meaningful behavior change to the weekly chain: it stops being the primary collection mechanism and becomes a low-frequency probe. Active teams (which the daily cron already covers) are excluded from the discovery query because they have future-dated rows.

**Cadence assumption.** Weekly is a starting point. If clubs typically publish schedules with <1 week lead time, the discovery pass needs to be more frequent (e.g., every 3 days) to avoid missing the first 1-2 games. Empirical question — answered after bootstrap by measuring the gap between "team had no future games on day N" and "team had games on day N+M."

### Safety net (Phase 5)

A final low-frequency catch-all for teams that the discovery pass somehow misses (deprecated-then-undeprecated, provider re-link, etc.):

```sql
SELECT team_id_master
FROM teams
WHERE is_deprecated = false
  AND (last_scraped_at IS NULL OR last_scraped_at < NOW() - INTERVAL '90 days')
```

Direct scrape, same import path. In practice this should rarely match because the discovery pass updates `last_scraped_at` weekly for the subset it touches, but it's worth keeping as a backstop.

### New-team scrape hook (Phase 6)

When a new team is added to `teams`, fire a single direct scrape on insert so it joins the daily-cron eligibility set immediately. This already exists in some form (verify during implementation — see Open Questions).

### Provider scoping

GotSport only. The daily cron and bootstrap must filter the trigger query to GotSport teams:

```sql
... AND t.provider_id = (SELECT id FROM providers WHERE code = 'gotsport')
```

(Exact provider lookup mechanism to confirm during implementation — see Open Questions.)

`GotSportScraper` is already wired in `process_missing_games.py:56`; the new daily cron can reuse the same instantiation pattern. No PlayMetrics work in this spec.

## Consumer audit

Before deploy, verify these consumers tolerate NULL-score rows in `games`:

| Consumer | Expected behavior | Risk |
|---|---|---|
| Ranking engine (Glicko-2 input) | Must skip rows where `home_score IS NULL OR away_score IS NULL` | High — corrupts ratings if leaked |
| `rankings_view` / `rankings_full` | Should already filter via score predicate; verify | Medium |
| `frontend/lib/api.ts` game history | Will render NULL rows as blank cells unless explicit "scheduled" handling exists | Low (cosmetic, not data) |
| `GameHistoryTable` and team-detail components | Behind premium gate per [[gotcha_team_detail_premium_gated]]; verify NULL rows don't crash | Low |
| Existing dedup logic | UPDATE-on-uid-collision path must not skip scheduled rows | High |
| `is_immutable` enforcement | Scheduled rows must be `false`; verify no code defaults to `true` | High — would block score updates |
| `result` column derivation | Must produce NULL for NULL scores (or be NULLABLE in schema) | Medium |
| Analytics / exports (CHANGELOG, weekly reports) | Verify nothing assumes `count(*) from games` = played games | Low |

Each row in this table is a separate verification task in the implementation plan.

## Rollout

1. **Pipeline patch** (one PR, ~5-20 lines + tests).
   - Patch both filter sites in `enhanced_pipeline.py`.
   - Add unit test: scoreless row with `game_date = today + 7` passes through; scoreless row with `game_date = today - 7` is still skipped.
   - Add integration test: same team scheduled-then-played sequence dedups to a single row with scores filled.
   - Deploy.

2. **Bootstrap script + dry-run** (one PR).
   - `scripts/bootstrap_schedule_scrape.py` with `--dry-run` and `--limit N` flags.
   - Run `--dry-run --limit 500` on a real batch; inspect logged sanity-check stats (% teams with future games, % rows future-dated).
   - If stats confirm the premise, run for real, batched.

3. **Daily cron** (one PR).
   - `scripts/scrape_yesterdays_games.py` with the trigger query above.
   - GitHub Actions workflow `daily-yesterday-scrape.yml`, schedule TBD.
   - Shadow-mode flag: log what would be scraped without scraping, for one cycle.
   - Cutover after one clean shadow run.

4. **Schedule-discovery pass** (one PR — modifies existing weekly chain).
   - Change the weekly chain's team-selection query from "all teams" to the `NOT EXISTS future games` subset.
   - Verify cadence empirically after 2-3 cycles; consider tightening to 3-day if discovery latency is biting.

5. **Safety net** (one PR or fold into discovery pass workflow).
   - Add `last_scraped_at > 90 days` predicate as a second OR-branch on the discovery pass query, or run as a separate weekly workflow.

6. **New-team hook** (verify or add).
   - Audit existing team-insert path. If a direct scrape isn't already wired, add one.

Order matters: pipeline patch first, then bootstrap, then daily cron. Daily cron is useless without scheduled rows to trigger on, and the bootstrap is wasted ZenRows budget if the patch isn't in.

## Open questions

These need answers during plan-drafting, not now:

1. **Daily cron timezone.** `America/Phoenix` is the user's TZ but GotSport posts scores on local-game-time clocks. 7am UTC vs 7am Phoenix changes coverage by 7 hours. Consensus: run early enough that East Coast late-Sunday games have posted by Monday morning. Likely 11am-1pm UTC.
2. **GotSport provider filter.** Confirm the exact predicate to scope the trigger query to GotSport teams (`teams.provider_id` join to `providers` table, or a direct code column on `teams`).
3. **New-team scrape hook.** Does this already exist? Where? If not, where does it belong — backend insert hook, frontend submit handler, or the matcher pipeline?
4. **`games.result` derivation.** Is `result` a generated column, a trigger-derived value, or set by the pipeline? If trigger-derived, confirm it gracefully handles NULL scores. If pipeline-set, confirm it sets NULL for NULL scores.
5. **Bootstrap batch size and pacing.** ~500/batch is a guess. Real number depends on ZenRows concurrency and GotSport WAF. Set during dry-run.

## Risks

- **Silent NULL leak into rankings.** Highest risk. Mitigation: explicit assertion in the ranking engine entrypoint that no input row has NULL scores. Fail loud if violated.
- **`game_uid` symmetry assumption is wrong somewhere.** Mitigation: integration test that proves a scheduled-then-played sequence produces exactly one row with both teams and the score filled.
- **Bootstrap reveals low future-game density.** If most teams have empty future schedules at any moment, the daily cron has minimal coverage and we end up relying on the safety net. Not catastrophic (we still get the score-collection benefit for active teams), but worth knowing before declaring the design successful.
- **GotSport behavior drift.** GotSport could start returning past games only when explicitly asked, or change its API to require an explicit `?future=true` parameter. Mitigation: contract test that scrapes a single known team and asserts at least N future-dated rows in the response, run weekly.

## Out of scope (follow-ups)

- UI surface for "scheduled" games in team history.
- Push notifications when a scheduled game posts a result.
- Schedule-conflict detection (same team, two games same day, different sources).
- Tournament event linkage (scheduled rows joining to `events` records).
