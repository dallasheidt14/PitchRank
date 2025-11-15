-- Fix age conversion in rankings_view
-- Convert TEXT age_group (e.g., "u12") to INTEGER age (e.g., 12)
-- This allows frontend queries to filter by integer age values

-- Drop and recreate rankings_view with proper age conversion
DROP VIEW IF EXISTS state_rankings_view CASCADE;
DROP VIEW IF EXISTS rankings_view CASCADE;

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

    -- Record stats (with fallback to current_rankings)
    COALESCE(rf.games_played, cr.games_played) AS games_played,
    COALESCE(rf.wins, cr.wins) AS wins,
    COALESCE(rf.losses, cr.losses) AS losses,
    COALESCE(rf.draws, cr.draws) AS draws,
    COALESCE(rf.win_percentage, cr.win_percentage) AS win_percentage,

    -- Metrics (ONLY from rankings_full, NO fallback)
    rf.power_score_final,
    rf.sos_norm,
    rf.off_norm AS offense_norm,
    rf.def_norm AS defense_norm,

    -- Rank (use precomputed ML ranking from rankings_full, do NOT recompute)
    COALESCE(rf.rank_in_cohort_ml, rf.rank_in_cohort) AS rank_in_cohort_final

FROM rankings_full rf
JOIN teams t ON rf.team_id = t.team_id_master
LEFT JOIN current_rankings cr ON cr.team_id = t.team_id_master
WHERE rf.power_score_final IS NOT NULL;

COMMENT ON VIEW rankings_view IS 'National rankings view using rankings_full as primary source. Converts TEXT age_group to INTEGER age for frontend filtering. Exposes only canonical fields.';

-- Recreate state_rankings_view (it uses age from rankings_view, so it will automatically get INTEGER)
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

    -- Record stats
    rv.games_played,
    rv.wins,
    rv.losses,
    rv.draws,
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
    ) AS rank_in_state_final

FROM rankings_view rv
WHERE rv.state IS NOT NULL;

COMMENT ON VIEW state_rankings_view IS 'State rankings view: National rankings filtered by state, with dynamically calculated rank_in_state_final. Uses INTEGER age from base view.';

-- Grant permissions
GRANT SELECT ON rankings_view TO authenticated;
GRANT SELECT ON rankings_view TO anon;
GRANT SELECT ON state_rankings_view TO authenticated;
GRANT SELECT ON state_rankings_view TO anon;

