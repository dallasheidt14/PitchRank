# TGS Direct ID Alias Maintenance

## Issue Summary

When TGS teams are created during game imports, aliases were being created with `match_method='import'` even when a `provider_team_id` exists. This causes inconsistent matching behavior:

- **Expected**: Teams with `provider_team_id` should use `match_method='direct_id'` for fast Tier 1 matching
- **Actual**: Some aliases used `match_method='import'`, requiring Tier 2 lookup (slower)

## Root Cause

In `src/models/tgs_matcher.py`, the `_match_team()` method creates new teams with `match_method='import'` regardless of whether `provider_team_id` exists:

```python
# OLD CODE (line 592)
match_method='import',  # System-created during import
```

This is inconsistent with:
- GotSport teams (use `direct_id` when imported via `import_teams_enhanced.py`)
- Modular11 teams (use `direct_id` for provider team IDs)
- Manual team creation (dashboard uses `direct_id`)

## Solution

### 1. Fixed TGS Matcher - Match Method (✅ Done)

Updated `src/models/tgs_matcher.py` to use `direct_id` when `provider_team_id` exists:

```python
# NEW CODE (line ~592)
match_method = 'direct_id' if provider_team_id else 'import'
```

**Impact**: All NEW teams created during imports will automatically use `direct_id` if they have a `provider_team_id`.

### 2. Fixed TGS Matcher - Age Group Validation (✅ Done)

**Problem**: Even with `match_method='direct_id'`, matches were being rejected if the scraped game's `age_group` didn't exactly match the team's stored `age_group`. This is problematic because:
- TGS `provider_team_id` is unique per team (unlike Modular11 where club_id is shared)
- Age groups change over time (U13 → U14 during year rollover)
- Teams may play up/down age groups

**Solution**: Overrode `_match_by_provider_id()` in `TGSGameMatcher` to skip age_group validation:

```python
# NEW CODE (lines 545-615)
def _match_by_provider_id(self, provider_id, provider_team_id, age_group=None, gender=None):
    """
    Override base method to skip age_group validation for TGS.
    
    Unlike Modular11 where the same provider_team_id (club_id) is used for multiple
    age groups, TGS provider_team_id is unique per team. Therefore, we don't need
    age_group validation - if the provider_team_id matches, it's the correct team.
    """
    # ... skips age_group validation ...
```

**Impact**: Direct ID matches will no longer be rejected due to age_group mismatches. This ensures maximum match rate for TGS teams.

### 2. Maintenance Script (✅ Created)

Created `scripts/maintain_tgs_direct_id_aliases.py` to fix existing aliases:

```bash
# Preview changes
python scripts/maintain_tgs_direct_id_aliases.py --dry-run

# Apply fixes
python scripts/maintain_tgs_direct_id_aliases.py
```

**When to run**:
- After bulk imports
- Periodically (weekly/monthly)
- Before major event imports
- As part of CI/CD pipeline

### 3. One-Time Fix (✅ Done)

Ran `scripts/update_tgs_aliases_to_direct_id.py` to update ~1000 existing aliases.

## Going Forward

### Best Practices

1. **New Imports**: The fix ensures new teams automatically use `direct_id` ✅
2. **Maintenance**: Run maintenance script periodically to catch any edge cases
3. **Monitoring**: Check alias match_method distribution:
   ```sql
   SELECT match_method, COUNT(*) 
   FROM team_alias_map 
   WHERE provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'
     AND review_status = 'approved'
     AND provider_team_id IS NOT NULL
   GROUP BY match_method;
   ```

### Scalability

As you scrape more events:

1. **Automatic**: New teams will use `direct_id` automatically (no manual intervention)
2. **Maintenance**: Run `maintain_tgs_direct_id_aliases.py` after large imports
3. **Performance**: Direct ID matches are O(1) lookups vs O(n) fuzzy matching

### Example Workflow

```bash
# 1. Scrape event
python scripts/scrape_tgs_event.py --start-event 4000 --end-event 4100

# 2. Import games (new teams will automatically use direct_id)
python scripts/import_games_enhanced.py data/raw/tgs/tgs_events_*.csv tgs

# 3. Optional: Run maintenance to fix any edge cases
python scripts/maintain_tgs_direct_id_aliases.py
```

## Verification

To verify direct matches for an event:

```python
import pandas as pd
from supabase import create_client

# Load CSV
df = pd.read_csv('data/raw/tgs/tgs_events_XXXX_XXXX_*.csv')
team_ids = set(df['team_id'].dropna().unique().tolist() + 
               df['opponent_id'].dropna().unique().tolist())

# Check direct matches
tgs_provider_id = 'ea79aa6e-679f-4b5b-92b1-e9f502df7582'
direct_result = supabase.table('team_alias_map').select(
    'provider_team_id'
).eq('provider_id', tgs_provider_id).eq(
    'match_method', 'direct_id'
).eq('review_status', 'approved').execute()

direct_ids = {str(r['provider_team_id']) for r in direct_result.data}
matched = [tid for tid in team_ids if str(tid) in direct_ids]

print(f"Direct matches: {len(matched)}/{len(team_ids)} ({len(matched)/len(team_ids)*100:.1f}%)")
```

## Related Files

- `src/models/tgs_matcher.py` - Fixed to use `direct_id` for new teams
- `scripts/maintain_tgs_direct_id_aliases.py` - Maintenance script
- `scripts/update_tgs_aliases_to_direct_id.py` - One-time fix script

