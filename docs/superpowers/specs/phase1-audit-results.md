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
