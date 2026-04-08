-- Add ranking-evidence features that help prediction reliability.
-- These fields already exist in calculator outputs; this migration persists them
-- to both rankings_full and point-in-time prediction snapshots.

ALTER TABLE rankings_full
    ADD COLUMN IF NOT EXISTS same_age_games INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_game_share FLOAT,
    ADD COLUMN IF NOT EXISTS same_age_unique_opponents INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_top100_opp_count INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_top500_opp_count INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_avg_opp_power_adj FLOAT,
    ADD COLUMN IF NOT EXISTS repeat_opponent_share FLOAT,
    ADD COLUMN IF NOT EXISTS positive_ml_evidence_scale FLOAT,
    ADD COLUMN IF NOT EXISTS publication_cap_rank INTEGER,
    ADD COLUMN IF NOT EXISTS publication_cap_score FLOAT;

ALTER TABLE prediction_feature_history
    ADD COLUMN IF NOT EXISTS same_age_games INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_game_share FLOAT,
    ADD COLUMN IF NOT EXISTS same_age_unique_opponents INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_top100_opp_count INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_top500_opp_count INTEGER,
    ADD COLUMN IF NOT EXISTS same_age_avg_opp_power_adj FLOAT,
    ADD COLUMN IF NOT EXISTS repeat_opponent_share FLOAT,
    ADD COLUMN IF NOT EXISTS positive_ml_evidence_scale FLOAT,
    ADD COLUMN IF NOT EXISTS publication_cap_rank INTEGER,
    ADD COLUMN IF NOT EXISTS publication_cap_score FLOAT;

COMMENT ON COLUMN rankings_full.same_age_games IS
'Count of same-age same-gender games used by the ranking engine for this team.';

COMMENT ON COLUMN rankings_full.same_age_game_share IS
'Share of selected games that were same-age same-gender matchups.';

COMMENT ON COLUMN rankings_full.repeat_opponent_share IS
'Share of selected games played against repeat opponents.';

COMMENT ON COLUMN rankings_full.positive_ml_evidence_scale IS
'Scale applied to positive ML lift based on same-age evidence quality.';

COMMENT ON COLUMN rankings_full.publication_cap_rank IS
'Publication cap tier derived from same-age evidence policy.';

COMMENT ON COLUMN rankings_full.publication_cap_score IS
'Maximum publishable score for evidence-constrained teams.';

COMMENT ON COLUMN prediction_feature_history.same_age_games IS
'Same-age same-gender game count captured at snapshot time.';

COMMENT ON COLUMN prediction_feature_history.repeat_opponent_share IS
'Repeat-opponent share captured at snapshot time.';

COMMENT ON COLUMN prediction_feature_history.positive_ml_evidence_scale IS
'Positive ML evidence scale captured at snapshot time.';

COMMENT ON COLUMN prediction_feature_history.publication_cap_score IS
'Evidence-based cap score captured at snapshot time.';
