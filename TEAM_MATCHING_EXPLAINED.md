# How Game Histories Are Matched to Master Team List

## Overview

When importing game histories, each game contains provider team IDs (like `544491` from GotSport) that need to be matched to master team UUIDs in your `teams` table. The system uses a **three-tier matching strategy** that prioritizes speed and accuracy.

---

## The Matching Process Flow

```
Game Import
    │
    ├─ For each game:
    │   ├─ Extract: home_team_id, away_team_id (provider IDs)
    │   ├─ Extract: team_name, club_name, age_group, gender
    │   │
    │   ├─ Match Home Team ────────────────────┐
    │   │                                       │
    │   │   Strategy 1: Direct ID Match       │
    │   │   ├─ Check alias cache (in-memory)   │
    │   │   ├─ Query team_alias_map            │
    │   │   └─ WHERE provider_id = X            │
    │   │       AND provider_team_id = Y        │
    │   │       AND match_method = 'direct_id'  │
    │   │                                       │
    │   │   Strategy 2: Alias Map Lookup       │
    │   │   ├─ Query team_alias_map            │
    │   │   └─ WHERE provider_id = X            │
    │   │       AND provider_team_id = Y        │
    │   │       AND review_status = 'approved'  │
    │   │                                       │
    │   │   Strategy 3: Fuzzy Matching         │
    │   │   ├─ Query teams by age_group+gender │
    │   │   ├─ Calculate similarity scores     │
    │   │   └─ Best match ≥ threshold?         │
    │   │       ├─ ≥0.90: Auto-approve         │
    │   │       ├─ 0.75-0.90: Review queue      │
    │   │       └─ <0.75: Reject               │
    │   │                                       │
    │   └─ Match Away Team ────────────────────┘
    │       (same process)
    │
    └─ Result: home_team_master_id, away_team_master_id
```

---

## Step-by-Step Matching Logic

### Step 1: Game Data Extraction

When a game is imported, it contains:

**From CSV/JSON:**
```python
game = {
    'provider': 'gotsport',
    'team_id': '544491',              # Provider team ID
    'team_name': 'FC Dallas U12 Boys',
    'club_name': 'FC Dallas',
    'opponent_id': '123456',
    'opponent_name': 'Solar SC U12',
    'age_group': 'u12',
    'gender': 'Male',
    'home_away': 'H',
    'goals_for': 3,
    'goals_against': 1
}
```

### Step 2: Call `match_game_history()`

The pipeline calls:
```python
matched_game = self.matcher.match_game_history(game)
```

This function:
1. Determines home/away teams based on `home_away` flag
2. Calls `_match_team()` for both home and away teams
3. Returns game record with `home_team_master_id` and `away_team_master_id`

### Step 3: Team Matching (`_match_team()`)

For each team (home and away), the system tries **three strategies in order**:

---

## Strategy 1: Direct ID Match (Fastest - O(1))

**When:** Team was imported via `import_teams_enhanced.py` with `provider_team_id`

**Where:** `team_alias_map` table (canonical source for provider→master mappings)

**Query Pattern:**
```sql
-- Tier 1: Direct ID match (from team importer)
SELECT team_id_master, review_status, match_method
FROM team_alias_map
WHERE provider_id = 'gotsport-uuid'
  AND provider_team_id = '544491'
  AND match_method = 'direct_id'
  AND review_status = 'approved'
LIMIT 1;

-- Tier 2: Fallback to any approved alias map entry
SELECT team_id_master, review_status, match_method
FROM team_alias_map
WHERE provider_id = 'gotsport-uuid'
  AND provider_team_id = '544491'
  AND review_status = 'approved'
LIMIT 1;
```

**Logic:**
- **First checks in-memory cache** (if preloaded at import start)
- Checks `team_alias_map` table (NOT `teams` table)
- `team_alias_map` is the canonical source for provider→master mappings
- Fastest method (single indexed lookup with composite index)
- Returns immediately if found
- Confidence: **100%** (1.0)
- Match method: `'direct_id'`

**Why `team_alias_map` and not `teams`?**
- Master teams don't store every provider's ID
- The alias table is the canonical map: `(provider_id, provider_team_id) → team_id_master`
- Keeps `teams` table as immutable master records
- Ensures consistency across all matching methods

**Example:**
```
Game has: team_id = '544491'
Alias cache/table has: provider_team_id = '544491', match_method='direct_id' 
  → team_id_master = 'abc-123-uuid'
Result: ✅ Matched instantly!
```

**Performance:** O(1) with composite index on `(provider_id, provider_team_id)`; ~1ms per lookup

---

## Strategy 2: Alias Map Lookup (Fast - O(1))

**When:** Team was matched previously (fuzzy match or manual review)

**Query:**
```sql
SELECT *
FROM team_alias_map
WHERE provider_id = 'gotsport-uuid'
  AND provider_team_id = '544491'  -- OR team_name LIKE '%FC Dallas%'
  AND review_status = 'approved'
LIMIT 1;
```

**Logic:**
- Checks historical mappings from previous imports
- Validates age_group and gender match
- Returns stored confidence score
- Match method: `'alias'`

**Why This Exists:**
- If a team was fuzzy-matched in a previous import, we don't need to re-match
- Saves computation time
- Ensures consistency across imports

---

## Strategy 3: Fuzzy Matching (Slower - O(n))

**When:** No direct ID or alias match found

**Step 3a: Query Candidate Teams**

```sql
SELECT team_id_master, team_name, club_name, age_group, gender, state_code
FROM teams
WHERE age_group = 'u12'
  AND gender = 'Male';
```

This returns all U12 Male teams from the master list.

**Step 3b: Calculate Similarity Scores**

For each candidate team, calculate a **weighted similarity score**:

```python
score = (
    team_name_similarity * 0.65 +      # 65% weight
    club_name_similarity * 0.25 +      # 25% weight
    age_group_match * 0.05 +           # 5% weight
    location_match * 0.05               # 5% weight
)
```

**Example Calculation:**

**Provider Team:**
- Name: `"FC Dallas U12 Boys"`
- Club: `"FC Dallas"`
- Age: `u12`
- Gender: `Male`

**Candidate Team:**
- Name: `"FC Dallas 12 Boys"`
- Club: `"FC Dallas"`
- Age: `u12`
- Gender: `Male`

**Normalization:**
1. Lowercase: `"fc dallas u12 boys"` → `"fc dallas 12 boys"`
2. Remove punctuation
3. Expand abbreviations: `"fc"` → `"football club"`
4. Remove suffixes: `"football club"` → removed

**Similarity Calculation:**
- Team name similarity: `0.95` (very similar after normalization)
- Club name similarity: `1.0` (identical)
- Age match: `1.0` (both u12)
- Location match: `0.0` (not provided)

**Final Score:**
```
score = (0.95 * 0.65) + (1.0 * 0.25) + (1.0 * 0.05) + (0.0 * 0.05)
      = 0.6175 + 0.25 + 0.05 + 0.0
      = 0.9175 (91.75%)
```

**Step 3c: Match Thresholds**

Based on the score:

**≥ 0.90 (90%)**: **Auto-Approve**
```python
# Create alias automatically
_create_alias(
    match_method='fuzzy_auto',
    confidence=0.9175,
    review_status='approved'
)
# Return: matched=True, team_id=<master_uuid>
```

**0.75 - 0.90 (75-90%)**: **Manual Review Queue**
```python
# Insert into team_match_review_queue (NOT team_alias_map)
_create_review_queue_entry(
    provider_id=provider_id,
    provider_team_id=provider_team_id,
    provider_team_name=team_name,
    suggested_master_team_id=fuzzy_match['team_id'],
    confidence_score=0.85,
    match_details={...},
    status='pending'
)
# Return: matched=False, team_id=None
# Game will be imported but team won't be matched until reviewed
# Once approved via review queue, alias is created and future matches become O(1)
```

**< 0.75 (75%)**: **Reject**
```python
# Don't create alias
# Return: matched=False, team_id=None
# Game will be imported but team won't be matched
```

---

## Normalization Details

Before comparing team names, both strings are normalized:

**1. Lowercase & Trim**
```
"FC Dallas U12 Boys" → "fc dallas u12 boys"
```

**2. Remove Punctuation**
```
"FC Dallas-U12 Boys!" → "fc dallas u12 boys"
```

**3. Expand Abbreviations**
```python
abbreviations = {
    'ys': 'youth soccer',
    'fc': 'football club',
    'sc': 'soccer club',
    'sa': 'soccer academy',
    'ac': 'academy'
}
```
```
"fc dallas" → "football club dallas"
```

**4. Remove Common Suffixes**
```python
suffixes = ['fc', 'sc', 'sa', 'ys', 'academy', 'soccer club', ...]
```
```
"football club dallas" → "dallas"
```

**5. Compress Whitespace**
```
"fc   dallas" → "fc dallas"
```

**Example Normalization:**
```
Original: "FC Dallas U12 Boys"
Normalized: "dallas"

Original: "FC Dallas 12 Boys"
Normalized: "dallas"

Result: Perfect match! (1.0 similarity)
```

---

## Club Name Weighting

Club name similarity gets **25% weight** and can significantly boost scores:

**Example:**
- Provider: `"FC Dallas U12"` from club `"FC Dallas"`
- Candidate 1: `"FC Dallas 12"` from club `"FC Dallas"` → **+0.25 boost**
- Candidate 2: `"FC Dallas 12"` from club `"Solar SC"` → No boost

**Identical Club Boost:**
If club names match exactly (after normalization), add **+0.05 bonus**:
```python
if club_similarity == 1.0:
    club_score += 0.05  # Bonus for identical clubs
```

---

## Match Status Determination

After matching both teams:

```python
if home_team_master_id and away_team_master_id:
    match_status = 'matched'      # ✅ Both teams matched
elif home_team_master_id or away_team_master_id:
    match_status = 'partial'       # ⚠️ One team matched
else:
    match_status = 'failed'        # ❌ Neither matched
```

**Game Import Behavior:**
- **`matched`**: Game imported with both team IDs
- **`partial`**: Game imported with one team ID (other is NULL)
- **`failed`**: Game imported but both team IDs are NULL (can't calculate rankings)

---

## Real-World Example

**Game from CSV:**
```python
{
    'team_id': '544491',
    'team_name': 'FC Dallas U12 Boys',
    'club_name': 'FC Dallas',
    'opponent_id': '123456',
    'opponent_name': 'Solar SC U12',
    'age_group': 'u12',
    'gender': 'Male'
}
```

**Matching Process:**

**Home Team (`544491`):**
1. ✅ **Direct ID Match**: Check `teams` table
   - Query: `WHERE provider_team_id = '544491'`
   - Found: `team_id_master = 'abc-123-uuid'`
   - **Result: Matched instantly!**

**Away Team (`123456`):**
1. ❌ **Direct ID Match**: Not found in `teams` table
2. ❌ **Alias Map**: Not found in `team_alias_map`
3. ✅ **Fuzzy Match**: 
   - Query: `WHERE age_group = 'u12' AND gender = 'Male'`
   - Found 50 candidates
   - Best match: `"Solar SC 12 Boys"` (club: `"Solar SC"`)
   - Score: `0.92` (92%)
   - **Result: Auto-approved, alias created**

**Final Game Record:**
```python
{
    'game_uid': 'gotsport:2024-11-01:123456:544491',
    'home_team_master_id': 'abc-123-uuid',      # ✅ Direct ID match
    'away_team_master_id': 'def-456-uuid',      # ✅ Fuzzy match (auto-approved)
    'match_status': 'matched'
}
```

---

## Performance Characteristics

**Strategy 1 (Direct ID):**
- **Speed**: O(1) - Single indexed lookup (or cache hit)
- **Accuracy**: 100%
- **Use Case**: Teams imported via master team list
- **Cache**: Preloaded at import start for instant lookups

**Strategy 2 (Alias Map):**
- **Speed**: O(1) - Single indexed lookup (or cache hit)
- **Accuracy**: 90-100% (stored confidence)
- **Use Case**: Previously matched teams (fuzzy or manual)

**Strategy 3 (Fuzzy):**
- **Speed**: O(n) - Must check all teams in age/gender cohort
- **Accuracy**: 75-95% (depends on name similarity)
- **Use Case**: New teams not in master list

**Typical Performance:**
- **Direct ID matches (cached)**: <0.1ms per team (in-memory lookup)
- **Direct ID matches (DB)**: ~1ms per team (indexed query)
- **Alias map matches (cached)**: <0.1ms per team
- **Alias map matches (DB)**: ~1-2ms per team
- **Fuzzy matches**: ~10-50ms per team (depends on cohort size)

**Caching Optimization:**
- At import start, all approved aliases for the provider are preloaded into memory
- Eliminates millions of tiny SELECT queries during imports
- Dramatically speeds up matching (cache hits are instant)

---

## Why This Three-Tier Approach?

1. **Speed**: Direct ID matches are instant (most common case)
2. **Consistency**: Alias map ensures same team always matches same way
3. **Flexibility**: Fuzzy matching handles name variations and new teams
4. **Accuracy**: High-confidence matches auto-approved, ambiguous ones reviewed

---

## Current Matching Statistics

From your database:
- **16,649 games** imported
- **14,031 fully matched** (84.3%) - Both teams matched
- **2,618 partially matched** (15.7%) - One team matched
- **0 unmatched** (0.0%) - Neither team matched

This suggests:
- Most teams are matching successfully
- Some teams may need manual review (partial matches)
- The matching system is working well overall

---

## Summary

The matching process is **hierarchical and optimized**:

1. **Try fastest first**: Direct ID lookup (instant)
2. **Check history**: Alias map lookup (instant, consistent)
3. **Fuzzy match**: Similarity scoring (slower, flexible)

This ensures:
- ✅ Fast imports (most teams match instantly)
- ✅ Consistent results (same team always matches same way)
- ✅ Handles edge cases (name variations, new teams)
- ✅ Data quality (high-confidence auto-approved, ambiguous reviewed)

