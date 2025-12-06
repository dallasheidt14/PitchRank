-- Safe Team Linking Migration
-- Allows frontend users to link unknown opponents to teams
-- with full audit trail and safety guarantees

-- =====================================================
-- AUDIT TABLE FOR TEAM LINKING
-- =====================================================

CREATE TABLE IF NOT EXISTS team_link_audit (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    provider_team_id TEXT NOT NULL,
    team_id_master UUID NOT NULL REFERENCES teams(team_id_master),
    provider_id UUID REFERENCES providers(id),
    games_updated INTEGER DEFAULT 0,
    linked_by TEXT DEFAULT 'frontend_user',
    linked_at TIMESTAMPTZ DEFAULT NOW(),
    reverted_at TIMESTAMPTZ,
    reverted_by TEXT,
    notes TEXT
);

-- Indexes for audit queries
CREATE INDEX IF NOT EXISTS idx_team_link_audit_provider_team ON team_link_audit(provider_team_id);
CREATE INDEX IF NOT EXISTS idx_team_link_audit_team_master ON team_link_audit(team_id_master);
CREATE INDEX IF NOT EXISTS idx_team_link_audit_linked_at ON team_link_audit(linked_at DESC);

-- =====================================================
-- SAFE IMMUTABILITY TRIGGER UPDATE
-- =====================================================

-- Drop existing trigger first
DROP TRIGGER IF EXISTS enforce_game_immutability ON games;

-- Create updated function that allows safe team linking
CREATE OR REPLACE FUNCTION prevent_game_updates() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_immutable = TRUE THEN
        -- SAFE: Allow linking teams to previously NULL fields only
        -- This is the ONLY modification allowed on immutable games

        DECLARE
            is_safe_team_link BOOLEAN := FALSE;
        BEGIN
            -- Check if this is a safe team linking operation:
            -- 1. Only home_team_master_id or away_team_master_id changed
            -- 2. Changed from NULL to a value (never overwrite existing)
            -- 3. All other fields remain unchanged

            IF (
                -- Home team linking: NULL -> value
                (OLD.home_team_master_id IS NULL AND NEW.home_team_master_id IS NOT NULL AND
                 OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id)
                OR
                -- Away team linking: NULL -> value
                (OLD.away_team_master_id IS NULL AND NEW.away_team_master_id IS NOT NULL AND
                 OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id)
                OR
                -- Both team linking at once: NULL -> value for both
                (OLD.home_team_master_id IS NULL AND NEW.home_team_master_id IS NOT NULL AND
                 OLD.away_team_master_id IS NULL AND NEW.away_team_master_id IS NOT NULL)
            ) THEN
                -- Verify NO other fields changed (strict safety check)
                IF OLD.home_score IS NOT DISTINCT FROM NEW.home_score AND
                   OLD.away_score IS NOT DISTINCT FROM NEW.away_score AND
                   OLD.game_date IS NOT DISTINCT FROM NEW.game_date AND
                   OLD.home_provider_id IS NOT DISTINCT FROM NEW.home_provider_id AND
                   OLD.away_provider_id IS NOT DISTINCT FROM NEW.away_provider_id AND
                   OLD.competition IS NOT DISTINCT FROM NEW.competition AND
                   OLD.division_name IS NOT DISTINCT FROM NEW.division_name AND
                   OLD.event_name IS NOT DISTINCT FROM NEW.event_name AND
                   OLD.venue IS NOT DISTINCT FROM NEW.venue AND
                   OLD.result IS NOT DISTINCT FROM NEW.result AND
                   OLD.provider_id IS NOT DISTINCT FROM NEW.provider_id AND
                   OLD.source_url IS NOT DISTINCT FROM NEW.source_url THEN
                    is_safe_team_link := TRUE;
                END IF;
            END IF;

            IF is_safe_team_link THEN
                RETURN NEW;  -- Allow safe team linking
            END IF;
        END;

        -- Block all other updates on immutable games
        RAISE EXCEPTION 'Cannot update immutable game. Use game_corrections table. Game ID: %', OLD.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Recreate trigger with updated function
CREATE TRIGGER enforce_game_immutability
    BEFORE UPDATE ON games
    FOR EACH ROW
    EXECUTE FUNCTION prevent_game_updates();

-- =====================================================
-- HELPER FUNCTION: Count games that would be affected
-- =====================================================

CREATE OR REPLACE FUNCTION count_linkable_games(
    p_provider_team_id TEXT,
    p_provider_id UUID
) RETURNS TABLE (
    as_home_team INTEGER,
    as_away_team INTEGER,
    total INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (SELECT COUNT(*)::INTEGER FROM games
         WHERE home_provider_id = p_provider_team_id
           AND provider_id = p_provider_id
           AND home_team_master_id IS NULL) as as_home_team,
        (SELECT COUNT(*)::INTEGER FROM games
         WHERE away_provider_id = p_provider_team_id
           AND provider_id = p_provider_id
           AND away_team_master_id IS NULL) as as_away_team,
        (SELECT COUNT(*)::INTEGER FROM games
         WHERE (home_provider_id = p_provider_team_id AND home_team_master_id IS NULL)
            OR (away_provider_id = p_provider_team_id AND away_team_master_id IS NULL)
           AND provider_id = p_provider_id) as total;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- HELPER FUNCTION: Safe backfill games for a provider_team_id
-- =====================================================

CREATE OR REPLACE FUNCTION backfill_team_links(
    p_provider_team_id TEXT,
    p_team_id_master UUID,
    p_provider_id UUID,
    p_linked_by TEXT DEFAULT 'frontend_user'
) RETURNS INTEGER AS $$
DECLARE
    v_home_updated INTEGER := 0;
    v_away_updated INTEGER := 0;
    v_total_updated INTEGER := 0;
BEGIN
    -- Update games where this provider_team_id is the HOME team
    UPDATE games
    SET home_team_master_id = p_team_id_master
    WHERE home_provider_id = p_provider_team_id
      AND provider_id = p_provider_id
      AND home_team_master_id IS NULL;

    GET DIAGNOSTICS v_home_updated = ROW_COUNT;

    -- Update games where this provider_team_id is the AWAY team
    UPDATE games
    SET away_team_master_id = p_team_id_master
    WHERE away_provider_id = p_provider_team_id
      AND provider_id = p_provider_id
      AND away_team_master_id IS NULL;

    GET DIAGNOSTICS v_away_updated = ROW_COUNT;

    v_total_updated := v_home_updated + v_away_updated;

    -- Log to audit table
    INSERT INTO team_link_audit (
        provider_team_id,
        team_id_master,
        provider_id,
        games_updated,
        linked_by,
        notes
    ) VALUES (
        p_provider_team_id,
        p_team_id_master,
        p_provider_id,
        v_total_updated,
        p_linked_by,
        format('Home: %s, Away: %s', v_home_updated, v_away_updated)
    );

    RETURN v_total_updated;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- COMMENTS
-- =====================================================

COMMENT ON TABLE team_link_audit IS 'Audit trail for manual team linking from frontend';
COMMENT ON FUNCTION count_linkable_games IS 'Preview count of games that would be affected by linking a provider_team_id';
COMMENT ON FUNCTION backfill_team_links IS 'Safely link all games with a provider_team_id to a team, with audit logging';
