---
status: done
---

# Plan: Fix null-score backfill blocked by is_immutable trigger

## Context

Scheduled GotSport games are persisted as null-score rows ahead of kickoff (the schedule-driven scraping feature, spec `2026-05-19-schedule-driven-scraping-design.md`). PR #845 (`5298ff2c6`) added `_update_null_score_games` so that when a team is re-scraped after the game is played, the existing null-score row is updated with the final score instead of being discarded as a duplicate.

That fix is a no-op in production. Every game row is inserted with `is_immutable=True` (in `_bulk_insert_games`), and the Postgres `BEFORE UPDATE` trigger `prevent_game_updates` raises `'Cannot update immutable game'` for any update that changes scores on an immutable row. `_update_null_score_games` does a raw `self.supabase.table("games").update(...)`, the trigger throws, and the exception is swallowed (`logger.error(...)` then `continue`) — so scores silently never land and the failure is invisible.

Confirmed live: team `245bbe81` (Elmbrook United – 2012 GA) was re-scraped on 2026-06-01 (its `scrape_requests` row completed 22:54), but game `6b70bd7a` (date 2026-05-31, vs Sockers FC – 2012 Aspire) is still null with `scraped_at=2026-05-26` and `is_immutable=true`. Blast radius at investigation time: **~26,044** past-dated null-score immutable rows (Apr 1–Jun 1) plus **~15,971** future scheduled rows that will get stuck the same way once played.

The original design spec flagged both halves of this bug as High-risk consumer-audit items (line 44: "scheduled rows must be `is_immutable=false`"; line 205: "UPDATE-on-uid-collision must not skip scheduled rows"). #845 implemented the dedup half but not the immutability half.

**Decisions made during planning (Dallas):**
- **Immutability fix = RPC toggle.** Keep the insert default `is_immutable=true`. Route null→final score writes through a new `SECURITY DEFINER` RPC that toggles immutability off → writes the score (only when the existing score is NULL) → toggles back on. This preserves the immutability invariant (a final score is never freely mutable) and mirrors the existing `apply_game_correction` pattern. Do **not** change the insert default to `false`.
- **Backlog = organic self-heal, no dedicated backfill.** Ship the forward fix only. The ~26k stuck rows fill in naturally the next time each team is scraped, because `scrape_team_games` re-scrapes a team's **full** game history (not just new games) — so any scrape (yesterday-enqueue, weekly discovery, 90-day safety net, or user-clicked) routes all of that team's historical null-score rows through the now-fixed update path. No one-time enqueue or standalone backfill script is built. Teams that never get scraped again stay blank, which is acceptable.

This change does not touch ranking math.

## Setup / Branch Hazard (read before editing)

- **`src/etl/enhanced_pipeline.py` has ~31 lines of unrelated, uncommitted staged changes** that are NOT on `origin/main` (`git diff origin/main..HEAD -- src/etl/enhanced_pipeline.py` is empty, but `git status` shows it staged `M `). The working tree on `main` is also broadly dirty (`config/settings.py` staged, modular11 spiders modified, an added spec).
- Before editing: branch from a clean `origin/main` (`git fetch origin && git switch -c fix/null-score-immutable-backfill origin/main`) so the unrelated staged edit and other dirty files do **not** get bundled into this fix. Confirm `git diff --stat origin/main -- src/etl/enhanced_pipeline.py src/etl/bulk_ops.py` is empty on the new branch before starting.
- **Line numbers in this plan are from the staged working-tree file and will drift on a clean checkout. Locate every edit by symbol name (function/field/literal), not by line number.**

## Pattern Survey

**Baseline:** `origin/main` HEAD. PR #845 is merged, so `_update_null_score_games` is present.

### Analogous Features
- `supabase/migrations/20240201000001_add_game_corrections.sql` → `apply_game_correction(...)` (≈ lines 78, 103-135): the canonical toggle-off → UPDATE scores → toggle-on pattern. Literal sequence `UPDATE games SET is_immutable=FALSE ...; UPDATE games SET home_score=...,away_score=...,result=...; UPDATE games SET is_immutable=TRUE`. Each statement passes the trigger because the toggle and the score-write change disjoint field sets. **This is the exact mechanism the new RPC mirrors.**
- `supabase/migrations/20251125000000_add_batch_update_ml_overperformance.sql` → `batch_update_ml_overperformance(updates JSONB)` (≈ line 33): `SECURITY DEFINER` bulk RPC taking a JSONB array, doing a set-based `UPDATE ... FROM jsonb_array_elements(...)`, returning `ROW_COUNT`. **This is the shape to mirror for the new bulk RPC** (grants + return convention). It relies on trigger Exception 3 (which forbids score changes), so it cannot be reused directly — the new RPC needs the toggle.
- `src/etl/enhanced_pipeline.py` → `_backfill_duplicate_team_links` (def ≈ line 1594-region sibling): structural twin of `_update_null_score_games` — same `game_uid` lookup + dry_run contract, surfaces a counter (`duplicate_links_backfilled`), and only writes NULL columns (no-clobber). Mirror its no-clobber discipline.

### Reusable Utilities
- `src/etl/bulk_ops.py` → `call_rpc_with_fallback(supabase, fn_name, params, *, fallback, limit, log_msg)` (line 32) and `bulk_update_last_scraped_at(supabase, updates, *, chunk_size, on_missing_function, ...)` (line 66): the shared chunked-RPC helpers. Handle SQLSTATE `42883` (RPC missing → Python fallback for rolling deploys), HTTP 413 with chunk halving (2000→125), and the `db-max-rows` cap. Constants `PG_UNDEFINED_FUNCTION="42883"`, `HTTP_PAYLOAD_TOO_LARGE_CODES`, `BULK_UPDATE_CHUNK_SIZE=2000`, `BULK_UPDATE_MIN_CHUNK=125`. **`bulk_update_last_scraped_at` is the direct template for a new `bulk_backfill_null_scores` helper.**
- `src/etl/enhanced_pipeline.py` → `@dataclass ImportMetrics` (line 36): counters live here. `scores_backfilled` (line 61) and its `to_dict()` key (line 87) already exist; `duplicate_links_backfilled` (line 60) shows the add pattern. Accumulation pattern: `self.metrics.X += ...` at the call site (lines 755-756) and `batch_metrics.X`.
- End-of-run summary: `logger.info(...)` blocks around lines 1030-1060 print `self.metrics.duplicates_found:,` etc. — where a new failed-backfill line is added.

### Convention Anchors
- **Writes to `is_immutable=TRUE` rows go through a `SECURITY DEFINER` RPC, never a raw client `.update()`.** Every legitimate immutable-row write today uses an RPC (`batch_update_ml_overperformance`, `link_game_team`, `apply_game_correction`). The failing `_update_null_score_games` does a bare `.update()` — that deviation is the bug.
- RPC migration shape: `CREATE OR REPLACE FUNCTION ... LANGUAGE plpgsql SECURITY DEFINER`, then `GRANT EXECUTE ON FUNCTION ... TO authenticated;` and `... TO service_role;`, then `COMMENT ON FUNCTION`. Existing RPCs do not pin `search_path` — this plan adds `SET search_path = public, pg_temp` as cheap hardening per Supabase least-privilege guidance. Filename format `YYYYMMDDHHMMSS_description.sql`; newest existing is `20260528000000_seed_somsports_provider.sql`.
- Live trigger: `supabase/migrations/20260309000000_restore_ml_bypass_in_immutability_trigger.sql` (`prevent_game_updates`). Exception 1 (lines 9-17) allows a pure `is_immutable` toggle ONLY when scores/teams/date are unchanged — this is what makes the 3-statement toggle sequence legal. **Do not modify this trigger.**
- Bulk backfill scripts use the supabase client (not psycopg2), but **this plan ships no backfill script** (organic self-heal decision).
- Self-heal path: `enqueue_yesterday_games.py` (yesterday's null-score GotSport teams, priority 2) + weekly discovery + 90-day safety net enqueue into `scrape_requests`; `process_missing_games.py` (workflow `process-missing-games.yml`, cron `7,22,37,52 * * * *`, `--limit 40`) drains the queue → `scrape_team_games` (full history) → `import_games_enhanced.py` subprocess → `EnhancedETLPipeline` → `_update_null_score_games`. Confirms the backlog heals organically once the update path works.

### Proposed Alignment
Add a `SECURITY DEFINER` RPC `batch_backfill_null_scores(updates jsonb)` modeled on `batch_update_ml_overperformance` (JSONB-array, set-based, returns rowcount) using the `apply_game_correction` toggle sequence. Add a `bulk_backfill_null_scores` helper to `bulk_ops.py` mirroring `bulk_update_last_scraped_at`. Rewire `_update_null_score_games` to call it instead of the raw `.update()`. Add a `scores_backfill_failed` counter so failures surface. Leave the insert default `is_immutable=True` unchanged. Build no backfill script.

## Implementation Steps

1. **Add migration `supabase/migrations/20260602000000_add_batch_backfill_null_scores.sql`.**
   - `CREATE OR REPLACE FUNCTION batch_backfill_null_scores(updates jsonb) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$ ... $$;`
   - Body (keyed on `game_uid`, which is the unique dedup key the helper already has):
     - Declare `v_targets text[]; v_count integer := 0;`
     - Resolve targets — only null-score rows actually present, enforcing the no-clobber guard:
       `SELECT array_agg(g.game_uid) INTO v_targets FROM games g JOIN jsonb_to_recordset(updates) AS u(game_uid text) ON g.game_uid = u.game_uid WHERE g.home_score IS NULL AND g.away_score IS NULL;`
     - `IF v_targets IS NULL THEN RETURN 0; END IF;`
     - Statement 1 (toggle off — passes trigger Exception 1): `UPDATE games SET is_immutable = false WHERE game_uid = ANY(v_targets);`
     - Statement 2 (write scores while mutable; capture count): `UPDATE games g SET home_score = u.home_score, away_score = u.away_score, result = LEFT(u.result, 1)::char(1), scraped_at = COALESCE(u.scraped_at, now()) FROM jsonb_to_recordset(updates) AS u(game_uid text, home_score integer, away_score integer, result text, scraped_at timestamptz) WHERE g.game_uid = u.game_uid AND g.game_uid = ANY(v_targets);` then `GET DIAGNOSTICS v_count = ROW_COUNT;`
       - **`result` is `CHAR(1)`** (`games.result CHAR(1) CHECK (result IN ('W','L','D','U'))`, `20240101000000_initial_schema.sql:71`). Declare the recordset column as `result text` but assign `LEFT(u.result, 1)::char(1)` (mirroring `apply_game_correction`'s explicit `::CHAR(1)` cast, `20240201000001:113`). A raw `result = u.result` assignment of a malformed multi-char value (e.g. a stray `"WIN"`) raises `value too long for type character(1)` and aborts the entire chunk — the bulk helper (Step 2) skips a whole chunk on any non-413/non-42883 `APIError`, so one bad row would silently drop ~2000 backfills.
     - Statement 3 (re-lock — passes Exception 1, scores now unchanged): `UPDATE games SET is_immutable = true WHERE game_uid = ANY(v_targets);`
     - `RETURN v_count;`
   - `GRANT EXECUTE ON FUNCTION batch_backfill_null_scores(jsonb) TO authenticated;` and `... TO service_role;`
   - `COMMENT ON FUNCTION batch_backfill_null_scores(jsonb) IS '...';` explaining the toggle and no-clobber guard.
   - **Preserve / do not touch:** the `prevent_game_updates` trigger and all other migrations. This RPC works *with* the trigger via Exception 1.
   - **Correctness notes for the implementer:** the three statements run in the function's implicit transaction, so rows are only briefly mutable and never observable mid-toggle by other sessions. The `home_score IS NULL AND away_score IS NULL` target filter is the idempotency/no-clobber guard — a second call after scores land selects no targets and returns 0. End state is always `is_immutable=true` (correct: a scored game is final). Rows that were already `is_immutable=false` with null scores are handled fine (statement 1 is a no-op for them, statement 3 sets them immutable — desired).

2. **Add `bulk_backfill_null_scores` helper to `src/etl/bulk_ops.py`.**
   - Mirror `bulk_update_last_scraped_at` exactly: chunked loop, 413 chunk-halving down to `BULK_UPDATE_MIN_CHUNK`, `42883` → `on_missing_function` fallback (no raise), returns total rows updated.
   - Signature: `def bulk_backfill_null_scores(supabase, updates, *, chunk_size=BULK_UPDATE_CHUNK_SIZE, on_missing_function=None, missing_function_log="PERF REGRESSION: batch_backfill_null_scores RPC missing: %s") -> int`.
   - Add module constant `BACKFILL_SCORES_RPC = "batch_backfill_null_scores"`. The RPC returns an integer rowcount (mirror the `res.data if isinstance(res.data, int) else len(chunk)` handling at line 93).

3. **Rewire `_update_null_score_games` in `src/etl/enhanced_pipeline.py` to call the RPC.**
   - Keep the existing guards: early-return on empty input; `dry_run` early-return (`logger.info("would backfill...")`).
   - Replace the per-row `for game in games_to_update:` loop that does `self.supabase.table("games").update(...)` (the raw `.update()` block ending at the swallowed `except Exception as e: logger.error("Failed to backfill...")`) with:
     - Build `payload = [{"game_uid": ..., "home_score": int(...), "away_score": int(...), "result": ..., "scraped_at": ...}]`, reusing the existing int-coercion logic (`int(float(home_score))` with the `try/except` skip for non-numeric) and skipping rows missing `game_uid`/scores. Preserve the same per-row validation currently inline.
     - Call `from .bulk_ops import bulk_backfill_null_scores` (top-of-file import alongside the existing bulk_ops import if present) and `updated = bulk_backfill_null_scores(self.supabase, payload, on_missing_function=lambda: 0)`.
     - `failed = len(payload) - updated`. Return `updated`.
     - **Do not swallow:** if `failed > 0`, `logger.warning("[Pipeline] %d/%d null-score backfills did not land (immutable-block, missing RPC, or already-scored by a concurrent scrape)", failed, len(payload))`. The `42883` path logs the PERF REGRESSION message via the helper and returns 0 (all counted as failed) — acceptable during the deploy window; see Step 6 ordering.
     - **Metric semantics (important):** `scores_backfill_failed` conflates three causes — (1) the immutable-block bug this plan fixes, (2) the transient missing-RPC deploy window (`42883`), and (3) benign races where another worker scored the row between the `regen_uid_master_ids` snapshot (read in `_check_duplicates`) and the RPC write, so the no-clobber guard correctly skips it, statement 2 returns 0 for it, and it's counted as "failed". So a non-zero count is a **signal to investigate, not a definitive error**, and in steady state post-deploy it should trend toward ~0. Document this where the counter is defined. (Optional, deferred for scope: have the RPC return both `v_targets` resolved and rows written so the helper can distinguish "didn't land" from "already landed" — not required for this change.)
   - **Mirror surfaces to preserve:** the helper must still return an int (consumed at the call site `score_bf = await self._update_null_score_games(...)`), and the call site at lines 753-756 accumulates `batch_metrics.scores_backfilled` / `self.metrics.scores_backfilled`.

4. **Add a `scores_backfill_failed` counter and surface it.**
   - In `ImportMetrics` (line 36), add `scores_backfill_failed: int = 0` right after `scores_backfilled` (line 61).
   - In `to_dict()` add `"scores_backfill_failed": self.scores_backfill_failed,` after the `scores_backfilled` key (line 87).
   - At the call site (lines 753-756), after computing `score_bf`, accumulate the shortfall: `failed = len(null_score_updates) - score_bf; batch_metrics.scores_backfill_failed = getattr(batch_metrics, "scores_backfill_failed", 0) + failed; self.metrics.scores_backfill_failed += failed`.
   - **Primary (load-bearing) surfacing is `to_dict()`** (Step 4 above): the `scores_backfill_failed` key flows into the JSONB build log and runs for every provider, including the GotSport scheduled-scrape path. This is the durable, always-on sink — do not rely on a console log for the signal.
   - For human-readable visibility, add a `Scores backfilled: X (Y failed)` line to the **provider-agnostic** `PROGRESS UPDATE` `logger.info(...)` block (≈ `enhanced_pipeline.py:1053-1066`, next to the `Links backfilled:` line). Note this block fires periodically *mid-run*, not at the end — that is acceptable for visibility since `to_dict()` is the authoritative record.
   - **Do NOT** add it to the `MODULAR11 IMPORT SUMMARY` rollup (`~2595-2613`): that block early-returns when `self.provider_code.lower() != "modular11"`, so its `Links Backfilled` print never fires for GotSport — putting the counter there would make it invisible for exactly the pipeline that produces these rows.

5. **Leave the insert default `is_immutable=True` unchanged (no edit).** The `"is_immutable": True` literal in `_bulk_insert_games` stays as-is by design (RPC-toggle decision). Add a brief inline comment there noting scheduled null-score rows are intentionally immutable and are score-backfilled via `batch_backfill_null_scores`, so a future reader doesn't "fix" it to `false`.

6. **No backfill script. Document the deploy ordering and self-heal.**
   - **Deploy ordering:** apply the migration (Step 1) BEFORE or together with the pipeline code so the `42883` fallback is never the live path. If code ships first, backfills are counted as failed (not silently lost) until the migration lands, then heal on the next scrape.
   - **Backlog self-heal (no action needed):** the ~26k stuck rows fill in as each team is next scraped (full-history re-scrape routes old null rows through the fixed path). Optionally, an operator can accelerate a specific team by enqueuing it into `scrape_requests` manually — not part of this change.

## Verification

- **Unit/integration test** in `tests/test_enhanced_pipeline.py` (mirror existing tests there): insert a games row with `home_score=NULL, away_score=NULL, is_immutable=true`; call `batch_backfill_null_scores` (or `_update_null_score_games`) with a scored payload for that `game_uid`; assert (a) `home_score/away_score/result` are now set, (b) `is_immutable` is still `true`, (c) a second call with a *different* score is a no-op (no-clobber — scores unchanged), (d) the helper returns 1 then 0. If the suite cannot reach a real DB, assert the helper builds the correct JSONB payload and calls `bulk_backfill_null_scores` (the raw `.update()` is gone).
- **Trigger-level check** (psql/Supabase SQL editor): on a copy of a stuck row, run `SELECT batch_backfill_null_scores('[{"game_uid":"<uid>","home_score":2,"away_score":1,"result":"W"}]'::jsonb);` → returns `1`, row updates, no `Cannot update immutable game` error, `is_immutable` remains `true`.
- **End-to-end** (only conclusive if GotSport has posted the score): on the branch, run `python scripts/process_missing_games.py --limit 5` after enqueuing team `645659`/`642491`, or trigger a scrape of that team; re-query game `6b70bd7a` → `home_score`/`away_score`/`result` non-null, `scraped_at` advanced past 2026-05-26, `is_immutable=true`.
- **Metric surfacing:** a pipeline run that backfills at least one row logs `scores_backfilled > 0`; force a failure (e.g., run before the migration applies) and confirm `scores_backfill_failed` is non-zero in the summary log and `to_dict()` output — i.e., the failure is no longer silent.
- **Regression guard:** confirm a normal scored-game insert (brand-new game_uid) is unaffected, and that a genuinely-final scored row cannot be mutated by the RPC (no-clobber selects it out).

## Context Files

- `src/etl/enhanced_pipeline.py` — `_update_null_score_games` (raw `.update()` to replace), the null_score_updates/true_dupes split + call site (lines ~735-756), `ImportMetrics` dataclass + `to_dict()` (lines 36-88, the durable metric sink), the provider-agnostic `PROGRESS UPDATE` log (~1053-1066, where the human-readable counter goes — NOT the Modular11-gated rollup at ~2595), and the `is_immutable: True` insert literal in `_bulk_insert_games`. **Has unrelated staged edits — see Setup hazard.**
- `src/etl/bulk_ops.py` — `call_rpc_with_fallback` and `bulk_update_last_scraped_at` (the template for the new helper) + error/chunk constants.
- `supabase/migrations/20240201000001_add_game_corrections.sql` — `apply_game_correction`: the toggle-off → write → toggle-on precedent to mirror.
- `supabase/migrations/20251125000000_add_batch_update_ml_overperformance.sql` — bulk JSONB `SECURITY DEFINER` RPC shape, return convention, and grant block to mirror.
- `supabase/migrations/20260309000000_restore_ml_bypass_in_immutability_trigger.sql` — the live `prevent_game_updates` trigger; Exception 1 is what permits the toggle sequence. Do not modify.
- `docs/superpowers/specs/2026-05-19-schedule-driven-scraping-design.md` — original design intent (lines 44, 47, 205-206) for why scheduled rows must be updatable.
- `scripts/process_missing_games.py` and `scripts/enqueue_yesterday_games.py` — the re-scrape/drain path that self-heals the backlog (verification + understanding only).
- `tests/test_enhanced_pipeline.py` — where the new test goes.
