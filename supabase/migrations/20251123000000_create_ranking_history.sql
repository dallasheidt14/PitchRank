-- Create ranking_history table for tracking rank changes over time
-- Date: 2025-11-23
-- Purpose: Store daily snapshots of rankings to enable accurate rank change calculations

-- =====================================================
-- Step 1: Create ranking_history table
-- =====================================================

CREATE TABLE IF NOT EXISTS ranking_history (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,

    -- Snapshot metadata
    snapshot_date DATE NOT NULL,

    -- Team reference
    team_id UUID REFERENCES teams(team_id_master) ON DELETE CASCADE NOT NULL,

    -- Team cohort (for partitioning)
    age_group TEXT NOT NULL,
    gender TEXT NOT NULL,

    -- Rank at this snapshot
    rank_in_cohort INTEGER NOT NULL,
    rank_in_cohort_ml INTEGER,

    -- Power score at this snapshot (for reference)
    power_score_final FLOAT,
    powerscore_ml FLOAT,

    -- Tracking
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Ensure one snapshot per team per day
    UNIQUE(team_id, snapshot_date)
);

-- =====================================================
-- Step 2: Create indexes for performance
-- =====================================================

-- Index for looking up historical ranks by team and date
CREATE INDEX IF NOT EXISTS idx_ranking_history_team_date
ON ranking_history(team_id, snapshot_date DESC);

-- Index for date-based queries (cleanup, analysis)
CREATE INDEX IF NOT EXISTS idx_ranking_history_date
ON ranking_history(snapshot_date DESC);

-- Index for cohort-based queries
CREATE INDEX IF NOT EXISTS idx_ranking_history_cohort
ON ranking_history(age_group, gender, snapshot_date DESC);

-- Composite index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_ranking_history_team_date_composite
ON ranking_history(team_id, snapshot_date DESC, rank_in_cohort);

-- =====================================================
-- Step 3: Add table comments
-- =====================================================

COMMENT ON TABLE ranking_history IS 'Daily snapshots of team rankings for tracking rank changes over time. Used to calculate rank_change_7d and rank_change_30d in rankings_full.';
COMMENT ON COLUMN ranking_history.snapshot_date IS 'Date of this ranking snapshot (UTC date, typically when rankings were calculated)';
COMMENT ON COLUMN ranking_history.rank_in_cohort IS 'National rank within age/gender cohort at this snapshot';
COMMENT ON COLUMN ranking_history.rank_in_cohort_ml IS 'ML-adjusted rank at this snapshot (if available)';

-- =====================================================
-- Step 4: Grant permissions
-- =====================================================

-- Only backend should write to this table
GRANT SELECT ON ranking_history TO authenticated;
GRANT SELECT ON ranking_history TO anon;

-- =====================================================
-- Step 5: Create helper function to get historical rank
-- =====================================================

CREATE OR REPLACE FUNCTION get_historical_rank(
    p_team_id UUID,
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

    -- Get the rank from the closest snapshot (within 3 days)
    SELECT COALESCE(rank_in_cohort_ml, rank_in_cohort)
    INTO v_rank
    FROM ranking_history
    WHERE team_id = p_team_id
      AND snapshot_date >= v_target_date - INTERVAL '3 days'
      AND snapshot_date <= v_target_date + INTERVAL '3 days'
    ORDER BY ABS(EXTRACT(EPOCH FROM (snapshot_date - v_target_date)))
    LIMIT 1;

    RETURN v_rank;
END;
$$;

COMMENT ON FUNCTION get_historical_rank IS 'Get historical rank for a team from N days ago. Returns NULL if no snapshot exists within ±3 days.';

-- =====================================================
-- Step 6: Create cleanup function (optional)
-- =====================================================

-- Function to clean up old snapshots (keep last 90 days)
CREATE OR REPLACE FUNCTION cleanup_old_ranking_snapshots()
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted_count INTEGER;
BEGIN
    -- Delete snapshots older than 90 days
    DELETE FROM ranking_history
    WHERE snapshot_date < CURRENT_DATE - INTERVAL '90 days';

    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;

    RETURN v_deleted_count;
END;
$$;

COMMENT ON FUNCTION cleanup_old_ranking_snapshots IS 'Delete ranking snapshots older than 90 days. Returns count of deleted rows. Run periodically via cron job.';

-- =====================================================
-- Notes
-- =====================================================
-- Usage:
-- 1. Calculator saves daily snapshot after computing rankings
-- 2. Calculator queries snapshots from 7 and 30 days ago
-- 3. Calculator calculates: rank_change = historical_rank - current_rank
-- 4. Positive value = improved (moved up in rankings)
-- 5. Negative value = declined (moved down in rankings)
--
-- Example query:
-- SELECT
--     team_id,
--     snapshot_date,
--     rank_in_cohort,
--     rank_in_cohort - LAG(rank_in_cohort, 7) OVER (PARTITION BY team_id ORDER BY snapshot_date) AS rank_change_7d
-- FROM ranking_history
-- WHERE age_group = '12' AND gender = 'M'
-- ORDER BY snapshot_date DESC, rank_in_cohort;
