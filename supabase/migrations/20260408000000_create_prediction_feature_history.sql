-- Point-in-time predictor feature snapshots for offline backtests and model training.
-- This stores the subset of team-level features consumed by match prediction as they
-- existed at ranking snapshot time, so evaluation can avoid current-snapshot leakage.

CREATE TABLE IF NOT EXISTS prediction_feature_history (
    snapshot_date DATE NOT NULL,
    team_id UUID NOT NULL REFERENCES teams(team_id_master) ON DELETE CASCADE,
    age_group TEXT,
    gender TEXT,
    state_code TEXT,
    status TEXT,
    rank_in_cohort_final INTEGER,
    power_score_final FLOAT,
    sos_norm FLOAT,
    offense_norm FLOAT,
    defense_norm FLOAT,
    glicko_rating FLOAT,
    glicko_rd FLOAT,
    glicko_volatility FLOAT,
    wins INTEGER,
    losses INTEGER,
    draws INTEGER,
    games_played INTEGER,
    win_percentage FLOAT,
    exp_margin FLOAT,
    exp_win_rate FLOAT,
    exp_goals_for FLOAT,
    exp_goals_against FLOAT,
    last_calculated TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_prediction_feature_history_snapshot
ON prediction_feature_history(snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_prediction_feature_history_team_date
ON prediction_feature_history(team_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_prediction_feature_history_cohort
ON prediction_feature_history(age_group, gender, snapshot_date DESC);

ALTER TABLE prediction_feature_history ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE prediction_feature_history IS
'Point-in-time predictor feature snapshots captured during ranking runs. Used for leakage-safe backtests and future model training.';

COMMENT ON COLUMN prediction_feature_history.snapshot_date IS
'UTC date for the ranking snapshot that produced this predictor feature row.';

COMMENT ON COLUMN prediction_feature_history.rank_in_cohort_final IS
'Published final rank at the time of the snapshot. Useful for stratified evaluation.';

COMMENT ON COLUMN prediction_feature_history.win_percentage IS
'Draw-aware win percentage used by compare feature assembly: (wins + 0.5 * draws) / games_played * 100.';

COMMENT ON COLUMN prediction_feature_history.exp_margin IS
'Optional predictive expected margin. Populated when the ranking pipeline emits it.';

COMMENT ON COLUMN prediction_feature_history.exp_win_rate IS
'Optional predictive expected win probability. Populated when the ranking pipeline emits it.';

GRANT SELECT, INSERT, UPDATE, DELETE ON prediction_feature_history TO service_role;
