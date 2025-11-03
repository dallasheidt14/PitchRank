-- PitchRank Team Match Review Queue Migration
-- Creates table for managing team matches that need manual review

-- =====================================================
-- TEAM MATCH REVIEW QUEUE TABLE
-- =====================================================

CREATE TABLE IF NOT EXISTS team_match_review_queue (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    provider_id UUID NOT NULL REFERENCES providers(id),
    provider_team_id TEXT NOT NULL,
    provider_team_name TEXT NOT NULL,
    suggested_master_team_id UUID REFERENCES teams(team_id_master),
    confidence_score DECIMAL(3,2) NOT NULL,
    match_details JSONB DEFAULT '{}',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'new_team')),
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Constraint: confidence_score must be between 0.75 and 0.90 for review queue
    CONSTRAINT confidence_range CHECK (confidence_score >= 0.75 AND confidence_score < 0.90)
);

-- =====================================================
-- INDEXES
-- =====================================================

-- Index for querying pending reviews
CREATE INDEX IF NOT EXISTS idx_match_review_status ON team_match_review_queue(status);

-- Index for sorting by confidence (highest first)
CREATE INDEX IF NOT EXISTS idx_match_review_confidence ON team_match_review_queue(confidence_score DESC);

-- Index for provider/team lookups
CREATE INDEX IF NOT EXISTS idx_match_review_provider_team ON team_match_review_queue(provider_id, provider_team_id);

-- Index for date-based queries
CREATE INDEX IF NOT EXISTS idx_match_review_created ON team_match_review_queue(created_at DESC);

-- Composite index for pending reviews sorted by confidence
CREATE INDEX IF NOT EXISTS idx_match_review_pending_confidence ON team_match_review_queue(status, confidence_score DESC) 
WHERE status = 'pending';

-- =====================================================
-- VIEWS
-- =====================================================

-- View for pending review queue with team details
CREATE OR REPLACE VIEW pending_match_reviews AS
SELECT 
    q.id,
    q.provider_id,
    p.name as provider_name,
    q.provider_team_id,
    q.provider_team_name,
    q.suggested_master_team_id,
    t.team_name as suggested_team_name,
    t.club_name as suggested_club_name,
    t.state_code as suggested_state_code,
    t.age_group as suggested_age_group,
    t.gender as suggested_gender,
    q.confidence_score,
    q.match_details,
    q.status,
    q.reviewed_by,
    q.reviewed_at,
    q.created_at,
    CASE 
        WHEN q.confidence_score >= 0.85 THEN 'high'
        WHEN q.confidence_score >= 0.80 THEN 'medium'
        ELSE 'low'
    END as confidence_level
FROM team_match_review_queue q
JOIN providers p ON q.provider_id = p.id
LEFT JOIN teams t ON q.suggested_master_team_id = t.team_id_master
WHERE q.status = 'pending'
ORDER BY q.confidence_score DESC, q.created_at ASC;

-- =====================================================
-- HELPER FUNCTIONS
-- =====================================================

-- Function to approve a match and create alias
CREATE OR REPLACE FUNCTION approve_team_match(
    p_review_id UUID,
    p_reviewer_name TEXT
)
RETURNS void AS $$
DECLARE
    review_record team_match_review_queue%ROWTYPE;
BEGIN
    -- Get the review record
    SELECT * INTO review_record
    FROM team_match_review_queue
    WHERE id = p_review_id AND status = 'pending';
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Review not found or not pending: %', p_review_id;
    END IF;
    
    -- Create team alias mapping
    INSERT INTO team_alias_map (
        provider_id,
        provider_team_id,
        team_id_master,
        match_confidence,
        match_method,
        review_status,
        created_at
    )
    VALUES (
        review_record.provider_id,
        review_record.provider_team_id,
        review_record.suggested_master_team_id,
        review_record.confidence_score,
        'manual_review',
        'approved',
        NOW()
    )
    ON CONFLICT (provider_id, provider_team_id) 
    DO UPDATE SET
        team_id_master = EXCLUDED.team_id_master,
        match_confidence = EXCLUDED.match_confidence,
        match_method = EXCLUDED.match_method,
        review_status = 'approved',
        created_at = NOW();
    
    -- Mark review as approved
    UPDATE team_match_review_queue
    SET status = 'approved',
        reviewed_by = p_reviewer_name,
        reviewed_at = NOW()
    WHERE id = p_review_id;
END;
$$ LANGUAGE plpgsql;

-- Function to reject a match
CREATE OR REPLACE FUNCTION reject_team_match(
    p_review_id UUID,
    p_reviewer_name TEXT
)
RETURNS void AS $$
BEGIN
    UPDATE team_match_review_queue
    SET status = 'rejected',
        reviewed_by = p_reviewer_name,
        reviewed_at = NOW()
    WHERE id = p_review_id AND status = 'pending';
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Review not found or not pending: %', p_review_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to mark as new team (no match found, create new team entry)
CREATE OR REPLACE FUNCTION mark_as_new_team(
    p_review_id UUID,
    p_reviewer_name TEXT
)
RETURNS void AS $$
BEGIN
    UPDATE team_match_review_queue
    SET status = 'new_team',
        reviewed_by = p_reviewer_name,
        reviewed_at = NOW()
    WHERE id = p_review_id AND status = 'pending';
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Review not found or not pending: %', p_review_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

