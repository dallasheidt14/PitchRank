# ETL & Scraping Pipeline Review

**Date:** 2026-03-10
**Scope:** Full review of ETL pipeline, scrapers, ranking data flow, and supporting utilities
**Goal:** Identify safe, incremental improvements that won't break existing functionality

---

## Executive Summary

The pipeline is **production-proven** — it handles 25K+ teams weekly, concurrent scraping, multi-provider ingestion, and a 13-layer ranking algorithm. The code is generally well-structured with good pagination, retry logic, and metrics tracking. The issues below are **improvement opportunities**, not showstoppers.

**Top 5 high-impact, low-risk improvements:**
1. Add pagination safety limits to prevent infinite loops
2. Add `asyncio.wait_for()` timeout on ranking gather calls
3. Fix cache invalidation key when merge_version is None
4. Batch `last_scraped_at` updates via RPC instead of per-team UPDATE
5. Add composite-key deduplication for cross-provider games

---

## 1. Resilience & Error Handling

### 1.1 Pagination loops lack safety limits

**Files:** `src/scrapers/base.py:86`, `src/etl/enhanced_pipeline.py:151`, `scripts/scrape_games.py:261`

All pagination loops use `while True` with a conditional break. If Supabase returns exactly `page_size` rows indefinitely (e.g., malformed response), the loop never terminates.

**Fix (safe):** Add a max-iterations guard:

```python
MAX_PAGES = 500  # 500K rows max
for page in range(MAX_PAGES):
    result = supabase.table(...).range(offset, offset + page_size - 1).execute()
    if not result.data or len(result.data) < page_size:
        break
    offset += page_size
else:
    logger.warning(f"Hit pagination safety limit ({MAX_PAGES} pages)")
```

### 1.2 No timeout on asyncio.gather() in ranking calculator

**File:** `src/rankings/calculator.py:476`

`pass1_results = await asyncio.gather(*pass1_tasks)` has no timeout. If one cohort hangs, the entire ranking run blocks forever (the GitHub Actions workflow has a 6-hour timeout, but that's a blunt instrument).

**Fix (safe):**
```python
pass1_results = await asyncio.wait_for(
    asyncio.gather(*pass1_tasks),
    timeout=3600  # 1 hour per pass
)
```

### 1.3 Silent cache failures in ranking calculator

**File:** `src/rankings/calculator.py:175-177, 200-202`

Cache load and save failures are silently swallowed. If cache is corrupted, the system falls through to recomputation without warning.

**Fix (safe):** Upgrade from silent to `logger.warning()`:
```python
except Exception as e:
    logger.warning(f"Cache load failed (will recompute): {e}")
```

### 1.4 State metadata fetch has no retry wrapper

**File:** `src/rankings/calculator.py:429-440`

Game fetches use `retry_supabase_query()` but state metadata fetches don't. If Supabase is temporarily unstable during the ranking run, SCF (Schedule Connectivity Factor) silently degrades.

**Fix (safe):** Wrap in the same `retry_supabase_query` decorator already used for game fetches.

### 1.5 Merge resolver silently defaults to empty on error

**File:** `src/utils/merge_resolver.py:107-111`

If Supabase is down during merge map load, the resolver silently operates with an empty map (version="error"). Deprecated teams then appear as canonical in rankings.

**Fix (safe):** Log at ERROR level and consider raising if this is a ranking calculation (not a scrape):
```python
except Exception as e:
    logger.error(f"CRITICAL: Merge map load failed, deprecated teams won't resolve: {e}")
    self._merge_map = {}
    self._version = "error"
```

---

## 2. Performance Improvements

### 2.1 Per-team last_scraped_at UPDATE is O(N) queries

**File:** `scripts/scrape_games.py:126-135`

After scraping, each team's `last_scraped_at` is updated individually. For 25K teams, that's 25K UPDATE queries.

**Fix (safe):** Create a Supabase RPC function for bulk timestamp updates:
```sql
CREATE OR REPLACE FUNCTION bulk_update_last_scraped(
    team_ids UUID[], scraped_at TIMESTAMPTZ
) RETURNS void AS $$
    UPDATE teams SET last_scraped_at = scraped_at
    WHERE team_id_master = ANY(team_ids);
$$ LANGUAGE sql;
```

Then call once per batch instead of per-team. This alone could save ~20 minutes on a 25K-team scrape run.

### 2.2 DataFrame concat in list comprehension (v53e)

**File:** `src/etl/v53e.py:738`

```python
g = pd.concat([clip_team_games(grp) for _, grp in g.groupby("team_id")]).reset_index(drop=True)
```

Creates N intermediate DataFrames before concatenation. For large datasets this causes memory spikes.

**Fix (safe):** Use `groupby().apply()`:
```python
g = g.groupby("team_id", group_keys=False).apply(clip_team_games).reset_index(drop=True)
```

### 2.3 Game matcher makes individual alias lookups

**File:** `src/models/game_matcher.py:846-875`

For teams not in the preloaded alias cache, individual Supabase queries are made. If the cache misses 1K teams, that's 1K round-trips.

**Fix (safe):** Collect all cache-miss team IDs, then batch-query:
```python
# Collect misses
missing_ids = [tid for tid in team_ids if tid not in self.alias_cache]
# Batch fetch in groups of 100
for batch in chunks(missing_ids, 100):
    result = self.db.table('team_alias_map').select(...).in_('provider_team_id', batch).execute()
```

### 2.4 Club name extraction makes extra API call per team

**File:** `src/scrapers/gotsport.py:301-321`

`_extract_club_name()` hits the GotSport API for every team, even if the club name is already known from the match response. With 25K teams, that's 25K extra HTTP requests.

**Fix (safe):** Check if club_name was already cached before making the API call:
```python
def _extract_club_name(self, team_id: int) -> str:
    cached = self.club_cache.get(str(team_id))
    if cached:
        return cached
    # ... existing API call
```

This is partially done (line 321 falls back to cache), but the API call is always attempted first. Invert the priority.

---

## 3. Data Quality & Validation

### 3.1 Cross-provider deduplication only uses game ID

**File:** `src/rankings/data_adapter.py:216-220`

Games are deduplicated by `id` column only. But the same real-world game can arrive via GotSport and TGS with different IDs.

**Fix (safe, additive):** Add a secondary deduplication pass using composite key:
```python
# After primary dedup by id
composite_key = ['game_date', 'home_team_master_id', 'away_team_master_id', 'goals_for', 'goals_against']
df = df.drop_duplicates(subset=composite_key, keep='first')
```

### 3.2 Age group validation in game imports

**File:** `src/models/game_matcher.py:650+`

No validation that home and away teams share the same age group and gender. A U13B vs U14G game would pass matching and create an invalid game record.

**Fix (safe, additive):** Add a post-match validation check:
```python
if matched_home.get('age_group') != matched_away.get('age_group'):
    logger.warning(f"Age group mismatch: {matched_home['age_group']} vs {matched_away['age_group']}")
    self.metrics.quarantined += 1
    continue
```

### 3.3 PowerScore bounds not enforced at save time

**File:** `scripts/calculate_rankings.py:514-523`

Out-of-bounds PowerScores are counted but not rejected. They get saved to the database.

**Fix (safe):** Clamp before saving:
```python
df['powerscore'] = df['powerscore'].clip(0.0, 1.0)
```

The v53e engine already does this internally, but a safety clamp at the save boundary prevents edge cases from ML Layer 13 adjustments.

### 3.4 Merge resolver doesn't detect circular references

**File:** `src/utils/merge_resolver.py:88-91`

If `team_merge_map` contains A→B and B→C, `resolve()` only resolves one level. Team A maps to B (deprecated), not to C (canonical).

**Fix (safe):** Add transitive resolution at load time:
```python
def _resolve_transitively(self):
    changed = True
    while changed:
        changed = False
        for k, v in list(self._merge_map.items()):
            if v in self._merge_map:
                self._merge_map[k] = self._merge_map[v]
                changed = True
```

---

## 4. Cache & State Management

### 4.1 Cache invalidation key doesn't distinguish None from "no_merges"

**File:** `src/rankings/calculator.py:148-154`

Cache key includes merge version only if `merge_version != "no_merges"`. But `merge_version = None` (when merge_resolver is None) produces the same key as "no_merges". After merges are loaded, stale cached rankings could be served.

**Fix (safe):**
```python
# Always include merge_version in hash, even if None
cache_key_parts = [str(lookback_days), str(merge_version)]
```

### 4.2 Alias cache in game_matcher never refreshes

**File:** `src/models/game_matcher.py:292-295`

The alias cache is populated once at init and never updated. In a long-running scrape (6 hours), new aliases created mid-run won't be reflected.

**Fix (safe):** Add a TTL-based refresh:
```python
def _maybe_refresh_cache(self):
    if time.time() - self._cache_loaded_at > 1800:  # 30 min TTL
        self._reload_alias_cache()
```

### 4.3 Club normalizer global state is not thread-safe

**File:** `src/utils/club_normalizer.py:625-629`

`_VARIATION_TO_CANONICAL` is built at module load and mutated by `add_canonical_club()`. In concurrent scraping with `asyncio.to_thread()`, this could cause race conditions.

**Fix (safe):** Use `threading.Lock` around mutations:
```python
_CANONICAL_LOCK = threading.Lock()

def add_canonical_club(name, variations):
    with _CANONICAL_LOCK:
        CANONICAL_CLUBS[name] = variations
        _rebuild_variation_map()
```

---

## 5. Logging & Observability

### 5.1 Error messages lack context for debugging

**File:** `src/rankings/calculator.py:70`

```
⚠️  Failed to fetch games at offset {offset} after retries...
```

Missing: which provider, which time window, which age group. Makes production debugging harder.

**Fix (safe):** Include context:
```python
logger.warning(f"Failed to fetch games at offset {offset} for {age_group}/{gender} "
               f"(window={lookback_days}d) after retries")
```

### 5.2 Debug logging leaks team IDs in production

**File:** `src/rankings/layer13_predictive_adjustment.py:229-238`

Extensive DEBUG logging with sample data values. In production with DEBUG enabled, this outputs team identifiers and game data.

**Fix (safe):** Gate behind config flag:
```python
if cfg.debug_mode:
    logger.debug(f"Sample features: {features_df.head()}")
```

### 5.3 Scrape status reporting

**File:** `scripts/scrape_games.py` (end of run)

The script logs total games scraped but doesn't report error rate, teams skipped, or duration per team. This makes it hard to detect slow degradation.

**Fix (safe, additive):** Add summary stats at end of run:
```python
console.print(f"Success rate: {success_count}/{total_teams} ({success_count/total_teams*100:.1f}%)")
console.print(f"Avg time per team: {total_duration/total_teams:.2f}s")
console.print(f"Error breakdown: {error_counter}")
```

---

## 6. Workflow & Orchestration

### 6.1 Scrape workflow doesn't notify on partial failure

**File:** `.github/workflows/scrape-games.yml:156-171`

The "Report results" step runs `if: always()` but only prints static info. It doesn't report success/failure counts from the actual scrape.

**Fix (safe):** Parse the scrape output for the machine-readable `IMPORT_RESULT` line:
```yaml
- name: Report results
  if: always()
  run: |
    if [ -f data/raw/scrape_summary.json ]; then
      cat data/raw/scrape_summary.json
    fi
```

### 6.2 No health check between scrape and ranking calculation

The Monday pipeline runs scraping at 6:00 AM and 11:15 AM, then rankings at 4:45 PM. If scraping fails silently, rankings run on stale data.

**Fix (safe, additive):** Add a pre-ranking validation step in `calculate-rankings.yml`:
```yaml
- name: Verify fresh data
  run: |
    python -c "
    from datetime import datetime, timedelta
    # Check that games table has records updated today
    # Fail if no recent scrape data found
    "
```

### 6.3 Concurrency group only covers game-scraping

**File:** `.github/workflows/scrape-games.yml:50-52`

The `game-scraping` concurrency group prevents overlapping scrape runs, but event scraping workflows (`auto-gotsport-event-scrape.yml`, `tgs-event-scrape-import.yml`) use separate concurrency groups. If both run simultaneously, they could create duplicate game records.

**Fix (safe):** Add a shared concurrency group for all data-writing workflows:
```yaml
concurrency:
  group: data-ingestion
  cancel-in-progress: false
```

---

## 7. Code Quality

### 7.1 Repeated pagination boilerplate

**Files:** `src/scrapers/base.py:86-100`, `src/etl/enhanced_pipeline.py:151-163`, `scripts/scrape_games.py:261-274` (6+ locations)

The same `while True / range / break` pagination pattern is copy-pasted across the codebase.

**Fix (safe):** Extract to a shared utility:
```python
# src/utils/supabase_helpers.py
def paginate_query(query_builder, page_size=1000, max_pages=500):
    """Paginate a Supabase query, yielding batches."""
    for page in range(max_pages):
        offset = page * page_size
        result = query_builder.range(offset, offset + page_size - 1).execute()
        if result.data:
            yield result.data
        if not result.data or len(result.data) < page_size:
            break
```

### 7.2 Column name inconsistency between v53e and Supabase formats

**File:** `src/rankings/layer13_predictive_adjustment.py:258-269, 479-487`

Layer 13 has multiple fallback chains for column names (`date` vs `game_date`, `team_id` vs `team_id_master`). This creates fragile detection logic.

**Fix (safe):** Define a canonical column schema at the data adapter boundary and enforce it:
```python
CANONICAL_COLUMNS = {
    'game_date': ['date', 'game_date', 'match_date'],
    'team_id': ['team_id', 'team_id_master', 'home_team_master_id'],
}
```

### 7.3 Dead legacy parameters in v53e

**File:** `src/etl/v53e.py:226-240`

Hardcoded legacy recency parameters (`RECENT_K=15`, `RECENT_SHARE=0.65`) are marked "no longer drive behavior" but still exist. Dead code adds confusion.

**Fix (safe):** Remove deprecated parameters or move behind a `LEGACY_MODE` flag for backward compatibility testing.

---

## 8. Quick Wins (< 30 min each)

| # | Fix | File | Risk | Impact |
|---|-----|------|------|--------|
| 1 | Add `MAX_PAGES` guard to all pagination loops | Multiple | None | Prevents infinite loops |
| 2 | Add `asyncio.wait_for()` timeout to gather calls | calculator.py | None | Prevents hung ranking runs |
| 3 | Fix cache key to include `None` merge_version | calculator.py | None | Prevents stale cache hits |
| 4 | Clamp PowerScore at save boundary | calculate_rankings.py | None | Prevents out-of-bounds scores |
| 5 | Invert club_name cache check in GotSport | gotsport.py | None | Saves ~25K HTTP requests/run |
| 6 | Upgrade silent `except` to `logger.warning` | calculator.py, merge_resolver.py | None | Improves debuggability |
| 7 | Add context to ranking error messages | calculator.py | None | Faster production debugging |
| 8 | Add transitive merge resolution | merge_resolver.py | Low | Fixes chain merges |

---

## 9. Scraper-Specific Issues

### 9.1 Timezone date-shift in GotSport match parsing

**File:** `src/scrapers/gotsport.py:373-382`

```python
if 'T' in match_date:
    dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
    if dt.tzinfo is not None:
        game_date = dt.astimezone(timezone.utc).date()
```

A game at `2025-11-07T23:00:00-04:00` (Eastern) converts to `2025-11-08` in UTC. This shifts the game to the wrong date, which affects the recency decay calculation and could cause duplicate detection to miss matches.

**Fix (safe):** Use the local date from the original timezone, not UTC:
```python
game_date = dt.date()  # Use local date, not UTC-converted date
```

### 9.2 Silent `except: pass` in match sort

**File:** `src/scrapers/gotsport.py:183-186`

```python
try:
    matches.sort(key=lambda m: m.get('match_date') or '', reverse=True)
except Exception:
    pass
```

If `match_date` is corrupted across records, the sort silently fails and games process in arbitrary order. The early-exit optimization (line 207) then breaks — it could stop at a random game instead of the oldest.

**Fix (safe):** Log the failure:
```python
except Exception as e:
    logger.warning(f"Match sort failed for team {normalized_team_id}, processing unsorted: {e}")
```

### 9.3 Empty opponent_id passes validation

**File:** `src/scrapers/gotsport.py:408`

```python
opponent_id = str(opponent.get('team_id', ''))  # Could be empty string ''
```

An empty string passes the truthiness check in `_game_data_to_dict()` (base.py:59). The game gets imported with `opponent_id=''`, which later fails silently during team matching.

**Fix (safe):** Validate before returning:
```python
opponent_id = opponent.get('team_id')
if not opponent_id:
    logger.debug(f"No opponent_id for match, skipping")
    return None
```

### 9.4 SincSports HTML selector fragility

**File:** `src/scrapers/sincsports.py:245-259`

HTML scraping uses CSS selectors with no fallback. If SincSports changes their HTML structure, the scraper silently returns empty results instead of failing visibly.

**Fix (safe):** Add a structure validation check:
```python
if not soup.select('.schedule-row'):
    logger.error(f"No schedule rows found — HTML structure may have changed")
    raise ValueError("SincSports HTML structure mismatch")
```

### 9.5 Inconsistent home/away perspective across providers

**File:** `src/scrapers/athleteone_scraper.py:175-217` vs `src/scrapers/sincsports.py:427`

AthleteOne creates **two** GameData objects per game (home + away perspectives). SincSports creates **one** (hardcoded `home_away='H'`). GotSport creates one from the scraped team's perspective.

This inconsistency means AthleteOne games get double-weighted in rankings unless the ETL pipeline deduplicates perspectives. The enhanced pipeline does handle this (via `duplicates_skipped` metric), but there's no validation that perspective dedup actually fired.

**Fix (safe, additive):** Add a provider-level assertion in the import pipeline:
```python
if provider == 'athleteone':
    expected_perspective_ratio = 2.0  # ~2 records per real game
    actual_ratio = total_records / unique_games
    if actual_ratio < 1.5:
        logger.warning(f"AthleteOne perspective ratio {actual_ratio:.1f} < expected 2.0")
```

### 9.6 GotSport event timeout env var not read by code

**File:** `.github/workflows/auto-gotsport-event-scrape.yml` sets `GOTSPORT_EVENT_TIMEOUT=240` but `src/scrapers/gotsport_event.py` never reads this env var.

**Fix (safe):** Add to event scraper init:
```python
self.per_event_timeout = int(os.getenv('GOTSPORT_EVENT_TIMEOUT', '240'))
```

### 9.7 TGS event range is hardcoded

**File:** `.github/workflows/tgs-event-scrape-import.yml:35-36`

```yaml
DEFAULT_START_EVENT='4050'
DEFAULT_END_EVENT='4150'
```

Only covers 100 event IDs. If TGS adds events beyond this range, they're silently skipped.

**Fix (safe):** Make the range dynamic or at least wider, and log when the range is exhausted:
```yaml
DEFAULT_END_EVENT='5000'  # Wider range with early-exit on 404s
```

### 9.8 Modular11 workflow schedule is disabled

**File:** `.github/workflows/modular11-weekly-scrape.yml:4-11`

The `schedule:` trigger is commented out. MLS NEXT games update frequently but rely on manual dispatch only.

**Fix (safe):** Re-enable the schedule or document why it was disabled.

---

## Summary

The pipeline is solid for its scale. The improvements above are all **additive or isolated** — none require restructuring the pipeline architecture. Priority order:

1. **Safety guards** (pagination limits, timeouts) — prevent runaway processes
2. **Cache fixes** (merge key, alias TTL) — prevent stale data in rankings
3. **Performance** (bulk updates, batch queries) — reduce scrape runtime by ~20%
4. **Data quality** (composite dedup, age validation) — improve ranking accuracy
5. **Observability** (logging context, error summaries) — faster incident response
