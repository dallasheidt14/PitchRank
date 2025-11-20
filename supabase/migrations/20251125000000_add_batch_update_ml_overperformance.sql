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
