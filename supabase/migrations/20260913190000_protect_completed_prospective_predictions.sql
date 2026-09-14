-- Prospective prediction payloads are immutable once completed. Preparation,
-- heuristic processing, and refresh jobs can overlap, so this guard must live
-- at the database write boundary rather than in a prior application read.
CREATE OR REPLACE FUNCTION protect_completed_prospective_predictions()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.heuristic_prediction_status = 'completed' THEN
        NEW.heuristic_prediction_status := OLD.heuristic_prediction_status;
        NEW.heuristic_model_version := OLD.heuristic_model_version;
        NEW.heuristic_prediction := OLD.heuristic_prediction;
        NEW.heuristic_predicted_at := OLD.heuristic_predicted_at;
    END IF;

    IF OLD.offline_prediction_status = 'completed' THEN
        NEW.offline_prediction_status := OLD.offline_prediction_status;
        NEW.offline_model_version := OLD.offline_model_version;
        NEW.offline_prediction := OLD.offline_prediction;
        NEW.offline_predicted_at := OLD.offline_predicted_at;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS protect_completed_prospective_predictions
    ON prospective_match_predictions;

CREATE TRIGGER protect_completed_prospective_predictions
    BEFORE UPDATE ON prospective_match_predictions
    FOR EACH ROW EXECUTE FUNCTION protect_completed_prospective_predictions();

COMMENT ON FUNCTION protect_completed_prospective_predictions() IS
    'Prevents concurrent fixture refreshes from replacing completed prospective prediction evidence.';
