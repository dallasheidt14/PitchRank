-- Migration: Add link_game_team function and fix immutability trigger
-- This function allows linking a team to a game while properly handling immutability

-- =====================================================
-- UPDATE IMMUTABILITY TRIGGER
-- Allow safe team linking AND is_immutable column changes
-- =====================================================

-- Drop existing trigger first
DROP TRIGGER IF EXISTS enforce_game_immutability ON games;

-- Create updated function that allows:
-- 1. Safe team linking (NULL -> value for team_master_id)
-- 2. is_immutable column changes (for administrative operations)
CREATE OR REPLACE FUNCTION prevent_game_updates() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_immutable = TRUE THEN
        -- EXCEPTION 1: Allow changing is_immutable itself (for admin/function use)
        -- This enables functions like link_game_team to work
        IF (NEW.is_immutable IS DISTINCT FROM OLD.is_immutable) AND
           (OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id) AND
           (OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id) AND
           (OLD.home_score IS NOT DISTINCT FROM NEW.home_score) AND
           (OLD.away_score IS NOT DISTINCT FROM NEW.away_score) AND
           (OLD.game_date IS NOT DISTINCT FROM NEW.game_date)
        THEN
            RETURN NEW; -- Allow immutability toggle
        END IF;

        -- EXCEPTION 2: Allow safe team linking
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
                   OLD.source_url IS NOT DISTINCT FROM NEW.source_url AND
                   OLD.is_immutable IS NOT DISTINCT FROM NEW.is_immutable THEN
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
-- HELPER FUNCTION: Link a team to a specific game
-- Uses direct UPDATE since trigger now allows safe team links
-- =====================================================

CREATE OR REPLACE FUNCTION link_game_team(
    p_game_id UUID,
    p_team_id_master UUID,
    p_is_home_team BOOLEAN
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_value UUID;
    v_success BOOLEAN := FALSE;
BEGIN
    -- Check if already linked (prevent accidental overwrites)
    IF p_is_home_team THEN
        SELECT home_team_master_id INTO v_current_value FROM games WHERE id = p_game_id;
        IF v_current_value IS NOT NULL THEN
            RAISE EXCEPTION 'Home team already linked to another team: %', v_current_value;
        END IF;
    ELSE
        SELECT away_team_master_id INTO v_current_value FROM games WHERE id = p_game_id;
        IF v_current_value IS NOT NULL THEN
            RAISE EXCEPTION 'Away team already linked to another team: %', v_current_value;
        END IF;
    END IF;

    -- Perform the team link update (trigger will allow this as a safe team link)
    IF p_is_home_team THEN
        UPDATE games SET home_team_master_id = p_team_id_master WHERE id = p_game_id;
    ELSE
        UPDATE games SET away_team_master_id = p_team_id_master WHERE id = p_game_id;
    END IF;

    -- Verify the update worked
    IF p_is_home_team THEN
        SELECT home_team_master_id = p_team_id_master INTO v_success FROM games WHERE id = p_game_id;
    ELSE
        SELECT away_team_master_id = p_team_id_master INTO v_success FROM games WHERE id = p_game_id;
    END IF;

    RETURN v_success;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Grant execute permission to authenticated and service role
GRANT EXECUTE ON FUNCTION link_game_team TO authenticated;
GRANT EXECUTE ON FUNCTION link_game_team TO service_role;

-- Comments
COMMENT ON FUNCTION link_game_team IS 'Safely link a team to a game. p_is_home_team=true for home team, false for away team.';
COMMENT ON FUNCTION prevent_game_updates IS 'Trigger function that enforces game immutability while allowing safe team links and immutability toggling.';
