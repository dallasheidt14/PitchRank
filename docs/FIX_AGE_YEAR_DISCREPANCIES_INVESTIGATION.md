# Fix Age Year Discrepancies – Investigation

## Current State

**Workflow:** `.github/workflows/fix-age-year-discrepancies.yml`  
**Script:** `scripts/fix_team_age_groups.py`  
**Schedule:** Monday 9:05 AM Mountain

### What It Does

1. Fetches teams from DB
2. Extracts birth year from `team_name` via regex (looks for `20XX` patterns)
3. Calculates expected `age_group` from birth year: `current_year - birth_year + 1` → U12, etc.
4. Updates teams where `age_group` ≠ expected

### Issues Found

| Issue | Impact |
|-------|--------|
| **`inputs` vs `github.event.inputs`** | Workflow uses `inputs.dry_run` – in GitHub Actions, workflow_dispatch inputs are at `github.event.inputs.X`. `inputs` context doesn't exist; inputs may not work on manual runs. |
| **No `is_deprecated` filter** | Script processes all teams; should skip deprecated teams. |
| **Runs before team name normalization** | `extract_birth_year` only finds `20XX` patterns. Names like "Team 14B" or "B2014" may not match. `normalize_team_names.py` (hygiene Step 2) converts "14B"→"2014" but runs Tuesday; this runs Monday. |
| **Workflow not aligned with others** | Uses setup-python@v4, no env block, no pip cache, no logs/artifacts, no step summary. |
| **No optional pre-step** | Match-state-from-club runs club standardization first for better results. This could run `normalize_team_names` first for better birth-year extraction. |

### Data Hygiene Pipeline Order

```
Tuesday: Step 1 (club) → Step 2 (team names) → Step 3 (fuzzy merge) → Step 4 (queue)
Monday 9:05: fix_team_age_groups (runs BEFORE hygiene)
```

So fix_team_age_groups runs on **un-normalized** team names. Names like "FC Premier 14B" won't yield 2014 because the regex expects `20\d{2}`.

### Optimization Options

1. **Run normalize_team_names first** (like match-state runs full_club_analysis first)
   - Converts "14B"→"2014", "U14B"→"U14", etc.
   - Better birth-year extraction from normalized names

2. **Improve extract_birth_year** to handle short formats
   - Use `team_name_normalizer.parse_age_gender` or add patterns for "14B", "B14", "U14"
   - Fallback when 20XX not found

3. **Exclude deprecated teams** in the fetch query

4. **Align workflow** with match-state-from-club:
   - env block, setup-python@v5, cache, verify secrets
   - Optional Step 1: normalize_team_names
   - Logs, artifacts, step summary
   - Fix `inputs` → `github.event.inputs`

### Recommendation

- Add optional Step 1: `normalize_team_names.py --all-teams` before fix (default: true for manual, true for schedule)
- Fix `github.event.inputs` bug
- Add `is_deprecated` filter to script
- Align workflow structure with other upgraded actions
- Optionally improve `extract_birth_year` for short formats (14B, B14) as fallback
