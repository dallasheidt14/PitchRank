# PitchRank Pipeline Process Map

> Comprehensive plain-English map of the scraping, ETL pipeline, team matching, fuzzy matching, and game matching systems.

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Layer 1: Data Sources & Scraping](#2-layer-1-data-sources--scraping)
3. [Layer 2: Pipeline Orchestration (ETL)](#3-layer-2-pipeline-orchestration-etl)
4. [Layer 3: Team Matching (The Heart of the System)](#4-layer-3-team-matching-the-heart-of-the-system)
5. [Layer 4: Fuzzy Matcher Deep-Dive](#5-layer-4-fuzzy-matcher-deep-dive)
6. [Layer 5: Game Matching & Deduplication](#6-layer-5-game-matching--deduplication)
7. [Layer 6: Rankings & Predictions](#7-layer-6-rankings--predictions)
8. [Supporting Systems](#8-supporting-systems)
9. [Weekly Data Hygiene Pipeline](#9-weekly-data-hygiene-pipeline)
10. [Affinity WA Matcher (Optimization Pattern)](#10-affinity-wa-matcher-optimization-pattern)
11. [Improvement Opportunities (Fuzzy & Game Matcher)](#11-improvement-opportunities-fuzzy--game-matcher)
12. [Deep Analysis: Hygiene Script Patterns for Real-Time Matcher Improvement](#12-deep-analysis-hygiene-script-patterns-for-real-time-matcher-improvement)

---

## 1. High-Level Overview

```
 DATA SOURCES              ETL PIPELINE                    DATABASE              OUTPUT
 ────────────             ──────────────                  ──────────            ────────
 GotSport API  ──┐
 Modular11 Web ──┤     ┌──────────────────┐           ┌────────────┐
 TGS/AthleteOne─┤────▶│  Enhanced ETL     │──────────▶│  Supabase  │────▶ Rankings
 SincSports   ──┤     │  Pipeline         │           │  (Postgres)│────▶ Predictions
 SurfSports   ──┘     │                   │           │            │────▶ Frontend
                       │  1. Validate      │           │  Tables:   │
                       │  2. Match Teams   │           │  - games   │
                       │  3. Match Games   │           │  - teams   │
                       │  4. Deduplicate   │           │  - aliases │
                       │  5. Insert        │           │  - reviews │
                       └──────────────────┘           └────────────┘
```

**The one-sentence summary:** We scrape soccer game results from multiple websites, normalize the messy team names into canonical team identities using a multi-tier matching system, deduplicate games, store them in a database, and then calculate power rankings.

---

## 2. Layer 1: Data Sources & Scraping

### 2.1 Data Providers

| Provider | Code | How We Get Data | What We Get |
|----------|------|-----------------|-------------|
| **GotSport** | `gotsport` | REST API (`system.gotsport.com/api/v1`) | Team schedules, scores, club IDs, event data |
| **Modular11** | `modular11` | Scrapy web scraper | Event schedules, division-based game results |
| **TGS/AthleteOne** | `tgs` | AthleteOne API client | Team schedules with club names embedded in team names |
| **SincSports** | `sincsports` | Web scraper | Tournament brackets, scores |
| **SurfSports** | `surfsports` | Web scraper | Tournament results |

### 2.2 Scraper Architecture

**File locations:**
- `src/scrapers/base.py` — Base scraper class all providers inherit from
- `src/scrapers/gotsport.py` — GotSport API scraper (primary source)
- `src/scrapers/gotsport_event.py` — Event-specific GotSport scraper
- `src/scrapers/athleteone_scraper.py` + `athleteone_html_parser.py` — TGS data via AthleteOne
- `src/scrapers/sincsports.py` — SincSports scraper
- `src/scrapers/surfsports.py` — SurfSports scraper
- `scrapers/modular11_scraper/` — Full Scrapy project for Modular11

**What each scraper produces:**
Every scraper outputs a list of game dictionaries with fields like:
```python
{
    'team_id': '544491',           # Provider's team ID
    'team_name': 'FC Dallas 2014 Blue ECNL',
    'club_name': 'FC Dallas',      # Sometimes provided, sometimes not
    'opponent_id': '387241',
    'opponent_name': 'Solar SC 2014 Gold',
    'goals_for': 3,
    'goals_against': 1,
    'home_away': 'H',
    'game_date': '2025-03-15',
    'age_group': 'u14',
    'gender': 'Male',
    'competition': 'ECNL Boys',
    'event_name': 'Regular Season',
    'provider': 'gotsport'
}
```

**Key scraping details:**
- GotSport uses HTTP session pooling (100 concurrent connections) with SSL via certifi
- Optional ZenRows proxy for anti-bot bypass
- Rate limiting: 1.5-2.5 second random delays between requests
- Retry logic: 3 attempts with exponential backoff on 500/502/503/504 errors

### 2.3 Data Formats by Provider

| Format Aspect | GotSport | Modular11 | TGS |
|---------------|----------|-----------|-----|
| Team identifier | Numeric team ID | Club ID (shared across age groups!) | Unique team ID |
| Club name | Separate field | Embedded in team name | Embedded with dash separator |
| Age format | `u14` | `u14` or `U14` | Birth year `2012` |
| Game perspective | Single (team vs opponent) | Single (team vs opponent) | Home/away already split |

---

## 3. Layer 2: Pipeline Orchestration (ETL)

### 3.1 Entry Points

**Weekly automation** (`scripts/weekly/update.py`):
```
Step 1: Scrape games → Step 2: Import games → Step 3: Calculate rankings
```

**Direct import** (`scripts/import_games_enhanced.py`):
- Reads CSV/JSONL files
- Streams data in batches (default 2000 games per batch)
- Supports concurrency (4 parallel batch processors)
- Checkpoint/resume capability

### 3.2 Enhanced ETL Pipeline (`src/etl/enhanced_pipeline.py`)

This is the main workhorse. On initialization it:

1. **Looks up provider UUID** from the `providers` table (with retry logic)
2. **Pre-flight health check** — verifies Supabase can read AND write before processing
3. **Preloads the entire alias cache** — paginates through ALL approved aliases (1000 rows per page) to build an in-memory lookup dictionary
4. **Selects the correct matcher** based on provider:
   - `modular11` → `Modular11GameMatcher` (ultra-conservative)
   - `tgs` → `TGSGameMatcher` (aggressive fuzzy)
   - Everything else → `GameHistoryMatcher` (balanced)

### 3.3 The `import_games()` Flow (per batch)

```
  ┌───────────────────────────────────────────────────────────┐
  │                    import_games(games)                     │
  │                                                           │
  │  Step 1: VALIDATE                                         │
  │    ├─ Check for valid dates (YYYY-MM-DD format)           │
  │    ├─ Check for valid scores (both must be numeric)       │
  │    ├─ Generate game_uid (deterministic from provider +    │
  │    │   date + sorted team IDs — NO scores in UID)         │
  │    ├─ Skip games with empty provider IDs                  │
  │    ├─ Normalize gender ("Boys"→"Male", "Girls"→"Female")  │
  │    └─ Convert birth year to age_group if needed           │
  │                                                           │
  │  Step 2: CHECK DUPLICATES                                 │
  │    ├─ Check game_uid against existing games in DB         │
  │    └─ (Don't filter yet — game_uid doesn't include scores)│
  │                                                           │
  │  Step 3: MATCH TEAMS (for each game)                      │
  │    ├─ Match home team → _match_team()                     │
  │    ├─ Match away team → _match_team()                     │
  │    ├─ Classify: 'matched' / 'partial' / 'failed'         │
  │    └─ Build game_record for DB insertion                  │
  │                                                           │
  │  Step 4: DEDUPLICATE                                      │
  │    ├─ Build composite key (provider + teams + date +      │
  │    │   scores) matching DB unique constraint              │
  │    └─ Filter out games already in DB                      │
  │                                                           │
  │  Step 5: BULK INSERT                                      │
  │    ├─ Insert matched games to `games` table               │
  │    ├─ Handle duplicate key violations gracefully          │
  │    └─ Log metrics and build summary                       │
  └───────────────────────────────────────────────────────────┘
```

### 3.4 Metrics Tracked

The pipeline tracks these metrics per import batch (in `ImportMetrics`):
- `games_processed` / `games_accepted` / `games_quarantined`
- `duplicates_found` / `duplicates_skipped`
- `teams_matched` / `teams_created`
- `fuzzy_matches_auto` / `fuzzy_matches_manual` / `fuzzy_matches_rejected`
- `matched_games_count` / `partial_games_count` / `failed_games_count`
- `duplicate_key_violations`

---

## 4. Layer 3: Team Matching (The Heart of the System)

### 4.1 The Matching Cascade

When a game arrives and we need to identify which master team it belongs to, we follow this cascade:

```
  INCOMING GAME: team_name="FC Dallas 2014 Blue ECNL", provider_team_id="544491"
         │
         ▼
  ┌─────────────────────────────────────────────────────┐
  │  Strategy 1: DIRECT PROVIDER ID (highest priority)   │
  │                                                       │
  │  Check alias cache → Check DB team_alias_map          │
  │  for exact match on (provider_id, provider_team_id)   │
  │                                                       │
  │  Also checks semicolon-separated IDs for merged teams │
  │  e.g., "123456;789012" contains "123456"              │
  │                                                       │
  │  For Modular11: MUST validate age_group because same  │
  │  club ID is used for U13, U14, U16 etc.               │
  │  For TGS: Skip age validation (IDs are unique/team)   │
  │                                                       │
  │  If found → return {matched: true, confidence: 1.0}   │
  └──────────────────────────┬──────────────────────────┘
                             │ Not found
                             ▼
  ┌─────────────────────────────────────────────────────┐
  │  Strategy 2: ALIAS MAP LOOKUP                        │
  │                                                       │
  │  Check team_alias_map by provider_team_id OR          │
  │  by team_name (case-insensitive ILIKE)                │
  │                                                       │
  │  Validates age_group and gender match                 │
  │                                                       │
  │  If found with confidence ≥ 0.90 → return matched    │
  └──────────────────────────┬──────────────────────────┘
                             │ Not found
                             ▼
  ┌─────────────────────────────────────────────────────┐
  │  Strategy 3: FUZZY MATCHING                          │
  │  (requires team_name + age_group + gender)           │
  │                                                       │
  │  See "Fuzzy Matcher Deep-Dive" section below          │
  │                                                       │
  │  Outcomes:                                            │
  │  ├─ Score ≥ 0.90 → AUTO-APPROVE                      │
  │  │   Create alias, return matched                     │
  │  ├─ Score 0.75–0.90 → REVIEW QUEUE                   │
  │  │   Insert to team_match_review_queue, NOT matched   │
  │  ├─ Score < 0.75 → LOW CONFIDENCE REVIEW              │
  │  │   Still queue for review with suggestion            │
  │  └─ No match at all → REVIEW QUEUE (no suggestion)    │
  └──────────────────────────┬──────────────────────────┘
                             │
                             ▼
  ┌─────────────────────────────────────────────────────┐
  │  Modular11 & TGS ONLY: CREATE NEW TEAM               │
  │                                                       │
  │  If no match found and we have team_name + age_group  │
  │  + gender, create a new team in the `teams` table     │
  │  and auto-create an alias. Return {matched: true}.    │
  └─────────────────────────────────────────────────────┘
```

### 4.2 Provider-Specific Matchers

#### Base Matcher (`GameHistoryMatcher` in `src/models/game_matcher.py`)
- Used for: GotSport and default providers
- Thresholds: fuzzy=0.75, auto_approve=0.90, review=0.75
- Uses structured distinction-based hard rejection + weighted scoring
- Does NOT create new teams (puts unmatched into review queue)

#### Modular11 Matcher (`Modular11GameMatcher` in `src/models/modular11_matcher.py`)
- Used for: Modular11 data
- **Ultra-conservative** — designed to avoid false matches
- Thresholds: minimum confidence=0.93, minimum gap=0.07 between best and 2nd-best
- Age-strict: validates birth year matches age_group (U14 → 2012)
- Division-aware: HD vs AD matching bonus/penalty
- Token overlap requirement: must share at least one meaningful token
- Creates new teams when no confident match found

#### TGS Matcher (`TGSGameMatcher` in `src/models/tgs_matcher.py`)
- Used for: TGS/AthleteOne data
- **More aggressive** — designed to match more teams
- Thresholds: fuzzy=0.75, auto_approve=0.91, review=0.70
- Special handling: strips club name prefix before dash (e.g., "Folsom Lake Surf- FLS 13B" → "FLS 13B")
- Club match boost: +0.25 if club matches AND age tokens overlap, +0.18 if club only
- Skips age_group validation on provider ID matches (TGS IDs are unique per team)
- Creates new teams when no match found

### 4.3 The Alias System

**Database table: `team_alias_map`**

| Column | Purpose |
|--------|---------|
| `provider_id` | Which provider (UUID) |
| `provider_team_id` | Provider's team identifier |
| `team_id_master` | Our canonical team UUID |
| `match_method` | How it was matched: `direct_id`, `fuzzy_auto`, `import`, etc. |
| `match_confidence` | Score 0.0–1.0 |
| `review_status` | `approved`, `pending`, `rejected` |

**Critical design choice:** The alias cache is preloaded into memory at pipeline startup and updated after every successful match. Without this, the same team would be fuzzy-matched repeatedly within a single import batch, potentially creating duplicate master teams and fragmenting game history.

**Semicolon-separated IDs:** Merged teams store multiple provider IDs as "123456;789012". The cache expands these so both "123456" and "789012" can find the same master team.

---

## 5. Layer 4: Fuzzy Matcher Deep-Dive

### 5.1 Algorithm Stack

The fuzzy matcher uses a **layered scoring approach**, not a single algorithm:

```
  INCOMING: "FC Dallas 2014 Blue ECNL" (age_group=u14, gender=Male)
         │
         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 1: EXTRACT CLUB NAME                       │
  │                                                    │
  │  If no club_name provided, extract from team_name  │
  │  by splitting on age/year pattern:                 │
  │    "FC Dallas 2014 Blue ECNL" → "FC Dallas"       │
  │                                                    │
  │  Uses: extract_club_from_team_name()               │
  │  File: src/utils/team_name_utils.py:336            │
  └──────────────────────┬─────────────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 2: EXTRACT STRUCTURAL DISTINCTIONS          │
  │                                                    │
  │  Decompose team name into 9 features:              │
  │    colors:      {"blue"}                           │
  │    directions:  {}                                 │
  │    programs:    {"ecnl"}                            │
  │    team_number: None                               │
  │    location_codes: {}                              │
  │    state_codes: {}                                 │
  │    squad_words: {}                                 │
  │    age_tokens:  ("14", "2014")                     │
  │    secondary_nums: ()                              │
  │                                                    │
  │  Uses: extract_distinctions()                      │
  │  File: src/utils/team_name_utils.py:110            │
  └──────────────────────┬─────────────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 3: RETRIEVE CANDIDATES FROM DATABASE        │
  │                                                    │
  │  First try: club-filtered query                    │
  │    SELECT * FROM teams                             │
  │    WHERE age_group='u14' AND gender='Male'         │
  │    AND club_name ILIKE 'FC Dallas'                 │
  │    LIMIT 50                                        │
  │                                                    │
  │  If no results: paginated broad query              │
  │    Fetch ALL teams for this age_group + gender     │
  │    (1000 per page, up to 5000 candidates)          │
  └──────────────────────┬─────────────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 4: FOR EACH CANDIDATE — HARD REJECTION      │
  │                                                    │
  │  Compare structural distinctions:                  │
  │  ✗ Colors differ? (Red ≠ Blue) → SKIP             │
  │  ✗ Directions differ? (North ≠ South) → SKIP      │
  │  ✗ Programs differ? (Academy ≠ ECNL) → SKIP       │
  │  ✗ Team numbers differ? (I ≠ II) → SKIP           │
  │  ✗ Location codes differ? (SM ≠ HB) → SKIP        │
  │  ✗ Squad words differ? (Bolts ≠ Clash) → SKIP     │
  │                                                    │
  │  This prevents EVER matching two teams from the    │
  │  same club that are actually different squads.     │
  │                                                    │
  │  Uses: should_skip_pair() / distinction comparison │
  │  File: src/utils/team_name_utils.py:222            │
  └──────────────────────┬─────────────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 5: WEIGHTED COMPONENT SCORING               │
  │                                                    │
  │  Score = (team_sim × 0.35)                         │
  │        + (club_sim × 0.35)                         │
  │        + (age_match × 0.10)                        │
  │        + (location_match × 0.10)                   │
  │        + club_boost (0.10 if club_sim ≥ 0.8)      │
  │                                                    │
  │  team_sim: SequenceMatcher on normalized names     │
  │  club_sim: Canonical registry lookup OR            │
  │            suffix-normalized comparison OR          │
  │            token_set_ratio (rapidfuzz/difflib)     │
  │  age_match: 0.10 if exact match, else 0.0         │
  │  location: 0.10 if state codes match, else 0.0    │
  │                                                    │
  │  Config: config/settings.py:176-189                │
  └──────────────────────┬─────────────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 6: LEAGUE BOOST / PENALTY                   │
  │                                                    │
  │  Both have ECNL RL?  → +0.05 boost                │
  │  Both have ECNL only? → +0.05 boost               │
  │  One RL, other not?  → -0.08 penalty              │
  │                                                    │
  │  File: src/models/game_matcher.py:1004-1019        │
  └──────────────────────┬─────────────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────────┐
  │  STEP 7: SELECT BEST MATCH                        │
  │                                                    │
  │  Return highest-scoring candidate ≥ threshold      │
  │  (0.75 for base, 0.93 for Modular11)              │
  └──────────────────────────────────────────────────┘
```

### 5.2 Name Normalization Pipeline

Before comparing two team names, both go through normalization (`_normalize_team_name()` → `normalize_name_for_matching()`):

1. Lowercase and strip whitespace
2. Strip league/tier markers: `ECNL-RL`, `ECNL`, `MLS NEXT`, `GA`, `RL`, `NPL`, `DPL`, etc.
3. Replace dashes with spaces
4. Normalize age formats: `B14` → `14`, `G2014` → `2014`, `U-14` → `u14`
5. Remove punctuation (except apostrophes in names like O'Brien)
6. Remove standalone gender words: `boys`, `girls`, `male`, `female`
7. Compress whitespace

**Example:**
```
"FC Dallas - ECNL B2014 Blue Boys"
  → "fc dallas 2014 blue"
```

### 5.3 Club Name Normalization (`src/utils/club_normalizer.py`)

Separate from team name normalization, club names go through:

1. Basic cleaning (lowercase, strip, remove artifacts like `...`)
2. Remove age group suffixes (U13, 2012 Boys, etc.)
3. Remove punctuation
4. Expand city abbreviations: `PHX` → `Phoenix`, `SD` → `San Diego`
5. (Optional) Strip suffixes: `FC`, `SC`, `Soccer Club`

**Canonical Club Registry:** 100+ clubs with known variations:
```python
'PHOENIX RISING': ['phoenix rising', 'phx rising', 'prfc', 'pr fc', ...]
'FC DALLAS': ['fc dallas', 'dallas fc', 'fcd', 'fcdallas', ...]
'ALBION SC': ['albion sc', 'albion', 'albion soccer club']
```

**Matching cascade:**
1. Normalize input → try exact lookup against all variations
2. If no exact match → fuzzy match using `token_set_ratio` (threshold 0.85)
3. If still no match → use normalized form with 0.8 confidence

### 5.4 The Scoring Algorithms

**Primary: `SequenceMatcher` (Python difflib)**
- Used for: team name similarity, club name similarity (when no canonical match)
- Algorithm: Longest common subsequence ratio
- File: `src/models/game_matcher.py:1046`

**Secondary: `rapidfuzz` (with difflib fallback)**
- Used for: club canonical registry matching
- Algorithms available: `ratio`, `partial_ratio`, `token_set_ratio`
- `token_set_ratio` handles word reordering (best for club names)
- File: `src/utils/club_normalizer.py:23-89`

**Tertiary: Structural distinction comparison**
- Not a scoring algorithm — used for hard rejection only
- Binary: if any distinction differs → reject, period
- File: `src/utils/team_name_utils.py:110-250`

### 5.5 Thresholds Summary

| Context | Threshold | What Happens |
|---------|-----------|-------------|
| Base auto-approve | ≥ 0.90 | Auto-link + create alias |
| Base review queue | 0.75 – 0.90 | Queue for human review |
| Base minimum | < 0.75 | Low-confidence review or no match |
| Modular11 minimum | ≥ 0.93 | Accept match |
| Modular11 gap | ≥ 0.07 | Between best and 2nd best candidate |
| TGS auto-approve | ≥ 0.91 | Auto-link |
| TGS minimum fuzzy | ≥ 0.75 | Accept match |
| TGS review | ≥ 0.70 | Queue for review |
| Club boost trigger | ≥ 0.80 club sim | +0.10 bonus |
| ECNL/RL match | both same | +0.05 bonus |
| ECNL/RL mismatch | one has, other doesn't | -0.08 penalty |

---

## 6. Layer 5: Game Matching & Deduplication

### 6.1 Game UID Generation

Every game gets a deterministic UID that does NOT include scores:

```python
game_uid = f"{provider}:{game_date}:{sorted_team1_id}:{sorted_team2_id}"
# Example: "gotsport:2025-03-15:3841:4719"
```

**Why no scores?** The same game reported from two different perspectives (team A vs team B, and team B vs team A) should have the same UID. Scores are the same regardless of perspective.

**Why sorted team IDs?** So `teamA:teamB` and `teamB:teamA` produce the same UID.

### 6.2 Composite Key (for true deduplication)

The database has a unique constraint matching:
```
(provider_id, home_provider_id, away_provider_id, game_date,
 COALESCE(home_score, -1), COALESCE(away_score, -1))
```

This means the same game with different scores (e.g., a correction) would be treated as a different record.

### 6.3 Perspective-Based Deduplication

Many providers report games from BOTH teams' perspectives. The pipeline:
1. Generates game_uid (perspective-independent thanks to sorted IDs)
2. Checks if this game_uid already exists in DB
3. If it does but scores differ → proceeds to team matching (composite key will catch true duplicates)
4. If it does and scores match → skips as duplicate

### 6.4 The `match_game_history()` Flow

```python
# Two formats supported:

# Format A: Source format (team perspective)
# Has: team_id, opponent_id, goals_for, goals_against, home_away
# → Determines home/away based on home_away flag
# → Matches both team and opponent

# Format B: Transformed format (already home/away)
# Has: home_team_id, away_team_id, home_score, away_score
# → Matches home team and away team directly
```

**Output match statuses:**
- `matched` — both home and away teams identified
- `partial` — only one team identified (the other goes to review queue)
- `failed` — neither team identified

---

## 7. Layer 6: Rankings & Predictions

After games are imported and teams are matched:

### 7.1 Rankings Engine (`src/etl/v53e.py` + `src/rankings/calculator.py`)

A 13-layer ranking system:
1. Window filter (365 days)
2. Game cap + goal diff cap + outlier guard
3. Recency weighting (recent 15 games weighted 65%)
4. Defense ridge
5. Adaptive K-factor
6. Performance adjustment
7. Bayesian shrinkage
8. Strength of Schedule (SOS)
9. Opponent-adjusted offense/defense
10. Final powerscore blend (Off 25% + Def 25% + SOS 50%)
11. Cross-age anchoring
12. Normalization (percentile-based)
13. ML predictive adjustment (XGBoost + Random Forest)

### 7.2 Match Predictor (`src/predictions/ml_match_predictor.py`)

Uses rankings to predict game outcomes (win/loss/draw probabilities).

---

## 8. Supporting Systems

### 8.1 Review Queue (`team_match_review_queue` table)

When fuzzy matching can't confidently identify a team, it enters the review queue:
- `provider_id` — which provider
- `provider_team_id` — their team ID
- `provider_team_name` — the raw team name
- `suggested_master_team_id` — fuzzy matcher's best guess (can be null)
- `confidence_score` — how confident the fuzzy matcher was
- `status` — `pending`, `approved`, `rejected`

### 8.2 Club Normalizer Skill (`agent_skills/pitchrank-club-normalizer/`)

An agent skill that normalizes raw club+team names into canonical identifiers, producing CSV output with: `club_id`, `club_norm`, `birth_year`, `gender`, `tier`, `branch`.

### 8.3 Merge System (`src/utils/merge_resolver.py` + `merge_suggester.py`)

Handles merging duplicate teams that were created before proper alias matching was in place.

### 8.4 Database Schema (Supabase/Postgres)

Key tables:
- `providers` — Provider registry (gotsport, modular11, tgs, etc.)
- `teams` — Master team records (team_id_master, team_name, club_name, age_group, gender)
- `games` — Game records (game_uid, home/away teams, scores, dates)
- `team_alias_map` — Maps provider team IDs to master team IDs
- `team_match_review_queue` — Unmatched teams awaiting human review
- `build_logs` — Pipeline run tracking and metrics

---

## 9. Weekly Data Hygiene Pipeline

### 9.1 Overview

**Workflow:** `.github/workflows/data-hygiene-weekly.yml`
**Schedule:** Every Tuesday 10:00 AM MST (17:00 UTC)
**Total timeout:** 180 minutes

The hygiene pipeline is a 4-step post-import cleanup that runs AFTER games are imported. It normalizes the DB state so that the real-time import matchers have cleaner candidates to match against. The steps have strict ordering dependencies.

### 9.2 The Four Steps (in order)

```
 ┌────────────────────────────────────────────────────────────┐
 │  Step 1: CLUB NAME STANDARDIZATION                         │
 │  Script: scripts/full_club_analysis.py                     │
 │                                                            │
 │  Fixes two types of problems in the teams.club_name col:   │
 │  • CAPS issues: "solar sc" vs "Solar SC" → picks majority │
 │  • Suffix variations: "Solar Soccer Club" → "Solar SC"     │
 │                                                            │
 │  Normalization: "Soccer Club"→"SC", "Football Club"→"FC"   │
 │  Preserves leading prefixes: "FC Dallas" ≠ "Dallas SC"     │
 │                                                            │
 │  WHY FIRST: Club names must be clean before team names     │
 │  are normalized, or team matching in Step 3 fails.         │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ┌────────────────────────────────────────────────────────────┐
 │  Step 2: NORMALIZE TEAM NAMES                              │
 │  Script: scripts/normalize_team_names.py                   │
 │                                                            │
 │  Normalizes team_name column across DB:                    │
 │  • Birth year formats: '12B' → '2012', '14B' → '2014'     │
 │  • Age group formats: 'U14B' → 'U14'                      │
 │  • Strips gender words: "2014 Boys Black" → "2014 Black"   │
 │  • Preserves squad identifiers (colors, coach names, etc.) │
 │  • Backs up original as team_name_original                 │
 │  • Only processes teams where team_name_original IS NULL   │
 │    (never re-processes)                                    │
 │                                                            │
 │  Uses direct Postgres (psycopg2) for speed, Supabase REST  │
 │  as fallback.                                              │
 │                                                            │
 │  WHY SECOND: Normalized names needed for fuzzy matching.   │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ┌────────────────────────────────────────────────────────────┐
 │  Step 3: FUZZY DUPLICATE MERGE                             │
 │  Script: scripts/find_fuzzy_duplicate_teams.py             │
 │                                                            │
 │  Finds and merges duplicate teams within the same club.    │
 │  Runs for ALL age groups (u10-u19) × selected genders.     │
 │                                                            │
 │  Algorithm:                                                │
 │  • Groups teams by state (only compare within state)       │
 │  • O(n²) pairwise comparison within each state group       │
 │  • Requirements for merge:                                 │
 │    1. Same club_name (exact match)                         │
 │    2. All distinctions match (extract_distinctions())       │
 │       - colors, directions, programs, team_number,         │
 │         location_codes, squad_words, age_tokens,           │
 │         secondary_nums, state_codes                        │
 │    3. No protected division (AD, HD, MLS NEXT, EA)         │
 │    4. Variant match (coach name, color, direction)         │
 │    5. Fuzzy score ≥ 0.85 (SequenceMatcher + boosts)       │
 │                                                            │
 │  Scoring: SequenceMatcher(normalized_a, normalized_b)      │
 │    + 0.15 if club_name matches exactly                     │
 │    + 0.05 if both ECNL-RL or both ECNL-only               │
 │    - 0.08 if ECNL/RL mismatch                             │
 │                                                            │
 │  Canonical selection: keeps team with club_name in         │
 │  team_name, mixed case, and longest name.                  │
 │                                                            │
 │  WHY THIRD: Fewer duplicates = fewer orphan queue entries. │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 ┌────────────────────────────────────────────────────────────┐
 │  Step 4: MATCH REVIEW QUEUE                                │
 │  Script: scripts/find_queue_matches.py                     │
 │                                                            │
 │  Processes team_match_review_queue entries that failed      │
 │  real-time matching during import.                         │
 │                                                            │
 │  For each pending entry:                                   │
 │  1. Extract club from provider_team_name                   │
 │  2. Parse age_group from name (not metadata — unreliable!) │
 │  3. Extract variant (color/direction/coach/roman numeral)  │
 │  4. Query candidates by gender + age + club + state        │
 │  5. Score via SequenceMatcher + club/league boosts         │
 │  6. CRITICAL: variant must match EXACTLY                   │
 │                                                            │
 │  Categorization:                                           │
 │  • EXACT (≥95%): Auto-approvable → creates alias          │
 │  • HIGH (90-94%): Likely safe (--include-high to approve)  │
 │  • MEDIUM (80-89%): Review recommended                     │
 │  • LOW (70-79%): Manual review needed                      │
 │  • NO MATCH (<70%): Needs new team creation                │
 │                                                            │
 │  Auto-merge: caps confidence at 0.99 in alias table,       │
 │  upserts on (provider_id, provider_team_id) conflict.      │
 └────────────────────────────────────────────────────────────┘
```

### 9.3 Shared Code Pattern

All hygiene scripts share these imports from `find_queue_matches.py`:
- `normalize_team_name()` — strips league markers, normalizes age, removes gender
- `extract_team_variant()` — color/direction/coach/roman numeral extraction
- `has_protected_division()` — AD, HD, MLS NEXT, EA detection
- `extract_club_from_name()` — splits team name on age pattern, strips suffixes

The core distinction extraction logic in `find_fuzzy_duplicate_teams.py` was later ported INTO the real-time matchers as `team_name_utils.extract_distinctions()` — the hygiene scripts are the original source of this optimization.

### 9.4 Key Design Insight: Hygiene Improves Real-Time Matching

The hygiene pipeline creates a feedback loop:
1. Import runs → some teams fail to match → go to review queue
2. Hygiene runs → normalizes names, merges duplicates, resolves queue
3. Next import → newly-created aliases + cleaner candidates = better match rate

---

## 10. Affinity WA Matcher (Optimization Pattern)

**File:** `src/models/affinity_wa_matcher.py` (branch: `affinity-wa-matcher-hardening`)
**Config:** `config/settings.py` → `MATCHING_CONFIG` affinity-specific keys

### 10.1 What It Is

The `AffinityWAGameMatcher` is the newest provider-specific matcher for **Washington Youth Soccer** data from `sctour.sportsaffinity.com`. It follows the pattern established by Modular11 and TGS matchers but introduces several optimizations worth porting to other matchers.

### 10.2 Key Optimizations Introduced

**A. Hygiene-style normalization at match time (not just offline)**

The biggest insight: the hygiene pipeline normalizes DB names (B14→2014, etc.) but incoming provider names still use the raw format. The affinity matcher applies the SAME normalization to incoming names BEFORE comparing:

```python
# _normalize_for_affinity_wa():
# B14 → 2014, G15 → 2015  (birth year expansion)
# XF → Crossfire            (club abbreviation expansion)
# WHT → White, BLK → Black  (color abbreviation expansion)
# Remove U-age labels        (formatting noise)
```

This means provider names and DB names are comparing apples-to-apples instead of "B14 Red" vs "2014 Red".

**B. Gated candidate selection (3-stage funnel)**

Instead of scoring all candidates and filtering after, the affinity matcher ELIMINATES bad candidates early through gates:

```
All WA teams for age+gender
      │
      ▼ Stage 1: Club gate
      │  are_same_club(provider_club, candidate_club, threshold=0.9)
      │  → Eliminates candidates from wrong clubs BEFORE scoring
      │
      ▼ Stage 2: Variant gate
      │  extract_team_variant(provider) == extract_team_variant(candidate)
      │  → Color/direction/coach mismatch = immediate reject
      │
      ▼ Stage 2b: RCL lane gate (domain-specific)
      │  _extract_rcl_number(provider) == _extract_rcl_number(candidate)
      │  → RCL 3 must NOT match RCL 2 (different competitive tiers)
      │
      ▼ Only surviving candidates get scored
```

**C. Post-match RCL rejection**

Even after the base matcher returns a fuzzy match, the affinity matcher double-checks: if the matched team has a different RCL number, it REJECTS the match and creates a new team instead. This prevents the most dangerous failure mode (merging teams from different competitive levels).

**D. Club+variant boost (+0.35)**

When the club AND variant both match, applies a strong +0.35 boost (configurable as `club_variant_match_boost`). This means "B14 Red" correctly matches "Eastside FC 2014 Red" even though the team names look very different, because the club is the same and the variant (Red) is the same.

**E. Deterministic tie-breaking**

When two candidates score equally, uses a 3-tuple tiebreaker:
1. Variant match (exact color/direction/coach)
2. Birth year token match
3. Strong club match (threshold=0.95)

**F. State-scoped query**

All candidates are filtered to `state_code='WA'` since all Affinity data is Washington-only. This eliminates cross-state club noise entirely.

### 10.3 Configuration Keys

```python
MATCHING_CONFIG = {
    ...
    'club_variant_match_boost': 0.35,           # When club same + variant same
    'affinity_variant_gate_required': True,      # Require variant match before scoring
    'affinity_rcl_strict': True,                 # RCL number must match exactly
    'affinity_club_similarity_threshold': 0.9,   # Club gate threshold
    'affinity_debug_match_reasons': False,        # Log rejection stats
}
```

### 10.4 Patterns Worth Porting to Other Matchers

| Pattern | What It Does | Where to Port |
|---------|-------------|--------------|
| Hygiene-style normalization at match time | Aligns incoming names with DB-normalized names | All matchers — `_normalize_team_name()` should call hygiene normalization |
| Gated candidate funnel | Eliminates bad candidates before expensive scoring | Base `_fuzzy_match_team()` — move distinction checks BEFORE score calc |
| Post-match domain validation | Double-checks match against domain rules | Modular11 (division), TGS (conference) |
| Club+variant boost | Strong signal when club AND variant match | Base `_calculate_match_score()` |
| Deterministic tie-breaking | Prevents random selection between equal scores | All matchers — currently no tie-breaking exists |
| State-scoped queries | Narrow candidates by known geography | Any provider with known state |

---

## 11. Improvement Opportunities (Fuzzy & Game Matcher)

### 11.1 Current Pain Points in the Fuzzy Matcher

**A. `SequenceMatcher` is the weakest link**
- It uses longest common subsequence which is sensitive to character position
- "Solar SC" vs "Dallas Solar" scores poorly because characters are in different positions
- `token_set_ratio` (from rapidfuzz) is only used in club_normalizer, NOT in the main team name comparison
- **Opportunity:** Replace `SequenceMatcher` in `_calculate_similarity()` with `rapidfuzz.fuzz.token_sort_ratio` or a combination scorer

**B. Normalization is inconsistent across matchers**
- Base matcher uses `normalize_name_for_matching()` from team_name_utils
- TGS matcher overrides `_normalize_team_name()` with its own logic (strip before dash)
- Modular11 has its own normalization with club synonyms
- **Opportunity:** Unify normalization into a single pipeline that all matchers share, with provider-specific hooks

**C. Club name matching is duplicated**
- `club_normalizer.py` has a full canonical registry with fuzzy matching
- `game_matcher.py:_calculate_match_score()` has its own club comparison logic
- `tgs_matcher.py:_calculate_match_score()` has yet another club comparison with state abbreviation expansion
- **Opportunity:** All club comparisons should go through `club_normalizer.normalize_to_club()` as the single source of truth

**D. Hard rejection may be too aggressive**
- If a team name has a word classified as a "squad_word" that the other doesn't, it's hard-rejected
- Short words (2-3 chars) that aren't in any known set get classified as "location_codes"
- This can incorrectly reject valid matches when one source includes extra metadata
- **Opportunity:** Make hard rejection configurable per provider, or use soft penalties instead of hard rejects for certain distinction types

**E. Candidate retrieval is a bottleneck**
- When club-filtered query returns nothing, falls back to loading up to 5000 teams
- Every candidate gets distinctions extracted and scored — O(n) per match attempt
- **Opportunity:** Pre-compute normalized names and distinctions in the DB, use trigram indexes for faster fuzzy lookups

### 11.2 Current Pain Points in the Game Matcher

**A. Game UID doesn't handle rescheduled games**
- If a game is rescheduled to a different date, it generates a new UID
- The old result stays in the DB alongside the new one
- **Opportunity:** Add a "supersedes" relationship or use provider-specific game IDs when available

**B. Composite key is fragile for score corrections**
- If a provider corrects a score (e.g., 3-1 → 3-2), the composite key changes
- Both the old and corrected game would exist in the DB
- **Opportunity:** Use provider game IDs as the primary dedup key when available, fall back to composite only when not

**C. Partial matches leave games incomplete**
- When only one team matches, the game has a NULL for the other team
- These partial games may never get completed if the review queue isn't processed
- **Opportunity:** Add a "re-match" pipeline that periodically retries partial games after new aliases are approved

**D. Score normalization is scattered**
- Float-to-int conversion for provider IDs happens in multiple places
- Score validation logic (`_has_valid_scores`) is separate from normalization
- **Opportunity:** Create a single `normalize_game_record()` function that handles all data cleaning

### 11.3 Lessons from the Affinity WA Matcher to Apply Everywhere

The Affinity WA matcher (`src/models/affinity_wa_matcher.py`) introduced several patterns that should be ported to all matchers:

1. **Apply hygiene normalization at match time** — Currently the hygiene pipeline normalizes DB names but incoming provider names still use raw formats. The affinity matcher's `_normalize_for_affinity_wa()` bridges this gap. All matchers should normalize incoming names using the same transforms the hygiene pipeline uses.

2. **Gate candidates before scoring** — The affinity matcher's 3-stage funnel (club gate → variant gate → domain gate → score) is more efficient than the current approach of scoring all candidates and filtering after. The base `_fuzzy_match_team()` already does distinction-based hard rejection but it happens INSIDE the scoring loop. Moving it to a pre-filter stage would be cleaner.

3. **Club+variant boost** — The +0.35 boost when club AND variant match is a strong signal. The base matcher gives +0.10 for club alone but doesn't consider variant alignment as a boost.

4. **Deterministic tie-breaking** — The base matcher just picks the highest score. When two candidates tie, the result is arbitrary. The affinity matcher's 3-tuple tiebreaker (variant, year, club) ensures consistent results.

5. **Post-match domain validation** — Even after fuzzy matching succeeds, the affinity matcher re-checks domain rules (RCL number). This "trust but verify" pattern should be applied to Modular11 (division check post-match) and TGS (conference check).

### 11.4 Quick Wins

1. **Swap `SequenceMatcher` for `rapidfuzz.token_sort_ratio`** in `_calculate_similarity()` — likely the single biggest improvement for fuzzy match quality
2. **Route all club comparisons through `normalize_to_club()`** — eliminates duplicate logic and leverages the canonical registry everywhere
3. **Pre-index team names with trigrams** in Supabase — eliminates the 5000-candidate paginated fallback
4. **Add a periodic re-match job** for partial games — clears the backlog as new aliases get approved
5. **Expand the canonical club registry** — every new club added eliminates fuzzy matching for all its variations

---

## 12. Deep Analysis: Hygiene Script Patterns for Real-Time Matcher Improvement

The weekly data hygiene scripts contain battle-tested patterns that evolved from months of production debugging. Many of these patterns are **more mature** than their counterparts in the real-time matchers. This section catalogs specific code and ideas worth porting.

### 12.1 Pattern: Parse Age From Name, Not Metadata

**Source:** `find_queue_matches.py:299-334` — `extract_age_group()`

The hygiene script learned the hard way that metadata `age_group` fields from providers are **unreliable**. The script always parses age from the team name first:

```python
# Priority chain:
# 1. U-age format from name:  "U13" → u13
# 2. Gender+year from name:   "B14" → 2014 → u12,  "G2013" → u13
# 3. Standalone birth year:   "2014" → u12
# 4. FALLBACK ONLY: metadata  details['age_group']
```

**Where to port:** `GameHistoryMatcher._match_team()` currently trusts the `age_group` parameter passed by the pipeline. It should validate by parsing the team name and flagging mismatches. This would catch cases where a provider labels "FC Dallas B14 Blue" as `u14` (wrong — B14 = birth year 2014 = U12).

### 12.2 Pattern: Enhanced Coach Name Detection

**Source:** `find_queue_matches.py:153-297` — `extract_team_variant()`

The hygiene script has the most sophisticated variant extraction in the codebase, including **coach name detection** that the real-time matchers completely lack:

```
Detection algorithm:
1. Find age/year position in name
2. Extract text AFTER the age token
3. Remove region markers in parentheses: "(CTX)" → ""
4. For each remaining word after age:
   - Skip if in common_words set (300+ words: ecnl, boys, soccer, etc.)
   - Skip if in region_codes set (100+ codes: ctx, phx, az, etc.)
   - Skip if in program_names set (30+ words: aspire, dynasty, etc.)
   - Skip if it's a number or age pattern
   - OTHERWISE: it's a coach name → return it
5. Fallback: check for coach in parens "(Holohan)" (not region codes)
6. Fallback: ALL CAPS words after year "2014 RIEDELL"
7. Fallback: capitalized last word that isn't a known token
```

**Why this matters:** Teams like "Atletico Dallas 15G Riedell" and "Atletico Dallas 15G Davis" are **different teams** (different coaches). Without coach name detection, the real-time matcher would merge them. The hygiene script catches this; the real-time import pipeline does not.

**Where to port:** `team_name_utils.extract_distinctions()` should add a `coach_name` distinction field. The exclusion sets (common_words, region_codes, program_names) from `find_queue_matches.py:189-210` should be shared constants.

### 12.3 Pattern: Multi-Strategy Club Extraction

**Source:** `find_queue_matches.py:62-144` — `extract_club_from_name()`

The hygiene script's club extraction handles edge cases the real-time matcher doesn't:

```
Strategy 1: Split on earliest age pattern
  "FC Tampa Rangers FCTS 2015 Falcons" → "FC Tampa Rangers FCTS"

Strategy 2: Strip suffix ladder (12 patterns)
  ECNL-RL, ECNL, RL, PRE-ECNL, COMP, GA, MLS NEXT,
  ACADEMY, SELECT, PREMIER, ELITE, PRE

Strategy 3: Deduplicate repeated words
  "Kingman SC Kingman SC U14" → "Kingman SC"
  (some providers concatenate club name twice)

Strategy 4: Min length guard
  Don't return club names < 3 chars (avoids "FC" as club)
```

**Where to port:** `team_name_utils.extract_club_from_team_name()` (line 336) has a simpler version. The word deduplication (Strategy 3) would catch real production bugs where providers send `"Club Name Club Name"`.

### 12.4 Pattern: Structured Distinction Extraction (The Origin Story)

**Source:** `find_fuzzy_duplicate_teams.py:107-237` — `extract_distinctions()`

This is the **original** implementation that was later ported to `team_name_utils.py`. The hygiene version has nuances the ported version preserved but also some the real-time matcher doesn't fully exploit:

```
4-Pass Classification:
  Pass 1: Known tokens → colors, directions, programs, location_codes,
           noise_words, US_states, roman_numerals, team_numbers
  Pass 2: Age patterns → age_tokens, secondary_nums (numbers AFTER first age)
  Pass 3: Age+gender combos → classify as age (15m, b06, u16b)
  Pass 4: Remaining → squad_words (≥4 chars) or location_codes (2-3 chars)
```

**Key detail worth porting:** The `secondary_nums` extraction (numbers appearing AFTER the first age token) catches cases like "Union 2010 FC 2009" vs "Union 2010 FC 2008" where the second number is a differentiator. The real-time matcher's `team_name_utils.py` has this but the base `game_matcher.py` doesn't fully use it in candidate filtering.

### 12.5 Pattern: Conservative Club Name Canonicalization

**Source:** `full_club_analysis.py:58-85` — `normalize_for_grouping()`

The hygiene script deliberately avoids aggressive suffix stripping because it causes false matches:

```python
# CONSERVATIVE: Normalize suffix TO canonical form, don't strip
# "Pride Soccer Club" → "pride sc"    (suffix normalized)
# "FC Dallas"         → "fc dallas"   (prefix preserved)

# THIS PREVENTS:
# "FC Arkansas" ≠ "Arkansas Soccer Club"  (prefix FC ≠ suffix SC)
# "FC United Soccer Club" ≠ "United SC"   (different clubs)
```

**Where to port:** `club_normalizer.py` strips suffixes more aggressively. The hygiene script's approach of **normalizing suffixes to canonical abbreviations** without stripping them is safer. The real-time matcher should adopt this for cases where the canonical registry doesn't have a match.

### 12.6 Pattern: Acronym-Aware Proper Casing

**Source:** `full_club_analysis.py:28-56` — `ACRONYMS` set + `proper_case()`

The hygiene script maintains a 70+ entry acronym set covering:
- Soccer acronyms: FC, SC, SA, AC, CF, CD, YSA
- Leagues: ECNL, GA, MLS
- Cities: LA, NY, NJ, OC, DC, KC, STL, ATL, PHX
- All 50 US state codes
- Club-specific: AFC, CFC, SFC, VFC, PFC, LAFC, NYCFC, NCFC

**Where to port:** The real-time matcher's normalization (`normalize_name_for_matching()`) lowercases everything. When creating new team records, the hygiene script's `proper_case()` produces cleaner names. This should be used when the pipeline creates new master teams.

### 12.7 Pattern: `parse_age_gender()` — The Most Robust Age Parser

**Source:** `team_name_normalizer.py:67-170`

This function handles **12+ age format combinations** that no other part of the codebase matches:

```
Format           → (age, gender)
'14B'            → ('2012', 'Male')    # 2-digit year + gender suffix
'B14'            → ('2012', 'Male')    # gender prefix + 2-digit year
'2014B'          → ('2014', 'Male')    # 4-digit year + gender suffix
'B2014'          → ('2014', 'Male')    # gender prefix + 4-digit year
'U14B'           → ('U14', 'Male')     # U-age + gender suffix
'U-14'           → ('U14', None)       # U-age with hyphen
'BU14'           → ('U14', 'Male')     # gender prefix + U-age
'2014'           → ('2014', None)      # bare 4-digit year
'U14'            → ('U14', None)       # bare U-age
'15M'            → ('2015', 'Male')    # M = Male variant
'2014 Boys'      → ('2014', 'Male')    # word gender
'12'             → ('2012', None)      # bare 2-digit (6-18 range → birth year)
```

**Where to port:** The base matcher's `normalize_name_for_matching()` handles only a subset of these. The affinity matcher added its own `_normalize_for_affinity_wa()` which covers some WA-specific abbreviations. `parse_age_gender()` should be the **single source of truth** for age parsing across all matchers.

### 12.8 Pattern: Multi-Word Token Joining

**Source:** `team_name_normalizer.py:173-222` — `extract_squad_identifier()`

The squad identifier extractor joins tokens that form compound terms BEFORE classifying them:

```
"ECNL" + "RL"   → "ECNL RL"    (not two separate programs)
"MLS" + "NEXT"   → "MLS NEXT"   (not "MLS" program + "NEXT" word)
"Pre" + "ECNL"   → "Pre-ECNL"   (not "Pre" word + "ECNL" program)
```

Also normalizes division aliases:
```
"ecnl-rl" → "ECNL RL"
"ecrl"    → "ECNL RL"
"rl"      → "ECNL RL"   (standalone RL = ECNL Regional League)
"mls-next" → "MLS NEXT"
```

**Where to port:** The base matcher treats each token independently. "ECNL RL" gets split into "ecnl" and "rl" which may be matched separately against candidates, leading to false partial matches. Token joining should happen in `normalize_name_for_matching()`.

### 12.9 Pattern: Idempotent Processing with Backup

**Source:** `normalize_team_names.py:14-15, 195-207`

The normalization script:
1. Only processes teams where `team_name_original IS NULL` (never re-processes)
2. Backs up the original name with `COALESCE(team_name_original, original)` (preserves first backup)
3. Uses `--all-teams` flag to override and re-scan everything

**Where to port:** The real-time matcher should adopt this pattern when creating aliases or updating team names. Currently, re-running an import can create duplicate aliases without tracking which ones were auto-generated vs human-approved.

### 12.10 Pattern: Candidate Narrowing Hierarchy

**Source:** `find_fuzzy_duplicate_teams.py:398-436` — 3-level candidate filtering

The hygiene fuzzy matcher narrows candidates through 3 levels before scoring:

```
Level 1: Group by state (only compare within state)
  → Eliminates cross-state false matches entirely
  → O(n) per state instead of O(n²) overall

Level 2: Require same club_name (exact match)
  → "2010 White" from Club A never merges with "2010 White" from Club B
  → Prevents the #1 most dangerous merge error

Level 3: Structural distinction filter (_should_skip_pair)
  → Colors, directions, programs, team numbers, location codes,
    squad words, age tokens, secondary nums must ALL match
  → After this filter, only true formatting variants remain
```

**Where to port:** The base `_fuzzy_match_team()` does Level 3 (distinction filter) but inside the scoring loop. Levels 1 and 2 are partially implemented (club-filtered query first, fallback to broad query). The improvement is to make the cascade explicit and mandatory: never fall back to the broad 5000-candidate query if club filtering returns results.

### 12.11 Pattern: Confidence Score Ceiling

**Source:** `find_queue_matches.py:658-659`

```python
# Cap score at 0.99 for alias table
db_score = min(0.99, r['score'])
```

The hygiene script NEVER writes 1.0 confidence for fuzzy matches. Only direct provider ID matches should be 1.0.

**Where to port:** The base matcher caps at different levels per method but doesn't enforce a hard ceiling. Adding `min(0.99, score)` in `_create_alias()` would make it clear which aliases were fuzzy-matched vs direct-matched when debugging.

### 12.12 Pattern: Connection Resilience

**Source:** `find_queue_matches.py:525-544`

```python
# Refresh Supabase client every 1000 entries (HTTP/2 timeout)
if i > 0 and i % 1000 == 0:
    supabase = get_supabase()

# Retry logic with fresh connection on transient errors
for attempt in range(max_retries):
    try:
        match, score, method = find_best_match(entry, supabase, None)
        break
    except Exception:
        supabase = get_supabase()  # Fresh connection
        time.sleep(2)
```

**Where to port:** The ETL pipeline's `import_games()` processes batches of 2000 games with a single Supabase client. Long-running imports (10k+ games) hit the same HTTP/2 timeout. The hygiene script's periodic client refresh pattern should be added to `enhanced_pipeline.py`.

### 12.13 Summary: Hygiene → Real-Time Matcher Porting Roadmap

| Priority | Pattern | Source Script | Target | Impact |
|----------|---------|--------------|--------|--------|
| **P0** | `parse_age_gender()` as single age parser | `team_name_normalizer.py:67` | All matchers | Eliminates age format mismatches |
| **P0** | Coach name detection in variant extraction | `find_queue_matches.py:183` | `team_name_utils.py` | Prevents merging different coach teams |
| **P0** | Multi-word token joining (ECNL+RL) | `team_name_normalizer.py:173` | `normalize_name_for_matching()` | Fixes compound term splitting |
| **P1** | Club extraction with dedup + min length | `find_queue_matches.py:62` | `team_name_utils.py:336` | Catches provider data bugs |
| **P1** | Conservative club suffix canonicalization | `full_club_analysis.py:58` | `club_normalizer.py` | Prevents prefix/suffix confusion |
| **P1** | Confidence ceiling (0.99 max for fuzzy) | `find_queue_matches.py:659` | `game_matcher.py:_create_alias` | Clean audit trail |
| **P2** | Age from name, not metadata | `find_queue_matches.py:299` | `game_matcher.py:_match_team` | Catches provider mislabeling |
| **P2** | Connection refresh every 1000 entries | `find_queue_matches.py:525` | `enhanced_pipeline.py` | Production reliability |
| **P2** | Idempotent processing with backup | `normalize_team_names.py:195` | Alias creation flow | Safe re-runs |
| **P3** | Proper case with acronym awareness | `full_club_analysis.py:28` | Team creation flow | Cleaner team names |
| **P3** | Mandatory candidate narrowing hierarchy | `find_fuzzy_duplicate_teams.py:398` | `_fuzzy_match_team()` | Faster matching, fewer false positives |

---

*Generated: 2026-03-01 | Source: Comprehensive codebase analysis of PitchRank pipeline*
