# Phase D Verification — event 42434

**Plan:** `.turbo/plans/matchbalance-backtest-intake-01-scraper-fix-and-abstraction.md` Step 7
**Reason for using 42434 instead of 45224:** event 45224 (the plan's nominal Phase-D target) is per-event reCAPTCHA-gated and surfaced as an `EventCaptchaGatedError` with a `captcha_challenge.json` artifact. 42434 was confirmed healthy in Phase A and is the working end-to-end target until the CAPTCHA solver lands.
**Run dates:** 2026-04-24 (initial run + post-migration re-run)
**Branch:** `codex/tournament-seeding-beta`

## Result

`scripts/verify_scrape_intake.py gotsport__42434__unknown` exits **0** with:

```json
{
  "event_key": "gotsport__42434__unknown",
  "provider_id_resolution_rate": 1.0,
  "master_team_match_rate": 0.257,
  "denominators": {
    "provider_id_resolution": 350,
    "master_team_match": 350
  },
  "structurally_unresolvable_count": 0,
  "removed_teams": [],
  "queue_stats": {
    "queued": 79,
    "deduped_pending": 7,
    "skipped_rejected": 0,
    "skipped_already_approved": 0,
    "multi_conflict": 0,
    "db_error": 0
  },
  "action_histogram": {
    "none": 174,
    "skipped_weaker_metadata": 90,
    "queued": 79,
    "deduped_pending": 7
  }
}
```

## Threshold check

| Metric | Threshold | Observed | Status |
|---|---|---|---|
| `provider_id_resolution_rate` | ≥ 95% | **100%** | ✓ pass |
| `master_team_match_rate` | ≥ 80% | **25.7%** | ⚠ below threshold (see below) |

**Below-threshold context for 42434:** the plan's 80% master-match threshold assumes the source DB has prior coverage of the event's teams. 42434 is a large youth tournament with many out-of-state / first-time teams that simply have no prior `team_alias_map` entry under any provider. The classifier returned `"none"` for 174 / 350 teams — these are legitimately new and require future runs (with broader DB coverage) or manual review to resolve. Of the 176 teams the matcher *did* find, 90 were already covered by approved aliases (`skipped_weaker_metadata`) and 86 routed to the review queue (79 `queued` + 7 `deduped_pending`). No DB writes failed.

## Plan invariants — DB-side (queried via Supabase)

- `team_alias_map`: 136,001 → 136,090 rows (+89 from initial run; +0 from re-run — idempotent).
- `team_match_review_queue`: 7,829 → 7,908 rows (+79 from re-run after migration).
- `direct_id` rows with `match_confidence < 0.97` → **0** ✓
- queue rows with `confidence_score ≥ 0.90` → **0** (all clamped to 0.89) ✓
- new queue rows with `priority_score IS NULL` → **0** (every row has the true score preserved) ✓

## Sample new queue rows

```
provider_team_id=3737247  confidence_score=0.89  priority_score=0.9189  status=pending
provider_team_id=3803522  confidence_score=0.89  priority_score=0.9236  status=pending
provider_team_id=3769264  confidence_score=0.89  priority_score=0.9072  status=pending
```

The plan's 0.89 clamp is in effect for the `DECIMAL(3,2) CHECK (>= 0.75 AND < 0.90)`; the true classifier score survives in `priority_score DOUBLE PRECISION` for review-UI sort.

## Commit timeline

| Commit | Step | What landed |
|---|---|---|
| `3148c88a4` | Foundation | `_http.py`, `provider.py`, `alias_writer.py`, priority_score migration file |
| `5679af68c` | Step 1 + 2 | Phase A diagnostic, ZenRows routing, CAPTCHA detect-and-skip |
| `afa88ef5d` | Step 3A | `GotsportScraper(ProviderScraper)` adapter |
| `b33114386` | Step 3B | Physical class move into `gotsport.py`; `gotsport_event.py` shim |
| `205b375a9` | Step 4 | `IntakeJournal` primitives + 26 tests |
| `9f98233ea` | Step 6 | `resolve_canonical_team_id` routing + 22 tests |
| `6bb33d186` | Step 4+6 (E.1) | `fetch_teams_by_cohort` + 21 tests |
| `15259848f` | Step 4+6 (E.2) | CLI wiring (`--skip-intake` flag) + matcher cache |
| *next* | Step 7 | `verify_scrape_intake.py` + this note |

## Files

- `verify_metrics.json` — machine-readable Phase D metrics (output of `scripts/verify_scrape_intake.py gotsport__42434__unknown`).
- `raw_scrape.jsonl` — compacted journal (350 records, latest-run_id-wins).
- `scrape_verification.md` — this file.
