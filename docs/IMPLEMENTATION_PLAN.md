# Implementation Plan: Matcher & Import Pipeline Improvements

> **Scope:** GotSport (base matcher) and TGS only. Modular11 is untouched.
> **Branch:** `claude/map-pipeline-improve-matchers-VvT2P`

---

## Execution Order Rationale

Changes flow **bottom-up**: shared utilities first (everything depends on them), then the matchers that consume them, then the pipeline that orchestrates everything. Each phase is independently testable.

---

## Phase 1: Shared Utilities — Foundation Layer

These are consumed by both GotSport and TGS matchers, the hygiene scripts, and the pipeline. Getting them right first means every downstream consumer improves automatically.

### 1.1 Upgrade `src/utils/team_name_utils.py` — Add Coach Name Detection + Token Joining

**What changes:**
- Add `extract_team_variant()` function ported from `find_queue_matches.py:153-297` with the full coach name detection algorithm (exclusion sets for common_words, region_codes, program_names)
- Add the 3 exclusion sets as module-level constants (shared with hygiene scripts)
- Update `extract_distinctions()` to include a `coach_name` field (10th distinction) populated by the new `extract_team_variant()`
- Update `should_skip_pair()` to check coach_name mismatch → hard reject
- Add multi-word token joining in `normalize_name_for_matching()`: join "ECNL"+"RL" → "ECNL RL", "MLS"+"NEXT" → "MLS NEXT", "Pre"+"ECNL" → "Pre-ECNL" BEFORE stripping league markers (ported from `team_name_normalizer.py:173-222`)

**Files modified:**
- `src/utils/team_name_utils.py`

**Why this order:** Everything downstream (both matchers, hygiene scripts) imports from this file. Coach name detection prevents the most dangerous false merges. Token joining fixes compound term splitting that currently causes ECNL RL teams to match ECNL-only teams.

### 1.2 Upgrade `src/utils/team_name_utils.py` — Improve Club Extraction

**What changes:**
- Port the word-deduplication logic from `find_queue_matches.py:127-135` into `extract_club_from_team_name()` — catches providers sending "Kingman SC Kingman SC"
- Add minimum length guard (skip club names < 3 chars) from `find_queue_matches.py:141`
- Expand the trailing suffix strip list to match `find_queue_matches.py:106-119` (add ACADEMY, SELECT, PREMIER, ELITE, PRE, COMP, GA, MLS NEXT)

**Files modified:**
- `src/utils/team_name_utils.py`

**Why this order:** Club extraction feeds into the club-filtered candidate query. Better extraction = better candidate narrowing = fewer false matches.

### 1.3 Upgrade `src/utils/club_normalizer.py` — Conservative Suffix Canonicalization

**What changes:**
- Add `normalize_club_conservative()` function that canonicalizes suffixes WITHOUT stripping: "Soccer Club" → "SC", "Football Club" → "FC", "F.C." → "FC" (ported from `full_club_analysis.py:58-85`)
- Use this as the fallback in `normalize_to_club()` when no canonical registry match is found (currently it just uppercases the normalized form)
- This prevents "FC Arkansas" from matching "Arkansas Soccer Club" (prefix FC ≠ suffix SC)

**Files modified:**
- `src/utils/club_normalizer.py`

**Why this order:** Club comparison is 35% of the match score. Making it more accurate has outsized impact.

### 1.4 Integrate `parse_age_gender()` as Shared Age Parser

**What changes:**
- Add a `parse_age_token()` function to `team_name_utils.py` that wraps `team_name_normalizer.parse_age_gender()` — this becomes the single source of truth for age parsing
- Import and use it in `normalize_name_for_matching()` for the age normalization step (replacing the current regex-only approach that misses formats like BU14, 15M, G2014)
- This handles all 12+ age format combinations that `parse_age_gender()` supports

**Files modified:**
- `src/utils/team_name_utils.py`

**Why this order:** Age parsing feeds into both normalization and distinction extraction. Using the most robust parser everywhere eliminates format mismatches.

---

## Phase 2: Base Matcher — GotSport Improvements

The base `GameHistoryMatcher` is used for GotSport (the primary data source). These changes improve match quality and speed for all GotSport imports.

### 2.1 Swap `SequenceMatcher` for `rapidfuzz` in `_calculate_similarity()`

**What changes:**
- Replace `SequenceMatcher(None, str1, str2).ratio()` with `rapidfuzz.fuzz.token_sort_ratio(str1, str2) / 100.0` in `game_matcher.py:1035-1046`
- `token_sort_ratio` handles word reordering ("Solar SC" vs "Dallas Solar") which `SequenceMatcher` scores poorly
- Add `rapidfuzz` import with graceful fallback to `SequenceMatcher` if not installed (matching the pattern already used in `club_normalizer.py`)
- Verify `rapidfuzz` is in `requirements.txt` (it's already a dependency via club_normalizer)

**Files modified:**
- `src/models/game_matcher.py` (method `_calculate_similarity`, lines 1035-1046)

**Why this order:** This is the single biggest quality improvement. Every fuzzy match score calculation goes through this method. Better similarity = fewer false matches + fewer missed true matches.

### 2.2 Add Gated Candidate Funnel (Pre-Score Filtering)

**What changes:**
- Restructure `_fuzzy_match_team()` (lines 871-1033) to implement a 3-stage funnel BEFORE scoring:
  - **Gate 1 (existing):** Club-filtered DB query (already implemented, lines 919-926)
  - **Gate 2 (new):** Variant gate — extract variant from provider name, skip candidates with different variant (ported from affinity matcher pattern)
  - **Gate 3 (existing but move earlier):** Distinction check — currently at lines 964-993 inside the scoring loop, move to a pre-filter step before `_calculate_match_score()` is called
- When club-filtered query returns candidates, do NOT fall back to the broad 5000-candidate query. The fallback should only trigger when club extraction itself fails (club_name is None).
- This reduces unnecessary scoring of candidates that would be rejected anyway.

**Files modified:**
- `src/models/game_matcher.py` (method `_fuzzy_match_team`, lines 871-1033)

**Why this order:** Depends on Phase 1.1 (coach name in variants) and 1.2 (better club extraction). Reduces compute time and false positives simultaneously.

### 2.3 Add Club+Variant Boost to Scoring

**What changes:**
- In `_calculate_match_score()` (lines 1071-1147), add a club+variant combined boost:
  - If club matches (similarity ≥ 0.8) AND variant matches exactly → add +0.15 (on top of existing club_boost of 0.10, total = 0.25)
  - This is the pattern from the affinity matcher's `club_variant_match_boost` but with a more conservative value for GotSport
- Add config key `club_variant_match_boost` to `MATCHING_CONFIG` in `config/settings.py` (default 0.15)

**Files modified:**
- `src/models/game_matcher.py` (method `_calculate_match_score`, lines 1071-1147)
- `config/settings.py` (add to `MATCHING_CONFIG`)

**Why this order:** Depends on Phase 1.1 (variant extraction). Club+variant is a strong match signal that helps disambiguate within-club teams.

### 2.4 Add Deterministic Tie-Breaking

**What changes:**
- In `_fuzzy_match_team()`, when two candidates have the same score (within 0.001), use a 3-tuple tiebreaker instead of arbitrary first-wins:
  1. Variant match (exact color/direction/coach)
  2. Birth year token match
  3. Strong club match (similarity ≥ 0.95)
- Ported from affinity matcher's deterministic tie-breaking pattern

**Files modified:**
- `src/models/game_matcher.py` (method `_fuzzy_match_team`)

**Why this order:** After scoring improvements (2.1-2.3), ties become more meaningful. Deterministic selection prevents flaky match results across runs.

### 2.5 Add Confidence Ceiling + Age Validation

**What changes:**
- In `_create_alias()` (lines 1149-1205), cap fuzzy match confidence at 0.99: `confidence = min(0.99, confidence)` for any `match_method` that isn't `direct_id`
- In `_match_team()`, add age validation: parse age from team_name using `parse_age_token()` (Phase 1.4) and compare against the `age_group` parameter. If they conflict (e.g., name says "B14" = birth year 2014 = U12 but parameter says U14), log a warning and prefer the name-parsed age.

**Files modified:**
- `src/models/game_matcher.py` (methods `_create_alias`, `_match_team`)

**Why this order:** Confidence ceiling is a data quality guard. Age validation catches provider mislabeling that currently causes cross-age-group matches.

---

## Phase 3: TGS Matcher Improvements

The TGS matcher has its own normalization and scoring overrides. These need to be aligned with the improved base without breaking TGS-specific logic.

### 3.1 Unify TGS Normalization with Shared Utilities

**What changes:**
- `_normalize_team_name()` override (lines 130-192) has TGS-specific dash-stripping and suffix removal that duplicates shared logic. Refactor to:
  1. First apply TGS-specific pre-processing (strip before first dash — this is unique to TGS)
  2. Then delegate to the shared `normalize_name_for_matching()` for everything else
  3. Remove the duplicated suffix/prefix removal lists (lines 165-187) — these are now handled by the shared function
- This ensures TGS benefits from Phase 1 improvements (token joining, better age parsing) automatically

**Files modified:**
- `src/models/tgs_matcher.py` (method `_normalize_team_name`, lines 130-192)

**Why this order:** Depends on Phase 1 (shared utilities must be upgraded first). Unifying normalization means TGS gets coach name detection, token joining, and robust age parsing for free.

### 3.2 Align TGS Club Boost with Base Improvements

**What changes:**
- `_calculate_match_score()` override (lines 194-475) has its own club normalization with state abbreviation expansion. Refactor to:
  1. Use `club_normalizer.normalize_to_club()` for canonical club comparison (replacing the internal `normalize_club_for_match_internal` function)
  2. Keep the TGS-specific age token overlap check (lines 449-473) — this is valuable
  3. Add the club+variant boost from Phase 2.3 (alongside the existing club+age boost)
  4. Use `rapidfuzz.token_sort_ratio` from Phase 2.1 (instead of duplicating the SequenceMatcher call)

**Files modified:**
- `src/models/tgs_matcher.py` (method `_calculate_match_score`, lines 194-475)

**Why this order:** Depends on Phases 1.3 and 2.1. Routes all club comparisons through the canonical registry. Keeps TGS's valuable age-token-overlap logic.

### 3.3 Add Gated Funnel to TGS Fuzzy Match

**What changes:**
- `_fuzzy_match_team()` override (lines 477-543) currently scores ALL candidates from the broad age+gender query. Add the same gated funnel from Phase 2.2:
  - Gate 1: Club-filtered query first (TGS currently doesn't do this — it queries all teams for age+gender)
  - Gate 2: Variant gate
  - Gate 3: Distinction filter (before scoring)
- This is especially important for TGS because it queries broadly and has a lower threshold (0.75)

**Files modified:**
- `src/models/tgs_matcher.py` (method `_fuzzy_match_team`, lines 477-543)

**Why this order:** Depends on Phase 2.2 (pattern established in base). TGS benefits even more because its broad query returns more candidates.

---

## Phase 4: Pipeline-Level Improvements

Changes to the orchestration layer that improve reliability and catch errors earlier.

### 4.1 Add Supabase Connection Resilience

**What changes:**
- In `enhanced_pipeline.py`, add periodic Supabase client refresh during long imports:
  - Track game count, refresh client every 1000 games processed
  - Pattern: `self.supabase = create_client(url, key)` + update `self.matcher.db = self.supabase`
  - Add retry wrapper with exponential backoff for transient Supabase errors (ported from `find_queue_matches.py:525-544`)
- Also pass the refresh to the matcher so its DB reference stays current

**Files modified:**
- `src/etl/enhanced_pipeline.py` (import_games loop, ~lines 332-436)

**Why this order:** Independent of matcher changes. Fixes production timeout issues on 10k+ game imports.

### 4.2 Apply Hygiene-Style Normalization Before Matching

**What changes:**
- In `import_games()` (lines 343-380), before calling `self.matcher.match_game_history(game)`:
  1. Run `parse_age_gender()` on the team name to validate/correct the `age_group` field (ported from `find_queue_matches.py:299-334`)
  2. If name-parsed age differs from metadata `age_group`, log a warning and use the name-parsed age
  3. Normalize club_name through `normalize_to_club()` before passing to the matcher — this means the matcher sees canonical club names instead of raw provider variants
- This bridges the gap between "what the hygiene pipeline normalizes offline" and "what the real-time matcher sees"

**Files modified:**
- `src/etl/enhanced_pipeline.py` (import_games, ~lines 332-380)

**Why this order:** Depends on Phase 1.4 (parse_age_token available). This is the "apply hygiene at import time" pattern from the affinity matcher.

### 4.3 Route All Club Comparisons Through Canonical Registry

**What changes:**
- In `_calculate_match_score()` (base matcher, lines 1094-1121), simplify the club comparison cascade:
  - Remove the 3-level fallback (normalize_to_club → normalize_club_for_comparison → SequenceMatcher)
  - Always use `normalize_to_club()` first. If both resolve to canonical IDs, compare IDs (1.0 or 0.0).
  - If either doesn't resolve to canonical, use `similarity_score()` from club_normalizer (which uses token_set_ratio)
  - Remove the separate `normalize_club_for_comparison()` path entirely — it's now redundant
- Same change in TGS matcher's override

**Files modified:**
- `src/models/game_matcher.py` (method `_calculate_match_score`)
- `src/models/tgs_matcher.py` (method `_calculate_match_score`)

**Why this order:** Depends on Phase 1.3 (improved club_normalizer). Eliminates duplicate club comparison logic across 3 code paths.

---

## Phase 5: Config Updates + Hygiene Script Alignment

### 5.1 Update `config/settings.py` with New Config Keys

**What changes:**
- Add to `MATCHING_CONFIG`:
  ```python
  'club_variant_match_boost': 0.15,       # Boost when club AND variant both match
  'fuzzy_confidence_ceiling': 0.99,        # Max confidence for fuzzy matches
  'age_validation_from_name': True,        # Parse age from name to validate metadata
  'connection_refresh_interval': 1000,     # Refresh Supabase client every N games
  ```

**Files modified:**
- `config/settings.py`

### 5.2 Update Hygiene Scripts to Import from Shared Utils

**What changes:**
- `find_queue_matches.py` and `find_fuzzy_duplicate_teams.py` currently define their own `extract_team_variant()`, `normalize_team_name()`, etc.
- After Phase 1 upgrades `team_name_utils.py`, update the hygiene scripts to import from it instead of defining their own:
  - `from src.utils.team_name_utils import extract_team_variant, normalize_name_for_matching, extract_distinctions, should_skip_pair`
- This ensures the hygiene scripts and real-time matchers use identical logic (currently they diverge)

**Files modified:**
- `scripts/find_queue_matches.py`
- `scripts/find_fuzzy_duplicate_teams.py`

**Why this order:** After all shared utilities are upgraded (Phase 1). Closes the loop: hygiene and real-time matching use the same code.

### 5.3 Add Unit Tests for New Shared Utilities

**What changes:**
- Add test file `tests/test_team_name_utils_improvements.py` with:
  - Coach name extraction tests (Riedell, Davis, Thompson, Holohan)
  - Token joining tests (ECNL + RL, MLS + NEXT, Pre + ECNL)
  - Club extraction with deduplication ("Kingman SC Kingman SC")
  - Age parsing via parse_age_token() (all 12+ formats)
  - Variant extraction tests (colors, directions, coach names, roman numerals)
  - Distinction comparison tests (should_skip_pair with coach_name field)
- Add test file `tests/test_matcher_improvements.py` with:
  - rapidfuzz vs SequenceMatcher comparison on known problematic pairs
  - Gated funnel tests (verify bad candidates are eliminated before scoring)
  - Club+variant boost tests
  - Confidence ceiling tests
  - Tie-breaking tests

**Files created:**
- `tests/test_team_name_utils_improvements.py`
- `tests/test_matcher_improvements.py`

---

## Summary: Execution Order

```
Phase 1 (Foundation — no matcher changes yet)
  1.1  team_name_utils: coach name detection + token joining
  1.2  team_name_utils: club extraction improvements
  1.3  club_normalizer: conservative suffix canonicalization
  1.4  team_name_utils: integrate parse_age_gender()

Phase 2 (Base Matcher — GotSport)
  2.1  game_matcher: swap SequenceMatcher → rapidfuzz
  2.2  game_matcher: gated candidate funnel
  2.3  game_matcher: club+variant boost
  2.4  game_matcher: deterministic tie-breaking
  2.5  game_matcher: confidence ceiling + age validation

Phase 3 (TGS Matcher)
  3.1  tgs_matcher: unify normalization with shared utils
  3.2  tgs_matcher: align club boost with canonical registry
  3.3  tgs_matcher: add gated funnel

Phase 4 (Pipeline)
  4.1  enhanced_pipeline: connection resilience
  4.2  enhanced_pipeline: hygiene-style normalization before matching
  4.3  game_matcher + tgs_matcher: route all club comparisons through registry

Phase 5 (Config + Tests + Alignment)
  5.1  settings.py: new config keys
  5.2  hygiene scripts: import from shared utils
  5.3  tests: unit tests for all improvements
```

## Risk Assessment

| Phase | Risk | Mitigation |
|-------|------|------------|
| 1.1 | Coach name false positives (mascots detected as coaches) | Use the hygiene script's exclusion sets (300+ words). Test against production team names. |
| 2.1 | rapidfuzz scores differ from SequenceMatcher → threshold shifts | Run both algorithms on production data, compare score distributions. Adjust thresholds if needed. |
| 2.2 | Gated funnel too aggressive → misses valid matches | Keep the broad fallback when club extraction fails (club_name is None). Log gate rejections for monitoring. |
| 3.1 | TGS dash-stripping interacts badly with shared normalization | Test with known TGS team names (e.g., "Folsom Lake Surf- FLS 13B Premier I"). Keep TGS pre-processing as first step. |
| 4.2 | Age from name disagrees with metadata → wrong age group used | Only override metadata when name-parsed age is high-confidence. Log all overrides for review. |

## Not In Scope

- Modular11 matcher (explicitly excluded per user request)
- Affinity WA matcher (already optimized, serves as pattern source only)
- Rankings engine (v53e.py) — no changes
- Database schema changes — all changes work with existing tables
- Frontend — no changes
