CREATE TABLE IF NOT EXISTS model_training_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    workflow_run_id BIGINT NOT NULL UNIQUE,
    workflow_run_attempt INTEGER NOT NULL DEFAULT 1,
    git_sha TEXT NULL,

    model_dir TEXT NOT NULL,
    model_version TEXT NOT NULL,

    lookback_days INTEGER NULL,
    limit_value INTEGER NULL,
    test_ratio DOUBLE PRECISION NULL,
    min_examples INTEGER NULL,
    requested_probability_strategy TEXT NULL,
    selected_probability_strategy TEXT NULL,

    calibration_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    calibration_method TEXT NULL,
    draw_calibration_method TEXT NULL,

    dataset_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    training_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    calibration_summary JSONB NULL,

    games_seen INTEGER NULL,
    games_used INTEGER NULL,
    examples_built INTEGER NULL,
    unique_snapshot_dates_used INTEGER NULL,

    winner_accuracy DOUBLE PRECISION NULL,
    draw_recall DOUBLE PRECISION NULL,
    predicted_draw_rate DOUBLE PRECISION NULL,
    log_loss DOUBLE PRECISION NULL,
    margin_mae DOUBLE PRECISION NULL,
    exact_score_accuracy DOUBLE PRECISION NULL,

    calibrated_log_loss DOUBLE PRECISION NULL,
    calibrated_draw_recall DOUBLE PRECISION NULL,
    calibrated_brier_score DOUBLE PRECISION NULL
);

CREATE INDEX IF NOT EXISTS idx_model_training_runs_created_at
    ON model_training_runs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_training_runs_model_version
    ON model_training_runs (model_version);

CREATE OR REPLACE FUNCTION update_model_training_runs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_model_training_runs_updated_at
    ON model_training_runs;

CREATE TRIGGER update_model_training_runs_updated_at
    BEFORE UPDATE ON model_training_runs
    FOR EACH ROW EXECUTE FUNCTION update_model_training_runs_updated_at();

ALTER TABLE model_training_runs ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE model_training_runs IS
    'Recorded summaries from Train Point-In-Time Match Model workflow runs for Mission Control.';
