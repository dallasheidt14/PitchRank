CREATE TABLE public.compare_calibration_experiments (
    model_signature TEXT PRIMARY KEY,
    model_version TEXT NOT NULL,
    first_code_revision TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    development_start DATE NOT NULL,
    train_end DATE NOT NULL,
    test_start DATE NOT NULL,
    test_end DATE NOT NULL,
    policy JSONB NOT NULL
);
ALTER TABLE public.compare_calibration_experiments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.compare_calibration_experiments FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.compare_calibration_experiments TO service_role;

CREATE FUNCTION public.keep_compare_experiment_immutable()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'Compare experiment manifests are immutable';
END;
$$;
CREATE TRIGGER keep_compare_experiment_immutable
BEFORE UPDATE OR DELETE ON public.compare_calibration_experiments
FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();

CREATE FUNCTION public.register_compare_experiment()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    first_week DATE;
    known_version TEXT;
    registered_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF NEW.heuristic_prediction_status <> 'completed' THEN RETURN NEW; END IF;
    IF TG_OP = 'UPDATE' AND OLD.heuristic_prediction_status = 'completed' THEN RETURN NEW; END IF;
    IF NULLIF(NEW.heuristic_prediction->>'codeRevision', '') IS NULL THEN
        RAISE EXCEPTION 'A frozen Compare experiment requires a code revision';
    END IF;
    -- The first complete UTC week starts on the Monday after registration.
    first_week := (date_trunc('week', registered_at AT TIME ZONE 'UTC') + interval '1 week')::DATE;
    INSERT INTO public.compare_calibration_experiments (
        model_signature, model_version, first_code_revision, created_at, development_start,
        train_end, test_start, test_end, policy
    ) VALUES (
        NEW.heuristic_prediction->>'modelSignature', NEW.heuristic_model_version,
        NEW.heuristic_prediction->>'codeRevision', registered_at, first_week,
        first_week + 27, first_week + 28, first_week + 55,
        '{"candidate_source":"pre_outcome","temperatures":[0.5,0.75,1,1.25,1.5,2],
          "minimum_games":1000,"minimum_events":20,"bootstrap_samples":1000,"seed":20260920,
          "scoring":"log_loss_and_multiclass_brier","outcome_policy":"unchanged"}'::JSONB
    ) ON CONFLICT (model_signature) DO NOTHING;
    SELECT model_version INTO known_version FROM public.compare_calibration_experiments
    WHERE model_signature = NEW.heuristic_prediction->>'modelSignature';
    IF known_version IS DISTINCT FROM NEW.heuristic_model_version THEN
        RAISE EXCEPTION 'Model signature already belongs to a different predictor version';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER register_compare_experiment
AFTER INSERT OR UPDATE ON public.prospective_match_predictions
FOR EACH ROW EXECUTE FUNCTION public.register_compare_experiment();
REVOKE ALL ON FUNCTION public.register_compare_experiment() FROM PUBLIC, anon, authenticated;
