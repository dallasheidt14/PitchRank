# SOS Issue Analysis: Identical Scores

## Summary

Many teams are getting identical SOS scores because opponents are missing from the `strength_map`, causing them all to default to the same value (0.35).

## Root Cause

The issue occurs in `/home/user/PitchRank/src/etl/v53e.py` at **line 456-477**:

### How it happens:

1. **Game Filtering (Line 224)**:
   ```python
   g = g[g["rank_recency"] <= cfg.MAX_GAMES_FOR_RANK].copy()
   ```
   - Only keeps the last 30 games PER TEAM (MAX_GAMES_FOR_RANK = 30)
   - This is calculated per `team_id`, so each team's games are filtered independently

2. **Asymmetric Filtering**:
   - If Team A played Team B, the game appears twice (mirrored data):
     - Row 1: `team_id=A, opp_id=B` (A's perspective)
     - Row 2: `team_id=B, opp_id=A` (B's perspective)

   - After rank_recency filtering:
     - If this game was one of A's recent 30 games → Row 1 is **KEPT**
     - If this game was NOT one of B's recent 30 games → Row 2 is **FILTERED OUT**

   - Result: `g` contains a row where `opp_id=B`, but NO row where `team_id=B`

3. **Team DataFrame Creation (Line 266)**:
   ```python
   team = g.groupby(["team_id", "age", "gender"], as_index=False).agg({...})
   ```
   - Groups by `team_id` only
   - Team B won't appear in `team` if all rows where `team_id=B` were filtered out
   - Even though Team B appears as `opp_id` in Team A's row!

4. **Strength Map Creation (Line 456)**:
   ```python
   strength_map = dict(zip(team["team_id"], team["abs_strength"]))
   ```
   - Only includes teams that appear in the `team` dataframe
   - Team B is NOT in `strength_map`

5. **SOS Calculation (Line 477)**:
   ```python
   g_sos["opp_strength"] = g_sos["opp_id"].map(lambda o: strength_map.get(o, cfg.UNRANKED_SOS_BASE))
   ```
   - When calculating Team A's SOS, it looks up opponent B in `strength_map`
   - Team B is missing → defaults to `UNRANKED_SOS_BASE` (0.35)
   - **If many teams have opponents missing from strength_map, they all get 0.35!**

## Example Scenario

### Setup:
- Team A: 20 total games (all kept)
- Team B: 80 total games (only last 30 kept)
- Team C: 90 total games (only last 30 kept)
- Team D: 100 total games (only last 30 kept)
- Teams A, X, Y, Z each played B, C, D in their older games

### What Happens:
```
Team A's games: A vs B (kept), A vs C (kept), A vs D (kept)
Team X's games: X vs B (kept), X vs C (kept), X vs D (kept)
Team Y's games: Y vs B (kept), Y vs C (kept), Y vs D (kept)
Team Z's games: Z vs B (kept), Z vs C (kept), Z vs D (kept)

But from B's perspective:
- Games vs A, X, Y, Z were in B's games #40-50 (FILTERED OUT)
- Only B's last 30 games are kept

Result:
- strength_map MISSING: Team B, Team C, Team D
- All opponents for A, X, Y, Z default to 0.35
- All four teams get identical SOS = 0.35!
```

## Impact

1. **Immediate Impact**: Teams with similar opponent profiles get identical SOS scores
2. **After Normalization**: Within age/gender cohorts, multiple teams with identical raw SOS get the same normalized SOS
3. **User Experience**: Rankings appear incorrect because many teams show identical SOS values

## Proof

See debugging scripts:
- `debug_sos.py`: Demonstrates how missing opponents cause identical SOS
- `debug_normalization.py`: Shows how percentile ranking preserves identical values
- `debug_strength_map.py`: Illustrates the root cause scenarios

## Solution

The fix is to **include ALL teams that appear as opponents** in the strength_map, even if they don't have rows as `team_id` in the filtered games.

### Proposed Fix (src/etl/v53e.py:456):

```python
# BEFORE (Line 456):
strength_map = dict(zip(team["team_id"], team["abs_strength"]))

# AFTER:
# Include all opponents, even if they don't have games as team_id
all_opponent_ids = set(g["opp_id"].unique())
missing_opponents = all_opponent_ids - set(team["team_id"].unique())

if missing_opponents:
    logger.info(f"⚠️  {len(missing_opponents)} opponents missing from strength_map, calculating their strength...")

    # For missing opponents, we need to calculate their strength from ALL their games,
    # not just their filtered games. We should look at the full games dataset.
    # For now, create placeholder entries or use a better default

strength_map = dict(zip(team["team_id"], team["abs_strength"]))
# TODO: Add missing opponents with calculated strength
```

### Better Solution:

Calculate strength for ALL teams that appear in ANY capacity (team_id OR opp_id) in the games dataset, BEFORE filtering to the last N games. This ensures every opponent has a strength value.

## Files Affected

- `src/etl/v53e.py`: Lines 224, 266, 456, 477
- Configuration: `MAX_GAMES_FOR_RANK = 30` may be too restrictive
