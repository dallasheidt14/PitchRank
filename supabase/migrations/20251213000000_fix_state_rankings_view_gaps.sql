-- Migration: Fix gaps in state rankings display
-- Purpose: Calculate rank_in_state_final ONLY for teams that will be displayed
--          (status = 'Active' or 'Not Enough Ranked Games')
--          to avoid gaps when Inactive teams are filtered out
--
-- Problem: The previous view calculated ROW_NUMBER() for ALL teams, but the
--          frontend filters to exclude Inactive teams. This caused gaps like
--          showing #2, #5, #6, #7 when teams #1, #3, #4 were Inactive.
--
-- Solution: Apply status filter BEFORE calculating ROW_NUMBER() so ranks
--           are sequential for the displayed teams.

-- =====================================================
-- Step 1: Drop existing views (CASCADE handles dependencies)
-- =====================================================

DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

-- =====================================================
-- Step 2: Recreate rankings_view WITH status filter
-- =====================================================
-- Filter to only include displayable teams (Active or Not Enough Ranked Games)
-- Inactive teams (0 games in 180 days) are excluded

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

    -- Record stats (from rankings_full - used for rankings algorithm)
    rf.games_played,
    rf.wins,
    rf.losses,
    rf.draws,

    -- Total games - same as games_played from rankings_full
    -- (rankings_full already has the authoritative game counts)
    rf.games_played AS total_games_played,
    rf.wins AS total_wins,
    rf.losses AS total_losses,
    rf.draws AS total_draws,

    -- Win percentage from rankings_full (already calculated by rankings engine)
    rf.win_percentage,

    -- Metrics (ONLY from rankings_full)
    rf.power_score_final,
    rf.sos_norm,
    rf.sos_norm_state,  -- State normalization (for state rankings display)
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Rank: Recalculate within displayable teams only
    -- This ensures no gaps when viewing rankings
    ROW_NUMBER() OVER (
        PARTITION BY
            CASE
              WHEN rf.age_group ~ '^[0-9]+$' THEN rf.age_group::INTEGER
              WHEN rf.age_group ~ '^[uU][0-9]+$' THEN (regexp_replace(rf.age_group, '^[uU]', ''))::INTEGER
              WHEN rf.age_group ~ '[0-9]+' THEN (regexp_replace(rf.age_group, '[^0-9]', '', 'g'))::INTEGER
              ELSE NULL
            END,
            CASE
              WHEN rf.gender = 'Male' THEN 'M'
              WHEN rf.gender = 'Female' THEN 'F'
              WHEN rf.gender = 'Boys' THEN 'M'
              WHEN rf.gender = 'Girls' THEN 'F'
              WHEN rf.gender = 'M' THEN 'M'
              WHEN rf.gender = 'F' THEN 'F'
              ELSE rf.gender
            END
        ORDER BY rf.power_score_final DESC, rf.sos_norm DESC NULLS LAST
    ) AS rank_in_cohort_final,

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
WHERE rf.power_score_final IS NOT NULL
  AND t.is_deprecated = FALSE
  -- CRITICAL FIX: Only include teams that will be displayed
  -- This prevents gaps in rank numbers when Inactive teams exist
  AND rf.status IN ('Active', 'Not Enough Ranked Games');

COMMENT ON VIEW rankings_view IS 'National rankings view. Only includes Active and provisional teams (excludes Inactive). Ranks are sequential with no gaps.';

-- =====================================================
-- Step 3: Recreate state_rankings_view WITH status filter
-- =====================================================
-- State rankings also need gap-free sequential ranks

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
    rv.sos_norm_state,  -- State normalization (for state rankings display)
    rv.offense_norm,
    rv.defense_norm,

    -- National rank (from base view - already gap-free)
    rv.rank_in_cohort_final,

    -- State rank: Sequential within state, no gaps
    -- (rankings_view already filtered to displayable teams only)
    ROW_NUMBER() OVER (
        PARTITION BY rv.state, rv.age, rv.gender
        ORDER BY rv.power_score_final DESC, rv.sos_norm DESC NULLS LAST
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

COMMENT ON VIEW state_rankings_view IS 'State rankings view. Only includes Active and provisional teams. Ranks are sequential with no gaps.';

-- =====================================================
-- Step 4: Grant SELECT permissions
-- =====================================================

GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

-- =====================================================
-- Step 5: Recreate merged_teams_view (preserved from previous migration)
-- =====================================================

-- Must DROP first because CREATE OR REPLACE cannot change column order
DROP VIEW IF EXISTS merged_teams_view CASCADE;

CREATE VIEW merged_teams_view AS
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

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_name = 'merged_teams_view'
    ) THEN
        RAISE EXCEPTION 'Migration failed: merged_teams_view not created';
    END IF;

    RAISE NOTICE 'Migration successful: Fixed rankings views to exclude Inactive teams BEFORE calculating ranks (prevents gaps)';
END $$;
