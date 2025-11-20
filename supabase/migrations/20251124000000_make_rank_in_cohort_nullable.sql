-- Make rank_in_cohort nullable to allow baseline snapshots
-- Date: 2025-11-24
-- Purpose: Allow NULL values in rank_in_cohort to establish baseline for rank change tracking

-- Change rank_in_cohort to allow NULL values
-- This enables saving snapshots for teams that don't have a rank yet (baseline)
ALTER TABLE ranking_history 
ALTER COLUMN rank_in_cohort DROP NOT NULL;

-- Update comment to reflect that NULL is allowed for baseline
COMMENT ON COLUMN ranking_history.rank_in_cohort IS 'National rank within age/gender cohort at this snapshot. NULL indicates no rank available (baseline for new teams or teams without enough games).';

-- Note: The get_historical_rank() function already handles NULL correctly:
-- - It uses COALESCE(rank_in_cohort_ml, rank_in_cohort) which returns NULL if both are NULL
-- - The function returns INTEGER (not INTEGER NOT NULL), so NULL is valid
-- - The Python code in ranking_history.py already handles NULL properly:
--   - get_historical_ranks() returns None for missing ranks
--   - calculate_rank_changes() checks pd.isna() and returns None, None for teams without ranks
--   - All rank change calculations check for None before doing arithmetic

