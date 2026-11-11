-- Forecast identities are historical facts, not live foreign-key relationships.
ALTER TABLE public.prospective_match_predictions
    ADD COLUMN source_game_id UUID,
    ADD COLUMN evaluation_group_kind TEXT,
    ADD COLUMN evaluation_group_key TEXT,
    ALTER COLUMN home_provider_team_id DROP NOT NULL,
    ALTER COLUMN away_provider_team_id DROP NOT NULL,
    DROP CONSTRAINT prospective_match_predictions_home_team_master_id_fkey,
    DROP CONSTRAINT prospective_match_predictions_away_team_master_id_fkey;

CREATE UNIQUE INDEX prospective_source_game_unique
    ON public.prospective_match_predictions(source_game_id) WHERE source_game_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.guard_prospective_forecast()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    source_game public.games%ROWTYPE;
    captured_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.heuristic_prediction_status = 'completed' THEN
            RAISE EXCEPTION 'Completed forecasts cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.heuristic_prediction_status = 'completed' THEN
        IF ROW(NEW.fixture_key, NEW.provider_code, NEW.source_system, NEW.source_artifact_path,
               NEW.source_event_id, NEW.source_match_key, NEW.source_game_id, NEW.game_date,
               NEW.competition, NEW.division_name, NEW.venue, NEW.home_provider_team_id,
               NEW.away_provider_team_id, NEW.home_team_name, NEW.away_team_name,
               NEW.home_team_master_id, NEW.away_team_master_id, NEW.fixture_payload,
               NEW.evaluation_group_kind, NEW.evaluation_group_key, NEW.heuristic_prediction_status,
               NEW.heuristic_model_version, NEW.heuristic_prediction, NEW.heuristic_predicted_at)
           IS DISTINCT FROM
           ROW(OLD.fixture_key, OLD.provider_code, OLD.source_system, OLD.source_artifact_path,
               OLD.source_event_id, OLD.source_match_key, OLD.source_game_id, OLD.game_date,
               OLD.competition, OLD.division_name, OLD.venue, OLD.home_provider_team_id,
               OLD.away_provider_team_id, OLD.home_team_name, OLD.away_team_name,
               OLD.home_team_master_id, OLD.away_team_master_id, OLD.fixture_payload,
               OLD.evaluation_group_kind, OLD.evaluation_group_key, OLD.heuristic_prediction_status,
               OLD.heuristic_model_version, OLD.heuristic_prediction, OLD.heuristic_predicted_at) THEN
            RAISE EXCEPTION 'Completed forecast and fixture identity are immutable';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.heuristic_prediction_status = 'completed' THEN
        IF NEW.game_date <= (captured_at AT TIME ZONE 'UTC')::DATE THEN
            RAISE EXCEPTION 'Forecast must be frozen before match day in UTC';
        END IF;
        IF NEW.resolution_status <> 'resolved'
           OR NEW.home_team_master_id IS NULL OR NEW.away_team_master_id IS NULL
           OR NEW.home_team_master_id = NEW.away_team_master_id
           OR NEW.heuristic_model_version IS NULL
           OR NEW.heuristic_prediction->>'modelVersion' IS DISTINCT FROM NEW.heuristic_model_version
           OR NEW.heuristic_prediction#>>'{shadowContext,predictorVersion}' IS DISTINCT FROM NEW.heuristic_model_version
           OR NEW.heuristic_prediction->>'modelSignature' IS NULL
           OR NEW.heuristic_prediction#>'{shadowContext,frozenEvidence,games}' IS NULL THEN
            RAISE EXCEPTION 'Incomplete or inconsistent forecast snapshot';
        END IF;
        IF NEW.source_game_id IS NOT NULL THEN
            SELECT * INTO source_game FROM public.games WHERE id = NEW.source_game_id FOR SHARE;
            IF NOT FOUND OR source_game.is_excluded IS DISTINCT FROM FALSE
               OR source_game.home_score IS NOT NULL OR source_game.away_score IS NOT NULL
               OR source_game.game_date IS DISTINCT FROM NEW.game_date
               OR source_game.source_url IS DISTINCT FROM NEW.fixture_payload#>>'{source_snapshot,source_url}'
               OR source_game.home_team_master_id::TEXT IS DISTINCT FROM NEW.fixture_payload#>>'{source_snapshot,home_team_master_id}'
               OR source_game.away_team_master_id::TEXT IS DISTINCT FROM NEW.fixture_payload#>>'{source_snapshot,away_team_master_id}'
               OR source_game.provider_id::TEXT IS DISTINCT FROM NEW.fixture_payload#>>'{source_snapshot,provider_id}' THEN
                RAISE EXCEPTION 'Source fixture changed or is no longer eligible';
            END IF;
        END IF;
        -- The server sets the time; callers cannot backdate completion.
        NEW.heuristic_predicted_at := clock_timestamp();
        IF NEW.game_date <= (NEW.heuristic_predicted_at AT TIME ZONE 'UTC')::DATE THEN
            RAISE EXCEPTION 'Match day began during forecast capture';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER guard_prospective_forecast
BEFORE INSERT OR UPDATE OR DELETE ON public.prospective_match_predictions
FOR EACH ROW EXECUTE FUNCTION public.guard_prospective_forecast();

CREATE OR REPLACE FUNCTION public.freeze_prospective_forecast(
    p_fixture_id UUID, p_model_version TEXT, p_prediction JSONB
) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE affected INTEGER;
BEGIN
    UPDATE public.prospective_match_predictions
    SET heuristic_prediction_status = 'completed',
        heuristic_model_version = p_model_version, heuristic_prediction = p_prediction
    WHERE id = p_fixture_id
      AND heuristic_prediction_status IN ('pending', 'error')
      AND resolution_status = 'resolved'
      AND game_date > (clock_timestamp() AT TIME ZONE 'UTC')::DATE;
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected = 1;
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_prospective_forecast(UUID, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_prospective_forecast(UUID, TEXT, JSONB) TO service_role;
REVOKE ALL ON public.prospective_match_predictions FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.prospective_match_predictions TO service_role;
