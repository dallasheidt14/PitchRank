-- Add team match review queue for manual review of ambiguous matches
CREATE TABLE IF NOT EXISTS team_match_review_queue (
    id SERIAL PRIMARY KEY,
    provider_id VARCHAR(50) NOT NULL,
    provider_team_id VARCHAR(255) NOT NULL,
    provider_team_name VARCHAR(255) NOT NULL,
    suggested_master_team_id UUID,  -- Changed from INTEGER to UUID
    confidence_score DECIMAL(3,2) NOT NULL,
    match_details JSONB,
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT confidence_range CHECK (confidence_score >= 0.75 AND confidence_score < 0.90)
);

CREATE INDEX idx_match_review_status ON team_match_review_queue(status);
CREATE INDEX idx_match_review_confidence ON team_match_review_queue(confidence_score DESC);

-- Add helper functions for match review
CREATE OR REPLACE FUNCTION approve_team_match(
    review_id INTEGER,
    approver VARCHAR(255)
) RETURNS VOID AS $$
DECLARE
    match_record RECORD;
    provider_uuid UUID;
BEGIN
    -- Get the match details
    SELECT * INTO match_record
    FROM team_match_review_queue
    WHERE id = review_id AND status = 'pending';
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Match review % not found or already processed', review_id;
    END IF;
    
    -- Get provider UUID
    SELECT id INTO provider_uuid
    FROM providers
    WHERE code = match_record.provider_id;
    
    -- Create the team alias mapping
    INSERT INTO team_alias_map (
        provider_id, 
        provider_team_id, 
        team_id_master,
        match_confidence, 
        match_method,
        created_at
    ) 
    VALUES (
        provider_uuid,
        match_record.provider_team_id,
        match_record.suggested_master_team_id,
        match_record.confidence_score,
        'manual_review',
        NOW()
    )
    ON CONFLICT (provider_id, provider_team_id) DO NOTHING;
    
    -- Update the review record
    UPDATE team_match_review_queue
    SET 
        status = 'approved',
        reviewed_by = approver,
        reviewed_at = NOW()
    WHERE id = review_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION reject_team_match(
    review_id INTEGER,
    reviewer VARCHAR(255)
) RETURNS VOID AS $$
BEGIN
    UPDATE team_match_review_queue
    SET 
        status = 'rejected',
        reviewed_by = reviewer,
        reviewed_at = NOW()
    WHERE id = review_id AND status = 'pending';
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Match review % not found or already processed', review_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- View for pending reviews with team details
CREATE OR REPLACE VIEW pending_match_reviews AS
SELECT 
    q.id,
    q.provider_id,
    q.provider_team_id,
    q.provider_team_name,
    q.suggested_master_team_id,
    t.team_name as suggested_team_name,
    t.age_group as suggested_age_group,
    t.gender as suggested_gender,
    t.state_code as suggested_state,
    q.confidence_score,
    q.match_details,
    q.created_at
FROM team_match_review_queue q
LEFT JOIN teams t ON t.team_id_master = q.suggested_master_team_id  -- Changed to use team_id_master
WHERE q.status = 'pending'
ORDER BY q.confidence_score DESC, q.created_at ASC;

-- Function to get match review statistics
CREATE OR REPLACE FUNCTION get_match_review_stats()
RETURNS TABLE (
    status VARCHAR(20),
    count BIGINT,
    avg_confidence DECIMAL(3,2)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        q.status,
        COUNT(*)::BIGINT as count,
        AVG(q.confidence_score)::DECIMAL(3,2) as avg_confidence
    FROM team_match_review_queue q
    GROUP BY q.status;
END;
$$ LANGUAGE plpgsql;