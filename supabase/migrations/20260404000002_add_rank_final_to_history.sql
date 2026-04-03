-- Add rank_in_cohort_final to ranking_history for published final rank tracking
ALTER TABLE ranking_history ADD COLUMN IF NOT EXISTS rank_in_cohort_final INTEGER;
COMMENT ON COLUMN ranking_history.rank_in_cohort_final IS 'Published final rank from power_score_final ordering. Replaces COALESCE(rank_in_cohort_ml, rank_in_cohort) as the canonical historical rank.';
