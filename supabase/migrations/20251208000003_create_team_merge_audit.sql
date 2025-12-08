-- Migration: Create team merge audit table
-- Purpose: Full audit trail for merge operations with revert capability
-- This is Phase 1.3 of the team merge implementation

-- ============================================================================
-- TEAM MERGE AUDIT TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS team_merge_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reference to the merge (NULL if merge was reverted and entry deleted)
    merge_id UUID REFERENCES team_merge_map(id) ON DELETE SET NULL,

    -- Team IDs (stored separately so we have them even after revert)
    deprecated_team_id UUID NOT NULL,
    canonical_team_id UUID NOT NULL,

    -- Action type
    action TEXT NOT NULL CHECK (action IN ('merge', 'revert', 'cascade_alias', 'recalculate_rankings')),

    -- Snapshot of deprecated team before merge (for recovery)
    deprecated_team_snapshot JSONB,

    -- Impact metrics
    games_affected INTEGER DEFAULT 0,
    aliases_updated INTEGER DEFAULT 0,
    rankings_recalculated BOOLEAN DEFAULT FALSE,

    -- Who and when
    performed_by TEXT NOT NULL,
    performed_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,

    -- Revert tracking
    reverted_at TIMESTAMPTZ,
    reverted_by TEXT,
    revert_reason TEXT,

    -- Additional context
    notes TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_merge_audit_deprecated
ON team_merge_audit(deprecated_team_id);

CREATE INDEX IF NOT EXISTS idx_merge_audit_canonical
ON team_merge_audit(canonical_team_id);

CREATE INDEX IF NOT EXISTS idx_merge_audit_date
ON team_merge_audit(performed_at DESC);

CREATE INDEX IF NOT EXISTS idx_merge_audit_action
ON team_merge_audit(action);

CREATE INDEX IF NOT EXISTS idx_merge_audit_merge_id
ON team_merge_audit(merge_id)
WHERE merge_id IS NOT NULL;

-- ============================================================================
-- EXECUTE TEAM MERGE FUNCTION
-- Performs merge with full audit trail
-- ============================================================================

CREATE OR REPLACE FUNCTION execute_team_merge(
    p_deprecated_team_id UUID,
    p_canonical_team_id UUID,
    p_merged_by TEXT,
    p_merge_reason TEXT DEFAULT NULL,
    p_confidence_score FLOAT DEFAULT NULL,
    p_suggestion_signals JSONB DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_merge_id UUID;
    v_deprecated_snapshot JSONB;
    v_aliases_updated INTEGER := 0;
    v_games_affected INTEGER := 0;
BEGIN
    -- 1. Validate deprecated team is not already deprecated
    IF EXISTS (
        SELECT 1 FROM teams
        WHERE team_id_master = p_deprecated_team_id
        AND is_deprecated = TRUE
    ) THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Team %s is already deprecated', p_deprecated_team_id)
        );
    END IF;

    -- 2. Snapshot the deprecated team before changes
    SELECT to_jsonb(t.*) INTO v_deprecated_snapshot
    FROM teams t
    WHERE team_id_master = p_deprecated_team_id;

    IF v_deprecated_snapshot IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Deprecated team %s not found', p_deprecated_team_id)
        );
    END IF;

    -- 3. Count affected games
    SELECT COUNT(*) INTO v_games_affected
    FROM games
    WHERE home_team_master_id = p_deprecated_team_id
       OR away_team_master_id = p_deprecated_team_id;

    -- 4. Create merge map entry (this triggers chain prevention validation)
    BEGIN
        INSERT INTO team_merge_map (
            deprecated_team_id,
            canonical_team_id,
            merged_by,
            merge_reason,
            confidence_score,
            suggestion_signals
        )
        VALUES (
            p_deprecated_team_id,
            p_canonical_team_id,
            p_merged_by,
            p_merge_reason,
            p_confidence_score,
            p_suggestion_signals
        )
        RETURNING id INTO v_merge_id;
    EXCEPTION WHEN OTHERS THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', SQLERRM
        );
    END;

    -- 5. Cascade update team_alias_map
    UPDATE team_alias_map
    SET team_id_master = p_canonical_team_id
    WHERE team_id_master = p_deprecated_team_id;

    GET DIAGNOSTICS v_aliases_updated = ROW_COUNT;

    -- 6. Mark deprecated team
    UPDATE teams
    SET is_deprecated = TRUE, updated_at = NOW()
    WHERE team_id_master = p_deprecated_team_id;

    -- 7. Create audit record
    INSERT INTO team_merge_audit (
        merge_id,
        deprecated_team_id,
        canonical_team_id,
        action,
        deprecated_team_snapshot,
        games_affected,
        aliases_updated,
        performed_by,
        notes
    )
    VALUES (
        v_merge_id,
        p_deprecated_team_id,
        p_canonical_team_id,
        'merge',
        v_deprecated_snapshot,
        v_games_affected,
        v_aliases_updated,
        p_merged_by,
        p_merge_reason
    );

    -- 8. Return success summary
    RETURN jsonb_build_object(
        'success', TRUE,
        'merge_id', v_merge_id,
        'deprecated_team_id', p_deprecated_team_id,
        'canonical_team_id', p_canonical_team_id,
        'games_affected', v_games_affected,
        'aliases_updated', v_aliases_updated,
        'message', format('Successfully merged team into %s', p_canonical_team_id)
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- REVERT TEAM MERGE FUNCTION
-- Reverts a merge with full audit trail
-- ============================================================================

CREATE OR REPLACE FUNCTION revert_team_merge(
    p_merge_id UUID,
    p_reverted_by TEXT,
    p_revert_reason TEXT DEFAULT NULL
)
RETURNS JSONB AS $$
DECLARE
    v_deprecated_team_id UUID;
    v_canonical_team_id UUID;
    v_aliases_reverted INTEGER := 0;
    v_original_provider_team_ids TEXT[];
BEGIN
    -- 1. Get merge details
    SELECT deprecated_team_id, canonical_team_id
    INTO v_deprecated_team_id, v_canonical_team_id
    FROM team_merge_map
    WHERE id = p_merge_id;

    IF v_deprecated_team_id IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Merge %s not found', p_merge_id)
        );
    END IF;

    -- 2. Get original provider_team_ids for this deprecated team from games
    SELECT ARRAY_AGG(DISTINCT provider_id) INTO v_original_provider_team_ids
    FROM (
        SELECT home_provider_id as provider_id FROM games
        WHERE home_team_master_id = v_deprecated_team_id
        UNION
        SELECT away_provider_id FROM games
        WHERE away_team_master_id = v_deprecated_team_id
    ) sub
    WHERE provider_id IS NOT NULL;

    -- 3. Revert alias mappings that were for this team's provider IDs
    IF v_original_provider_team_ids IS NOT NULL THEN
        UPDATE team_alias_map
        SET team_id_master = v_deprecated_team_id
        WHERE team_id_master = v_canonical_team_id
          AND provider_team_id = ANY(v_original_provider_team_ids);

        GET DIAGNOSTICS v_aliases_reverted = ROW_COUNT;
    END IF;

    -- 4. Un-deprecate the team
    UPDATE teams
    SET is_deprecated = FALSE, updated_at = NOW()
    WHERE team_id_master = v_deprecated_team_id;

    -- 5. Update audit record for the original merge
    UPDATE team_merge_audit
    SET
        reverted_at = NOW(),
        reverted_by = p_reverted_by,
        revert_reason = p_revert_reason
    WHERE merge_id = p_merge_id AND action = 'merge';

    -- 6. Create revert audit record
    INSERT INTO team_merge_audit (
        merge_id,
        deprecated_team_id,
        canonical_team_id,
        action,
        aliases_updated,
        performed_by,
        notes
    )
    VALUES (
        p_merge_id,
        v_deprecated_team_id,
        v_canonical_team_id,
        'revert',
        v_aliases_reverted,
        p_reverted_by,
        p_revert_reason
    );

    -- 7. Remove merge map entry
    DELETE FROM team_merge_map WHERE id = p_merge_id;

    -- 8. Return success
    RETURN jsonb_build_object(
        'success', TRUE,
        'deprecated_team_id', v_deprecated_team_id,
        'canonical_team_id', v_canonical_team_id,
        'aliases_reverted', v_aliases_reverted,
        'message', format('Successfully reverted merge of team %s', v_deprecated_team_id)
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- VIEW: Recent merge activity
-- ============================================================================

CREATE OR REPLACE VIEW recent_merge_activity AS
SELECT
    ma.id,
    ma.action,
    ma.deprecated_team_id,
    dt.team_name as deprecated_team_name,
    ma.canonical_team_id,
    ct.team_name as canonical_team_name,
    ma.games_affected,
    ma.aliases_updated,
    ma.performed_by,
    ma.performed_at,
    ma.reverted_at,
    ma.reverted_by,
    ma.revert_reason,
    ma.notes
FROM team_merge_audit ma
LEFT JOIN teams dt ON ma.deprecated_team_id = dt.team_id_master
LEFT JOIN teams ct ON ma.canonical_team_id = ct.team_id_master
ORDER BY ma.performed_at DESC;

-- ============================================================================
-- DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE team_merge_audit IS
    'Audit trail for all team merge and revert operations. Stores snapshots '
    'for recovery and tracks who performed each action.';

COMMENT ON FUNCTION execute_team_merge IS
    'Performs a team merge with full validation, alias cascade, and audit logging. '
    'Returns JSON with success status and impact metrics.';

COMMENT ON FUNCTION revert_team_merge IS
    'Reverts a team merge by merge_id. Restores team status, reverts aliases, '
    'and creates audit trail. Returns JSON with success status.';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'team_merge_audit'
    ) THEN
        RAISE EXCEPTION 'Migration failed: team_merge_audit table not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'execute_team_merge'
    ) THEN
        RAISE EXCEPTION 'Migration failed: execute_team_merge function not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'revert_team_merge'
    ) THEN
        RAISE EXCEPTION 'Migration failed: revert_team_merge function not created';
    END IF;

    RAISE NOTICE 'Migration successful: team_merge_audit table and merge functions created';
END $$;
