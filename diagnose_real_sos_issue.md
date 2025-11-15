# SOS Issue Diagnosis

## What I Found

After extensive testing, I discovered that **my initial diagnosis may have been incorrect**.

### Original Hypothesis (PROBABLY WRONG)
I thought opponents were missing from `strength_map` because:
- Games are filtered to last 30 per team
- This creates asymmetry where Team B appears as `opp_id` but not `team_id`

### Why This Doesn't Actually Happen
In your codebase, games are ALWAYS created in mirrored pairs (see `data_adapter.py` lines 207-233):
- Each game creates TWO rows (home and away perspectives)
- When filtering to last 30 games per team, BOTH perspectives get filtered independently
- So if Team B has games, it will have rows as `team_id` in the filtered data

### The REAL Causes of Identical SOS Scores

After testing, I believe identical SOS scores come from:

1. **Similar opponents within leagues/divisions**
   - Teams in the same league play similar opponents
   - All get similar SOS values naturally

2. **Percentile normalization amplifies ties**
   - If 50 teams have raw SOS between 0.48-0.52, they all get normalized to ~0.50
   - Percentile ranking with `method="average"` gives identical values to ties

3. **Default values for edge cases**
   - Teams with no games after filtering: SOS = 0.5 (line 509)
   - Opponents not in rankings: strength = 0.35 (UNRANKED_SOS_BASE)

## My Fix

The fix I implemented (lines 459-509) estimates strength for opponents that don't appear as `team_id`.

**Status**: The fix is **technically correct** but may not address your specific issue because:
- It only triggers when opponents are truly missing from `strength_map`
- In normal operation with mirrored game data, this rarely happens
- The identical SOS scores you're seeing are likely from causes #1-#3 above

## Questions for You

To help me fix the RIGHT problem:

1. **How many teams have identical SOS?**
   - Is it like 5-10 teams, or hundreds?

2. **What are the actual SOS values?**
   - Are they all ~0.35 (unranked default)?
   - Are they all ~0.50 (no games default)?
   - Or are they varied values like 0.42, 0.58, etc.?

3. **Are these teams in the same age group/gender?**
   - SOS is normalized within age/gender cohorts
   - Teams in the same cohort playing similar opponents will have similar SOS

4. **Do these teams play in the same league/region?**
   - Teams in closed leagues naturally have similar SOS

## Next Steps

**Option 1: Keep the fix (safe)**
- It doesn't hurt anything
- It handles edge cases better
- Provides more accurate opponent strength estimation

**Option 2: Investigate the real cause**
- Need to see actual SOS distribution from your database
- Check if it's a normalization issue vs. a calculation issue
- Might need different solution (e.g., different normalization method)

**Option 3: Rollback and investigate first**
- Remove my fix
- Run rankings on real data
- Check logs for what's actually happening
- Then implement targeted fix

## My Recommendation

**Let's test with your actual data** to see:
1. If the fix triggers (check logs for "Found X opponents missing")
2. If SOS diversity improves after the fix
3. What the actual distribution looks like

Then we can decide if this fix is helpful or if we need a different approach.
