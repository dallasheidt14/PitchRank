-- Migration: Add optimized national rankings RPCs
-- Date: 2026-04-06
-- Purpose: Replace direct rankings_view scans for national rankings with RPCs
--          that filter on rankings_full first, then paginate the filtered cohort.

-- =====================================================
-- Function 1: get_national_rankings - paginated national rankings list
-- =====================================================

CREATE OR REPLACE FUNCTION get_national_rankings(
    p_age TEXT DEFAULT '',
    p_gender TEXT DEFAULT '',
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
    age_norm AS (
        SELECT CASE
            WHEN NULLIF(p_age, '') IS NULL THEN NULL
            WHEN p_age::INTEGER = 18 THEN 19
            ELSE p_age::INTEGER
        END AS age_val
    ),
    gender_norm AS (
        SELECT CASE
            WHEN p_gender IN ('M', 'B') THEN 'Male'
            WHEN p_gender IN ('F', 'G') THEN 'Female'
            ELSE p_gender
        END AS gender_val
    ),
    base AS (
        SELECT
            t.team_id_master,
            t.team_name,
            t.club_name,
            rf.state_code,
            CASE
                WHEN (
                    CASE
                        WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                        WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                        WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                        ELSE NULL
                    END
                ) = 18 THEN 19
                ELSE
                    CASE
                        WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                        WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                        WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                        ELSE NULL
                    END
            END AS normalized_age,
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
            CASE
                WHEN rf.status = 'Active'
                THEN COALESCE(rf.rank_in_cohort_final, rf.rank_in_cohort_ml, rf.rank_in_cohort)
                ELSE NULL
            END AS rank_in_cohort_final,
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
        CROSS JOIN age_norm an
        CROSS JOIN gender_norm gn
        WHERE rf.status IN ('Active', 'Not Enough Ranked Games')
          AND t.is_deprecated IS NOT TRUE
          AND rf.power_score_final IS NOT NULL
          AND (
              an.age_val IS NULL
              OR
              CASE
                  WHEN (
                      CASE
                          WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                          WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                          WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                          ELSE NULL
                      END
                  ) = 18 THEN 19
                  ELSE
                      CASE
                          WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                          WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                          WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                          ELSE NULL
                      END
              END = an.age_val
          )
          AND (
              NULLIF(p_gender, '') IS NULL
              OR rf.gender = gn.gender_val
          )
    )
    SELECT
        b.team_id_master,
        b.team_name,
        b.club_name,
        b.state_code AS state,
        b.normalized_age AS age,
        CASE
            WHEN b.raw_gender = 'Male' THEN 'M'
            WHEN b.raw_gender = 'Female' THEN 'F'
            WHEN b.raw_gender = 'Boys' THEN 'M'
            WHEN b.raw_gender = 'Girls' THEN 'F'
            WHEN b.raw_gender = 'M' THEN 'M'
            WHEN b.raw_gender = 'F' THEN 'F'
            ELSE b.raw_gender
        END AS gender,
        b.games_played,
        b.wins,
        b.losses,
        b.draws,
        b.total_games_played,
        b.total_wins,
        b.total_losses,
        b.total_draws,
        CASE
            WHEN b.total_games_played > 0
            THEN ((b.total_wins::NUMERIC + b.total_draws::NUMERIC * 0.5)
                  / b.total_games_played::NUMERIC) * 100
            ELSE NULL
        END AS win_percentage,
        b.power_score_final,
        b.sos_norm,
        b.sos_norm_state,
        b.off_norm AS offense_norm,
        b.def_norm AS defense_norm,
        b.perf_centered,
        b.rank_in_cohort_final,
        b.sos_rank_national,
        b.sos_rank_state,
        b.rank_change_7d,
        b.rank_change_30d,
        b.rank_change_state_7d,
        b.rank_change_state_30d,
        b.status,
        b.last_game,
        b.last_calculated
    FROM base b
    ORDER BY
        b.rank_in_cohort_final ASC NULLS LAST,
        b.team_id_master ASC
    LIMIT p_limit
    OFFSET p_offset;
$$;

COMMENT ON FUNCTION get_national_rankings IS
  'Paginated national rankings RPC. Filters on rankings_full first, then returns '
  'RankingRow-compatible rows ordered by stored rank_in_cohort_final. Intended '
  'for national age/gender cohort pages to avoid heavy rankings_view scans.';

-- =====================================================
-- Function 2: get_national_rankings_count - fast count
-- =====================================================

CREATE OR REPLACE FUNCTION get_national_rankings_count(
    p_age TEXT DEFAULT '',
    p_gender TEXT DEFAULT ''
)
RETURNS BIGINT LANGUAGE sql STABLE AS $$
    WITH age_norm AS (
        SELECT CASE
            WHEN NULLIF(p_age, '') IS NULL THEN NULL
            WHEN p_age::INTEGER = 18 THEN 19
            ELSE p_age::INTEGER
        END AS age_val
    )
    SELECT COUNT(*)
    FROM rankings_full rf
    JOIN teams t ON t.team_id_master = rf.team_id
    CROSS JOIN age_norm an
    WHERE rf.status IN ('Active', 'Not Enough Ranked Games')
      AND t.is_deprecated IS NOT TRUE
      AND rf.power_score_final IS NOT NULL
      AND (
          an.age_val IS NULL
          OR
          CASE
              WHEN (
                  CASE
                      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                      WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                      ELSE NULL
                  END
              ) = 18 THEN 19
              ELSE
                  CASE
                      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
                      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
                      WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
                      ELSE NULL
                  END
          END = an.age_val
      )
      AND (
          NULLIF(p_gender, '') IS NULL
          OR rf.gender = CASE
              WHEN p_gender IN ('M', 'B') THEN 'Male'
              WHEN p_gender IN ('F', 'G') THEN 'Female'
              ELSE p_gender
          END
      );
$$;

COMMENT ON FUNCTION get_national_rankings_count IS
  'Fast count of national rankings rows for an age/gender cohort. Uses rankings_full '
  'filters directly instead of querying rankings_view with exact count.';

-- =====================================================
-- Grant permissions
-- =====================================================

GRANT EXECUTE ON FUNCTION get_national_rankings(TEXT, TEXT, INT, INT) TO anon;
GRANT EXECUTE ON FUNCTION get_national_rankings(TEXT, TEXT, INT, INT) TO authenticated;
GRANT EXECUTE ON FUNCTION get_national_rankings_count(TEXT, TEXT) TO anon;
GRANT EXECUTE ON FUNCTION get_national_rankings_count(TEXT, TEXT) TO authenticated;
