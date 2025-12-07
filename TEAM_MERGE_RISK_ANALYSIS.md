# PitchRank Team Merge Risk Analysis

## Executive Summary
The ranking calculation system has critical dependencies on `team_id` as a stable, unique identifier. A team merge (where two `team_id`s become one) would cause:
- **Stale cached rankings** (incorrect PowerScores)
- **Duplicate entries** in ranking history
- **Lost historical data** (automatic cascade deletes)
- **Race conditions** during concurrent ranking runs
- **ML model corruption** (misaligned game residuals)

## System Architecture Overview

### Key Tables and Relationships
```
teams(team_id_master) 
  ├─ ranking_history(team_id FK + snapshot_date, UNIQUE)
  ├─ rankings_full(team_id FK, PRIMARY KEY)
  ├─ current_rankings(team_id FK, PRIMARY KEY)
  └─ games(home_team_master_id FK, away_team_master_id FK)
```

### Team ID Usage Pattern
- **Games Table**: `home_team_master_id`, `away_team_master_id` (FK to teams.team_id_master)
- **Rankings**: Uses `team_id` (string version of team_id_master UUID)
- **Lookups**: Dictionary-based (strength_map, power_map, team_off_norm_map, etc.)
- **Aggregations**: GroupBy on (team_id, age, gender)
- **Snapshots**: Indexed by (team_id, snapshot_date) with UNIQUE constraint

---

## 1. CACHE INCONSISTENCIES

### File: `/home/user/PitchRank/src/rankings/calculator.py` (lines 139-194)

**How it works:**
```python
# Cache key is MD5 hash of sorted game IDs + lookback_days + provider_filter
game_ids = games_df["game_id"].astype(str).tolist()
hash_input = "".join(sorted(game_ids)) + str(lookback_days) + (provider_filter or "")
cache_key = hashlib.md5(hash_input.encode()).hexdigest()

# Cache stored as parquet files with this hash
cache_file_teams = cache_dir / f"rankings_{cache_key}_teams.parquet"
```

**Merge Risk: CRITICAL**

If Team A (id=abc123) and Team B (id=def456) merge to Team C (id=ghi789):

1. **Games don't change** - games still reference abc123 and def456
2. **Cache key stays the same** - still based on same game IDs
3. **Cached rankings are stale** - cached file has OLD team_ids (abc123, def456) but real data now has ghi789
4. **Next ranking run loads stale cache** - returns incorrect powers for the merged teams
5. **Cache never invalidates** - because game IDs haven't changed, the MD5 hash is identical

**Timeline of failure:**
- Day 1: Teams A & B computed, cached as abc123 + def456
- Day 2: Merge happens (abc123 + def456 → ghi789)
- Day 3: Next ranking run hits cache, loads old team_ids, processes games under wrong identifiers
- Day 4+: Until cache expires, all rankings are based on pre-merge team identities

**Impact:** PowerScores for merged teams are completely wrong for 7-90 days (until cache expires)

---

## 2. DICTIONARY/MAP LOOKUPS & MISSING FALLBACKS

### Files: 
- `/home/user/PitchRank/src/etl/v53e.py` (lines 461-554, 586-630)
- `/home/user/PitchRank/src/rankings/layer13_predictive_adjustment.py` (line 289)

**Critical Maps:**

```python
# v53e.py lines 461-462
strength_map = dict(zip(team["team_id"], team["abs_strength"]))
power_map = dict(zip(team["team_id"], team["power_presos"]))

# Also created at line 553-554 (after opponent adjustment)
team_off_norm_map = dict(zip(team["team_id"], team["off_norm"]))
team_def_norm_map = dict(zip(team["team_id"], team["def_norm"]))
team_gp_map = dict(zip(team["team_id"], team["gp"]))
team_anchor_map = dict(zip(team["team_id"], team["anchor"]))

# layer13 line 289
power_map = dict(zip(out["team_id"].astype(str), out[base_power_col].astype(float)))
```

**How lookups use these maps:**

```python
# v53e.py line 562 (adaptive_k calculation)
gap = abs(strength_map.get(row["team_id"], 0.5) - strength_map.get(row["opp_id"], 0.5))

# v53e.py line 655 (SOS calculation)
g_sos["opp_strength"] = g_sos["opp_id"].map(get_opponent_strength)
  ↓
def get_opponent_strength(opp_id):
    if opp_id in base_strength_map:
        return base_strength_map[opp_id]
    # ... fallback to global_strength_map or UNRANKED_SOS_BASE (0.35)
```

**Merge Risk: HIGH**

Timeline:
1. **Before merge**: Team A games reference team_id=abc123, map contains abc123→0.75
2. **Merge happens**: Team A absorbed into Team C (new team_id=ghi789)
3. **Games still reference old team_id**: Games weren't updated to ghi789
4. **Next ranking calculation**:
   - New teams table doesn't have abc123
   - strength_map won't have abc123
   - Lookups default to fallback: 0.5 (cohort mean or UNRANKED_SOS_BASE)
   - SOS calculations using 0.35 instead of 0.75
   - Opponent Adjustment calculations wrong (opponent strength halved)

**Games affected**: ALL games where:
- One team is the merged team (old identity)
- Opponent lookup fails, defaults to neutral 0.35/0.5
- Result: SOS artificially lowered, PowerScores distorted

---

## 3. MERGE OPERATIONS & ROW MULTIPLICATION

### File: `/home/user/PitchRank/src/rankings/calculator.py` (lines 481-492)

**In Pass 3 (National/State SOS Normalization):**

```python
# Fetch teams metadata
result = supabase_client.table('teams').select(
    'team_id_master, state_code'
).in_('team_id_master', batch).execute()
teams_metadata.extend(result.data)

# Merge into teams_combined
metadata_df = metadata_df.drop_duplicates(subset=['team_id_master'])
teams_combined = teams_combined.merge(
    metadata_df[['team_id_master', 'state_code']],
    left_on='team_id',
    right_on='team_id_master',
    how='left'
)
```

**Merge Risk: MEDIUM**

If metadata has duplicate team_id_master entries (can happen after failed cleanup):
1. `drop_duplicates` catches simple duplicates
2. But if ONE team_id_master maps to MULTIPLE entries in metadata (orphaned old records)
3. Merge creates cartesian product: 1 ranking row × 2 metadata rows = 2 rows
4. Result: Duplicate team rankings with different state_codes

Similar risk in v53e.py line 369-375 and layer13 line 375:
```python
team = team.merge(gp_counts, on=["team_id", "age", "gender"], how="left")
team = team.merge(gp_recent_counts, on=["team_id", "age", "gender"], how="left")
team = team.merge(perf_team, on=["team_id", "age", "gender"], how="left")
team = team.merge(team_resid, on=["team_id", "age", "gender"], how="left")
```

If merge keys are not unique after a team merge, cartesian product explodes row count.

---

## 4. FOREIGN KEY CASCADE DELETES & LOST HISTORY

### Files: 
- `/home/user/PitchRank/supabase/migrations/20251123000000_create_ranking_history.sql` (line 16)
- `/home/user/PitchRank/supabase/migrations/20250120130000_create_rankings_full.sql` (line 5)

**Schema:**
```sql
-- ranking_history
team_id UUID REFERENCES teams(team_id_master) ON DELETE CASCADE

-- rankings_full
team_id UUID REFERENCES teams(team_id_master) ON DELETE CASCADE PRIMARY KEY
```

**Merge Risk: CRITICAL**

If merge implementation deletes old team_id from teams table:

1. **Old team_id deleted** from teams table (Team A, id=abc123)
2. **ON DELETE CASCADE triggers** automatically
3. **ranking_history rows deleted** - 90 days of historical snapshots GONE
4. **rankings_full row deleted** - current ranking data wiped
5. **Cannot recover** - no warning, no transaction roll back available in async operations

**Data Loss Timeline:**
- 7 days of rank_change_7d calculations become impossible
- 30 days of rank_change_30d calculations become impossible
- State/regional ranking history erased
- Performance analysis data lost

**Worse: If merge happens during ranking run:**
- ranking_history upsert on line 87-90 (ranking_history.py) tries to insert
- Foreign key constraint fails silently (or throws uncaught exception)
- Snapshots for MERGED team never saved
- Creates data integrity gap

---

## 5. UNIQUE CONSTRAINT VIOLATIONS

### File: `/home/user/PitchRank/src/rankings/ranking_history.py` (line 89)

**Schema:**
```sql
UNIQUE(team_id, snapshot_date)
```

**Code:**
```python
response = supabase_client.table("ranking_history").upsert(
    batch,
    on_conflict="team_id,snapshot_date"
).execute()
```

**Merge Risk: HIGH**

If ranking runs DURING merge (race condition):

1. **Pre-merge state**: ranking_history has (abc123, 2025-12-07, rank=5)
2. **Merge starts**: two teams consolidated, but games still dual-referenced
3. **Ranking calculation for abc123**: computes rank=5 again
4. **Ranking calculation for def456**: computes rank=10 (merged team perspective)
5. **Attempt to save**:
   - Both (abc123, 2025-12-07, rank=5) and (def456, 2025-12-07, rank=10)
   - Foreign key fails: abc123 no longer exists in teams table
   - Upsert fails with cryptic FK error
   - Snapshot not saved at all
6. **Next 7d/30d calculations**: Missing data, rank_change_7d is NULL

**Even without merge:** If two teams somehow have same (team_id, snapshot_date):
- Upsert will silently pick one and discard other
- Which one wins is non-deterministic
- If Team A wins, Team B's history is lost

---

## 6. ML LAYER TEAM RESIDUAL MISALIGNMENT

### Files:
- `/home/user/PitchRank/src/rankings/layer13_predictive_adjustment.py` (lines 144-202)
- `/home/user/PitchRank/src/rankings/calculator.py` (lines 240-256)

**Game Residual Extraction:**
```python
def _extract_game_residuals(feats: pd.DataFrame, games_df: pd.DataFrame, cfg: Layer13Config) -> pd.DataFrame:
    # Filter to home team perspective only
    feats['team_id_str'] = feats['team_id'].astype(str).str.strip().str.lower()
    feats['home_team_master_id_str'] = feats['home_team_master_id'].astype(str).str.strip().str.lower()
    home_perspective = feats[feats['team_id_str'] == feats['home_team_master_id_str']].copy()
    
    # Extract game_id (UUID) and residual
    result_df = home_perspective[['id', 'residual']].copy()
    result_df = result_df.rename(columns={'id': 'game_id', 'residual': 'ml_overperformance'})
```

**ML Aggregation:**
```python
def _aggregate_team_residuals(feats: pd.DataFrame, cfg: Layer13Config) -> pd.DataFrame:
    # ... build ml_overperf per (team_id, age, gender)
    team_resid = agg[["team_id", "age", "gender", "ml_overperf"]].copy()
```

**Merge Risk: CRITICAL**

Timeline:
1. **ML training on Team A games**: learns residuals = +0.3 goals (overperformance)
2. **Model persists** in memory during ranking run
3. **Merge happens**: Team A absorbed into Team C
4. **Games reclassified**: old games now attributed to Team C
5. **Next ranking run**:
   - Residuals still computed from games (game_id → ml_residual)
   - **BUT:** Team aggregation tries to sum residuals by (team_id, age, gender)
   - Games still have old team_id from games table
   - Teams table has new team_id
   - Mismatch: games reference old team_id, teams table has new
   - Merge on team_id fails
   - Team C gets residual=0 (missing data)
   - Team A still appears in results with stale residual=+0.3

**Even worse:** If games are updated to new team_id before rankings run:
1. Games now reference Team C
2. ML model trained on Team A games
3. Residuals apply to wrong team context
4. Team C gets residual calculated from Team A performance characteristics
5. ML boost meant for Team A's opponent matchups applied to Team C

---

## 7. RACE CONDITIONS DURING CONCURRENT RANKING RUNS

### Files:
- `/home/user/PitchRank/src/rankings/calculator.py` (lines 82-296)
- `/home/user/PitchRank/src/rankings/ranking_history.py` (lines 87-104)

**Ranking Pipeline:**
```python
async def compute_rankings_with_ml(...):
    # 1. Fetch games (includes team_id references)
    games_df = await fetch_games_for_rankings(...)
    
    # 2. Check cache based on game_ids
    base = None
    if not force_rebuild and cache_file_teams.exists():
        cached_teams = pd.read_parquet(cache_file_teams)
    
    # 3. Calculate rankings (uses team_id for all lookups)
    base = compute_rankings(games_df=games_df, ...)
    
    # 4. Save snapshot (uses team_id as FK)
    await save_ranking_snapshot(...)
```

**Merge Risk: CRITICAL if merge happens between steps**

Scenario: Team A + Team B → Team C merge happens at step 2:

**Run A (started before merge, running during merge):**
- Step 1: Fetches games with team_id=abc123, def456
- Step 2: Checks cache (finds games for abc123)
- **MERGE HAPPENS between step 2-3**
- Step 3: Computes rankings using abc123 (just deleted from teams table!)
- Step 4: Tries to save snapshot with FK to abc123
- Result: FK constraint fails, snapshot lost

**Run B (started after merge):**
- Step 1: Fetches games (games updated to ghi789, but old team_ids still in some games)
- Step 2: Cache miss (game IDs changed? No, they didn't)
- **HITS STALE CACHE from before merge**
- Step 3: Uses cached rankings (with old team_ids)
- Step 4: Saves stale ranking snapshot
- Result: Wrong rankings saved for 24 hours

**Worst case**: Run A and Run B overlap:
- Run A calculating with team_id=abc123
- Run B trying to upsert same snapshot_date with team_id=ghi789
- One updates wins, other update lost
- **No transactional guarantee**: PostgreSQL upsert may pick either one

---

## 8. RANK CHANGE CALCULATIONS BECOME INVALID

### File: `/home/user/PitchRank/src/rankings/ranking_history.py` (lines 212-313)

**Logic:**
```python
async def calculate_rank_changes(...):
    # Get current team IDs
    team_ids = current_rankings_df["team_id"].dropna().unique().tolist()
    
    # Query 7 days ago snapshots
    ranks_7d_ago = await get_historical_ranks(supabase_client, team_ids, days_ago=7)
    
    # Calculate change = historical_rank - current_rank
    change_7d = (rank_7d - current_rank) if rank_7d is not None else None
```

**Merge Risk: HIGH**

If Team A merged to Team C:

1. **Current rankings**: Team C with rank=8
2. **Query historical ranks for Team C**: "where team_id = ghi789"
3. **Database returns**: NULL (no snapshots for ghi789)
4. **But**: Snapshots for abc123 still exist (maybe not deleted if old ID kept)
5. **Result**: rank_change_7d = NULL
6. **Display issue**: Shows "N/A" instead of actual 3-position improvement

Even worse: If Team A is RETIRED (not merged):
- Snapshots for abc123 cascade deleted via FK
- Cannot calculate historical change even if Team B unmerged later
- History is permanently lost

---

## 9. CROSS-AGE SOS LOOKUPS BREAK

### File: `/home/user/PitchRank/src/rankings/calculator.py` (lines 408-418)

**Build global strength map (Pass 1):**
```python
global_strength_map = {}
for result in pass1_results:
    if not result["teams"].empty:
        teams_df = result["teams"]
        if "abs_strength" in teams_df.columns:
            for _, row in teams_df.iterrows():
                team_id = str(row["team_id"])
                global_strength_map[team_id] = float(row["abs_strength"])

logger.info(f"🌍 Built global strength map with {len(global_strength_map):,} teams")
```

**Use in SOS (line 648):**
```python
opp_id_str = str(opp_id)
if global_strength_map and opp_id_str in global_strength_map:
    cross_age_found += 1
    return global_strength_map[opp_id_str]
```

**Merge Risk: MEDIUM**

If Team C plays an opponent from different age group:
1. SOS lookup tries: base_strength_map[opp_id] - MISS (wrong age group)
2. Falls back to: global_strength_map[opp_id] - MAY MISS if opp merged
3. Falls back to: UNRANKED_SOS_BASE (0.35)
4. Result: Cross-age opponent undervalued, SOS depressed

Timeline:
- Pass 1 builds map with Team A (abc123 → 0.7)
- Merge happens to Team C (ghi789 → 0.8)
- Pass 2 runs, opponent lookup tries ghi789
- **ghi789 NOT in global map** (built before merge)
- Falls back to 0.35
- Cross-age SOS corrupted

---

## 10. PERFORMANCE REGRESSION & LONG-TERM EFFECTS

### Where Team ID is used to track performance:

1. **Per-team performance residuals** (v53e.py lines 822-850)
   ```python
   g_perf["team_power"] = g_perf["team_id"].map(lambda t: power_map.get(t, 0.5))
   # If team_id lookup fails, defaults to 0.5
   ```

2. **Cohort aggregations** (v53e.py line 853-855)
   ```python
   team["perf_centered"] = team.groupby(["age", "gender"])["perf_raw"].transform(
       lambda s: s.rank(method="average", pct=True) - 0.5
   )
   # If team_id changes after computation, performance ranking changes
   ```

3. **Sample size weighting** (v53e.py lines 746-747)
   ```python
   sos_weight = (team["gp"] / cfg.SOS_SAMPLE_SIZE_THRESHOLD).clip(0, 1)
   # Games played counted by team_id, merged team has gp from only one perspective
   ```

**Merge Risk: MEDIUM (cumulative effect)**

Over time:
- Performance metrics corrupted
- SOS biased toward undervalued opponents
- Low-sample-size shrinkage applied incorrectly
- Rankings drift away from true strength

---

## Summary Table: Risk by Component

| Component | Risk Level | Impact | Recovery |
|-----------|-----------|--------|----------|
| Cache System | **CRITICAL** | Stale rankings for weeks | Manual cache clear |
| Dictionary Lookups | **HIGH** | Wrong SOS, opponent adjustment fails | Manual reset |
| Merge Operations | **MEDIUM** | Duplicate rows | Data cleanup required |
| FK Cascades | **CRITICAL** | Lost history | Unrecoverable |
| Unique Constraints | **HIGH** | Snapshot insertion fails | Manual upsert/retry |
| ML Residuals | **CRITICAL** | Wrong team attribution | Retrain model |
| Race Conditions | **CRITICAL** | Data corruption | No guarantee |
| Rank Changes | **HIGH** | Historical comparison broken | Lost data |
| Cross-age SOS | **MEDIUM** | Biased strength calculation | Recalculate |
| Performance Regression | **MEDIUM** | Gradual ranking drift | Recompute all |

---

## Recommended Safeguards

1. **Cache Invalidation**: Add team_id to cache key, not just game_ids
2. **Pre-merge Validation**: Verify team_id stability before merge
3. **Snapshot Pre-merge**: Save snapshots with BOTH old and new team_ids
4. **Soft Deletes**: Never hard-delete teams, use is_active flag
5. **Audit Trail**: Log all team_id changes with timestamps
6. **Transactional Ranking**: Wrap entire ranking in database transaction
7. **Historical Archive**: Keep read-only snapshot of ranking_history before merge
8. **Model Retraining**: Retrain ML models after any team merge
9. **Cross-validation**: Compare pre/post-merge rankings for consistency
10. **Locking**: Prevent ranking runs during merge windows
