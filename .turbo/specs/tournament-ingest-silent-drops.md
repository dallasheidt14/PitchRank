# Tournament-Schedule Ingest: Surface Silent Failures, Stop Score Clobber

> **Empirically rescoped 2026-04-29.** A query against `build_logs` for
> recent SincSports `game_import` runs ([data](../diagnostics/tournament-ingest-bucket-data.md))
> overturned the prior version of this spec. Buckets always sum to
> `games_processed` (drift = 0). The "440 vanished" was always
> `failed_games_count` — exposed in `IMPORT_RESULT` JSON but hidden from
> the rich-console summary. Most of the prior spec's infrastructure was
> solving problems not present in the data. The history of that pass lives
> in `.turbo/specs/council-tournament-ingest-iter3.md`.

## Problem

`scripts/import_games_enhanced.py` shows operators a misleading rich-console
summary: when `failed_games_count > 0`, records appear to vanish because
the rich-console shows only 5 of 9 input-consuming counters. The
machine-readable `IMPORT_RESULT:<json>` line already reports the missing
counters correctly.

Separately, when SincSports tournament-schedule re-ingest hits a game
already imported by the deprecated per-team `games.aspx` route with
different scores, `enhanced_pipeline.py:759` routes the record to
`_update_games_with_scores()` and clobbers the per-team scores. User
preference: skip-on-match (no UPDATE) for SincSports tournament source.

The schedule.aspx scraper also emits U08 and U09 division codes, which are
below PitchRank's u10 ranking floor. Today they fail at the matcher's
auto-create gate (missing `age_group` at top level); after the rich-console
fix, they would surface as a noisy `failed_match` count.

## Empirical baseline (Puri Cup TZ2565, 2026-04-25 12:24 run)

- 441 records emitted by schedule.aspx scraper
- 171 accepted, 224 already-in-DB duplicates_found, 45 failed_match,
  1 perspective dup
- Buckets sum exactly. `teams_created = 0` in every run — auto-create
  path is not firing successfully.

## The fix (PR 1 of 2)

**(1) Rich-console summary extension** — `scripts/import_games_enhanced.py:580-616`

Add the 4 input-consuming counters that are currently hidden:
`failed_games_count`, `skipped_empty_provider_ids`, `skipped_empty_game_date`,
`skipped_empty_scores`, `duplicate_key_violations`. Show non-zero only.
~10 lines.

**(2) Provider-gated score-UPDATE skip** — `enhanced_pipeline.py:759`

Add a top-level `source: "sincsports_tournament_schedule"` field in
`scripts/scrape_sincsports_tournament_schedule.py::perspective_record()`.
At the score-UPDATE branch (line 759), guard:

```python
if game.get("source") == "sincsports_tournament_schedule":
    # Tournament schedule re-ingest — skip on match, no clobber
    logger.info(f"[Pipeline] Skipping score UPDATE for tournament re-ingest: {game_uid}")
    continue
```

`source` must reach the matched `game_record` so line 759 sees it. Three
small touches:
- `perspective_record()` emits `source` at top level
- `match_game_history` (`game_matcher.py`, around line 670-683 where
  `game_record` is built) copies `game_data.get("source")` into the
  matched record
- Phase 3 guard at `enhanced_pipeline.py:759` reads it

Other providers (Modular11, GotSport, etc.) keep current
UPDATE-on-score-diff behavior unchanged.

**(3) Sub-U10 scraper filter** — `scripts/scrape_sincsports_tournament_schedule.py`

Filter records whose `division_code` matches `^U0[89]` before JSONL emit.
Add a `--include-sub-u10` flag (default `False`) for future use. Log the
filtered count to stderr. Rationale: PitchRank rankings are u10+ by
design; sub-u10 games would not contribute to ranking even if imported,
and they currently inflate `failed_match` once age_group is lifted.

**(4) Surface the 45-record alias gap** — narrow follow-up

Run 5's 45 failed-match records are real. Add a one-shot diagnostic
script (`scripts/diagnose_failed_matches.py`) that queries the JSONL plus
`team_alias_map` and lists the 45 teams with no SincSports alias. Decide
between seeding aliases (manual or scripted) or accepting as a documented
known limitation. **This is investigation, not code change.**

## Constraints

- **No bucket-arithmetic invariant code.** Empirically buckets sum
  (drift=0); the invariant is solving a non-existent problem. If we want
  guard-rails against future drift, log the sum at end-of-run and warn if
  drift != 0; do not raise.
- **No `PITCHRANK_DIAGNOSTIC` interceptor.** The empirical query against
  `build_logs` already provides the disposition data needed; no in-pipeline
  diagnostic mode required for this PR.
- **No `parse_sincsports_division_code` helper.** Sub-U10 records are
  filtered at the scraper; the existing pipeline normalization handles
  the rest. If age/gender lift to top level is needed for the 45 alias
  gap (per item 4), add it then with the smallest possible parser.
- **Reuse existing patterns.** No new abstractions; in-place patches only.

## Validation

- Re-ingest Puri Cup raw file. Expect Run 5's pattern: ~171 accepted,
  ~224 duplicates_found, ~45 failed_match. Rich console now shows all
  three counts plainly.
- For one previously-imported Puri Cup game with different scraper-side
  scores (if any exist), confirm `goals_for` / `goals_against` in the DB
  remain unchanged after the re-ingest. (If no such game exists, this
  test passes vacuously.)
- Sub-U10 records do not appear in the JSONL output of the scraper.

## What this fix does NOT do

- Land the 45 still-failing records. That's item (4) — investigation only,
  may become a follow-up PR.
- Build the auto-create path for new SincSports tournament teams.
  `teams_created=0` in every run; the matcher's auto-create branch isn't
  firing. Investigation in item (4) decides whether to fix that here or
  punt to PR 2.
- Restructure the metrics contract or aggregator. The data shows it's
  already correct end-to-end.

## Out of scope

- Bucket-sum invariant + TerminalDisposition ledger (data shows no need).
- `PITCHRANK_DIAGNOSTIC` env flag + Supabase write interceptor.
- `alias_cache` freeze in diagnostic mode.
- `parse_sincsports_division_code` helper.
- Per-batch trace JSONL infrastructure.
- `watchy_health_check` threshold updates (the `missing_club` threshold
  is dead code per memory; `missing_state` change isn't load-bearing here).
- Refactor of triplicated `_create_new_*_team` autocreate (separate
  improvements.md item, 2026-04-21).
- PR 2 (SincSports re-scrape via aliases after team merges) — independent.
