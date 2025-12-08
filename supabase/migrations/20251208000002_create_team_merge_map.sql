-- Migration: Create team merge map table
-- Purpose: Core redirect table for team merges (Option 1 architecture)
-- This is Phase 1.2 of the team merge implementation
--
-- The team_merge_map table enables the "redirect merge" pattern:
-- - Instead of updating game records, we redirect team lookups
-- - Queries use COALESCE(mm.canonical_team_id, g.team_id) pattern
-- - Fully reversible by deleting the mapping row

-- ============================================================================
-- TEAM MERGE MAP TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_merge_map (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The team being deprecated (merged FROM)
    -- UNIQUE ensures one team can only be deprecated once
    deprecated_team_id UUID NOT NULL UNIQUE
        REFERENCES teams(team_id_master),

    -- The canonical team (merged INTO)
    canonical_team_id UUID NOT NULL
        REFERENCES teams(team_id_master),

    -- Audit fields
    merged_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    merged_by TEXT NOT NULL,
    merge_reason TEXT,

    -- Option 8 integration: store suggestion confidence and signals
    confidence_score FLOAT CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
    suggestion_signals JSONB,

    -- Prevent merging a team into itself
    CONSTRAINT no_self_merge CHECK (deprecated_team_id != canonical_team_id)
);

-- Index for fast lookups when resolving team IDs
CREATE INDEX IF NOT EXISTS idx_merge_map_deprecated
ON team_merge_map(deprecated_team_id);

-- Index for finding all teams merged into a canonical team
CREATE INDEX IF NOT EXISTS idx_merge_map_canonical
ON team_merge_map(canonical_team_id);

-- Index for audit queries by date
CREATE INDEX IF NOT EXISTS idx_merge_map_date
ON team_merge_map(merged_at DESC);

-- ============================================================================
-- CHAIN PREVENTION TRIGGER
-- Prevents: A → B → C (chains) and A → B, B → A (circular)
-- ============================================================================

CREATE OR REPLACE FUNCTION prevent_merge_chains()
RETURNS TRIGGER AS $$
BEGIN
    -- RULE 1: Cannot merge into a team that is itself deprecated/merged
    -- This prevents chains like: A → B, then B → C (A would still point to B, not C)
    IF EXISTS (
        SELECT 1 FROM team_merge_map
        WHERE deprecated_team_id = NEW.canonical_team_id
    ) THEN
        RAISE EXCEPTION
            'Cannot merge into team % - it is already merged into another team. '
            'This would create a chain (A→B→C). Merge into the final canonical team instead.',
            NEW.canonical_team_id
        USING HINT = 'Find the final canonical team and merge directly into that.';
    END IF;

    -- RULE 2: Cannot deprecate a team that other teams are already merged into
    -- This prevents orphaning existing merges
    IF EXISTS (
        SELECT 1 FROM team_merge_map
        WHERE canonical_team_id = NEW.deprecated_team_id
    ) THEN
        RAISE EXCEPTION
            'Cannot deprecate team % - other teams are already merged into it. '
            'You must first re-merge those teams to a different canonical team.',
            NEW.deprecated_team_id
        USING HINT = 'Query: SELECT deprecated_team_id FROM team_merge_map WHERE canonical_team_id = ''%''',
            NEW.deprecated_team_id;
    END IF;

    -- RULE 3: Validate both teams exist and canonical is not deprecated
    IF NOT EXISTS (
        SELECT 1 FROM teams
        WHERE team_id_master = NEW.deprecated_team_id
    ) THEN
        RAISE EXCEPTION 'Deprecated team % does not exist', NEW.deprecated_team_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM teams
        WHERE team_id_master = NEW.canonical_team_id
    ) THEN
        RAISE EXCEPTION 'Canonical team % does not exist', NEW.canonical_team_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM teams
        WHERE team_id_master = NEW.canonical_team_id
        AND is_deprecated = TRUE
    ) THEN
        RAISE EXCEPTION
            'Cannot merge into team % - it is marked as deprecated. '
            'Choose an active team as the canonical target.',
            NEW.canonical_team_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach trigger to run before insert or update
DROP TRIGGER IF EXISTS check_merge_chains ON team_merge_map;
CREATE TRIGGER check_merge_chains
    BEFORE INSERT OR UPDATE ON team_merge_map
    FOR EACH ROW
    EXECUTE FUNCTION prevent_merge_chains();

-- ============================================================================
-- HELPER FUNCTION: Resolve a team ID to its canonical form
-- ============================================================================

CREATE OR REPLACE FUNCTION resolve_team_id(p_team_id UUID)
RETURNS UUID AS $$
DECLARE
    v_canonical_id UUID;
BEGIN
    -- Look up if this team has been merged
    SELECT canonical_team_id INTO v_canonical_id
    FROM team_merge_map
    WHERE deprecated_team_id = p_team_id;

    -- Return canonical if found, otherwise return original
    RETURN COALESCE(v_canonical_id, p_team_id);
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- HELPER FUNCTION: Check if a team is deprecated (merged)
-- ============================================================================

CREATE OR REPLACE FUNCTION is_team_merged(p_team_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM team_merge_map
        WHERE deprecated_team_id = p_team_id
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- HELPER FUNCTION: Get merge info for a team
-- ============================================================================

CREATE OR REPLACE FUNCTION get_merge_info(p_team_id UUID)
RETURNS TABLE (
    is_merged BOOLEAN,
    canonical_team_id UUID,
    merged_at TIMESTAMPTZ,
    merged_by TEXT,
    merge_reason TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        TRUE as is_merged,
        mm.canonical_team_id,
        mm.merged_at,
        mm.merged_by,
        mm.merge_reason
    FROM team_merge_map mm
    WHERE mm.deprecated_team_id = p_team_id;

    -- If no rows returned, return a "not merged" row
    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, NULL::UUID, NULL::TIMESTAMPTZ, NULL::TEXT, NULL::TEXT;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE team_merge_map IS
    'Maps deprecated team IDs to their canonical team. Used for redirect-based merging '
    'where game records are not modified. Queries resolve team IDs via COALESCE pattern.';

COMMENT ON COLUMN team_merge_map.deprecated_team_id IS
    'The team being merged/deprecated. This team''s games will be attributed to canonical_team_id.';

COMMENT ON COLUMN team_merge_map.canonical_team_id IS
    'The surviving team that games will be attributed to after merge.';

COMMENT ON COLUMN team_merge_map.confidence_score IS
    'If merge was suggested by Option 8 algorithm, the confidence score (0-1).';

COMMENT ON COLUMN team_merge_map.suggestion_signals IS
    'JSON object containing the individual signal scores that led to the merge suggestion.';

COMMENT ON FUNCTION resolve_team_id(UUID) IS
    'Returns the canonical team ID for a given team. If team is not merged, returns the input ID.';

COMMENT ON FUNCTION is_team_merged(UUID) IS
    'Returns TRUE if the team has been merged into another team.';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
BEGIN
    -- Verify table exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'team_merge_map'
    ) THEN
        RAISE EXCEPTION 'Migration failed: team_merge_map table not created';
    END IF;

    -- Verify trigger exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.triggers
        WHERE trigger_name = 'check_merge_chains'
    ) THEN
        RAISE EXCEPTION 'Migration failed: check_merge_chains trigger not created';
    END IF;

    -- Verify functions exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'resolve_team_id'
    ) THEN
        RAISE EXCEPTION 'Migration failed: resolve_team_id function not created';
    END IF;

    RAISE NOTICE 'Migration successful: team_merge_map table and chain prevention created';
END $$;
