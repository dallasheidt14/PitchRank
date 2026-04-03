-- Add rank_in_cohort_final: the published rank computed from power_score_final ordering
-- Computed in calculator.py after power_score_true is set, using canonical order:
-- power_score_true DESC, team_id ASC. Active teams only; NULL for non-Active.
ALTER TABLE rankings_full ADD COLUMN IF NOT EXISTS rank_in_cohort_final INTEGER;
COMMENT ON COLUMN rankings_full.rank_in_cohort_final IS 'Published cohort rank from power_score_true DESC, team_id ASC. Active teams only; NULL for non-Active.';
