-- PitchRank Enhanced Build Logs Migration
-- Adds metrics JSONB column to build_logs for detailed import tracking

-- =====================================================
-- ADD METRICS COLUMN TO BUILD_LOGS
-- =====================================================

-- Add metrics JSONB column to store detailed import metrics
ALTER TABLE build_logs ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT '{}';

-- Create GIN index on metrics for efficient JSONB queries
CREATE INDEX IF NOT EXISTS idx_build_logs_metrics ON build_logs USING GIN (metrics);

-- =====================================================
-- METRICS STRUCTURE DOCUMENTATION
-- =====================================================

-- The metrics JSONB column will store structured data like:
-- {
--   "games_processed": 1000,
--   "games_accepted": 950,
--   "games_quarantined": 50,
--   "duplicates_found": 25,
--   "teams_matched": 920,
--   "teams_created": 30,
--   "fuzzy_matches_auto": 850,
--   "fuzzy_matches_manual": 70,
--   "fuzzy_matches_rejected": 50,
--   "processing_time_seconds": 45.2,
--   "memory_usage_mb": 128.5,
--   "errors": [
--     {"message": "Error description", "count": 5}
--   ]
-- }

-- =====================================================
-- HELPER FUNCTION TO UPDATE METRICS
-- =====================================================

-- Function to merge metrics into existing build_log entry
CREATE OR REPLACE FUNCTION update_build_metrics(
    p_build_id TEXT,
    p_stage TEXT,
    p_metrics JSONB
)
RETURNS void AS $$
BEGIN
    UPDATE build_logs
    SET metrics = COALESCE(metrics, '{}'::JSONB) || p_metrics
    WHERE build_id = p_build_id AND stage = p_stage;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- VIEW FOR METRICS SUMMARY
-- =====================================================

-- View to easily query build metrics
CREATE OR REPLACE VIEW build_metrics_summary AS
SELECT 
    build_id,
    stage,
    provider_id,
    started_at,
    completed_at,
    records_processed,
    records_succeeded,
    records_failed,
    metrics->>'games_processed' AS games_processed,
    metrics->>'games_accepted' AS games_accepted,
    metrics->>'games_quarantined' AS games_quarantined,
    metrics->>'duplicates_found' AS duplicates_found,
    metrics->>'teams_matched' AS teams_matched,
    metrics->>'teams_created' AS teams_created,
    metrics->>'fuzzy_matches_auto' AS fuzzy_matches_auto,
    metrics->>'fuzzy_matches_manual' AS fuzzy_matches_manual,
    metrics->>'fuzzy_matches_rejected' AS fuzzy_matches_rejected,
    metrics->>'processing_time_seconds' AS processing_time_seconds,
    metrics->>'memory_usage_mb' AS memory_usage_mb,
    metrics->'errors' AS errors
FROM build_logs
WHERE metrics IS NOT NULL AND metrics != '{}'::JSONB
ORDER BY started_at DESC;

