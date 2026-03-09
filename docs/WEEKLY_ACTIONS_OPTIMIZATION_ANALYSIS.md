# Weekly Actions – Optimization & Accuracy Analysis

## Current Schedule (UTC)

| Time (UTC) | Day | Workflow | What It Does |
|------------|-----|----------|---------------|
| 16:00 | Mon | Match State from Club | Club standardization + state matching |
| 16:05 | Mon | Fix Age Year | Team name normalization + age fix |
| 17:00 | Mon | Update Missing Club Names | Backfill `club_name` from GotSport API |
| 17:00 | Tue | Data Hygiene | Club → Team Names → Fuzzy Merge → Queue |

## Dependency Chain

```
Update Club Names ──► club_name populated (for teams missing it)
        │
        ▼
Club Standardization ──► "Solar Soccer Club" → "Solar SC" (full_club_analysis)
        │
        ├──► Match State from Club (uses club_name to infer state_code)
        │
        ▼
Team Name Normalization ──► "14B" → "2014" (normalize_team_names)
        │
        ├──► Fix Age Year (extracts birth year from team_name)
        │
        ▼
Fuzzy Merge, Queue (hygiene Steps 3–4)
```

## Critical Issues

### 1. **Update Club Names runs AFTER Match State** ❌

- **Match State** uses `club_name` to match teams to state codes.
- **Update Club Names** backfills missing `club_name` from GotSport.
- **Current order:** Match State 16:00 → Update Club Names 17:00
- **Correct order:** Update Club Names first → Match State second

Teams that get `club_name` from Update Club Names at 17:00 are never used by Match State, which already ran at 16:00.

### 2. **Fix Age runs before club standardization completes**

- **Hygiene rule:** Club names must be standardized before team name normalization.
- **Fix Age** runs `normalize_team_names` at 16:05.
- **Club standardization** runs inside Match State at 16:00.
- Match State and Fix Age are separate workflows; Fix Age can start while Match State is still running. If club standardization is slow, Fix Age may normalize before clubs are standardized.

### 3. **Redundancy**

- **Club standardization** runs in Match State (Mon) and again in Hygiene (Tue).
- **Team name normalization** runs in Fix Age (Mon) and again in Hygiene (Tue).

Same work is done twice per week.

## Recommended Setup

### Option A: Fix Order Only (Minimal Change)

Adjust Monday schedule so dependencies are respected:

| Time (UTC) | Workflow | Rationale |
|------------|----------|-----------|
| 16:00 | **Update Missing Club Names** | First: backfill club names |
| 17:00 | **Match State from Club** | Second: use club names for state |
| 17:30 | **Fix Age Year** | Third: after Match State (club standardization) is done |

- Pros: Small change, fixes dependency order.
- Cons: Redundancy with Tuesday hygiene remains.

### Option B: Consolidate into Hygiene (Most Accurate)

Move Match State and Fix Age into the Tuesday hygiene pipeline:

**Monday 17:00 UTC:** Update Missing Club Names only

**Tuesday 17:00 UTC:** Full pipeline
1. Club standardization
2. Team name normalization
3. Fuzzy duplicate merge
4. Match review queue
5. **Match State from Club** (new Step 5)
6. **Fix Age Year** (new Step 6)

- Pros: Correct order, no redundancy, single pipeline.
- Cons: Match State and Fix Age run Tuesday instead of Monday.

### Option C: Hybrid (Balance)

**Monday:**
- 16:00: Update Missing Club Names
- 17:00: Match State from Club (club standardization + state match)

**Tuesday:**
- 17:00: Hygiene Steps 1–4 + **Fix Age Year** as Step 5

- Pros: Update Club Names and Match State run Monday; Fix Age runs after hygiene (no redundant normalize).
- Cons: Club standardization still runs twice (Mon in Match State, Tue in hygiene).

## Recommendation

**Option B (Consolidate)** — implemented.

1. Update Club Names runs Monday 17:00 UTC to backfill `club_name`.
2. Tuesday hygiene runs in order: Club → Team Names → Fuzzy → Queue → Match State (Step 5) → Fix Age (Step 6).
3. No duplicate club or team name work.
4. Match State and Fix Age workflows: schedule removed; manual trigger only.

## Dry Run Before Going Live

Before the first live run, trigger the hygiene workflow manually with **dry_run=true**:

1. Go to Actions → Weekly Data Hygiene → Run workflow
2. Set **dry_run** to `true`
3. Run

This runs all 6 steps in scan-only mode (no DB writes). Check the step summary and logs to verify counts and behavior. Then run again with dry_run=false to apply changes.
