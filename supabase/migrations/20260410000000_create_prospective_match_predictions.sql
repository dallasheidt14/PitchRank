CREATE TABLE IF NOT EXISTS prospective_match_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    fixture_key TEXT NOT NULL UNIQUE,
    provider_code TEXT NOT NULL DEFAULT 'gotsport',
    source_system TEXT NOT NULL DEFAULT 'gotsport_event_schedule',
    source_artifact_path TEXT NULL,
    source_event_id TEXT NULL,
    source_match_key TEXT NULL,

    game_date DATE NOT NULL,
    competition TEXT NULL,
    division_name TEXT NULL,
    venue TEXT NULL,

    home_provider_team_id TEXT NOT NULL,
    away_provider_team_id TEXT NOT NULL,
    home_team_name TEXT NOT NULL,
    away_team_name TEXT NOT NULL,
    home_team_master_id UUID NULL REFERENCES teams(team_id_master) ON DELETE SET NULL,
    away_team_master_id UUID NULL REFERENCES teams(team_id_master) ON DELETE SET NULL,
    home_resolution_method TEXT NULL,
    away_resolution_method TEXT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'pending',

    fixture_payload JSONB NOT NULL DEFAULT '{}'::jsonb,

    heuristic_prediction_status TEXT NOT NULL DEFAULT 'pending',
    heuristic_model_version TEXT NULL,
    heuristic_prediction JSONB NULL,
    heuristic_predicted_at TIMESTAMPTZ NULL,

    offline_prediction_status TEXT NOT NULL DEFAULT 'pending',
    offline_model_version TEXT NULL,
    offline_prediction JSONB NULL,
    offline_predicted_at TIMESTAMPTZ NULL,

    actual_game_id UUID NULL REFERENCES games(id) ON DELETE SET NULL,
    actual_home_score INTEGER NULL,
    actual_away_score INTEGER NULL,
    actual_outcome TEXT NULL,
    actual_recorded_at TIMESTAMPTZ NULL,
    evaluation_status TEXT NOT NULL DEFAULT 'pending_result',
    evaluation_notes JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_prospective_match_predictions_game_date
    ON prospective_match_predictions (game_date ASC);

CREATE INDEX IF NOT EXISTS idx_prospective_match_predictions_resolution_status
    ON prospective_match_predictions (resolution_status, game_date ASC);

CREATE INDEX IF NOT EXISTS idx_prospective_match_predictions_heuristic_status
    ON prospective_match_predictions (heuristic_prediction_status, game_date ASC);

CREATE INDEX IF NOT EXISTS idx_prospective_match_predictions_offline_status
    ON prospective_match_predictions (offline_prediction_status, game_date ASC);

CREATE INDEX IF NOT EXISTS idx_prospective_match_predictions_actual_status
    ON prospective_match_predictions (evaluation_status, game_date ASC);

CREATE INDEX IF NOT EXISTS idx_prospective_match_predictions_provider_pair
    ON prospective_match_predictions (provider_code, home_provider_team_id, away_provider_team_id, game_date ASC);

CREATE OR REPLACE FUNCTION update_prospective_match_predictions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_prospective_match_predictions_updated_at
    ON prospective_match_predictions;

CREATE TRIGGER update_prospective_match_predictions_updated_at
    BEFORE UPDATE ON prospective_match_predictions
    FOR EACH ROW EXECUTE FUNCTION update_prospective_match_predictions_updated_at();

ALTER TABLE prospective_match_predictions ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE prospective_match_predictions IS
    'Prospective evaluation fixtures with frozen heuristic/offline predictions and eventual actual results.';
