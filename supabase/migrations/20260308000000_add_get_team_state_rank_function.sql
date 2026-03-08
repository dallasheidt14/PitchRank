-- RPC function to compute a team's state rank from rankings_full.
-- This avoids the state_rankings_view timeout (which requires ROW_NUMBER over all rows)
-- and avoids the FLOAT8 vs NUMERIC precision bug in PostgREST .gt() filters.
-- By using a subquery to get the team's score as FLOAT8, the comparison is FLOAT8 > FLOAT8.

CREATE OR REPLACE FUNCTION get_team_state_rank(p_team_id UUID)
RETURNS TABLE (
    state_rank BIGINT,
    sos_rank_state BIGINT
) LANGUAGE sql STABLE AS $$
    WITH team_info AS (
        SELECT
            team_id,
            state_code,
            age_group,
            gender,
            power_score_final,
            sos_norm_state,
            status
        FROM rankings_full
        WHERE team_id = p_team_id
    )
    SELECT
        -- State rank: count teams with higher power_score_final in same state/age/gender + 1
        (
            SELECT COUNT(*) + 1
            FROM rankings_full rf
            WHERE rf.state_code = ti.state_code
              AND rf.age_group = ti.age_group
              AND rf.gender = ti.gender
              AND rf.status IN ('Active', 'Not Enough Ranked Games')
              AND rf.power_score_final > ti.power_score_final
        )::BIGINT AS state_rank,
        -- SOS state rank: count teams with higher sos_norm_state in same state/age/gender + 1
        (
            SELECT COUNT(*) + 1
            FROM rankings_full rf
            WHERE rf.state_code = ti.state_code
              AND rf.age_group = ti.age_group
              AND rf.gender = ti.gender
              AND rf.status IN ('Active', 'Not Enough Ranked Games')
              AND rf.sos_norm_state IS NOT NULL
              AND ti.sos_norm_state IS NOT NULL
              AND rf.sos_norm_state > ti.sos_norm_state
        )::BIGINT AS sos_rank_state
    FROM team_info ti
    WHERE ti.status IN ('Active', 'Not Enough Ranked Games');
$$;

-- Grant access
GRANT EXECUTE ON FUNCTION get_team_state_rank(UUID) TO anon;
GRANT EXECUTE ON FUNCTION get_team_state_rank(UUID) TO authenticated;
