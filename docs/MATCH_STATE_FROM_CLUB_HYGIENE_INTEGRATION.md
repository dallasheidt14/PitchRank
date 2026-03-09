# match_state_from_club + Data Hygiene Integration

## Overview

`match_state_from_club.py` now reuses logic from the **data-hygiene-weekly** pipeline (Steps 1–3) to improve state code matching from club names.

## Logic Reused

### Step 1: Club Name Standardization (full_club_analysis.py)

**`normalize_for_grouping()`** – Club names are normalized the same way as in the hygiene pipeline:

- Suffix variations: "Soccer Club" / "S.C." → ` sc`
- Suffix variations: "Football Club" / "F.C." / "Futbol Club" → ` fc`
- Preserves FC vs SC distinction: "FC Dallas" ≠ "Dallas SC" (different clubs)
- Strips `(XX)` before normalizing so "Titans FC (CA)" matches "Titans FC"

This alignment means clubs standardized by the weekly hygiene run will match our lookup.

### Step 3: Fuzzy Matching (find_fuzzy_duplicate_teams.py)

**SequenceMatcher fallback** – When exact normalized match fails:

- Uses `SequenceMatcher(None, a, b).ratio()` (same as fuzzy duplicate merge)
- Threshold: 0.90 (aligned with workflow `--min-score 0.90`)
- First-word index: only compares against clubs sharing the first word (keeps it fast)
- Only single-state clubs are considered (no multi-state ambiguity)

## Match Confidence Types

| Type          | Description                                      |
|---------------|--------------------------------------------------|
| `single_state`| Exact normalized club match (highest confidence)  |
| `from_club_name` | State extracted from `(XX)` in club name      |
| `fuzzy_match` | SequenceMatcher ≥ 0.90 (review recommended)     |

## Results (Dry Run)

| Metric              | Before | After |
|---------------------|--------|-------|
| Matched             | 14     | 141   |
| No match            | 667    | 540   |
| By confidence       | -      | exact=122, (XX)=1, fuzzy=18 |

## Pipeline Order

The hygiene pipeline runs **before** state matching in the weekly flow:

1. **Step 1** – Club names standardized → cleaner `club_name` values
2. **Step 2** – Team names normalized (not used for state matching)
3. **Step 3** – Fuzzy duplicate merge (same SequenceMatcher logic)
4. **State match** – `match_state_from_club.py` uses the cleaned club names

Running `match_state_from_club` after Step 1 yields more exact matches.
