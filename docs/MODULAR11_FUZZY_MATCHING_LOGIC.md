# Modular11 Fuzzy Matching Logic - Detailed Explanation

## Overview

The Modular11 matcher uses an **ultra-conservative** fuzzy matching system designed to prevent incorrect matches. When no confident match is found, it creates a new team rather than forcing a match.

## Decision Flow

```
1. Alias Lookup (ALWAYS FIRST)
   ↓ (if no alias found)
2. Fuzzy Matching
   ↓ (if no confident match)
3. Create New Team
```

---

## Step 1: Alias Lookup (Priority #1)

**What it does:**
- Checks if a `provider_team_id` already has a mapping in `team_alias_map`
- If alias exists, validates age_group and gender match
- If valid, returns immediately (NO fuzzy matching)

**Why this is first:**
- Once a team is mapped, we trust that mapping
- Prevents re-matching teams that have already been reviewed/approved
- Fastest path (database lookup)

**Example:**
- `provider_team_id=102` → Already mapped to `Barca Residency Academy U16`
- Age validation: Incoming `U16` matches stored `u16` ✅
- **Result:** Match accepted immediately (confidence: 1.0)

---

## Step 2: Fuzzy Matching (Only if no alias)

### 2.1 Candidate Filtering

**Strict Filters Applied:**
1. **Age Group:** Must match exactly (case-insensitive)
   - Incoming: `U16` → Query: `age_group = 'u16'`
2. **Gender:** Must match exactly
   - Incoming: `Male` → Query: `gender = 'Male'`

**Why strict:**
- Prevents cross-age matches (U16 → U13)
- Prevents cross-gender matches
- Reduces false positives dramatically

### 2.2 Scoring Algorithm

For each candidate team, a **base similarity score** is calculated using weighted factors:

#### Score Components:

```
Final Score = Team Name Score + Club Name Score + Location Score + Age Score
```

**Weights (from config):**
- **Team Name:** 65% (primary identifier)
- **Club Name:** 25% (secondary identifier)
- **Location (State):** 5% (weak signal)
- **Age Group:** 5% (already filtered, so usually 1.0)

#### Team Name Similarity (65% weight)

**Method:** `SequenceMatcher.ratio()` with normalization

**Normalization steps:**
1. Convert to lowercase
2. Remove punctuation
3. Expand abbreviations:
   - `FC` → `football club`
   - `SC` → `soccer club`
   - `SA` → `soccer academy`
   - `AC` → `academy`
   - `YS` → `youth soccer`

**Example:**
- Incoming: `"Breakers FC U16 HD"`
- Normalized: `"breakers football club u16 hd"`
- Candidate: `"Breakers FC U16"`
- Normalized: `"breakers football club u16"`
- Similarity: ~0.95 (very high)

#### Club Name Similarity (25% weight)

**Smart Normalization:**
- Removes common suffixes: `FC`, `SC`, `SA`, `Academy`, `Soccer Club`, etc.
- Removes common prefixes: `FC `, `CF `, etc.

**Multiple Matching Strategies (takes best):**
1. **Direct match** after normalization → 1.0
2. **Partial ratio** (handles "IMG" vs "IMG Academy") → 0.0-1.0
3. **Token set ratio** (handles word reordering) → 0.0-1.0
4. **Substring match** (one contains the other) → 0.95
5. **First word match** (if ≥90% similar) → 0.9

**Example:**
- Incoming: `"IMG"` (club name)
- Candidate: `"IMG Academy"` (club name)
- After normalization: Both become `"img"`
- **Result:** Direct match → 1.0

**Boost:**
- If club similarity ≥ 0.90, add +0.05 bonus

#### Location Score (5% weight)

- Only if both teams have state codes
- Match = 0.05, No match = 0.0

#### Age Score (5% weight)

- Since we already filtered by age, this is usually 1.0 × 0.05 = 0.05
- Acts as a small bonus for age-matched teams

### 2.3 Token Overlap Requirement

**What it checks:**
- Do the two team names share at least one "major token"?

**Major tokens include:**
- Predefined list: `galaxy`, `strikers`, `ideasport`, `united`, `city`, `fc`, `academy`, etc.
- Any token ≥ 4 characters long

**Why this matters:**
- Prevents false matches between unrelated teams
- Example: `"City SC Southwest"` vs `"City FC North"` → Both have "City" ✅
- Example: `"Breakers FC"` vs `"Ballistic United"` → No overlap ❌

**Rejection if no overlap:**
- Even if similarity score is high, reject if no token overlap
- This is a **hard requirement** (cannot be bypassed)

### 2.4 Division Adjustment

**Division Logic:**
- Modular11 teams have divisions: `HD` (Homegrown) or `AD` (Academy)
- Division info is stored in `team_alias_map.division` column

**Adjustments:**
1. **Both have same division (HD=HD or AD=AD):**
   - **Bonus:** +0.05 to score
   - `division_match = True`

2. **Different divisions (HD vs AD):**
   - **Penalty:** -0.10 from score
   - `division_match = False`

3. **One has division, other doesn't:**
   - **Small penalty:** -0.02
   - `division_match = False`

4. **Neither has division:**
   - **Neutral:** No adjustment
   - `division_match = True`

**Example:**
- Incoming: `"Breakers FC U16 HD"` (division = HD)
- Candidate: `"Breakers FC U16"` (division = HD from alias)
- **Result:** +0.05 bonus, `division_match = True`

### 2.5 Final Score Calculation

```
base_score = team_score + club_score + location_score + age_score
final_score = base_score + division_adjustment
final_score = clamp(final_score, 0.0, 1.0)  # Ensure between 0 and 1
```

---

## Step 3: Acceptance Criteria (ALL must pass)

After scoring all candidates, the **best match** must meet **ALL** of these criteria:

### 3.1 Minimum Confidence Threshold

```
best_score >= 0.93
```

**Why 0.93?**
- Ultra-conservative threshold (vs 0.90 for GotSport)
- Only accepts very high confidence matches
- Prevents borderline matches

**Example from dry run:**
- `Breakers FC U16 HD` → Best score: 0.846
- **Rejected:** 0.846 < 0.93 ❌

### 3.2 Score Gap Requirement

```
(best_score - second_best_score) >= 0.07
```

**Why this matters:**
- If two candidates have similar scores, it's ambiguous
- Requires a clear winner (7% gap minimum)
- Prevents matches when multiple teams are equally likely

**Example from dry run:**
- `Ballistic United U16 HD` → Best: 0.600, Second: 0.600
- **Gap:** 0.000 < 0.07 ❌
- **Rejected:** Too ambiguous

### 3.3 Token Overlap Requirement

```
best_match.token_overlap == True
```

**Hard requirement:** Must share at least one major token

### 3.4 Division Match Requirement

```
(best_match.division_match == True) OR (division is None)
```

**Logic:**
- If incoming team has a division, it must match the candidate's division
- If incoming team has no division, this check is skipped

**Example from dry run:**
- `Breakers FC U16 HD` → Candidate has `AD` division
- **Rejected:** Division mismatch (HD ≠ AD) ❌

---

## Step 4: Rejection Reasons

If a match fails, the system logs **exact reasons**:

### Possible Rejection Reasons:

1. **`score < 0.93 required minimum`**
   - Best score was below threshold
   - Example: Score 0.846 < 0.93

2. **`score gap too small`**
   - Best and second-best scores too close
   - Example: Gap 0.0065 < 0.07

3. **`no token overlap`**
   - No shared major tokens between names
   - Hard requirement failed

4. **`division mismatch`**
   - Incoming division (HD/AD) doesn't match candidate division
   - Example: Incoming `HD`, candidate `AD`

**Example from dry run:**
```
Breakers FC U16 HD: 
  score < 0.93 required minimum (got 0.8459) | division mismatch
```

---

## Step 5: New Team Creation (When no match)

**When this happens:**
- No alias found
- Fuzzy matching failed (didn't meet all 4 criteria)

**What happens:**
1. **Create new team** in `teams` table:
   - Generate new `team_id_master` (UUID)
   - Store team name (with HD/AD suffix removed)
   - Store age_group, gender, club_name
   - Set `provider_id` and `provider_team_id`

2. **Create alias** in `team_alias_map`:
   - Link `provider_team_id` → `team_id_master`
   - `match_method = 'import'` (system-created)
   - `confidence = 1.0` (new team = 100% confidence)
   - Store `division` (HD/AD)

3. **Add to review queue** (`team_match_review_queue`):
   - Status: `pending`
   - Includes fuzzy match suggestions (top 5 candidates)
   - Allows manual review/merging later

**Why create new teams:**
- **Safety first:** Better to create a new team than force a wrong match
- **100% game ingestion:** All games get imported (no data loss)
- **Future merging:** Can merge teams later if needed
- **Rankings integrity:** Prevents polluting rankings with wrong matches

---

## Real Examples from Dry Run

### Example 1: Alias Match (Success)

```
Incoming: Barca Residency Academy U16 AD
Provider ID: 102

Step 1: Alias lookup
  → Found alias: provider_team_id=102 → team_id_master=48ad435f...
  → Team: Barca Residency Academy U16 (age=u16, gender=Male)
  → Age validation: U16 == u16 ✅
  
Result: MATCHED (alias, confidence: 1.0)
```

### Example 2: Fuzzy Match Rejected (Score too low)

```
Incoming: Breakers FC U16 HD
Provider ID: 1346

Step 1: Alias lookup
  → No alias found

Step 2: Fuzzy matching
  → Found 100+ candidates (age=u16, gender=Male)
  → Best match: "Breakers FC U16" (score: 0.846)
  → Second best: 0.649
  → Gap: 0.197 ✅
  → Token overlap: Yes ✅
  → Division: Candidate has AD, incoming is HD ❌
  
  Final score after division penalty: 0.746
  
Step 3: Acceptance check
  ❌ Score 0.746 < 0.93 (required minimum)
  ❌ Division mismatch
  
Result: REJECTED → New team created
```

### Example 3: Fuzzy Match Rejected (Gap too small)

```
Incoming: Ballistic United U16 HD

Step 2: Fuzzy matching
  → Best match: "Ballistic United U16" (score: 0.600)
  → Second best: "Ballistic United U15" (score: 0.600)
  → Gap: 0.000 ❌
  
Step 3: Acceptance check
  ❌ Score 0.600 < 0.93
  ❌ Gap 0.000 < 0.07 (too ambiguous)
  
Result: REJECTED → New team created
```

### Example 4: New Team Created

```
Incoming: Metropolitan Oval U16 HD
Provider ID: 1234

Step 1: Alias lookup
  → No alias found

Step 2: Fuzzy matching
  → Found candidates, but none met all 4 criteria
  → Best score: 0.45 (too low)
  
Step 3: Create new team
  → Generated team_id_master: 7fedb0de-7b59-4853-ab0d-09702d208519
  → Team name: "Metropolitan Oval U16" (HD suffix removed)
  → Created alias: provider_team_id=1234 → team_id_master=7fedb0de...
  → Added to review queue with suggestions
  
Result: NEW TEAM CREATED (confidence: 1.0)
```

---

## Summary Statistics from Dry Run

**Total Teams Processed:** 38

**Breakdown:**
- **Alias Matches:** 0 (no existing aliases)
- **Fuzzy Matches Accepted:** 0 (all rejected due to strict thresholds)
- **Fuzzy Matches Rejected:** 7
  - All had scores < 0.93
  - Most had division mismatches
  - Some had gaps too small
- **New Teams Created:** 8
  - All U16 teams
  - Mix of HD (7) and AD (1)
- **Review Queue Entries:** 1

**Key Insight:**
The system is working as designed - it's being **ultra-conservative** and creating new teams when it can't confidently match, which prevents incorrect matches.

---

## Configuration Constants

```python
MODULAR11_MIN_CONFIDENCE = 0.93      # Minimum score to accept (vs 0.90 for GotSport)
MODULAR11_MIN_GAP = 0.07             # Minimum gap between best and second-best
MODULAR11_DIVISION_MATCH_BONUS = 0.05 # Bonus for matching division
MODULAR11_DIVISION_MISMATCH_PENALTY = 0.10 # Penalty for mismatched division
```

---

## Why This Approach?

1. **No Wrong Matches:** Better to create a new team than force a wrong match
2. **100% Game Ingestion:** All games get imported (no data loss)
3. **Future Automation:** Can merge teams later if needed
4. **Rankings Integrity:** Prevents polluting rankings with wrong matches
5. **Manual Review:** Review queue allows human verification
6. **Isolated from GotSport:** Modular11 logic doesn't affect other providers

---

## Next Steps After Dry Run

1. **Review the summary** to see which teams were created
2. **Check review queue** for teams that need manual mapping
3. **Manually approve aliases** if fuzzy matches were close but rejected
4. **Merge teams** if duplicates were created
5. **Re-run import** after mapping to link games to correct teams













