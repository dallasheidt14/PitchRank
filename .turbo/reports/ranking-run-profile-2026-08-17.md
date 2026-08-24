# Weekly ranking run profile — 2026-08-17 (run 32033951303)

Wall clock: 2h33m total; the `Calculate Rankings` step is 2h30m. Recent runs: Aug 2 3h40m,
Aug 3 2h50m, Aug 10 3h00m, Aug 17 2h33m. The "60-minute ranking run" figure in
`.claude/rules/git-workflow.md` is stale by ~3×.

## Where the 150 minutes go

| Offset | Duration | Phase |
|---|---|---|
| +0m | 14m | Fetch 889K games from Supabase (paginated) |
| +14m | 3m | Metadata fetch (138K teams), merge resolution, v53e-format conversion |
| +17m | 28m | Glicko-2 Pass 1, 18 cohorts (incl. per-cohort ML fit; persistence skipped) |
| +45m | ~36m | Glicko-2 Pass 2 **interleaved with ML residual UPDATEs** (row batches vs `games`) |
| +81m | 20m | Explainability upserts — ~101K rows via RPC batches |
| +101m | 17m | **Silent gap**: same-age evidence gates prep (single log line at each end) |
| +118m | 2m | Gates, anchors, monotonicity |
| +120m | 6m | Rank changes for 124,622 teams |
| +126m | ~24m | Save 124,622 snapshots (125 batches, statement-timeout retries) + `rankings_full` + `current_rankings` + stats backfill |

Engine math is ~45 min. Roughly 100 min is Supabase I/O and one silent pandas step.

## Hotspots, in order of value

1. **Residual + explainability persistence (~55 min).** `_persist_game_residuals` and
   `_persist_game_explainability` (src/rankings/calculator.py:1883, :91) walk small batches;
   progress lines show minutes per 5K rows. Batched RPC with larger payloads, or staging to a
   temp table + one SQL merge, is the biggest single win.
2. **Final saves (~24 min)** hit `canceling statement due to statement timeout` on ~1K-row
   snapshot batches and retry. Trigger/index pressure on `ranking_history`/`rankings_full`
   worth a look before shrinking batches (see data-safety rule: don't over-shrink).
3. **Evidence-gates silent 17 min** (calculator.py `_compute_same_age_evidence_metrics` area):
   likely row-wise pandas `.apply` over 124K teams; vectorizing or logging progress would
   either speed it or at least make it visible.
4. **Game fetch 14 min**: already paginated; minor.

## Bugs surfaced by the same log (not timing)

- **`_backfill_game_stats_python` fails batches with `null value in column "age_group" of
  relation "rankings_full" violates not-null constraint`** (scripts/calculate_rankings.py:662
  warning). Cause: it upserts win/loss aggregates for every team seen in `games`, but teams
  that didn't survive publication have no `rankings_full` row, so the upsert INSERTs a row
  with only stats columns → NOT NULL violation → whole 500-row batch dies (and its retry),
  so stats for teams *in* that batch that DO exist go stale too. Fix: filter to team_ids
  present in `rankings_full` (or upsert with `ignore_duplicates=false` + explicit column
  guard).
- **`SUPABASE_KEY is not set — database calls will fail`** logged at startup by some module
  while the run proceeds on `SUPABASE_SERVICE_ROLE_KEY` — a misleading warning in every run log.
