-- Migration: Add merge resolution to ranking views
-- Purpose: Make views automatically resolve deprecated teams to canonical teams
-- This is Phase 1.4 of the team merge implementation
--
-- Key changes:
-- 1. Filter out deprecated teams from results
-- 2. Game counts resolve merged teams via resolve_team_id() function
-- 3. Rankings continue to work seamlessly after merges

-- =====================================================
-- Step 1: Drop existing views (CASCADE handles dependencies)
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view with merge resolution
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

    -- Record stats (from rankings_full - CAPPED AT 30 GAMES for rankings algorithm)
    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,

    -- Total games count (ALL games, not capped) for display
    -- Uses resolve_team_id() to include games from merged teams
    (SELECT COUNT(*)
     FROM games g
     WHERE (resolve_team_id(g.home_team_master_id) = t.team_id_master
            OR resolve_team_id(g.away_team_master_id) = t.team_id_master)
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_games_played,

    -- Total wins from ALL games (including merged team games)
    (SELECT COUNT(*)
     FROM games g
     WHERE ((resolve_team_id(g.home_team_master_id) = t.team_id_master AND g.home_score > g.away_score)
            OR (resolve_team_id(g.away_team_master_id) = t.team_id_master AND g.away_score > g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_wins,

    -- Total losses from ALL games (including merged team games)
    (SELECT COUNT(*)
     FROM games g
     WHERE ((resolve_team_id(g.home_team_master_id) = t.team_id_master AND g.home_score < g.away_score)
            OR (resolve_team_id(g.away_team_master_id) = t.team_id_master AND g.away_score < g.home_score))
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_losses,

    -- Total draws from ALL games (including merged team games)
    (SELECT COUNT(*)
     FROM games g
     WHERE (resolve_team_id(g.home_team_master_id) = t.team_id_master
            OR resolve_team_id(g.away_team_master_id) = t.team_id_master)
       AND g.home_score = g.away_score
       AND g.home_score IS NOT NULL
       AND g.away_score IS NOT NULL
    ) AS total_draws,

    -- Recalculated win_percentage based on TOTAL games (including merged)
    CASE
      WHEN (SELECT COUNT(*)
            FROM games g
            WHERE (resolve_team_id(g.home_team_master_id) = t.team_id_master
                   OR resolve_team_id(g.away_team_master_id) = t.team_id_master)
              AND g.home_score IS NOT NULL
              AND g.away_score IS NOT NULL) > 0
      THEN (
        (
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE ((resolve_team_id(g.home_team_master_id) = t.team_id_master AND g.home_score > g.away_score)
                  OR (resolve_team_id(g.away_team_master_id) = t.team_id_master AND g.away_score > g.home_score))
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL)
          +
          (SELECT COUNT(*)::NUMERIC
           FROM games g
           WHERE (resolve_team_id(g.home_team_master_id) = t.team_id_master
                  OR resolve_team_id(g.away_team_master_id) = t.team_id_master)
             AND g.home_score = g.away_score
             AND g.home_score IS NOT NULL
             AND g.away_score IS NOT NULL) * 0.5
        ) /
        (SELECT COUNT(*)::NUMERIC
         FROM games g
         WHERE (resolve_team_id(g.home_team_master_id) = t.team_id_master
                OR resolve_team_id(g.away_team_master_id) = t.team_id_master)
           AND g.home_score IS NOT NULL
           AND g.away_score IS NOT NULL)
      ) * 100
      ELSE NULL
    END AS win_percentage,

    -- Metrics (ONLY from rankings_full)
    rf.power_score_final,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Rank (use precomputed ML ranking from rankings_full)
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final,

    -- SOS Ranks (pre-calculated in rankings engine)
    rf.sos_rank_national,
    rf.sos_rank_state,

    -- Rank change tracking
    rf.rank_change_7d,
    rf.rank_change_30d,

    -- Activity status fields
    rf.status,
    rf.last_game,

    -- Metadata
    rf.last_calculated

FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
LEFT JOIN current_rankings cr ON cr.team_id = t.team_id_master
WHERE rf.power_score_final IS NOT NULL
  AND t.is_deprecated = FALSE;  -- Exclude deprecated teams from results

COMMENT ON VIEW rankings_view IS 'National rankings view with merge resolution. Deprecated teams are excluded. Game counts include games from merged teams via resolve_team_id().';

-- =====================================================
-- Step 3: Recreate state_rankings_view
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
    rv.win_percentage,

    -- Metrics
    rv.power_score_final,
    rv.sos_norm,
    rv.offense_norm,
    rv.defense_norm,

    -- National rank (from base view)
    rv.rank_in_cohort_final,

    -- State rank (computed live in view)
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC
    ) AS rank_in_state_final,

    -- SOS Ranks
    rv.sos_rank_national,
    rv.sos_rank_state,

    -- Rank change tracking
    rv.rank_change_7d,
    rv.rank_change_30d,

    -- Activity status fields
    rv.status,
    rv.last_game,

    -- Metadata
    rv.last_calculated

FROM rankings_view rv
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view with merge resolution inherited from rankings_view. Deprecated teams excluded.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Step 5: Create helper view for merged teams lookup
-- =====================================================

CREATE OR REPLACE VIEW merged_teams_view AS
SELECT
    mm.id as merge_id,
    mm.deprecated_team_id,
    dt.team_name as deprecated_team_name,
    dt.club_name as deprecated_club_name,
    mm.canonical_team_id,
    ct.team_name as canonical_team_name,
    ct.club_name as canonical_club_name,
    mm.merged_at,
    mm.merged_by,
    mm.merge_reason,
    mm.confidence_score,
    (SELECT COUNT(*) FROM games g
     WHERE g.home_team_master_id = mm.deprecated_team_id
        OR g.away_team_master_id = mm.deprecated_team_id) as games_with_deprecated_id
FROM team_merge_map mm
JOIN teams dt ON mm.deprecated_team_id = dt.team_id_master
JOIN teams ct ON mm.canonical_team_id = ct.team_id_master
ORDER BY mm.merged_at DESC;

COMMENT ON VIEW merged_teams_view IS 'View of all team merges with team names and game counts for admin dashboard.';

GRANT SELECT ON merged_teams_view TO authenticated;

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

    RAISE NOTICE 'Migration successful: Ranking views updated with merge resolution';
END $$;
