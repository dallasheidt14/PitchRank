# Null-Score Game Backfill

## Problem

Games scraped as future/scheduled games are inserted with `home_score=NULL, away_score=NULL`. When the scraper re-visits the team after the game is played, the pipeline's `game_uid` duplicate check sees the game already exists and silently discards the scored version. Scores are never backfilled.

Affects **gotsport only** — the only provider that imports future-dated games. Modular11 path is unaffected (separate code branch).

As of 2026-05-27, 13,127 null-score past games exist in the DB. These will self-heal as teams are naturally re-scraped.

## Root Cause

In `src/etl/enhanced_pipeline.py`, the non-Modular11 regen-UID dedup (line ~719) filters out ALL games whose regenerated `game_uid` already exists in the DB — regardless of whether the existing record has scores. This blanket filter prevents scored re-scrapes from reaching the existing score-update logic at Step 3C.

## Fix

Targeted patch at the regen-UID dedup stage in the non-Modular11 path:

1. **`_check_duplicates`**: Also fetch `home_score`/`away_score` from existing records (adds 2 fields to the SELECT and return dict).

2. **Regen-UID dedup block**: Instead of filtering all matches, classify each:
   - **True duplicate** (existing has scores, or incoming has no scores) → filter out as before, backfill master IDs.
   - **Null-score update** (existing has NULL scores, incoming has actual scores) → call `_update_null_score_games` to UPDATE the DB record with scores, result, and scraped_at.

3. **New `_update_null_score_games` method**: Iterates games needing score backfill, issues individual UPDATE queries by `game_uid`. Logs each backfill.

4. **`ImportMetrics`**: New `scores_backfilled` counter.

### What is NOT changed

- Modular11 path (lines 600-714) — separate code branch, untouched.
- Step 3C score-update logic (lines 820-939) — unchanged, still handles Modular11 and any edge cases.
- Composite key dedup, master-level dedup — unchanged.
- `_bulk_insert_games` — unchanged.
- Scraper logic — unchanged (scraper correctly retrieves scores).
- Frontend `GameHistoryTable` — already handles null scores gracefully ("No score" / "—").

### Edge cases

| Scenario | Behavior |
|----------|----------|
| Null→actual scores | UPDATE via `_update_null_score_games` |
| Both incoming and existing have null scores | True duplicate, filtered out |
| Existing has scores, incoming has null | True duplicate, filtered out (no downgrade) |
| Existing has scores, incoming has different scores | True duplicate, filtered out (score corrections are a separate issue) |
| Cancelled game (stays null forever) | Incoming also null → filtered as true dupe |
| Concurrent scraper runs update same game | UPDATE is idempotent, safe |
| Partial scores (one null, one not) | Treated as null-score if either is null |

## Files Changed

- `src/etl/enhanced_pipeline.py` — `_check_duplicates`, regen-UID dedup block, new `_update_null_score_games`, `ImportMetrics`
- `tests/test_enhanced_pipeline.py` — Update `test_duplicate_detection` mock to include score fields

## Verification

- Existing test suite passes (3 pre-existing failures unrelated to this change).
- Syntax check passes.
- Natural scraping will backfill the 13K existing null-score games over time.
