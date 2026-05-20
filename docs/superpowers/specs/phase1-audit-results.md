# Phase 1 Audit Results — NULL-Score Guard

## Task 1.5: Rankings NULL-score guard

**Status: CONFIRMED — Option A**

Rankings NULL-score guard: confirmed at `src/rankings/data_adapter.py:205-206`.
Query filters with `.not_.is_("home_score", "null").not_.is_("away_score", "null")`.

### Layers of protection (deepest-first)

| Layer | Location | Predicate |
|-------|----------|-----------|
| SQL query (primary) | `data_adapter.py:205-206` | `.not_.is_("home_score","null") .not_.is_("away_score","null")` in `fetch_games_for_rankings` |
| Date upper bound (secondary) | `data_adapter.py:199-202` | `.lte("game_date", today_date_str)` — future-dated rows excluded even if scores were somehow non-NULL |
| Python post-filter (tertiary) | `data_adapter.py:589` | `v53e_df.dropna(subset=["gf", "ga"])` in `supabase_to_v53e_format` |
| View layer (independent) | `supabase/migrations/20250125000000_add_sos_norm_state_to_views.sql:56-91` | `AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL` (SOS sub-views) |

### Conclusion

Future-dated NULL-score rows persisted by Phase 1 (`spec/schedule-driven-scraping`) **cannot reach Glicko-2 input**. The primary SQL filter plus date upper bound block them at fetch time; `dropna` catches any residuals. No code change required.

A regression guard test is at `tests/unit/test_ranking_null_score_guard.py`.

---

## Task 1.6: games.result derivation

**Status: DONE — Outcome B (patched)**

### Column definition

`games.result` is `CHAR(1)` with `CHECK (result IN ('W', 'L', 'D', 'U'))` and is **nullable** (no NOT NULL constraint). Defined at `supabase/migrations/20240101000000_initial_schema.sql:71`. No generated column expression; no trigger that derives it from scores.

### Mechanism

Result is **pipeline-set** — the scraper computes it from scores and places it in the game dict. It flows to the DB via `enhanced_pipeline.py:1856` as `"result": game.get("result")` (passes through whatever value is in the dict).

### NULL-score behavior (before patch)

Two defects caused `result = "U"` instead of `NULL` for scheduled (NULL-score) games:

| Location | Defect |
|---|---|
| `src/scrapers/gotsport.py:822` | `_determine_result` returned `"U"` when either score was `None` |
| `src/scrapers/base.py:62` | `_game_data_to_dict` coerced `None` → `"U"` via `game.result or "U"` |
| `scripts/process_missing_games.py:223` (and 8 sibling scripts) | Same `game.result or "U"` pattern in standalone script dict construction |

A `"U"` value satisfies the CHECK constraint so inserts succeed, but it misleads downstream consumers into treating scheduled games as played-but-result-unknown rather than unplayed.

### Action taken

Patched all three defect sites:

- **`src/scrapers/gotsport.py`** — `_determine_result` now returns `None` (not `"U"`) when scores are NULL. Return type widened to `Optional[str]`.
- **`src/scrapers/base.py`** — `_game_data_to_dict` now uses `game.result if game.result in ("W", "L", "D") else None` to accept only valid values and treat everything else (including `"U"` and `None`) as NULL.
- **9 standalone scripts** (`scripts/scrape_*.py`, `scripts/process_missing_games.py`) — same `game.result or "U"` → `game.result if game.result in ("W", "L", "D") else None` substitution.

### Verification

No existing NULL-score rows in production yet (Phase 1 not yet deployed). Schema allows NULLs (no NOT NULL constraint), so inserts of scheduled rows with `result=NULL` will succeed.

Sample from production (5 rows + NULL-score query):
```
{'game_uid': 'gotsport:2025-01-26:114511:281444', 'game_date': '2025-01-26', 'home_score': 0, 'away_score': 14, 'result': 'L'}
{'game_uid': 'tgs:2024-11-23:...', 'game_date': '2024-11-23', 'home_score': 4, 'away_score': 1, 'result': 'W'}
{'game_uid': 'gotsport:2026-04-08:...', 'game_date': '2026-04-08', 'home_score': 7, 'away_score': 0, 'result': 'W'}
{'game_uid': 'gotsport:2024-11-24:...', 'game_date': '2024-11-24', 'home_score': 5, 'away_score': 6, 'result': 'W'}
{'game_uid': 'gotsport:2025-01-04:...', 'game_date': '2025-01-04', 'home_score': 3, 'away_score': 2, 'result': 'W'}
--- NULL home_score rows ---
(empty — no scheduled games in DB yet)
```
