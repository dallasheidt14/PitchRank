CREATE TABLE IF NOT EXISTS match_prediction_shadow_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    request_ip TEXT NULL,
    team_a_id UUID NOT NULL,
    team_b_id UUID NOT NULL,
    predictor_version TEXT NOT NULL,
    shadow_model_version TEXT NULL,
    shadow_status TEXT NOT NULL DEFAULT 'pending',
    live_response JSONB NOT NULL,
    team_a_input JSONB NOT NULL,
    team_b_input JSONB NOT NULL,
    request_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    shadow_prediction JSONB NULL
);

CREATE INDEX IF NOT EXISTS idx_match_prediction_shadow_log_created_at
    ON match_prediction_shadow_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_match_prediction_shadow_log_shadow_status
    ON match_prediction_shadow_log (shadow_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_match_prediction_shadow_log_teams
    ON match_prediction_shadow_log (team_a_id, team_b_id, created_at DESC);

ALTER TABLE match_prediction_shadow_log ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE match_prediction_shadow_log IS
    'Fail-open shadow logging for /compare match predictions. Stores live request inputs and prediction payloads so candidate models can be evaluated side-by-side before rollout.';
