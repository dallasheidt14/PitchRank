# PitchRank Team Mapping & Unknown Teams Analysis

## Executive Summary

The PitchRank system has a sophisticated three-tier team matching architecture that assigns games to master teams. "Unknown" teams appear in the frontend when:
1. **Games have NULL team IDs** (failed/partial matches during import)
2. **Team name lookup failures** (opponent team not found in the team map)
3. **Gender fallback issues** (unmatched gender values in ranking views)

This report covers the complete team mapping pipeline, where unknown teams originate, and recommended fixes.

---

## 1. Team Storage & Mapping Architecture

### 1.1 Core Database Tables

**`teams` Table** (Master Team List)
```sql
- team_id_master (UUID) - Primary identifier
- provider_team_id (TEXT) - Provider-specific ID (e.g., GotSport ID)
- provider_id (UUID) - References provider
- team_name, club_name, age_group, gender, state_code
```

**`team_alias_map` Table** (Canonical Team Mappings)
```sql
- provider_id (UUID) - Which provider this mapping is for
- provider_team_id (TEXT) - Team ID from that provider
- team_id_master (UUID) - Maps to this master team
- match_method ('direct_id' | 'provider_id' | 'alias' | 'fuzzy_auto')
- match_confidence (0.0-1.0)
- review_status ('approved' | 'pending' | 'rejected')
```

**`games` Table** (Game History)
```sql
- home_team_master_id (UUID NULLABLE) - NULL if match failed
- away_team_master_id (UUID NULLABLE) - NULL if match failed
- home_provider_id (TEXT) - Original provider ID
- away_provider_id (TEXT) - Original provider ID
```

### 1.2 Team Matching Flow

The system uses a **3-tier hierarchy** during game import:

```
Import Game → Match Teams ┌─→ Strategy 1: Direct ID Match (instant)
                          ├─→ Strategy 2: Alias Map Lookup (instant)
                          └─→ Strategy 3: Fuzzy Matching (slow, accuracy-based)
                          
Result: home_team_master_id & away_team_master_id assigned or NULL
```

**Location:** `/home/user/PitchRank/src/models/game_matcher.py`

---

## 2. Where "Unknown" Teams Appear

### 2.1 Frontend Components with "Unknown" Fallback

**File: `/home/user/PitchRank/frontend/lib/api.ts` (Line 529)**
```typescript
// In getCommonOpponents()
opponent_name: teamMap.get(opponentId) || 'Unknown',
```
**Trigger:** When an opponent's team_id_master exists but the team name lookup fails (team not in database).

**File: `/home/user/PitchRank/frontend/components/GameHistoryTable.tsx` (Line 264)**
```typescript
<span className="text-muted-foreground">{opponent || 'Unknown'}</span>
```
**Trigger:** When opponent team name is missing/undefined.

**File: `/home/user/PitchRank/frontend/components/MomentumMeter.tsx` (Line 245)**
```typescript
opponentName: opponentName || 'Unknown',
```
**Trigger:** When analyzing opponent strength but team name is not available.

### 2.2 Backend Handling of Unknown Gender

**File:** `/home/user/PitchRank/src/rankings/data_adapter.py` (Lines 569-580)**
```python
# Gender normalization during ranking calculation
if rankings_df['gender'].isna().any():
    logger.warning(f"⚠️ Found {rankings_df['gender'].isna().sum()} teams with NULL gender")
    rankings_df['gender'] = rankings_df['gender'].fillna('Unknown')
```
**Trigger:** Teams with missing gender values during ranking view creation.

---

## 3. Root Causes of Unknown Teams

### 3.1 Partially Matched Games

Games can be imported in **three match statuses:**

**Status: "matched"** ✅
- Both home_team_master_id and away_team_master_id assigned
- Both teams successfully mapped to master IDs
- Game fully usable in rankings

**Status: "partial"** ⚠️
- One team_id is assigned, one is NULL
- Common when: away team is new/unmapped but home team exists
- Game is imported but only half-usable

**Status: "failed"** ❌
- Both team_ids are NULL
- Both teams failed to match
- Game is imported but cannot contribute to rankings

**Impact:** Games with NULL team_id_master cannot be joined with the teams table, causing:
- Missing opponent names in game history
- Incomplete strength of schedule calculations
- Unknown opponent display

### 3.2 Team Mapping Failures

**Scenario 1: Team Never Imported**
- New team from provider not in master teams list
- Fuzzy match score < 0.75 (rejected)
- Result: NULL team_id_master

**Scenario 2: Team Exists but Confidence Too Low**
- Fuzzy match score 0.75-0.90 (requires manual review)
- Entry goes to `team_match_review_queue`, not `team_alias_map`
- Result: Unmatched until human review approves

**Scenario 3: Multiple Fuzzy Candidates**
- Team name is generic ("United", "FC Rangers")
- Age/gender doesn't help disambiguate
- Matching picks best candidate (might be wrong)
- Result: Matched but potentially to wrong master team

### 3.3 NULL Gender in Rankings

**Location:** `/home/user/PitchRank/src/rankings/data_adapter.py`

During ranking calculation, teams might have NULL gender if:
1. Master teams table has NULL gender (data issue)
2. Game metadata missing gender during import
3. Ranking view conversion failures

**Current fallback:** `fillna('Unknown')`

---

## 4. Configuration: Team Matching Rules

**File:** `/home/user/PitchRank/config/settings.py` (Lines 159-173)**

```python
MATCHING_CONFIG = {
    'fuzzy_threshold': 0.75,           # Minimum for any match
    'auto_approve_threshold': 0.9,     # Automatically create alias
    'review_threshold': 0.75,          # Queue for human review
    'max_age_diff': 2,
    'weights': {
        'team': 0.65,      # 65% - team name similarity
        'club': 0.25,      # 25% - club name similarity
        'age': 0.05,       # 5% - age group match
        'location': 0.05   # 5% - state match
    },
    'club_boost_identical': 0.05,
    'club_min_similarity': 0.8
}
```

**Key Parameters:**
- Teams with 0.90+ confidence → auto-approved, alias created immediately
- Teams with 0.75-0.90 confidence → queued for manual review
- Teams below 0.75 → rejected, no alias created

---

## 5. Data Sources for Teams

### 5.1 Master Teams Import

**Script:** `/home/user/PitchRank/scripts/import_teams_enhanced.py`

Imports teams from CSV with columns:
- `team_id` / `Team_ID` → provider_team_id
- `Team_Name` → team_name
- `Age_Group` → age_group ('u10', 'u11', etc.)
- `Gender` → gender ('Male', 'Female')
- `State_Code`, `Club` (optional)

Creates **direct_id mappings** automatically:
```python
team_id_master = uuid.uuid4()
# Store in teams table
# Create team_alias_map entry with match_method='direct_id'
```

### 5.2 Game Data Import

**Script:** `/home/user/PitchRank/scripts/import_games_enhanced.py`

Maps CSV columns to game data:
```python
'team_id' → home/away team provider ID
'team_name' → used for fuzzy matching if no direct ID match
'age_group', 'gender' → constraints for fuzzy matching
'opponent_id' → away/home team provider ID
```

### 5.3 Team Name Lookup

**In Frontend API:** `/home/user/PitchRank/frontend/lib/api.ts` (Lines 378-393)

When fetching games, system enriches them with team names:
```typescript
// Get all team IDs from games
const teamIds = new Set<string>();
games.forEach((game: Game) => {
  if (game.home_team_master_id) teamIds.add(game.home_team_master_id);
  if (game.away_team_master_id) teamIds.add(game.away_team_master_id);
});

// Fetch team names for these IDs
const teams = await supabase
  .from('teams')
  .select('team_id_master, team_name, club_name')
  .in('team_id_master', Array.from(teamIds));

// Build lookup map
const teamNameMap = new Map<string, string>();
teams?.forEach((team) => {
  teamNameMap.set(team.team_id_master, team.team_name);
});
```

**Problem:** If team_id_master is NULL (unmatched game), no name can be looked up.

---

## 6. Configuration Files & Aliases

### 6.1 Provider Configuration

**File:** `/home/user/PitchRank/config/settings.py` (Lines 46-65)**

```python
PROVIDERS = {
    'gotsport': {
        'code': 'gotsport',
        'name': 'GotSport',
        'base_url': 'https://www.gotsport.com',
        'adapter': 'src.scrapers.gotsport'
    },
    'tgs': { ... },
    'usclub': { ... }
}
```

Each provider gets a UUID in the database:
```sql
INSERT INTO providers (code, name, base_url) 
VALUES ('gotsport', 'GotSport', 'https://www.gotsport.com')
ON CONFLICT (code) DO NOTHING;
```

### 6.2 Age Group Configuration

**File:** `/home/user/PitchRank/config/settings.py` (Lines 68-78)**

```python
AGE_GROUPS = {
    'u10': {'birth_year': 2016, 'anchor_score': 0.40},
    'u11': {'birth_year': 2015, 'anchor_score': 0.44},
    ...
    'u18': {'birth_year': 2008, 'anchor_score': 1.00}
}
```

Used in:
- Fuzzy matching (age_group constraint)
- Ranking cohort calculation
- Cross-age normalization

### 6.3 Team Normalization Rules

**File:** `/home/user/PitchRank/src/models/game_matcher.py` (Lines 549-591)**

Team names normalized before fuzzy matching:

```python
def _normalize_team_name(self, name: str) -> str:
    name = name.lower().strip()
    # Remove punctuation
    # Expand abbreviations: fc → football club, sc → soccer club
    # Remove common suffixes: fc, sc, academy, etc.
    # Compress whitespace
    return name
```

**Example:**
```
"FC Dallas U12 Boys" → "dallas"
"FC Dallas 12 Boys" → "dallas"
Match score: 1.0 (perfect)
```

---

## 7. Recommended Fix Strategy

### 7.1 Immediate Fixes (High Impact)

**1. Fix NULL Team ID Handling in Frontend**

Replace hard-coded 'Unknown' with actual fallback team names.

**Location:** `/home/user/PitchRank/frontend/lib/api.ts` (Line 529)

Instead of:
```typescript
opponent_name: teamMap.get(opponentId) || 'Unknown'
```

Try to fetch name from game data:
```typescript
const fallbackName = games.find(g => 
  (g.home_team_master_id === opponentId || g.away_team_master_id === opponentId)
)?.opponent_name || `Team #${opponentId.slice(0, 8)}`; // Use team ID fragment

opponent_name: teamMap.get(opponentId) || fallbackName
```

**2. Add Game Match Status Filter**

Only display games where both teams matched.

**Location:** `/home/user/PitchRank/frontend/components/GameHistoryTable.tsx`

```typescript
// Filter out games where one or both teams are unmatched
const validGames = games.filter(game => 
  game.home_team_master_id && game.away_team_master_id
);
```

Show warning if games exist with NULL team IDs.

**3. Pre-import Team Validation**

Run team import BEFORE game import to establish master teams.

```bash
# Step 1: Import master teams
python scripts/import_teams_enhanced.py data/master_teams.csv gotsport

# Step 2: Verify direct ID mappings
python scripts/verify_team_mappings.py gotsport

# Step 3: THEN import games
python scripts/import_games_enhanced.py data/games.csv gotsport
```

### 7.2 Medium-term Improvements

**1. Automatic Team Detection**

When fuzzy match fails, create temporary "pending" master team:
```python
# Instead of: match_status = 'failed'
# Create: temporary team with match_status = 'unmatched'

pending_team = {
    'team_id_master': str(uuid.uuid4()),
    'team_name': f"[UNMATCHED] {game['team_name']}",
    'age_group': game['age_group'],
    'gender': game['gender'],
    'temporary': True,
    'created_from_game': True
}
```

Games can now reference this team, and frontend won't show "Unknown".

**2. Batch Gender Inference**

Infer gender from team metadata if NULL:
```python
if gender is None:
    # Look up team's other games to infer gender
    similar_games = db.query(
        "SELECT gender FROM games WHERE team_id LIKE %gender_pattern%"
    )
    if similar_games:
        gender = majority_vote(similar_games.gender)
```

**3. Fuzzy Match Confidence Monitoring**

Log all fuzzy matches with scores < 0.85:
```python
logger.warning(
    f"Low confidence match: {team_name} → {master_team} (score: {confidence:.2f})"
)
# Flag for audit
```

### 7.3 Long-term Architecture

**1. Team Name Aliases**

Create `team_name_aliases` table:
```sql
CREATE TABLE team_name_aliases (
    team_id_master UUID REFERENCES teams,
    alias_name TEXT,
    source TEXT ('provider_game' | 'manual'),
    confidence FLOAT,
    created_at TIMESTAMPTZ
);
```

Track all names a team is called and map them back.

**2. Gender Standardization**

Normalize gender in teams table:
```sql
ALTER TABLE teams 
ALTER COLUMN gender SET CHECK (gender IN ('M', 'F', 'B', 'G'));
```

Current: `'Male'`, `'Female'` (text)
Better: `'M'`, `'F'` (standardized)

**3. Match Status Tracking**

Add metrics table:
```sql
CREATE TABLE match_metrics (
    date DATE,
    provider_id UUID,
    total_games INT,
    matched_games INT,
    partial_matches INT,
    failed_matches INT,
    avg_match_confidence FLOAT
);
```

Monitor matching quality over time.

---

## 8. Verification & Diagnostics

### 8.1 Check Match Quality

```sql
SELECT 
    match_method,
    COUNT(*) as count,
    AVG(match_confidence) as avg_confidence,
    MIN(match_confidence) as min_confidence
FROM team_alias_map
GROUP BY match_method
ORDER BY count DESC;
```

### 8.2 Find Unmatched Games

```sql
SELECT 
    COUNT(*) as unmatched_games,
    COUNT(CASE WHEN home_team_master_id IS NULL THEN 1 END) as null_home,
    COUNT(CASE WHEN away_team_master_id IS NULL THEN 1 END) as null_away
FROM games;
```

### 8.3 Check Gender Nulls

```sql
SELECT 
    COUNT(*) as null_gender_teams
FROM teams
WHERE gender IS NULL;
```

### 8.4 Find Pending Reviews

```sql
SELECT 
    provider_team_name,
    confidence_score,
    status,
    COUNT(*) as count
FROM team_match_review_queue
GROUP BY provider_team_name, confidence_score, status
ORDER BY count DESC
LIMIT 20;
```

---

## 9. Implementation Roadmap

| Priority | Item | Location | Effort | Impact |
|----------|------|----------|--------|--------|
| **P0** | Fix NULL team ID in game history | frontend/lib/api.ts | 2h | HIGH - Eliminates most "Unknown" |
| **P0** | Pre-import team validation workflow | scripts/import_teams_enhanced.py | 1h | HIGH - Prevents failed matches |
| **P1** | Gender normalization in rankings | src/rankings/data_adapter.py | 3h | MEDIUM - Cleaner data |
| **P1** | Confidence monitoring for fuzzy matches | scripts/import_games_enhanced.py | 4h | MEDIUM - Quality tracking |
| **P2** | Team name aliases architecture | supabase/migrations/*.sql | 8h | HIGH - Long-term scalability |
| **P2** | Temporary team creation for unmatched | src/models/game_matcher.py | 6h | MEDIUM - Better UX |

---

## 10. Key Files Summary

### Core Team Matching
- `/home/user/PitchRank/src/models/game_matcher.py` - Three-tier matching logic
- `/home/user/PitchRank/config/settings.py` - Matching thresholds & configs
- `/home/user/PitchRank/scripts/import_teams_enhanced.py` - Team import with direct ID
- `/home/user/PitchRank/scripts/import_games_enhanced.py` - Game import & matching

### Frontend Team Display
- `/home/user/PitchRank/frontend/lib/api.ts` - Team name lookup (Line 529 Unknown)
- `/home/user/PitchRank/frontend/components/GameHistoryTable.tsx` - Game display (Line 264)
- `/home/user/PitchRank/frontend/components/MomentumMeter.tsx` - Opponent analysis (Line 245)
- `/home/user/PitchRank/frontend/lib/types.ts` - Team data contracts

### Database Schema
- `/home/user/PitchRank/supabase/migrations/20240101000000_initial_schema.sql` - Core tables
- `/home/user/PitchRank/supabase/migrations/20240201000003_add_match_review_queue.sql` - Review queue
- `/home/user/PitchRank/supabase/migrations/20250120130000_create_rankings_full.sql` - Rankings table

### Documentation
- `/home/user/PitchRank/TEAM_MATCHING_EXPLAINED.md` - Complete matching guide
- `/home/user/PitchRank/README_PITCHRANK_FRONTEND_DATA.md` - Frontend data contract

---

## Conclusion

"Unknown" teams in PitchRank appear due to:
1. **Games with NULL team_id_master** (failed/partial matches)
2. **Missing team names in lookups** (team not in teams table)
3. **NULL gender fallback** (rare, in ranking calculations)

The root cause is the **three-tier matching system** - when fuzzy matching fails or scores are below threshold, games remain partially unmatched.

**Quick Wins:**
1. Implement pre-import team verification
2. Add game filtering by match status in frontend
3. Use team ID fragments as fallback instead of "Unknown"

**Long-term:**
1. Create team name aliases table
2. Monitor matching metrics continuously
3. Implement automatic temporary team creation for unmapped teams

