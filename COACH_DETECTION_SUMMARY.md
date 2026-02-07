# Coach Name Detection Enhancement Summary

## Problem
The team matching script (`scripts/find_queue_matches.py`) was incorrectly matching teams with different coach names as the same team.

**Example failure:**
- ❌ "Atletico Dallas Youth 15G **Riedell** (CTX)" matched to "Atlético Dallas Youth 2015 **Davis** CTX"
- These are **different teams** (different coaches = different squads), but were being matched as duplicates

## Root Cause
The `extract_team_variant()` function detected colors (Blue, Red) and directions (North, South) as team variants, but had incomplete coach name detection that missed common patterns.

## Solution
Enhanced `extract_team_variant()` with robust coach name detection:

### Key Improvements

1. **Position-based detection** - Coach names typically appear AFTER age/year but BEFORE regions
   - Pattern: `"Club [Age] [CoachName] (Region)"` or `"Club [Age] [CoachName] Region"`
   - Examples: `"15G Riedell (CTX)"`, `"2015 Davis CTX"`, `"2014 Thompson"`, `"U14 Blanton"`

2. **Smart filtering** - Exclude known non-coach words:
   - **Region codes**: CTX, PHX, ATX, DAL, etc. (100+ codes)
   - **Program names**: Aspire, Rise, Revolution, Legacy, etc.
   - **Common words**: ECNL, Academy, Select, Premier, etc.
   - **Colors/directions**: Already handled by existing logic

3. **Improved logic order**:
   - Check colors/directions first (highest priority)
   - Check roman numerals (I, II, III)
   - **NEW:** Extract coach name from position after age
   - **NEW:** Filter coach-in-parens vs region-in-parens
   - Fallback to legacy patterns

## Testing Results

All test cases pass ✅:

```
✅ 'Atletico Dallas Youth 15G Riedell (CTX)' → variant: riedell
✅ 'Atlético Dallas Youth 2015 Davis CTX' → variant: davis
✅ 'FC Tampa 2014 Thompson' → variant: thompson
✅ 'Phoenix Rising U14 Clark' → variant: clark
✅ 'Real Salt Lake 2013 Blanton' → variant: blanton
✅ 'FC Dallas 2014 Blue' → variant: blue (color, not coach)
✅ 'Select North 2015' → variant: north (direction, not coach)
✅ 'Team 2014 (CTX)' → variant: None (region filtered out)
✅ 'Soccer Club 15G Aspire (PHX)' → variant: None (program name filtered)
✅ 'United 2014 ECNL' → variant: None (league, no coach)
✅ 'Club 2015 (Davis)' → variant: davis (coach in parens)
```

**Critical test passes:**
- Team 1: "Atletico Dallas Youth 15G Riedell (CTX)" → variant: `riedell`
- Team 2: "Atlético Dallas Youth 2015 Davis CTX" → variant: `davis`
- Result: **Variants differ → teams will NOT be matched** ✅

## Impact

This enhancement prevents false positives in team matching:
- Teams with different coach names will no longer be incorrectly merged
- More accurate team deduplication
- Better data quality for rankings

## Files Changed

- `scripts/find_queue_matches.py` - Enhanced `extract_team_variant()` function
- Commit: `91ea121` - "feat: Add coach name detection to prevent false team matches"

## Future Considerations

- Monitor for edge cases where coach names might be missed
- Consider maintaining a coach name database if patterns become more complex
- May need to add more region codes or program names to filter lists over time
