-- Fix rankings_view performance by using pre-computed rank_in_cohort
-- Instead of computing rank_in_cohort_final dynamically with ROW_NUMBER()
-- which causes statement timeouts on large datasets
-- Date: 2025-01-25

-- =====================================================
-- Step 1: Drop existing views
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view using pre-computed rank_in_cohort
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
    rf.sos_norm,  -- National normalization (for national rankings)
    rf.sos_norm_state,  -- State normalization (for state rankings)
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- National rank (use pre-computed rank_in_cohort from rankings_full instead of computing dynamically)
    -- This is MUCH faster than ROW_NUMBER() window function on 66k+ rows
    -- SAFETY: Anchor scaling (power_score_final = powerscore_ml * anchor_val) is monotonic, so order is preserved
    -- Therefore, rank_in_cohort_ml (based on powerscore_ml) matches rank by power_score_final
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,

    -- SOS Ranks (pre-calculated in rankings engine)
    rf.sos_rank_national,  -- National SOS rank
    rf.sos_rank_state,     -- State SOS rank

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
WHERE rf.power_score_final IS NOT NULL OR cr.national_power_score IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view using rankings_full as primary source. Uses pre-computed rank_in_cohort instead of computing dynamically for performance. Exposes sos_norm (national) and sos_norm_state (state-normalized) for proper display in state vs national views. Respects RLS policies.';

-- =====================================================
-- Step 3: Recreate state_rankings_view with optimized rank_in_state_final
-- =====================================================

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
    rv.sos_norm,  -- National normalization (kept for backward compatibility)
    rv.sos_norm_state,  -- State normalization (use this for state rankings display)
    rv.offense_norm,
    rv.defense_norm,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank (computed live in view - only for teams in same state/age/gender)
    -- This is much smaller than computing national rank, so it should be fast
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final,

    -- SOS Ranks (passed through from base view)
    rv.sos_rank_national,  -- National SOS rank
    rv.sos_rank_state,     -- State SOS rank (pre-calculated in rankings engine)

    -- Rank change tracking (passed through from base view)
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- Activity status fields (passed through from base view)
    rv.status,
    rv.last_game,
    rv.last_calculated

FROM rankings_view rv
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state_code, with dynamically calculated state_rank. Uses pre-computed rank_in_cohort_final from base view for performance. Exposes sos_norm (national) and sos_norm_state (state-normalized). Frontend should use sos_norm_state for state rankings display. Respects RLS policies.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

