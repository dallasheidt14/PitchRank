# Handoff: Skip inactive teams in the scrape queue

Plan: `.turbo/plans/skip-inactive-teams-in-scrape-queue.md` (status `done`, with a note
pointing here and at the blockers report).

## Where this landed

The feature is **shipped, applied to production, and live**. Three PRs today:

| PR | What | State |
|---|---|---|
| #1047 | The activity filter: 4 columns on `teams`, the refresh RPC, `find_topup_teams`, the predicate in `find_stale_teams` / `find_discovery_teams`, scrape logging in `process_missing_games` | merged `2d48cdc80` |
| #1048 | Moved the four enqueue crons off minute 0 | merged `bfb6e4e53` |
| #1049 | `pipefail-substitution` check for the `review-workflows` skill | **open, not merged** |

Migrations applied by hand and verified: 4 columns, 2 new functions locked to
`service_role`, predicate live in both gated functions, revival producers uncontaminated.

The live backfill ran 2026-08-28: **41.7s, 107 pages, 211,401 rows**. Verified against the
plan's own sizing and it matched closely (dormant-with-future-fixture came in at 462 against
a predicted 461; the zero-game-with-a-fixture integrity check returned 0 as required).

Current effect: **32,803 of 171,989 GotSport teams (19.1%) are now filtered**, 25,088 of
them scraped within the last 14 days, which is the pool the top-up draws from.

## Two things the plan got wrong — do not re-derive these

1. **`SET LOCAL statement_timeout` inside a function does nothing.** PostgreSQL arms that
   timer once per top-level command; statements inside a function never re-arm it. A
   service-role PostgREST call inherits `authenticator`'s 8s regardless. The refresh
   therefore pages from the caller (`p_after` / `p_batch_size`), ~290ms per page. The same
   bug silently breaks `backfill_total_game_stats` — logged as IMP-128, and
   `rankings_full`'s total games/wins/losses have been frozen for months as a result.
2. **The filter does not bind on the two Sunday enqueue jobs.** Both fill their `LIMIT`
   from a pool that passes the predicate anyway (`find_stale_teams` returns 500 never-scraped
   teams; `find_discovery_teams` has 31,335 candidates with a game in the last 90 days
   against a limit of 1,000). It binds on `drain_queue`'s top-up. Accepted deliberately;
   the Sunday jobs benefit as their backlogs drain.

Also corrected in-session: `scrape_attempts` is **not** near-zero. `team_scrape_log` has
been written by the bulk and manual scrapers since 2025-11-03, so the never-productive rule
was live immediately rather than needing a week's soak (max observed: 104 attempts).

## Outstanding work

1. **`drain_queue` does not release claims when cancelled.** Its two `_release_queue_items`
   calls are both pre-scrape; `except KeyboardInterrupt` at `scripts/drain_queue.py:885`
   exits without releasing. A cancelled `clear-queue` run on 2026-08-23T18:17 stranded 5,981
   rows in one second. Until fixed, the next cancellation strands thousands more.
2. **Retire the 6,482 rows stuck in `processing`.** Mark them `failed`, not `pending` —
   they are days old and returning them would push stale requests ahead of current work.
3. **Correct the docs.** `CLAUDE.md` claims stranded teams "cannot be re-enqueued and are
   silently dropped". False: `idx_scrape_requests_pending_team` is `UNIQUE … WHERE status =
   'pending'`, so a processing row blocks nothing, and 1,974 of the 6,392 affected teams have
   already been queued again. IMP-127 repeats the same wrong rationale. The workflow table's
   times are also now 13-56 minutes off after #1048.
4. **Enable the refresh cron.** `.github/workflows/refresh-team-scrape-activity.yml` is
   `workflow_dispatch`-only by design. Now that a live run is verified, add
   `cron: '0 12 * * 0'` — but pick an off-hour minute, per #1048's finding — and add the row
   to CLAUDE.md's workflow table in the same commit, or
   `tests/unit/test_agent_doc_references.py` fails.
5. **Merge or close #1049.**

## Uncommitted work in the tree — read before touching these

Four modified tracked files, and they are **mixed authorship**:

- `.claude/skills/supabase-pitchrank/SKILL.md` — the planning session's additions, plus this
  session's rewrite of the "Long-running RPCs" section, which previously taught the exact
  timeout mistake in point 1 above.
- `CLAUDE.md` — the planning session's additions, plus this session's corrections to the
  `team_scrape_log` section and two new Verification rules.
- `.turbo/improvements.md` — the planning session's entries, plus IMP-128 through IMP-133.
- `scripts/backfill_unknown_team_names.py` — entirely the planning session's; untouched here.

Nothing in this list was staged or committed, deliberately. Backups of the first three are at
`%LOCALAPPDATA%\Temp\claude\C--PitchRank\fa7a9900-4d08-4144-9b4a-0c4c6094ab6b\scratchpad\uncommitted-backup\`.

Note the local `main` branch is stale and a checkout to it fails on `.turbo/improvements.md`.
Branch from `origin/main` instead. Local branches were left alone: squash merges mean
`git log origin/main..<branch>` reports merged branches as unmerged, so verify via `gh pr
view` before deleting any.

## Next concrete action

Fix `drain_queue` so a cancelled run releases its claims, then retire the 6,482 stranded rows
as `failed` in the same change. That is the only outstanding item that actively costs
something: every cancelled Help Clear Queue run strands another few thousand requests.
