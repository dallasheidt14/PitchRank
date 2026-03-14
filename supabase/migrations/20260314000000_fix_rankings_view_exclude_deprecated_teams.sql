-- Fix: Restore is_deprecated filter to rankings_view
-- Date: 2026-03-14
-- Problem: Migration 20260210000000 rewrote rankings_view but dropped the
--          `AND t.is_deprecated = FALSE` filter that was in 20251208000005.
--          Subsequent migrations (20260211, 20260220) also omitted it.
--          This caused merged/deprecated teams to still appear in rankings.
--
-- Fix: Add `AND t.is_deprecated IS NOT TRUE` to the WHERE clause.
--      Uses IS NOT TRUE instead of = FALSE to safely handle NULLs.

-- =====================================================
-- Step 1: Drop existing views (state depends on rankings)
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view with is_deprecated filter restored
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
    CASE
      WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
      WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
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

    -- Activity status fields
    rf.status,
    rf.last_game,
    rf.last_calculated

FROM teams t
LEFT JOIN rankings_full rf ON t.team_id_master = rf.team_id
LEFT JOIN current_rankings cr ON t.team_id_master = cr.team_id
WHERE (rf.power_score_final IS NOT NULL OR cr.national_power_score IS NOT NULL)
  AND t.is_deprecated IS NOT TRUE;  -- Exclude deprecated/merged teams from rankings

COMMENT ON VIEW rankings_view IS 'National rankings view. Excludes deprecated/merged teams (is_deprecated filter). Filters is_excluded games from total counts. Uses pre-computed rank_in_cohort_ml. Respects RLS policies.';

-- =====================================================
-- Step 3: Recreate state_rankings_view with status filter
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
  AND rv.status IN ('Active', 'Not Enough Ranked Games');  -- Only rank active teams

COMMENT ON VIEW state_rankings_view IS 'State rankings view with rank_in_state_final computed among Active/Not Enough Ranked Games teams only. Inherits deprecated team exclusion from rankings_view.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Verification
-- =====================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: rankings_view not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'state_rankings_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: state_rankings_view not created';
    END IF;

    RAISE NOTICE 'Migration successful: Restored is_deprecated filter to rankings_view';
END $$;
