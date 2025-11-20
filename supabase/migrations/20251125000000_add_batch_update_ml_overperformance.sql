-- Modify the immutability trigger to allow ml_overperformance updates
-- This is a computed field that doesn't affect game integrity

CREATE OR REPLACE FUNCTION prevent_game_updates() RETURNS TRIGGER AS $$
BEGIN
    -- Allow updates only if is_immutable is false
    -- OR if only ml_overperformance is being updated (it's a computed field)
    IF OLD.is_immutable = TRUE THEN
        -- Check if only ml_overperformance changed
        IF (
            OLD.game_date IS NOT DISTINCT FROM NEW.game_date AND
            OLD.home_team_master_id IS NOT DISTINCT FROM NEW.home_team_master_id AND
            OLD.away_team_master_id IS NOT DISTINCT FROM NEW.away_team_master_id AND
            OLD.home_score IS NOT DISTINCT FROM NEW.home_score AND
            OLD.away_score IS NOT DISTINCT FROM NEW.away_score AND
            OLD.game_uid IS NOT DISTINCT FROM NEW.game_uid AND
            OLD.provider_id IS NOT DISTINCT FROM NEW.provider_id
        ) THEN
            -- Only ml_overperformance or other computed fields changed - allow it
            RETURN NEW;
        END IF;

        -- Core game data changed - block it
        RAISE EXCEPTION 'Cannot update immutable game. Use game_corrections table instead. Game UID: %', OLD.game_uid;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create RPC function for batch updating ml_overperformance
-- This is much faster than individual UPDATE queries

CREATE OR REPLACE FUNCTION batch_update_ml_overperformance(
    updates JSONB
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    -- Update games using the provided JSON array
    -- Expected format: [{"id": "uuid", "ml_overperformance": 1.23}, ...]
    WITH update_data AS (
        SELECT
            (item->>'id')::UUID AS game_id,
            (item->>'ml_overperformance')::FLOAT AS ml_value
        FROM jsonb_array_elements(updates) AS item
    )
    UPDATE games g
    SET ml_overperformance = ud.ml_value
    FROM update_data ud
    WHERE g.id = ud.game_id;

    GET DIAGNOSTICS updated_count = ROW_COUNT;

    RETURN updated_count;
END;
$$;

-- Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION batch_update_ml_overperformance(JSONB) TO authenticated;
GRANT EXECUTE ON FUNCTION batch_update_ml_overperformance(JSONB) TO service_role;

COMMENT ON FUNCTION batch_update_ml_overperformance IS
'Batch update ml_overperformance values for multiple games.
Takes a JSONB array of {id, ml_overperformance} objects.
Returns the number of rows updated.';
