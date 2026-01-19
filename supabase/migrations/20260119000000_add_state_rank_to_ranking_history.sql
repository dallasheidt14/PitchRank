-- Add state rank tracking to ranking_history table
-- Date: 2026-01-19
-- Purpose: Enable state rank change calculations (rank_change_state_7d, rank_change_state_30d)
-- This allows tracking how teams move within their state rankings over time

-- =====================================================
-- Step 1: Add state columns to ranking_history
-- =====================================================

-- Add state_code column (nullable for backward compatibility with existing data)
ALTER TABLE ranking_history
ADD COLUMN IF NOT EXISTS state_code TEXT;

-- Add rank_in_state column (nullable for backward compatibility)
ALTER TABLE ranking_history
ADD COLUMN IF NOT EXISTS rank_in_state INTEGER;

-- =====================================================
-- Step 2: Create indexes for state-based lookups
-- =====================================================

-- Index for looking up historical state ranks by team, state, and date
CREATE INDEX IF NOT EXISTS idx_ranking_history_state
ON ranking_history(state_code, snapshot_date DESC)
WHERE state_code IS NOT NULL;

-- Composite index for efficient state rank lookups within cohort
CREATE INDEX IF NOT EXISTS idx_ranking_history_state_cohort
ON ranking_history(team_id, state_code, age_group, gender, snapshot_date DESC)
WHERE state_code IS NOT NULL;

-- =====================================================
-- Step 3: Add comments for documentation
-- =====================================================

COMMENT ON COLUMN ranking_history.state_code IS 'State code (e.g., AZ, CA, TX) for state-level rank tracking';
COMMENT ON COLUMN ranking_history.rank_in_state IS 'Rank within state + age_group + gender cohort at this snapshot';

-- =====================================================
-- Step 4: Create helper function for historical state rank
-- =====================================================

CREATE OR REPLACE FUNCTION get_historical_state_rank(
    p_team_id UUID,
    p_state_code TEXT,
    p_days_ago INTEGER
)
RETURNS INTEGER
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_rank INTEGER;
    v_target_date DATE;
BEGIN
    -- Calculate target date (days ago from today)
    v_target_date := CURRENT_DATE - (p_days_ago || ' days')::INTERVAL;

    -- Get the state rank from the closest snapshot (within 3 days)
    SELECT rank_in_state
    INTO v_rank
    FROM ranking_history
    WHERE team_id = p_team_id
      AND state_code = p_state_code
      AND snapshot_date >= v_target_date - INTERVAL '3 days'
      AND snapshot_date <= v_target_date + INTERVAL '3 days'
    ORDER BY ABS(EXTRACT(EPOCH FROM (snapshot_date - v_target_date)))
    LIMIT 1;

    RETURN v_rank;
END;
$$;

COMMENT ON FUNCTION get_historical_state_rank IS 'Get historical state rank for a team from N days ago. Returns NULL if no snapshot exists within +/- 3 days.';

-- =====================================================
-- Notes
-- =====================================================
-- Existing snapshots will have NULL state_code and rank_in_state.
-- New snapshots (after this migration) will include state data.
-- State rank changes will be NULL until ~7-30 days of new snapshots accumulate.
--
-- Usage:
-- 1. save_ranking_snapshot() now saves state_code and rank_in_state
-- 2. calculate_rank_changes() now computes rank_change_state_7d and rank_change_state_30d
-- 3. state_rankings_view exposes these new fields
