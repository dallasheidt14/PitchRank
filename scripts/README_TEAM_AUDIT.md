# Team SOS Audit Script

## Overview

The `team_audit_sos.py` script is a powerful debugging tool that helps verify Strength of Schedule (SOS) calculations for individual teams.

## Features

- **Interactive Team Search**: Search for teams by name
- **Complete Game History**: View all games for the selected team
- **SOS Breakdown**: See detailed SOS contribution for each game:
  - Opponent strength (abs_strength value)
  - Game weight (w_sos)
  - SOS contribution
  - Whether the game is included in SOS calculation (repeat cap)
- **Manual Verification**: Calculates SOS manually and compares with database value
- **Summary Statistics**: Shows aggregate stats about opponents and games

## Usage

### Prerequisites

Ensure your environment variables are set:
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

These should be in `.env` or `.env.local` file in the project root.

### Running the Script

```bash
python scripts/team_audit_sos.py
```

### Interactive Prompts

1. **Team Search**: Enter a team name to search
   ```
   Enter team name to search: Dallas Tigers
   ```

2. **Select Team**: If multiple matches, select the team number
   ```
   Select team number (1-5): 1
   ```

3. **View Results**: The script will display:
   - Team information (age group, gender)
   - SOS comparison (manual vs database)
   - Detailed game history table
   - Summary statistics

## Output Explanation

### SOS Comparison Panel

```
Manual SOS (Pass 1):   0.543210
Actual SOS (from DB):  0.548765
Difference:            0.005555
SOS Normalized:        0.6234
```

- **Manual SOS**: Calculated directly from game data (Pass 1 only)
- **Actual SOS**: Value from database (includes all 3 passes with transitivity)
- **Difference**: Should be small (< 0.05); large differences indicate issues
- **SOS Normalized**: Percentile rank within age/gender cohort

### Game History Table

| Date       | Opponent           | Score | Opp Str | Weight  | Contrib  | In SOS? | Loc  |
|------------|-------------------|-------|---------|---------|----------|---------|------|
| 2024-11-15 | FC Dallas Academy | 2-1   | 0.7234  | 0.8234  | 0.045231 | ✓       | Home |
| 2024-11-10 | Solar SC          | 1-3   | 0.6543  | 0.7891  | 0.041234 | ✓       | Away |

**Columns:**
- **Date**: Game date
- **Opponent**: Opponent team name
- **Score**: Goals For - Goals Against
- **Opp Str**: Opponent's strength value (0-1 scale)
  - Green (≥0.65): Strong opponent
  - Yellow (0.45-0.65): Average opponent
  - Red (<0.45): Weak opponent
- **Weight**: Game weight (w_sos) based on recency and score differential
- **Contrib**: This game's contribution to overall SOS
- **In SOS?**: Whether included in SOS calculation (repeat cap check)
- **Loc**: Home/Away location

### Summary Statistics

Shows aggregate information:
- Total games vs games included in SOS
- Number of unique opponents
- Average, strongest, and weakest opponent strength
- SOS configuration parameters

## Understanding the Results

### Good SOS Calculation
- Difference between manual and actual SOS is < 0.05
- All expected games are marked "In SOS? ✓"
- Opponent strengths are reasonable (not all 0.35)

### Potential Issues
- Large difference (> 0.05) between manual and actual SOS
- Many games marked "In SOS? ✗" unexpectedly
- All opponents show strength of 0.35 (UNRANKED_SOS_BASE)
- No SOS value in database (shows "N/A")

## SOS Configuration

The script shows current configuration:
- **Repeat Cap**: Maximum games per opponent counted (default: 4)
- **Unranked Base**: Default strength for unranked opponents (default: 0.35)
- **Iterations**: Number of SOS calculation passes (default: 3)
- **Transitivity Lambda**: Weight for transitive SOS (default: 0.20)

These values come from `src/etl/v53e.py::V53EConfig`

## Troubleshooting

### No teams found
- Check team name spelling
- Try partial name (e.g., "Dallas" instead of "Dallas Tigers U14 Red")
- Verify teams exist in database

### No games found
- Team may not have games in the last 365 days
- Check if games are properly imported
- Verify team_id_master matches in games table

### SOS shows N/A
- Rankings may not have been calculated yet
- Run `python scripts/calculate_rankings.py` first
- Check if team has minimum games required

### Large SOS difference
- Expected if manual vs actual > 0.05
- May indicate issues with:
  - Opponent strength calculations
  - Game weights
  - Transitivity calculations
  - Data quality issues

## Related Scripts

- `check_sos.py` - General SOS verification across all teams
- `verify_sos_impact.py` - Analyze impact of SOS on rankings
- `calculate_rankings.py` - Generate new rankings
- `show_rankings_details.py` - Show detailed rankings info

## Technical Details

The script replicates the SOS calculation from `src/etl/v53e.py:468-530`:

1. **Weight Calculation**: `w_sos = w_game * k_adapt`
   - `w_game`: Recency decay weight
   - `k_adapt`: Strength gap adjustment

2. **Repeat Cap**: Only top 4 games per opponent by weight

3. **Opponent Strength**: Maps opponent ID to abs_strength value

4. **Weighted Average**:
   ```
   SOS = Σ(opp_strength × w_sos) / Σ(w_sos)
   ```

5. **Transitivity** (not in manual calc): Blends direct + opponents' opponents

Note: Manual calculation shows Pass 1 only. Actual SOS includes all 3 iterative passes with transitivity, which is why small differences are expected.
