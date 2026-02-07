# Match Prediction Component Diagnosis

## Overview
The match prediction component on the compare page uses an enhanced prediction model with explanations.

## Data Flow

1. **ComparePanel Component** (`frontend/components/ComparePanel.tsx`)
   - Uses `useMatchPrediction(team1Id, team2Id)` hook (line 50)
   - Displays `EnhancedPredictionCard` if `matchPrediction` exists (line 336)
   - Falls back to `PredictedMatchCard` if enhanced prediction fails (line 358)

2. **useMatchPrediction Hook** (`frontend/lib/hooks.ts`)
   - Calls `api.getMatchPrediction(teamAId, teamBId)` (line 142)
   - Enabled when both teams are selected and different (line 143)
   - Cached for 15 minutes (line 144)

3. **getMatchPrediction API** (`frontend/lib/api.ts`)
   - Fetches team data using `getTeam()` for both teams (lines 661-662)
   - Fetches recent games (last 60 days) for form calculation (lines 670-677)
   - Calls `predictMatch()` to generate prediction (line 689)
   - Calls `explainMatch()` to generate explanations (line 692)
   - Returns both prediction and explanation (lines 694-707)

4. **predictMatch Function** (`frontend/lib/matchPredictor.ts`)
   - Uses `power_score_final` (line 399)
   - Uses `sos_norm` (line 405)
   - Uses `offense_norm` and `defense_norm` (lines 414-417)
   - Calculates recent form from games (lines 408-409)
   - Returns `MatchPrediction` with win probabilities, expected scores, confidence

5. **explainMatch Function** (`frontend/lib/matchExplainer.ts`)
   - Generates human-readable explanations
   - Provides factors, insights, and prediction quality

## Required Data Fields

The prediction requires these fields from `TeamWithRanking`:
- ✅ `power_score_final` - ML-adjusted power score (we fixed this)
- ✅ `sos_norm` - Normalized SOS (we fixed this)
- ✅ `offense_norm` - Normalized offense rating (we fixed this)
- ✅ `defense_norm` - Normalized defense rating (we fixed this)
- ✅ `age` - Age group for league average goals calculation
- ✅ `team_id_master` - For form calculation

## Potential Issues

### 1. Game Query
The games query selects:
```typescript
.select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
```

But the `Game` interface expects more fields. However, `predictMatch` only uses:
- `home_team_master_id`
- `away_team_master_id`
- `home_score`
- `away_score`
- `game_date` (for form calculation)

✅ **Status**: This should work fine - the query selects all needed fields.

### 2. Team Data Fields
Since we just fixed `getTeam()` to return:
- `power_score_final`
- `sos_norm`
- `offense_norm`
- `defense_norm`
- `rank_in_cohort_final`
- `sos_rank_national`
- `sos_rank_state`

✅ **Status**: All required fields should now be available.

### 3. Null/Undefined Handling
The `predictMatch` function uses fallbacks:
- `teamA.power_score_final || 0.5` (line 399)
- `teamA.sos_norm || 0.5` (line 405)
- `teamA.offense_norm || 0.5` (line 414)
- `teamA.defense_norm || 0.5` (line 415)

✅ **Status**: Handles null/undefined gracefully.

### 4. Age Field
`getAgeSpecificMarginMultiplier` uses `teamA.age` (line 435)
`getLeagueAverageGoals` uses `teamA.age` (line 440)

⚠️ **Potential Issue**: If `age` is null, these functions may not work correctly.

## Testing Checklist

1. ✅ Verify `getTeam()` returns all required fields (we just fixed this)
2. ⚠️ Test with teams that have null `age` values
3. ⚠️ Test with teams that have no recent games (form calculation)
4. ⚠️ Test with teams that have null `power_score_final`, `sos_norm`, etc.
5. ⚠️ Check browser console for errors when loading compare page

## Next Steps

1. Check if `age` field is always populated in `getTeam()` response
2. Verify games query works correctly
3. Test the component with real teams
4. Check for any console errors

















