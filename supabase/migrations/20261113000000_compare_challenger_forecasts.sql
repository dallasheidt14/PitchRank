-- Separate, private confirmation records. Existing forecasts and study manifests are untouched.
CREATE TABLE IF NOT EXISTS public.compare_challenger_manifests (
  candidate_signature text PRIMARY KEY CHECK (candidate_signature ~ '^[a-f0-9]{64}$'),
  manifest jsonb NOT NULL,
  registered_at timestamptz NOT NULL,
  confirmation_start date NOT NULL,
  confirmation_end date NOT NULL,
  CHECK (confirmation_end = confirmation_start + 27)
);

CREATE TABLE IF NOT EXISTS public.compare_challenger_forecasts (
  baseline_forecast_id uuid NOT NULL REFERENCES public.prospective_match_predictions(id),
  candidate_signature text NOT NULL REFERENCES public.compare_challenger_manifests(candidate_signature),
  frozen_inputs jsonb NOT NULL,
  prediction jsonb NOT NULL,
  provenance jsonb NOT NULL,
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
  captured_at timestamptz NOT NULL,
  PRIMARY KEY (baseline_forecast_id, candidate_signature)
);

ALTER TABLE public.compare_challenger_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.compare_challenger_forecasts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.compare_challenger_manifests, public.compare_challenger_forecasts
  FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.compare_challenger_manifests, public.compare_challenger_forecasts TO service_role;

CREATE OR REPLACE FUNCTION public.guard_compare_challenger_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  RAISE EXCEPTION 'Challenger records are immutable';
END;
$$;
REVOKE ALL ON FUNCTION public.guard_compare_challenger_immutable() FROM PUBLIC, anon, authenticated, service_role;
DROP TRIGGER IF EXISTS guard_compare_challenger_manifest ON public.compare_challenger_manifests;
CREATE TRIGGER guard_compare_challenger_manifest
  BEFORE UPDATE OR DELETE ON public.compare_challenger_manifests
  FOR EACH ROW EXECUTE FUNCTION public.guard_compare_challenger_immutable();
DROP TRIGGER IF EXISTS guard_compare_challenger_forecast ON public.compare_challenger_forecasts;
CREATE TRIGGER guard_compare_challenger_forecast
  BEFORE UPDATE OR DELETE ON public.compare_challenger_forecasts
  FOR EACH ROW EXECUTE FUNCTION public.guard_compare_challenger_immutable();

CREATE OR REPLACE FUNCTION public.register_compare_challenger(p_manifest text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  definition jsonb := p_manifest::jsonb;
  signature text := encode(sha256(convert_to(p_manifest, 'UTF8')), 'hex');
  registered timestamptz := clock_timestamp();
  first_day date;
BEGIN
  IF definition->>'kind' IS DISTINCT FROM 'compare_form_confirmation'
     OR definition->>'schema_version' IS DISTINCT FROM '1'
     OR definition->>'baseline_model_signature' IS DISTINCT FROM
        '1718e7be40328a18901f93df30ed31f99581b7b481af71de9277f700462dde05'
     OR definition->>'predictor_revision' IS DISTINCT FROM '866f30c73a84524028b9fe8e55b3108ec8d544fc'
     OR coalesce(definition->>'candidate', '') NOT IN
        ('form_off','residual_sequence','residual_30','residual_60','residual_30_capped','residual_60_capped')
     OR definition->'production_promotion' IS DISTINCT FROM 'false'::jsonb
     OR definition->'confirmation_policy' IS DISTINCT FROM
        '{"weeks":4,"start":"next_complete_utc_monday_after_registration","minimum_paired_settled":1000,"minimum_groups":20,"lower_brier":true,"upper_95_group_bootstrap_log_loss_delta_below_zero":true,"complete_risk_outputs":true}'::jsonb
     OR definition#>>'{qualification,status}' IS DISTINCT FROM 'qualifies_for_confirmation'
     OR definition#>>'{qualification,reviewed}' IS DISTINCT FROM 'true'
     OR coalesce(definition#>>'{qualification,report_sha256}', '') !~ '^[a-f0-9]{64}$'
     OR coalesce(definition#>>'{qualification,dataset_sha256}', '') !~ '^[a-f0-9]{64}$'
     OR coalesce(definition#>>'{qualification,study_manifest_sha256}', '') !~ '^[a-f0-9]{64}$'
     OR coalesce((definition#>>'{qualification,periods,development,games}')::integer, 0) < 1000
     OR coalesce((definition#>>'{qualification,periods,evaluation,games}')::integer, 0) < 1000
     OR coalesce((definition#>>'{qualification,periods,development,groups}')::integer, 0) < 20
     OR coalesce((definition#>>'{qualification,periods,evaluation,groups}')::integer, 0) < 20
     OR (definition#>>'{qualification,evaluation_end}')::date >= (registered AT TIME ZONE 'UTC')::date
     OR definition#>>'{qualification,evaluation_end}' IS NULL
     OR coalesce(definition->>'research_revision', '') !~ '^[a-f0-9]{40}$'
     OR jsonb_typeof(definition->'research_sources') IS DISTINCT FROM 'object'
     OR definition->'research_sources' = '{}'::jsonb
     OR jsonb_typeof(definition->'qualified_execution_sources') IS DISTINCT FROM 'object'
     OR definition->'qualified_execution_sources' = '{}'::jsonb THEN
    RAISE EXCEPTION 'Incomplete or unqualified challenger manifest';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_each_text(definition->'qualified_execution_sources') entry
             WHERE definition->'research_sources'->>entry.key IS DISTINCT FROM entry.value) THEN
    RAISE EXCEPTION 'Candidate sources differ from its qualification';
  END IF;
  IF EXISTS (SELECT 1 FROM public.compare_challenger_manifests WHERE candidate_signature=signature) THEN
    RETURN signature; -- A retry never changes the first registration or confirmation dates.
  END IF;
  first_day := (registered AT TIME ZONE 'UTC')::date;
  first_day := first_day + (8 - extract(isodow FROM first_day)::integer);
  INSERT INTO public.compare_challenger_manifests
    VALUES (signature, definition, registered, first_day, first_day + 27)
    ON CONFLICT (candidate_signature) DO NOTHING;
  RETURN signature;
END;
$$;
REVOKE ALL ON FUNCTION public.register_compare_challenger(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_compare_challenger(text) TO service_role;

CREATE OR REPLACE FUNCTION public.freeze_compare_challenger(
  p_baseline_forecast_id uuid, p_candidate_signature text, p_payload text
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  baseline public.prospective_match_predictions%ROWTYPE;
  candidate public.compare_challenger_manifests%ROWTYPE;
  source public.games%ROWTYPE;
  payload jsonb := p_payload::jsonb;
  prediction jsonb := payload->'prediction';
  captured timestamptz;
  field text;
  probability double precision;
  total double precision := 0;
  affected integer;
BEGIN
  SELECT * INTO candidate FROM public.compare_challenger_manifests
    WHERE candidate_signature=p_candidate_signature;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unregistered challenger'; END IF;
  SELECT * INTO baseline FROM public.prospective_match_predictions WHERE id=p_baseline_forecast_id FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing baseline forecast'; END IF;
  -- Retry is harmless even after kickoff; it cannot overwrite a completed record.
  IF EXISTS (SELECT 1 FROM public.compare_challenger_forecasts
             WHERE baseline_forecast_id=p_baseline_forecast_id AND candidate_signature=p_candidate_signature) THEN
    RETURN false;
  END IF;
  captured := clock_timestamp();
  IF baseline.heuristic_prediction_status <> 'completed'
     OR baseline.source_game_id IS NULL
     OR baseline.heuristic_prediction->>'modelSignature' IS DISTINCT FROM candidate.manifest->>'baseline_model_signature'
     OR baseline.heuristic_predicted_at IS NULL
     OR baseline.heuristic_predicted_at >= baseline.game_date::timestamp AT TIME ZONE 'UTC'
     OR baseline.game_date <= (captured AT TIME ZONE 'UTC')::date
     OR baseline.game_date NOT BETWEEN candidate.confirmation_start AND candidate.confirmation_end
     OR baseline.evaluation_status NOT IN ('pending_result','result_not_found') THEN
    RAISE EXCEPTION 'Baseline is not eligible for prematch paired capture';
  END IF;
  SELECT * INTO source FROM public.games WHERE id=baseline.source_game_id FOR SHARE;
  IF NOT FOUND OR source.is_excluded IS DISTINCT FROM false
     OR source.home_score IS NOT NULL OR source.away_score IS NOT NULL
     OR source.game_date IS DISTINCT FROM baseline.game_date
     OR source.source_url IS DISTINCT FROM baseline.fixture_payload#>>'{source_snapshot,source_url}'
     OR source.home_team_master_id::text IS DISTINCT FROM baseline.fixture_payload#>>'{source_snapshot,home_team_master_id}'
     OR source.away_team_master_id::text IS DISTINCT FROM baseline.fixture_payload#>>'{source_snapshot,away_team_master_id}'
     OR source.provider_id::text IS DISTINCT FROM baseline.fixture_payload#>>'{source_snapshot,provider_id}' THEN
    RAISE EXCEPTION 'Source fixture changed or has a result';
  END IF;
  IF payload#>'{frozen_inputs,baseline_prediction}' IS DISTINCT FROM baseline.heuristic_prediction
     OR payload#>>'{frozen_inputs,case,fixture,source_game_id}' IS DISTINCT FROM baseline.source_game_id::text
     OR payload#>>'{frozen_inputs,case,fixture,game_date}' IS DISTINCT FROM baseline.game_date::text
     OR payload#>'{frozen_inputs,case,teamA}' IS DISTINCT FROM baseline.heuristic_prediction#>'{shadowContext,teamAInput}'
     OR payload#>'{frozen_inputs,case,teamB}' IS DISTINCT FROM baseline.heuristic_prediction#>'{shadowContext,teamBInput}'
     OR payload#>'{frozen_inputs,case,games}' IS DISTINCT FROM baseline.heuristic_prediction#>'{shadowContext,frozenEvidence,games}'
     OR payload#>>'{provenance,candidate_signature}' IS DISTINCT FROM p_candidate_signature
     OR payload#>'{provenance,research_sources}' IS DISTINCT FROM candidate.manifest->'research_sources'
     OR payload#>>'{provenance,aa_parity}' IS DISTINCT FROM 'true'
     OR payload#>>'{provenance,predictor_revision}' IS DISTINCT FROM candidate.manifest->>'predictor_revision'
     OR jsonb_typeof(prediction->'expectedMargin') IS DISTINCT FROM 'number'
     OR jsonb_typeof(prediction#>'{expectedScore,teamA}') IS DISTINCT FROM 'number'
     OR jsonb_typeof(prediction#>'{expectedScore,teamB}') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'Challenger inputs or provenance do not match the registered baseline';
  END IF;
  FOREACH field IN ARRAY ARRAY['winProbabilityA','drawProbability','winProbabilityB','blowout4PlusProbability'] LOOP
    IF jsonb_typeof(prediction->field) IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'Complete probability and risk outputs are required';
    END IF;
    probability := (prediction->>field)::double precision;
    IF probability < 0 OR probability > 1 THEN RAISE EXCEPTION 'Invalid probability'; END IF;
    IF field <> 'blowout4PlusProbability' THEN total := total + probability; END IF;
  END LOOP;
  IF abs(total - 1) > 0.000000001 THEN RAISE EXCEPTION 'Outcome probabilities must sum to one'; END IF;
  captured := clock_timestamp();
  IF baseline.game_date <= (captured AT TIME ZONE 'UTC')::date THEN
    RAISE EXCEPTION 'Match day began during challenger capture';
  END IF;
  INSERT INTO public.compare_challenger_forecasts
    VALUES (p_baseline_forecast_id, p_candidate_signature, payload->'frozen_inputs', prediction,
            payload->'provenance', encode(sha256(convert_to(p_payload, 'UTF8')), 'hex'), captured)
    ON CONFLICT (baseline_forecast_id, candidate_signature) DO NOTHING;
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected = 1;
END;
$$;
REVOKE ALL ON FUNCTION public.freeze_compare_challenger(uuid,text,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_compare_challenger(uuid,text,text) TO service_role;

-- Scores always come from the baseline's exact-source matching. This view exposes counts only.
CREATE OR REPLACE VIEW public.compare_challenger_pair_coverage AS
SELECT m.candidate_signature, b.game_date, b.provider_code, b.fixture_payload->>'cohort' AS cohort,
       count(*) AS baseline_forecasts, count(c.baseline_forecast_id) AS paired_forecasts,
       count(*) FILTER (WHERE c.baseline_forecast_id IS NULL) AS missing_challenger_forecasts,
       count(*) FILTER (WHERE c.baseline_forecast_id IS NOT NULL AND b.evaluation_status='settled') AS paired_settled
FROM public.compare_challenger_manifests m
JOIN public.prospective_match_predictions b
  ON b.game_date BETWEEN m.confirmation_start AND m.confirmation_end
 AND b.heuristic_prediction_status='completed'
 AND b.heuristic_prediction->>'modelSignature'=m.manifest->>'baseline_model_signature'
LEFT JOIN public.compare_challenger_forecasts c
  ON c.baseline_forecast_id=b.id AND c.candidate_signature=m.candidate_signature
GROUP BY 1,2,3,4;
REVOKE ALL ON public.compare_challenger_pair_coverage FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.compare_challenger_pair_coverage TO service_role;
