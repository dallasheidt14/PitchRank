# SincSports Team Matching Scenarios

## Overview

When importing SincSports teams and games, the system handles several scenarios based on whether teams already exist in the database. The matching system uses a **3-tier strategy** that works across providers.

---

## Scenario 1: Team Already Exists from SincSports

**Example:**
- We previously imported `NCM14762` (NC Fusion U12 PRE ECNL BOYS RED)
- We're importing it again

**What Happens:**
1. ✅ Import script checks `teams` table by `provider_id` + `provider_team_id`
2. ✅ Finds existing team → Skips creation
3. ✅ Ensures alias mapping exists in `team_alias_map`
4. ✅ Game import uses existing team → **Full match**

**Result:** No duplicate teams, games match perfectly

---

## Scenario 2: Team Exists from Different Provider (GotSport)

**Example:**
- GotSport has: `"FC Dallas U12 Boys"` (ID: `544491`)
- SincSports has: `"FC Dallas U12 Boys"` (ID: `NCM12345`)

**What Happens:**

### During Team Import:
1. ✅ Import script checks `teams` table by `provider_id` + `provider_team_id`
2. ❌ No match found (different provider)
3. ✅ Creates new team record with SincSports provider ID
4. ✅ Creates alias mapping: `NCM12345` → `new_master_team_id`

**Problem:** This creates a **duplicate team**! 😱

### During Game Import (Better Approach):
1. ✅ Game matcher tries to match `NCM12345`
2. ✅ **Strategy 1**: Direct ID match → Not found (no alias yet)
3. ✅ **Strategy 2**: Alias map lookup → Not found
4. ✅ **Strategy 3**: Fuzzy matching → Finds `"FC Dallas U12 Boys"` from GotSport!
5. ✅ If confidence ≥ 90%:
   - Auto-links SincSports ID to existing GotSport master team
   - Creates alias mapping: `NCM12345` → `existing_gotsport_master_id`
   - **No duplicate team created**
   - Games from both providers contribute to same team

**Result:** Same team from different providers → Same master team ✅

---

## Scenario 3: Partial Match (One Team Exists, Opponent Doesn't)

**Example:**
- Home team `NCM14762` exists (from SincSports)
- Away team `SCM14140` doesn't exist

**What Happens:**
1. ✅ Home team matches → `home_team_master_id` = `c37a082c...`
2. ❌ Away team doesn't match → `away_team_master_id` = `None`
3. ✅ Match status = `"partial"`
4. ✅ Import pipeline accepts partial matches
5. ⚠️ Game is imported but incomplete (missing away team)

**Result:** Game imported with `match_status = 'partial'`

---

## Scenario 4: Neither Team Exists

**Example:**
- Both teams are new SincSports teams

**What Happens:**
1. ❌ Home team doesn't match → `home_team_master_id` = `None`
2. ❌ Away team doesn't match → `away_team_master_id` = `None`
3. ❌ Match status = `"failed"`
4. ⚠️ Import pipeline may still accept (depending on configuration)
5. ⚠️ Game imported but incomplete

**Result:** Game imported with `match_status = 'failed'` (needs manual review)

---

## Best Practice: Import Teams First, Then Games

### Recommended Workflow:

1. **Import Teams** (with fuzzy matching):
   ```python
   # Import SincSports teams
   python scripts/import_sincsports_teams.py --team-ids NCM14762 SCM14140 ...
   ```

2. **During Team Import:**
   - If team exists from SincSports → Skip
   - If team exists from GotSport → **Should use fuzzy matching to link!**
   - If team doesn't exist → Create new team

3. **Import Games**:
   ```python
   # Import games (teams should already be matched)
   python scripts/test_sincsports_import_full.py
   ```

### Current Limitation:

**The team import script doesn't use fuzzy matching!** It only checks for exact provider ID matches. This means:

- ✅ If team exists from SincSports → Works perfectly
- ❌ If team exists from GotSport → Creates duplicate team

**Solution:** We should enhance the team import script to use fuzzy matching before creating new teams.

---

## How Fuzzy Matching Works

### Matching Criteria (Weighted):
- **Team Name**: 65% weight
- **Club Name**: 25% weight  
- **Age Group**: 5% weight
- **Location**: 5% weight

### Confidence Thresholds:
- **≥ 90%**: Auto-approve → Create alias automatically
- **75-90%**: Review queue → Manual review needed
- **< 75%**: Reject → No match

### Example Match:
```
GotSport Team:
  Name: "FC Dallas U12 Boys"
  Club: "FC Dallas"
  Age: u12
  Gender: Male

SincSports Team:
  Name: "FC Dallas U12 Boys"
  Club: "FC Dallas"
  Age: u12
  Gender: Male

Match Score: 100% → Auto-linked! ✅
```

---

## Recommendations

### 1. Enhance Team Import Script

Add fuzzy matching to `scripts/import_sincsports_teams.py`:

```python
# Before creating new team, try fuzzy matching
matcher = GameHistoryMatcher(supabase, provider_id=provider_id)
match_result = matcher._match_team(
    provider_id=provider_id,
    provider_team_id=team_id,
    team_name=team_data['team_name'],
    age_group=team_data['age_group'],
    gender=team_data['gender'],
    club_name=team_data.get('club_name')
)

if match_result['matched']:
    # Use existing master team
    master_id = match_result['team_id']
    # Create alias mapping
else:
    # Create new team
    master_id = create_new_team(...)
```

### 2. Extract Opponent Teams Automatically

When importing games, automatically extract opponent IDs and import those teams too:

```python
# Extract unique opponent IDs from games
opponent_ids = set()
for game in games:
    if game.opponent_id:
        opponent_ids.add(game.opponent_id)

# Import opponent teams
import_teams(list(opponent_ids))
```

### 3. Handle Partial Matches

The import pipeline accepts partial matches, but we should:
- Log partial matches for review
- Optionally auto-create missing teams during import
- Provide dashboard to review/manually match teams

---

## Summary

| Scenario | Home Team | Away Team | Result |
|----------|-----------|-----------|---------|
| Both exist (same provider) | ✅ Matched | ✅ Matched | **Full match** |
| Both exist (different providers) | ✅ Fuzzy matched | ✅ Fuzzy matched | **Full match** (if ≥90% confidence) |
| One exists | ✅ Matched | ❌ Not found | **Partial match** |
| Neither exists | ❌ Not found | ❌ Not found | **Failed match** |

**Key Insight:** The system is designed to handle cross-provider matching through fuzzy matching, but the team import script should be enhanced to use it proactively to avoid duplicates.

















