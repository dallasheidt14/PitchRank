-- Migration: Merge U18 into U19 age group
-- Date: 2026-03-25
-- Purpose: U19 now encompasses both birth years 2007 and 2008 (formerly U18+U19).
--          The rankings_full table still has age_group='u18' for birth year 2008 teams.
--          This migration remaps age 18 → 19 in the views and RPCs so the frontend
--          filter for U19 includes all former U18 teams.
--
-- What changes:
--   - rankings_view: age column returns 19 instead of 18 for u18 age_group
--   - state_rankings_view: inherits from rankings_view (no direct change needed)
--   - get_state_rankings RPC: WHERE clause remaps 18 → 19 for age comparison
--   - get_state_rankings_count RPC: same remap
--
-- What does NOT change:
--   - All other columns in the views (power scores, ranks, game counts, etc.)
--   - The rankings_full table itself (age_group column stays 'u18' until next ranking run)
--   - The teams table (age_group stays 'u18' for birth year 2008 teams)

-- =====================================================
-- Step 1: Drop existing views (state depends on rankings)
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view with age 18→19 remap
-- =====================================================

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields (always canonical, never deprecated)
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code AS state,
    -- Age extraction with U18→U19 remap: U19 encompasses birth years 2007+2008
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
    END AS age,
    CASE
      WHEN rf.gender = 'Male' THEN 'M'
      WHEN rf.gender = 'Female' THEN 'F'
      WHEN rf.gender = 'Boys' THEN 'M'
      WHEN rf.gender = 'Girls' THEN 'F'
      WHEN rf.gender = 'M' THEN 'M'
      WHEN rf.gender = 'F' THEN 'F'
      ELSE rf.gender
    END AS gender,

    -- Record stats (from rankings_full with fallback - CAPPED AT 30 GAMES for rankings algorithm)
    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,

    -- Total games count (ALL non-excluded games) for display
    (SELECT COUNT(*)
     FROM games g
     WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_games_played,

    -- Total wins from ALL non-excluded games
    (SELECT COUNT(*)
     FROM games g
     WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score > g.away_score)
            OR (g.away_team_master_id = t.team_id_master AND g.away_score > g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_wins,

    -- Total losses from ALL non-excluded games
    (SELECT COUNT(*)
     FROM games g
     WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score < g.away_score)
            OR (g.away_team_master_id = t.team_id_master AND g.away_score < g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_losses,

    -- Total draws from ALL non-excluded games
    (SELECT COUNT(*)
     FROM games g
     WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
       AND g.home_score = g.away_score
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
       AND g.is_excluded = FALSE
    ) AS total_draws,

    -- Recalculated win_percentage based on TOTAL non-excluded games
    CASE
      WHEN (SELECT COUNT(*)
            FROM games g
            WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
              AND g.home_score IS NOT NULL
              AND g.away_score IS NOT NULL
              AND g.is_excluded = FALSE) > 0
      THEN (
        (
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score > g.away_score)
                  OR (g.away_team_master_id = t.team_id_master AND g.away_score > g.home_score))
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL
             AND g.is_excluded = FALSE)
          +
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
             AND g.home_score = g.away_score
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL
             AND g.is_excluded = FALSE) * 0.5
        ) /
        (SELECT COUNT(*)::NUMERIC
         FROM games g
         WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
           AND g.home_score IS NOT NULL
           AND g.away_score IS NOT NULL
           AND g.is_excluded = FALSE)
      ) * 100
      ELSE NULL
    END AS win_percentage,

    -- Metrics (ONLY from rankings_full, NO fallback)
    rf.power_score_final,
    rf.sos_norm,
    rf.sos_norm_state,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Performance/form signal from v53e Layer 6
    rf.perf_centered,

    -- National rank (pre-computed)
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,

    -- SOS Ranks
    rf.sos_rank_national,
    rf.sos_rank_state,

    -- Rank change tracking
    rf.rank_change_7d,
    rf.rank_change_30d,

    -- State rank changes
    rf.rank_change_state_7d,
    rf.rank_change_state_30d,

    -- Activity status fields
    rf.status,
    rf.last_game,
    rf.last_calculated

FROM teams t
LEFT JOIN rankings_full rf ON t.team_id_master = rf.team_id
LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
WHERE (rf.power_score_final IS NOT NULL OR cr.national_power_score IS NOT NULL)
  AND t.is_deprecated IS NOT TRUE;

COMMENT ON VIEW rankings_view IS 'National rankings view. Age 18 remapped to 19 (U19 encompasses birth years 2007+2008). Excludes deprecated/merged teams. Filters is_excluded games from total counts. Uses pre-computed rank_in_cohort_ml. Respects RLS policies.';

-- =====================================================
-- Step 3: Recreate state_rankings_view (inherits age remap from rankings_view)
-- =====================================================

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
SELECT
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state AS state,
    rv.age AS age,
    rv.gender,

    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,

    rv.total_games_played,
    rv.total_wins,
    rv.total_losses,
    rv.total_draws,
    rv.win_percentage,

    rv.power_score_final,
    rv.sos_norm,
    rv.sos_norm_state,
    rv.offense_norm,
    rv.defense_norm,

    rv.perf_centered,

    rv.rank_in_cohort_final,

    -- State rank: computed ONLY among Active/Not Enough Ranked Games teams
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final,

    rv.sos_rank_national,
    rv.sos_rank_state,

    rv.rank_change_7d,
    rv.rank_change_30d,

    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
WHERE rv.state IS NOT NULL
  AND rv.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW state_rankings_view IS 'State rankings view with rank_in_state_final computed among Active/Not Enough Ranked Games teams only. Inherits age 18→19 remap and deprecated team exclusion from rankings_view.';

-- =====================================================
-- Step 4: Update get_state_rankings RPC with age 18→19 remap
-- =====================================================

CREATE OR REPLACE FUNCTION get_state_rankings(
    p_state TEXT,
    p_age TEXT,
    p_gender TEXT
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
    total_games_played BIGINT,
    total_wins BIGINT,
    total_losses BIGINT,
    total_draws BIGINT,
    win_percentage NUMERIC,
    power_score_final DOUBLE PRECISION,
    sos_norm DOUBLE PRECISION,
    sos_norm_state DOUBLE PRECISION,
    offense_norm DOUBLE PRECISION,
    defense_norm DOUBLE PRECISION,
    perf_centered DOUBLE PRECISION,
    rank_in_cohort_final BIGINT,
    rank_in_state INT,
    sos_rank_national BIGINT,
    sos_rank_state BIGINT,
    rank_change_7d INT,
    rank_change_30d INT,
    rank_change_state_7d INT,
    rank_change_state_30d INT,
    status TEXT,
    last_game TIMESTAMPTZ,
    last_calculated TIMESTAMPTZ
)
LANGUAGE sql STABLE AS $$
    WITH gender_norm AS (
        SELECT CASE
            WHEN p_gender IN ('M', 'B', 'male', 'Male', 'boys', 'Boys') THEN 'Male'
            WHEN p_gender IN ('F', 'G', 'female', 'Female', 'girls', 'Girls') THEN 'Female'
            ELSE p_gender
        END AS gender_val
    ),
    -- Remap age: if caller asks for 19, match both 18 and 19 in the data
    -- If caller asks for 18, also remap to 19 (U18 no longer exists as standalone)
    age_target AS (
        SELECT CASE
            WHEN p_age::INTEGER IN (18, 19) THEN 19
            ELSE p_age::INTEGER
        END AS target_age
    ),
    cohort AS (
        SELECT
            t.team_id_master,
            t.team_name,
            t.club_name,
            t.state_code,
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
            END AS age,
            gn.gender_val AS gender,
            COALESCE(rf.games_played, cr.games_played) AS games_played,
            COALESCE(rf.wins, cr.wins) AS wins,
            COALESCE(rf.losses, cr.losses) AS losses,
            COALESCE(rf.draws, cr.draws) AS draws,
            rf.power_score_final,
            rf.sos_norm,
            rf.sos_norm_state,
            rf.off_norm AS offense_norm,
            rf.def_norm AS defense_norm,
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
        FROM rankings_full rf
        JOIN teams t ON t.team_id_master = rf.team_id
        LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
        CROSS JOIN gender_norm gn
        WHERE rf.state_code = UPPER(p_state)
          AND (
              -- Extract numeric age, remap 18→19 (U18 merged into U19), then compare
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
              END
          ) = (SELECT at.target_age FROM age_target at)
          AND rf.gender = gn.gender_val
          AND rf.status IN ('Active', 'Not Enough Ranked Games')
          AND t.is_deprecated IS NOT TRUE
          AND rf.power_score_final IS NOT NULL
    ),
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
        (SELECT at.target_age FROM age_target at)::INT AS age,
        c.gender::TEXT,
        c.games_played,
        c.wins,
        c.losses,
        c.draws,
        -- Total game stats from precomputed columns
        COALESCE(tgs.total_games_played, 0)::BIGINT AS total_games_played,
        COALESCE(tgs.total_wins, 0)::BIGINT AS total_wins,
        COALESCE(tgs.total_losses, 0)::BIGINT AS total_losses,
        COALESCE(tgs.total_draws, 0)::BIGINT AS total_draws,
        COALESCE(tgs.win_percentage, 0)::NUMERIC AS win_percentage,
        c.power_score_final,
        c.sos_norm,
        c.sos_norm_state,
        c.offense_norm,
        c.defense_norm,
        c.perf_centered,
        c.rank_in_cohort_final::BIGINT,
        COALESCE(ar.rank_in_state, 0)::INT AS rank_in_state,
        c.sos_rank_national::BIGINT,
        c.sos_rank_state::BIGINT,
        c.rank_change_7d::INT,
        c.rank_change_30d::INT,
        c.rank_change_state_7d::INT,
        c.rank_change_state_30d::INT,
        c.status::TEXT,
        c.last_game,
        c.last_calculated
    FROM cohort c
    LEFT JOIN active_ranked ar ON c.team_id_master = ar.team_id_master
    LEFT JOIN teams tgs ON c.team_id_master = tgs.team_id_master
    ORDER BY c.power_score_final DESC;
$$;

COMMENT ON FUNCTION get_state_rankings IS
  'State rankings RPC with age 18→19 remap (U19 encompasses birth years 2007+2008). '
  'Returns teams in a (state, age, gender) cohort with rank_in_state. '
  'Age normalization handles 12, u12, U12 formats via regex. '
  'Matches both age 18 and 19 when queried for U19.';

-- =====================================================
-- Step 5: Update get_state_rankings_count RPC with same remap
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
      AND (
          -- Extract numeric age, remap 18→19 (U18 merged into U19), then compare
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
          END
      ) = CASE WHEN p_age::INTEGER = 18 THEN 19 ELSE p_age::INTEGER END
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
  'Fast count of teams in a (state, age, gender) cohort with age 18→19 remap. '
  'Matches both age 18 and 19 when queried for U19.';

-- =====================================================
-- Step 6: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO anon, authenticated;
GRANT SELECT ON state_rankings_view TO anon, authenticated;
