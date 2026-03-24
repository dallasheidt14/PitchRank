-- RPC function to return state rankings for a specific (state, age, gender) cohort.
-- This replaces querying state_rankings_view which times out on large states (TX, CA, NY, WA)
-- because its ROW_NUMBER() window function scans ALL rows across ALL states before
-- PostgREST filters are applied.
--
-- This RPC filters FIRST to the specific cohort, then computes ROW_NUMBER() only
-- on that small set (typically <500 rows), making it fast and reliable.

-- =====================================================
-- Function 1: get_state_rankings — paginated state rankings list
-- =====================================================

CREATE OR REPLACE FUNCTION get_state_rankings(
    p_state TEXT,
    p_age TEXT,
    p_gender TEXT,
    p_limit INT DEFAULT 1000,
    p_offset INT DEFAULT 0
)
RETURNS TABLE (
    team_id_master UUID,
    team_name TEXT,
    club_name TEXT,
    state TEXT,
    age INT,
    gender TEXT,
    games_played INT,
    wins INT,
    losses INT,
    draws INT,
    total_games_played INT,
    total_wins INT,
    total_losses INT,
    total_draws INT,
    win_percentage NUMERIC,
    power_score_final FLOAT8,
    sos_norm FLOAT8,
    sos_norm_state FLOAT8,
    offense_norm FLOAT8,
    defense_norm FLOAT8,
    perf_centered FLOAT8,
    rank_in_cohort_final INT,
    rank_in_state_final BIGINT,
    sos_rank_national INT,
    sos_rank_state INT,
    rank_change_7d INT,
    rank_change_30d INT,
    rank_change_state_7d INT,
    rank_change_state_30d INT,
    status TEXT,
    last_game TIMESTAMPTZ,
    last_calculated TIMESTAMPTZ
) LANGUAGE sql STABLE AS $$
    WITH
    -- Normalize gender parameter to rankings_full format
    gender_norm AS (
        SELECT CASE
            WHEN p_gender IN ('M', 'B') THEN 'Male'
            WHEN p_gender IN ('F', 'G') THEN 'Female'
            ELSE p_gender
        END AS gender_val
    ),
    -- Filter to the specific cohort first (fast — uses indexes)
    cohort AS (
        SELECT
            t.team_id_master,
            t.team_name,
            t.club_name,
            rf.state_code,
            rf.age_group,
            rf.gender AS raw_gender,
            COALESCE(rf.games_played, cr.games_played) AS games_played,
            COALESCE(rf.wins, cr.wins) AS wins,
            COALESCE(rf.losses, cr.losses) AS losses,
            COALESCE(rf.draws, cr.draws) AS draws,
            COALESCE(rf.total_games_played, 0) AS total_games_played,
            COALESCE(rf.total_wins, 0) AS total_wins,
            COALESCE(rf.total_losses, 0) AS total_losses,
            COALESCE(rf.total_draws, 0) AS total_draws,
            rf.power_score_final,
            rf.sos_norm,
            rf.sos_norm_state,
            rf.off_norm,
            rf.def_norm,
            rf.perf_centered,
            COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,
            rf.sos_rank_national,
            rf.sos_rank_state,
            rf.rank_change_7d,
            rf.rank_change_30d,
            rf.rank_change_state_7d,
            rf.rank_change_state_30d,
            rf.status,
            rf.last_game,
            rf.last_calculated
        FROM teams t
        JOIN rankings_full rf ON t.team_id_master = rf.team_id
        LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
        CROSS JOIN gender_norm gn
        WHERE rf.state_code = UPPER(p_state)
          AND rf.age_group = p_age
          AND rf.gender = gn.gender_val
          AND rf.status IN ('Active', 'Not Enough Ranked Games')
          AND t.is_deprecated IS NOT TRUE
          AND rf.power_score_final IS NOT NULL
    ),
    -- Compute state rank ONLY for Active teams within this cohort
    active_ranked AS (
        SELECT
            c.team_id_master,
            ROW_NUMBER() OVER (ORDER BY c.power_score_final DESC) AS rank_in_state
        FROM cohort c
        WHERE c.status = 'Active'
    )
    SELECT
        c.team_id_master,
        c.team_name,
        c.club_name,
        c.state_code AS state,
        c.age_group::INT AS age,
        CASE
            WHEN c.raw_gender = 'Male' THEN 'M'
            WHEN c.raw_gender = 'Female' THEN 'F'
            WHEN c.raw_gender = 'Boys' THEN 'M'
            WHEN c.raw_gender = 'Girls' THEN 'F'
            WHEN c.raw_gender = 'M' THEN 'M'
            WHEN c.raw_gender = 'F' THEN 'F'
            ELSE c.raw_gender
        END AS gender,
        c.games_played,
        c.wins,
        c.losses,
        c.draws,
        c.total_games_played,
        c.total_wins,
        c.total_losses,
        c.total_draws,
        CASE
            WHEN c.total_games_played > 0
            THEN ((c.total_wins::NUMERIC + c.total_draws::NUMERIC * 0.5)
                  / c.total_games_played::NUMERIC) * 100
            ELSE NULL
        END AS win_percentage,
        c.power_score_final,
        c.sos_norm,
        c.sos_norm_state,
        c.off_norm AS offense_norm,
        c.def_norm AS defense_norm,
        c.perf_centered,
        c.rank_in_cohort_final,
        ar.rank_in_state AS rank_in_state_final,
        c.sos_rank_national,
        c.sos_rank_state,
        c.rank_change_7d,
        c.rank_change_30d,
        c.rank_change_state_7d,
        c.rank_change_state_30d,
        c.status,
        c.last_game,
        c.last_calculated
    FROM cohort c
    LEFT JOIN active_ranked ar ON c.team_id_master = ar.team_id_master
    ORDER BY c.power_score_final DESC
    LIMIT p_limit
    OFFSET p_offset;
$$;

COMMENT ON FUNCTION get_state_rankings IS
  'Fast state rankings RPC. Filters to (state, age, gender) cohort FIRST, '
  'then computes ROW_NUMBER() only on the filtered set. Replaces querying '
  'state_rankings_view which times out on large states due to unscoped window function. '
  'Returns RankingRow-compatible shape with pagination support.';

-- =====================================================
-- Function 2: get_state_rankings_count — fast count
-- =====================================================

CREATE OR REPLACE FUNCTION get_state_rankings_count(
    p_state TEXT,
    p_age TEXT,
    p_gender TEXT
)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    SELECT COUNT(*)
    FROM rankings_full rf
    JOIN teams t ON t.team_id_master = rf.team_id
    WHERE rf.state_code = UPPER(p_state)
      AND rf.age_group = p_age
      AND rf.gender = CASE
          WHEN p_gender IN ('M', 'B') THEN 'Male'
          WHEN p_gender IN ('F', 'G') THEN 'Female'
          ELSE p_gender
      END
      AND rf.status IN ('Active', 'Not Enough Ranked Games')
      AND t.is_deprecated IS NOT TRUE
      AND rf.power_score_final IS NOT NULL;
$$;

COMMENT ON FUNCTION get_state_rankings_count IS
  'Fast count of teams in a (state, age, gender) cohort. '
  'Uses same filters as get_state_rankings but without ROW_NUMBER overhead.';

-- =====================================================
-- Grant permissions
-- =====================================================

GRANT EXECUTE ON FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT) TO anon;
GRANT EXECUTE ON FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_state_rankings_count(TEXT, TEXT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION get_state_rankings_count(TEXT, TEXT, TEXT) TO authenticated;
