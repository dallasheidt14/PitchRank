# Game Count Discrepancy Analysis

## Problem Statement

**Team:** 2014 Elite Phoenix United Futbol ClubAZ
**Rankings Page:** 19 games
**Team Details Page:** 29 games
**Discrepancy:** 10 games (34% difference)

---

## Root Cause Analysis

After comprehensive code review, the **10-game difference** is caused by **data quality filtering** in the ranking calculation pipeline.

### Where the Counts Come From

#### 1. Rankings Page: `games_played = 19`
- **Source:** `rankings_full` table → `rankings_view`
- **Calculated by:** Backend ETL pipeline (`src/etl/v53e.py` + `src/rankings/data_adapter.py`)
- **What it represents:** Games that pass ALL quality filters and are used in power score calculation

#### 2. Team Details Page: `total_games_played = 29`
- **Source:** Direct count from `games` table (`frontend/lib/api.ts:130`)
- **Calculated by:** Frontend API
- **What it represents:** ALL game records in database (including incomplete data)

---

## The Filtering Logic

The ranking engine applies **4 sequential filters** to games:

### Filter 1: Time Window (365 days)
**Location:** `src/etl/v53e.py:206-207`
```python
cutoff = today - pd.Timedelta(days=cfg.WINDOW_DAYS)  # 365 days
g = g[g["date"] >= cutoff].copy()
```
**Status for this team:** ✅ All 29 games are from Feb-Oct 2025 (within 365 days)

### Filter 2: Game Cap (30 most recent)
**Location:** `src/etl/v53e.py:222-224`
```python
g = g[g["rank_recency"] <= cfg.MAX_GAMES_FOR_RANK].copy()  # Top 30
```
**Status for this team:** ✅ Only 29 games total (under 30-game cap)

### Filter 3: Missing Scores
**Location:** `src/rankings/data_adapter.py:247-250`
```python
# Filter out rows with missing scores
v53e_df = v53e_df.dropna(subset=['gf', 'ga'])
```
**Filters out:** Games where `home_score` or `away_score` is NULL

### Filter 4: Missing Team Metadata
**Location:** `src/rankings/data_adapter.py:203-205`
```python
# Skip if missing age/gender
if not home_age or not home_gender or not away_age or not away_gender:
    continue
```
**Filters out:** Games where opponent team doesn't have `age_group` or `gender` in `teams` table

---

## Why 10 Games Are Excluded

Since Filters 1 & 2 passed (all games recent, under cap), the **10 excluded games** must be failing **Filter 3 or Filter 4**:

### Scenario A: Missing Scores (Filter 3)
- 10 games have NULL `home_score` or `away_score` in database
- Cannot calculate offense/defense metrics without scores
- **Likelihood:** Medium (games might be scheduled but not yet played)

### Scenario B: Missing Opponent Metadata (Filter 4)
- 10 opponent teams don't exist in `teams` table, OR
- 10 opponent teams are missing `age_group` or `gender` fields
- Cannot group teams into cohorts without metadata
- **Likelihood:** High (common issue with opponent teams from other clubs)

### Scenario C: Combination
- Some games missing scores + some missing opponent metadata
- **Likelihood:** Most likely

---

## Code Locations

| Component | File | Line | What It Does |
|-----------|------|------|--------------|
| **Frontend** |
| Rankings total count | `frontend/hooks/useRankings.ts` | 23-26, 59 | Queries games table, counts all games |
| Rankings display | `frontend/components/RankingsTable.tsx` | 429-434 | Shows "19 / 29" format |
| Team details count | `frontend/lib/api.ts` | 120-130 | Queries games table, counts all games |
| **Backend** |
| Time window filter | `src/etl/v53e.py` | 206-207 | Filters to last 365 days |
| Game cap filter | `src/etl/v53e.py` | 222-224 | Limits to 30 most recent |
| Score filter | `src/rankings/data_adapter.py` | 247-250 | Removes games with NULL scores |
| Metadata filter | `src/rankings/data_adapter.py` | 203-205 | Removes games with missing team data |
| Game count calculation | `src/etl/v53e.py` | 287 | Counts games passing all filters |

---

## Diagnostic Tools

I've created two diagnostic scripts in the repo root:

### 1. `diagnose_game_count.py`
**Purpose:** Comprehensive analysis of all filtering stages
**Requires:** Python, pandas, python-dotenv, supabase-py
**Usage:**
```bash
source .venv/bin/activate
python3 diagnose_game_count.py
```

**Output:**
- Team identification
- Games in rankings_full table
- All games from database
- Analysis of missing scores
- Analysis of missing team metadata
- Step-by-step filter results
- Final game count with breakdown

### 2. `simple_game_check.py`
**Purpose:** Quick check using frontend API perspective
**Requires:** Python, python-dotenv, supabase-py
**Usage:**
```bash
source .venv/bin/activate
python3 simple_game_check.py
```

**Output:**
- Team ranking data
- Total game count
- Date range of games
- List of all game dates

---

## Solution Implemented

✅ **Frontend now shows both metrics** (PR already committed):

**Before:**
- Rankings page: "19"
- Team details: "29"
- ❌ Confusing discrepancy

**After:**
- Rankings page: **"19 / 29"** with tooltip
- Team details: "29"
- ✅ Clear transparency

**Tooltip explains:**
- **Ranked Games (19):** Last 30 games within 365 days with complete data
- **Total Games (29):** All games in database

---

## Recommendations

### 1. **Immediate: Run Diagnostic** ⚡
Run `diagnose_game_count.py` to identify exactly which 10 games are excluded and why:
```bash
cd /home/user/PitchRank
source .venv/bin/activate
python3 diagnose_game_count.py
```

### 2. **Data Quality: Fix Missing Metadata** 🔧
If Filter 4 is the issue:
- Ensure all opponent teams are in `teams` table
- Populate `age_group` and `gender` for all teams
- Re-run rankings calculation

### 3. **Data Quality: Add Missing Scores** 📊
If Filter 3 is the issue:
- Identify games with NULL scores
- Update games with actual scores if available
- Or remove placeholder/scheduled games from database

### 4. **Documentation: Update UI** 📝
Consider adding a "Games Breakdown" section to team details:
```
Games Played
├─ 19 ranked games (used for power score)
├─ 10 excluded games:
│  ├─ 5 missing opponent data
│  └─ 5 missing scores
└─ 29 total games
```

### 5. **Analytics: Track Data Quality** 📈
Add monitoring for:
- % of games with complete data
- Teams without metadata
- Games without scores
- Filter rejection rates

---

## Technical Details

### Frontend Implementation (My Changes)

**File:** `frontend/hooks/useRankings.ts`
- Added `enrichWithTotalGames()` function
- Queries `games` table for all teams in rankings
- Counts games per team efficiently
- Merges `total_games_played` into ranking data

**File:** `frontend/components/RankingsTable.tsx`
- Updated "Games" column to show "Ranked / Total" format
- Added tooltip explaining the difference
- Styled with font-weight to emphasize ranked games

**File:** `frontend/types/RankingRow.ts`
- Added `total_games_played?: number` field
- Added comments explaining ranked vs total games

### Backend Ranking Pipeline

**Pipeline Flow:**
1. **Fetch games** (`data_adapter.py:38`) → Get games from last 365 days
2. **Convert to v53e format** (`data_adapter.py:181`) → Create home/away perspectives
3. **Filter by metadata** (`data_adapter.py:203-205`) → Remove games with incomplete team data
4. **Filter by scores** (`data_adapter.py:247-250`) → Remove games with NULL scores
5. **Apply time window** (`v53e.py:206-207`) → Keep games within 365 days
6. **Apply game cap** (`v53e.py:222-224`) → Keep only 30 most recent per team
7. **Count games** (`v53e.py:287`) → `gp` field = games passing all filters
8. **Store in rankings_full** → `games_played` column

---

## Conclusion

The UI fix correctly exposes the real data quality issue: **10 games exist in the database but lack the complete information needed for ranking calculations**. This is working as designed - rankings should only use complete, valid data.

**Next Step:** Run the diagnostic script to identify which specific games and opponent teams need data cleanup.
