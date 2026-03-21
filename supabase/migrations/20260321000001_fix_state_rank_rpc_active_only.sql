-- Fix: get_team_state_rank RPC should only rank Active teams
-- Date: 2026-03-21
-- Problem: The function counted 'Not Enough Ranked Games' teams in the state rank
--          calculation, which meant:
--          1. Non-Active teams could receive a state rank
--          2. Active teams' ranks were inflated by counting non-Active teams ahead of them
--
-- Fix: Only count Active teams in the ranking query AND only return
--      a rank for Active teams.

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
        -- State rank: count Active teams with higher power_score_final + 1
        (
            SELECT COUNT(*) + 1
            FROM rankings_full rf
            WHERE rf.state_code = ti.state_code
              AND rf.age_group = ti.age_group
              AND rf.gender = ti.gender
              AND rf.status = 'Active'
              AND rf.power_score_final > ti.power_score_final
        )::BIGINT AS state_rank,
        -- SOS state rank: count Active teams with higher sos_norm_state + 1
        (
            SELECT COUNT(*) + 1
            FROM rankings_full rf
            WHERE rf.state_code = ti.state_code
              AND rf.age_group = ti.age_group
              AND rf.gender = ti.gender
              AND rf.status = 'Active'
              AND rf.sos_norm_state IS NOT NULL
              AND ti.sos_norm_state IS NOT NULL
              AND rf.sos_norm_state > ti.sos_norm_state
        )::BIGINT AS sos_rank_state
    FROM team_info ti
    WHERE ti.status = 'Active';  -- Only return rank for Active teams
$$;

-- Grant access
GRANT EXECUTE ON FUNCTION get_team_state_rank(UUID) TO anon;
GRANT EXECUTE ON FUNCTION get_team_state_rank(UUID) TO authenticated;
