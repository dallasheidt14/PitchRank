---
name: rankings-algorithm
description: PitchRank v53e ranking algorithm knowledge - calculation flow, validation, PowerScore bounds
---

# Rankings Algorithm Skill for PitchRank

You are working on PitchRank's ranking system. This skill explains the algorithm.

## Ranking Pipeline

```
┌─────────────────┐
│  Fetch Games    │  365-day lookback window
│  (from Supabase)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Resolve Merges  │  Apply team_merge_map
│                 │  Deprecated → Canonical
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  v53e Base      │  Win/loss/draw → base score
│  Calculation    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SOS Iterations │  3 passes of Strength of Schedule
│  (3 passes)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ML Layer 13    │  XGBoost predictive adjustment
│  (optional)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Normalize      │  Scale to [0.0, 1.0]
│  PowerScore     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Save to DB     │  rankings_full + current_rankings
└─────────────────┘
```

## v53e Algorithm Components

### Base Score
```python
# Win = 3 points, Draw = 1 point, Loss = 0 points
# Plus goal differential (capped)
base_score = (wins * 3 + draws * 1) / games_played
goal_diff_bonus = min(goal_diff / games_played, 0.5)  # Capped at 0.5
```

### Strength of Schedule (SOS)
```python
# 3 iterations to stabilize
for iteration in range(3):
    for team in teams:
        opponent_scores = [get_score(opp) for opp in team.opponents]
        team.sos = mean(opponent_scores)
        team.adjusted_score = team.base_score * (1 + team.sos * weight)
```

### Recency Weighting
```python
# Recent games matter more
days_ago = (today - game_date).days
recency_weight = max(0.5, 1.0 - (days_ago / 365))
```

## PowerScore Requirements

### MUST be in [0.0, 1.0]
```python
# Validation check
assert 0.0 <= power_score <= 1.0, f"Invalid PowerScore: {power_score}"

# After calculation
power_score = max(0.0, min(1.0, power_score))  # Clamp to bounds
```

### Higher = Better
- 0.95+ = Elite national team
- 0.80-0.95 = Top tier
- 0.50-0.80 = Competitive
- 0.20-0.50 = Developing
- <0.20 = Limited data or new team

## ML Layer 13

### When Enabled
```python
if args.ml:
    result = await compute_all_cohorts(
        supabase_client=supabase,
        lookback_days=365,
        # ... other params
    )
```

### What It Does
- XGBoost model trained on historical outcomes
- Predicts expected performance vs actual
- Adjusts base v53e score up/down
- Improves ranking accuracy for edge cases

## Calculation Arguments

```bash
python scripts/calculate_rankings.py \
    --ml                    # Enable ML layer
    --lookback-days 365     # Game window
    --dry-run              # Don't save to DB
    --force-rebuild        # Ignore cache
    --age-group u14        # Filter age group
    --gender Male          # Filter gender
```

## Merge Resolution

### During Calculation
```python
from src.utils.merge_resolver import MergeResolver

resolver = MergeResolver(supabase)
resolver.load_merge_map()

# Resolve team IDs in game data
games_df['home_team_id'] = games_df['home_team_id'].apply(resolver.resolve)
games_df['away_team_id'] = games_df['away_team_id'].apply(resolver.resolve)
```

### Why Important
- Deprecated teams' games count toward canonical team
- Prevents double-counting merged teams
- Maintains historical continuity

## Validation Checklist

Before saving rankings:

1. **PowerScore bounds**
   ```python
   violations = teams_df[~teams_df['power_score'].between(0.0, 1.0)]
   assert len(violations) == 0, f"{len(violations)} out of bounds"
   ```

2. **Minimum games**
   ```python
   # Teams need minimum games for reliable ranking
   MIN_GAMES = 5
   reliable = teams_df[teams_df['games_played'] >= MIN_GAMES]
   ```

3. **No duplicate team IDs**
   ```python
   assert teams_df['team_id'].is_unique
   ```

4. **Rankings are assigned**
   ```python
   assert teams_df['national_rank'].notna().all()
   ```

## Output Tables

### `rankings_full` (Primary)
```sql
team_id                 UUID
national_power_score    FLOAT (0.0-1.0)
national_rank           INT
state_rank              INT
age_group               TEXT
gender                  TEXT
state_code              TEXT
games_played            INT
wins, losses, draws     INT
goals_for, goals_against INT
strength_of_schedule    FLOAT
last_calculated         TIMESTAMPTZ
```

### `current_rankings` (Legacy)
```sql
team_id                 UUID
national_power_score    FLOAT
national_rank           INT
games_played            INT
-- Subset of rankings_full for backward compatibility
```

## Dry Run Pattern

```python
if args.dry_run:
    console.print("[yellow]Dry run - rankings not saved[/yellow]")
    # Still show summary
    console.print(f"Teams ranked: {len(teams_df)}")
    console.print(f"PowerScore range: {min_score:.4f} - {max_score:.4f}")
else:
    await save_rankings_to_supabase(supabase, teams_df)
```

## Common Issues

### "0 teams ranked"
- Check if games exist in lookback window
- Verify Supabase connectivity
- Check filter parameters

### PowerScore out of bounds
- Normalization step may have failed
- Check for NaN values in calculation
- Verify SOS calculation didn't produce infinity

### Rankings stale
- Monday workflow may have failed
- Check GitHub Actions logs
- Verify Supabase write permissions
