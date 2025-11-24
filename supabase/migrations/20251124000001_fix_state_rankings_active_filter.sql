-- Fix state rankings to compute rank_in_state_final only for Active teams
-- Date: 2025-11-24
-- Purpose: Prevent rank gaps when frontend filters by status='Active'
--          Previously, ranks were computed for ALL teams, causing gaps when inactive teams were filtered out.
--          Now ranks are computed only for Active teams, so rank numbers are contiguous.

-- =====================================================
-- Step 1: Drop existing views
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view (unchanged from previous)
-- =====================================================

CREATE VIEW rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields
    t.team_id_master,
    t.team_name,
    t.club_name,
    t.state_code AS state,
    CASE
      -- If it's already a number (e.g., "12"), cast directly
      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
      -- If it starts with 'u' or 'U' followed by digits (e.g., "u12", "U12"), extract the number
      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
      -- Try to extract any number from the string as fallback
      WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
      ELSE NULL
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

    -- Record stats (from rankings_full with fallback - these are CAPPED AT 30 GAMES for rankings algorithm)
    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,

    -- Total games count (ALL games, not capped) for display
    (SELECT COUNT(*)
     FROM games g
     WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_games_played,

    -- Total wins/losses/draws from ALL games (for accurate win% calculation)
    (SELECT COUNT(*)
     FROM games g
     WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score > g.away_score)
            OR (g.away_team_master_id = t.team_id_master AND g.away_score > g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_wins,

    (SELECT COUNT(*)
     FROM games g
     WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score < g.away_score)
            OR (g.away_team_master_id = t.team_id_master AND g.away_score < g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_losses,

    (SELECT COUNT(*)
     FROM games g
     WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
       AND g.home_score = g.away_score
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_draws,

    -- Recalculated win_percentage based on TOTAL games (not capped)
    CASE
      WHEN (SELECT COUNT(*)
            FROM games g
            WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
              AND g.home_score IS NOT NULL
              AND g.away_score IS NOT NULL) > 0
      THEN (
        (
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE ((g.home_team_master_id = t.team_id_master AND g.home_score > g.away_score)
                  OR (g.away_team_master_id = t.team_id_master AND g.away_score > g.home_score))
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL)
          +
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
             AND g.home_score = g.away_score
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL) * 0.5
        ) /
        (SELECT COUNT(*)::NUMERIC
         FROM games g
         WHERE (g.home_team_master_id = t.team_id_master OR g.away_team_master_id = t.team_id_master)
           AND g.home_score IS NOT NULL
           AND g.away_score IS NOT NULL)
      ) * 100
      ELSE NULL
    END AS win_percentage,

    -- Metrics (ONLY from rankings_full, NO fallback)
    rf.power_score_final,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Rank (use precomputed ML ranking from rankings_full, do NOT recompute)
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,

    -- SOS Ranks (pre-calculated in rankings engine)
    rf.sos_rank_national,  -- SOS rank within (age, gender) cohort nationally
    rf.sos_rank_state,     -- SOS rank within (age, gender, state)

    -- Rank change tracking (historical data from rankings_full)
    rf.rank_change_7d,
    rf.rank_change_30d,

    -- Activity status fields for filtering inactive teams
    rf.status,                -- 'Active', 'Inactive', or 'Not Enough Ranked Games'
    rf.last_game,             -- Timestamp of last game played

    -- Metadata
    rf.last_calculated

FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
LEFT JOIN current_rankings cr ON cr.team_id = t.team_id_master
WHERE rf.power_score_final IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view using rankings_full as primary source. Includes sos_rank_national and sos_rank_state for pre-calculated SOS rankings, rank change tracking (7-day and 30-day), total_games_played, recalculated win_percentage, and activity status fields.';

-- =====================================================
-- Step 3: Recreate state_rankings_view with ACTIVE-ONLY ranking
-- =====================================================
-- FIX: Compute rank_in_state_final only for Active teams
-- This prevents rank gaps when frontend filters by status='Active'

CREATE VIEW state_rankings_view
WITH (security_invoker = true)
AS
SELECT
    -- Team identity fields
    rv.team_id_master,
    rv.team_name,
    rv.club_name,
    rv.state AS state,
    rv.age AS age,
    rv.gender,

    -- Record stats (capped at 30 for rankings algorithm)
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,

    -- Total games and record (all games, not capped)
    rv.total_games_played,
    rv.total_wins,
    rv.total_losses,
    rv.total_draws,
    rv.win_percentage, -- Already recalculated from total games in base view

    -- Metrics
    rv.power_score_final,
    rv.sos_norm,
    rv.offense_norm,
    rv.defense_norm,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank - FIX: Only rank Active teams to avoid gaps
    -- Teams with status != 'Active' get NULL rank_in_state_final
    CASE
        WHEN rv.status = 'Active' THEN
            ROW_NUMBER() OVER (
                PARTITION BY rv.state, rv.age, rv.gender
                ORDER BY
                    CASE WHEN rv.status = 'Active' THEN 0 ELSE 1 END,
                    rv.power_score_final DESC
            )
        ELSE NULL
    END AS rank_in_state_final,

    -- SOS Ranks (passed through from base view)
    rv.sos_rank_national,  -- National SOS rank (same as in rankings_view)
    rv.sos_rank_state,     -- State SOS rank (pre-calculated in rankings engine)

    -- Rank change tracking (passed through from base view)
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- Activity status fields (passed through from base view)
    rv.status,
    rv.last_game,

    -- Metadata
    rv.last_calculated

FROM rankings_view rv
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view with rank_in_state_final computed ONLY for Active teams (non-Active teams get NULL rank). This ensures contiguous rank numbers when filtering by status=Active. Includes pre-calculated SOS ranks, rank change tracking, total_games_played, win_percentage, and activity status fields.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Notes
-- =====================================================
-- This migration fixes the state ranking calculation to prevent rank gaps.
--
-- PROBLEM: Previously, rank_in_state_final was computed using ROW_NUMBER()
-- over ALL teams in a state/age/gender partition, regardless of status.
-- When the frontend filtered by status='Active', ranks had gaps (1, 2, 4, 7...)
-- because inactive teams were removed but their ranks remained in sequence.
--
-- SOLUTION: Now rank_in_state_final is computed only for Active teams.
-- Non-Active teams get NULL for rank_in_state_final.
-- This ensures that when filtering by status='Active', ranks are contiguous (1, 2, 3, 4...).
--
-- The CASE statement ensures:
-- - Active teams get ranked 1, 2, 3... based on power_score_final
-- - Non-Active teams (status = 'Not Enough Ranked Games' or NULL) get NULL rank
