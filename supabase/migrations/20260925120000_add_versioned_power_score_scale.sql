-- Separate the published age/gender PowerScore scale from the stable numeric
-- input used by existing prediction consumers. Historical rows remain intact;
-- new ranking runs populate the version/provenance columns together.

ALTER TABLE public.rankings_full
    ADD COLUMN IF NOT EXISTS prediction_power_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS power_score_scale_version TEXT;

ALTER TABLE public.ranking_history
    ADD COLUMN IF NOT EXISTS power_score_true DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS prediction_power_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS power_score_scale_version TEXT;

ALTER TABLE public.prediction_feature_history
    ADD COLUMN IF NOT EXISTS prediction_power_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS power_score_scale_version TEXT;

ALTER TABLE public.rankings_full
    ADD CONSTRAINT rankings_full_prediction_power_score_bounds
        CHECK (prediction_power_score IS NULL OR prediction_power_score BETWEEN 0.0 AND 1.0) NOT VALID,
    ADD CONSTRAINT rankings_full_scale_version_requires_prediction_score
        CHECK (power_score_scale_version IS NULL OR prediction_power_score IS NOT NULL) NOT VALID;

ALTER TABLE public.ranking_history
    ADD CONSTRAINT ranking_history_power_score_true_bounds
        CHECK (power_score_true IS NULL OR power_score_true BETWEEN 0.0 AND 1.0) NOT VALID,
    ADD CONSTRAINT ranking_history_prediction_power_score_bounds
        CHECK (prediction_power_score IS NULL OR prediction_power_score BETWEEN 0.0 AND 1.0) NOT VALID,
    ADD CONSTRAINT ranking_history_scale_version_requires_prediction_score
        CHECK (power_score_scale_version IS NULL OR prediction_power_score IS NOT NULL) NOT VALID;

ALTER TABLE public.prediction_feature_history
    ADD CONSTRAINT prediction_feature_history_prediction_power_score_bounds
        CHECK (prediction_power_score IS NULL OR prediction_power_score BETWEEN 0.0 AND 1.0) NOT VALID,
    ADD CONSTRAINT prediction_feature_history_scale_version_requires_prediction_score
        CHECK (power_score_scale_version IS NULL OR prediction_power_score IS NOT NULL) NOT VALID;

COMMENT ON COLUMN public.rankings_full.prediction_power_score IS
'Legacy anchor-scaled PowerScore retained as the stable numeric input for prediction consumers after the published age/gender scale changed.';

COMMENT ON COLUMN public.rankings_full.power_score_scale_version IS
'Version of the age/gender publication mapping used to produce power_score_final.';

COMMENT ON COLUMN public.ranking_history.power_score_true IS
'Unscaled post-gate competitive score saved so a published scale change is distinguishable from team performance movement.';

COMMENT ON COLUMN public.ranking_history.prediction_power_score IS
'Prediction-compatible score captured at the ranking snapshot.';

COMMENT ON COLUMN public.ranking_history.power_score_scale_version IS
'Published PowerScore scale version for this history row; NULL means legacy or unknown provenance.';

COMMENT ON COLUMN public.prediction_feature_history.prediction_power_score IS
'Stable prediction feature score; use this instead of the published display scale when populated.';

COMMENT ON COLUMN public.prediction_feature_history.power_score_scale_version IS
'Published display-scale version active when the prediction feature row was captured.';
