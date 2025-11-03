-- PitchRank Direct ID Match Type Migration
-- Adds support for direct_id match type in team_alias_map

-- =====================================================
-- UPDATE MATCH TYPE CONSTRAINT
-- =====================================================

-- Drop existing constraint if it exists
ALTER TABLE team_alias_map DROP CONSTRAINT IF EXISTS valid_match_type;

-- Add new constraint with direct_id support
ALTER TABLE team_alias_map 
ADD CONSTRAINT valid_match_type CHECK (
    match_method IN ('auto', 'manual', 'import', 'direct_id', 'fuzzy_auto', 'fuzzy_review')
);

-- =====================================================
-- ADD INDEX FOR FASTER LOOKUPS
-- =====================================================

-- Ensure index exists for faster provider team ID lookups
-- (This may already exist from previous migrations, but ensure it's optimal)
CREATE INDEX IF NOT EXISTS idx_team_alias_provider_team_id 
ON team_alias_map(provider_id, provider_team_id);

-- =====================================================
-- ADD COMMENT EXPLAINING MATCH TYPES
-- =====================================================

COMMENT ON COLUMN team_alias_map.match_method IS 
'Match type: direct_id=ID match from master list (confidence 1.0), fuzzy_auto=auto fuzzy match (>=0.9), fuzzy_review=manual review needed (0.75-0.9), manual=human verified, import=initial import, auto=legacy auto match';

-- =====================================================
-- VIEW FOR MATCH TYPE STATISTICS
-- =====================================================

CREATE OR REPLACE VIEW match_type_statistics AS
SELECT 
    provider_id,
    p.name as provider_name,
    match_method,
    COUNT(*) as mapping_count,
    AVG(match_confidence) as avg_confidence,
    MIN(match_confidence) as min_confidence,
    MAX(match_confidence) as max_confidence
FROM team_alias_map tam
JOIN providers p ON tam.provider_id = p.id
GROUP BY provider_id, p.name, match_method
ORDER BY provider_id, mapping_count DESC;

