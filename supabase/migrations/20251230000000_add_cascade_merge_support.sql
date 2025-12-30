-- Migration: Add cascade merge support
-- Purpose: Allow merging teams that have other teams merged into them by auto-cascading
-- This enables merge chains like C → A → B by automatically re-pointing C → B when A → B is merged

-- ============================================================================
-- UPDATED EXECUTE TEAM MERGE FUNCTION WITH CASCADE SUPPORT
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
    v_cascaded_teams INTEGER := 0;
    v_cascaded_team_ids UUID[];
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

    -- 2. Validate canonical team exists and is not deprecated
    IF NOT EXISTS (
        SELECT 1 FROM teams
        WHERE team_id_master = p_canonical_team_id
    ) THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Canonical team %s does not exist', p_canonical_team_id)
        );
    END IF;

    IF EXISTS (
        SELECT 1 FROM teams
        WHERE team_id_master = p_canonical_team_id
        AND is_deprecated = TRUE
    ) THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Cannot merge into team %s - it is marked as deprecated', p_canonical_team_id)
        );
    END IF;

    -- 3. Prevent self-merge
    IF p_deprecated_team_id = p_canonical_team_id THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', 'Cannot merge a team into itself'
        );
    END IF;

    -- 4. CASCADE: Re-point any teams that are merged INTO the deprecated team
    -- This handles the case where C → A exists and we want to merge A → B
    -- We first update C to point directly to B
    SELECT ARRAY_AGG(deprecated_team_id) INTO v_cascaded_team_ids
    FROM team_merge_map
    WHERE canonical_team_id = p_deprecated_team_id;

    IF v_cascaded_team_ids IS NOT NULL AND array_length(v_cascaded_team_ids, 1) > 0 THEN
        -- Update all incoming merges to point to the new canonical
        UPDATE team_merge_map
        SET canonical_team_id = p_canonical_team_id
        WHERE canonical_team_id = p_deprecated_team_id;

        GET DIAGNOSTICS v_cascaded_teams = ROW_COUNT;

        -- Log cascade in audit
        INSERT INTO team_merge_audit (
            deprecated_team_id,
            canonical_team_id,
            action,
            performed_by,
            notes
        )
        VALUES (
            p_deprecated_team_id,
            p_canonical_team_id,
            'cascade_alias',
            p_merged_by,
            format('Auto-cascaded %s teams from %s to %s: %s',
                   v_cascaded_teams,
                   p_deprecated_team_id,
                   p_canonical_team_id,
                   v_cascaded_team_ids::text)
        );
    END IF;

    -- 5. Snapshot the deprecated team before changes
    SELECT to_jsonb(t.*) INTO v_deprecated_snapshot
    FROM teams t
    WHERE team_id_master = p_deprecated_team_id;

    IF v_deprecated_snapshot IS NULL THEN
        RETURN jsonb_build_object(
            'success', FALSE,
            'error', format('Deprecated team %s not found', p_deprecated_team_id)
        );
    END IF;

    -- 6. Count affected games
    SELECT COUNT(*) INTO v_games_affected
    FROM games
    WHERE home_team_master_id = p_deprecated_team_id
       OR away_team_master_id = p_deprecated_team_id;

    -- 7. Create merge map entry (trigger validation should now pass since we cascaded)
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

    -- 8. Cascade update team_alias_map
    UPDATE team_alias_map
    SET team_id_master = p_canonical_team_id
    WHERE team_id_master = p_deprecated_team_id;

    GET DIAGNOSTICS v_aliases_updated = ROW_COUNT;

    -- 9. Mark deprecated team
    UPDATE teams
    SET is_deprecated = TRUE, updated_at = NOW()
    WHERE team_id_master = p_deprecated_team_id;

    -- 10. Create audit record
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
        CASE
            WHEN v_cascaded_teams > 0 THEN
                format('%s (cascaded %s incoming merges)', COALESCE(p_merge_reason, ''), v_cascaded_teams)
            ELSE
                p_merge_reason
        END
    );

    -- 11. Return success summary
    RETURN jsonb_build_object(
        'success', TRUE,
        'merge_id', v_merge_id,
        'deprecated_team_id', p_deprecated_team_id,
        'canonical_team_id', p_canonical_team_id,
        'games_affected', v_games_affected,
        'aliases_updated', v_aliases_updated,
        'cascaded_teams', v_cascaded_teams,
        'cascaded_team_ids', v_cascaded_team_ids,
        'message', CASE
            WHEN v_cascaded_teams > 0 THEN
                format('Successfully merged team into %s (auto-cascaded %s incoming merges)', p_canonical_team_id, v_cascaded_teams)
            ELSE
                format('Successfully merged team into %s', p_canonical_team_id)
        END
    );
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DOCUMENTATION
-- ============================================================================

COMMENT ON FUNCTION execute_team_merge IS
    'Performs a team merge with full validation, alias cascade, and audit logging. '
    'Now supports CASCADE: if other teams are merged into the deprecated team, they are '
    'automatically re-pointed to the new canonical team. Returns JSON with success status, '
    'impact metrics, and cascade info.';

-- ============================================================================
-- VERIFICATION
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc WHERE proname = 'execute_team_merge'
    ) THEN
        RAISE EXCEPTION 'Migration failed: execute_team_merge function not updated';
    END IF;

    RAISE NOTICE 'Migration successful: execute_team_merge now supports cascading merges';
END $$;
