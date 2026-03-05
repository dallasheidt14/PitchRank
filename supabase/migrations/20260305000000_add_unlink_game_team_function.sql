-- Migration: Add unlink_game_team function
-- Allows reverting an incorrect team link by setting team_master_id back to NULL
-- Bypasses immutability trigger safely via SECURITY DEFINER

-- Update immutability trigger to also allow value -> NULL (unlinking)
DROP TRIGGER IF EXISTS enforce_game_immutability ON games;

CREATE OR REPLACE FUNCTION prevent_game_updates() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_immutable = TRUE THEN
        -- EXCEPTION 1: Allow changing is_immutable itself (for admin/function use)
        IF (NEW.is_immutable IS DISTINCT FROM OLD.is_immutable) AND
           (OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id) AND
           (OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id) AND
           (OLD.home_score IS NOT DISTINCT FROM NEW.home_score) AND
           (OLD.away_score IS NOT DISTINCT FROM NEW.away_score) AND
           (OLD.game_date IS NOT DISTINCT FROM NEW.game_date)
        THEN
            RETURN NEW;
        END IF;

        -- EXCEPTION 2: Allow safe team linking (NULL -> value) AND unlinking (value -> NULL)
        DECLARE
            is_safe_team_change BOOLEAN := FALSE;
        BEGIN
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
                OR
                -- Home team unlinking: value -> NULL
                (OLD.home_team_master_id IS NOT NULL AND NEW.home_team_master_id IS NULL AND
                 OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id)
                OR
                -- Away team unlinking: value -> NULL
                (OLD.away_team_master_id IS NOT NULL AND NEW.away_team_master_id IS NULL AND
                 OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id)
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
                    is_safe_team_change := TRUE;
                END IF;
            END IF;

            IF is_safe_team_change THEN
                RETURN NEW;
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

-- Function to unlink a team from a specific game
CREATE OR REPLACE FUNCTION unlink_game_team(
    p_game_id UUID,
    p_team_id_master UUID,
    p_is_home_team BOOLEAN
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_value UUID;
    v_success BOOLEAN := FALSE;
BEGIN
    -- Verify the current value matches what we expect to unlink
    IF p_is_home_team THEN
        SELECT home_team_master_id INTO v_current_value FROM games WHERE id = p_game_id;
        IF v_current_value IS NULL THEN
            RAISE EXCEPTION 'Home team is already unlinked for game: %', p_game_id;
        END IF;
        IF v_current_value != p_team_id_master THEN
            RAISE EXCEPTION 'Home team mismatch: expected %, found %', p_team_id_master, v_current_value;
        END IF;
        UPDATE games SET home_team_master_id = NULL WHERE id = p_game_id;
    ELSE
        SELECT away_team_master_id INTO v_current_value FROM games WHERE id = p_game_id;
        IF v_current_value IS NULL THEN
            RAISE EXCEPTION 'Away team is already unlinked for game: %', p_game_id;
        END IF;
        IF v_current_value != p_team_id_master THEN
            RAISE EXCEPTION 'Away team mismatch: expected %, found %', p_team_id_master, v_current_value;
        END IF;
        UPDATE games SET away_team_master_id = NULL WHERE id = p_game_id;
    END IF;

    -- Verify the update worked
    IF p_is_home_team THEN
        SELECT home_team_master_id IS NULL INTO v_success FROM games WHERE id = p_game_id;
    ELSE
        SELECT away_team_master_id IS NULL INTO v_success FROM games WHERE id = p_game_id;
    END IF;

    RETURN v_success;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

GRANT EXECUTE ON FUNCTION unlink_game_team TO authenticated;
GRANT EXECUTE ON FUNCTION unlink_game_team TO service_role;

COMMENT ON FUNCTION unlink_game_team IS 'Safely unlink a team from a game by setting team_master_id back to NULL. Verifies the current link matches before unlinking.';
