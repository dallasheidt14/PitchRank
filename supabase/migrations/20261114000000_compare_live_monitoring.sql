-- Observational live forecasts and preregistered SOS arms; no public formula changes.
CREATE TABLE public.compare_monitoring_models (
  signature text PRIMARY KEY CHECK (signature ~ '^[a-f0-9]{64}$'),
  manifest jsonb NOT NULL, registered_at timestamptz NOT NULL,
  development_start date NOT NULL, development_end date NOT NULL
);
CREATE TABLE public.compare_monitoring_forecasts (
  baseline_forecast_id uuid NOT NULL REFERENCES public.prospective_match_predictions(id),
  monitor_signature text NOT NULL REFERENCES public.compare_monitoring_models(signature),
  payload jsonb NOT NULL, payload_sha256 text NOT NULL, captured_at timestamptz NOT NULL,
  PRIMARY KEY (baseline_forecast_id, monitor_signature)
);
CREATE TABLE public.compare_sos_selections (
  monitor_signature text PRIMARY KEY REFERENCES public.compare_monitoring_models(signature),
  multiplier numeric NOT NULL CHECK (multiplier IN (0,0.5,1.5)),
  qualification jsonb NOT NULL, registered_at timestamptz NOT NULL,
  confirmation_start date NOT NULL, confirmation_end date NOT NULL,
  CHECK (confirmation_end=confirmation_start+27)
);
CREATE TABLE public.compare_monitor_result_audit (
  baseline_forecast_id uuid NOT NULL,
  monitor_signature text NOT NULL,
  state_sha256 text NOT NULL,
  state jsonb NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (baseline_forecast_id,monitor_signature,state_sha256),
  FOREIGN KEY (baseline_forecast_id,monitor_signature)
    REFERENCES public.compare_monitoring_forecasts(baseline_forecast_id,monitor_signature)
);
ALTER TABLE public.compare_monitor_result_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.compare_monitor_result_audit FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.compare_monitor_result_audit TO service_role;
CREATE TRIGGER immutable_compare_monitor_audit BEFORE UPDATE OR DELETE ON public.compare_monitor_result_audit
  FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();
ALTER TABLE public.compare_monitoring_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.compare_monitoring_forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.compare_sos_selections ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.compare_monitoring_models,public.compare_monitoring_forecasts,public.compare_sos_selections
  FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.compare_monitoring_models,public.compare_monitoring_forecasts,public.compare_sos_selections TO service_role;
CREATE TRIGGER immutable_compare_monitor_models BEFORE UPDATE OR DELETE ON public.compare_monitoring_models
  FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();
CREATE TRIGGER immutable_compare_monitor_forecasts BEFORE UPDATE OR DELETE ON public.compare_monitoring_forecasts
  FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();
CREATE TRIGGER immutable_compare_sos_selection BEFORE UPDATE OR DELETE ON public.compare_sos_selections
  FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();

CREATE FUNCTION public.register_compare_monitor(p_manifest text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  m jsonb := p_manifest::jsonb;
  sig text := encode(sha256(convert_to(p_manifest,'UTF8')),'hex');
  captured timestamptz := clock_timestamp();
  first_day date := (date_trunc('week',captured AT TIME ZONE 'UTC')+interval '1 week')::date;
BEGIN
  IF m->>'kind' IS DISTINCT FROM 'compare_live_sos_monitoring'
    OR m->>'schema_version' IS DISTINCT FROM '1'
    OR m->'multipliers' IS DISTINCT FROM '[0,0.5,1,1.5]'::jsonb
    OR m->'production_promotion' IS DISTINCT FROM 'false'::jsonb
    OR coalesce(m->>'model_version','')=''
    OR coalesce(m->>'model_signature','') !~ '^[a-f0-9]{64}$'
    OR coalesce(m->>'algorithm_hash','') !~ '^[a-f0-9]{64}$'
    OR coalesce(m->>'research_hash','') !~ '^[a-f0-9]{64}$'
    OR coalesce(m->>'code_revision','') !~ '^[a-f0-9]{40}$' THEN
    RAISE EXCEPTION 'Invalid monitoring manifest';
  END IF;
  INSERT INTO public.compare_monitoring_models VALUES(sig,m,captured,first_day,first_day+27)
    ON CONFLICT DO NOTHING;
  RETURN sig;
END; $$;

CREATE FUNCTION public.freeze_compare_monitor(p_baseline uuid,p_signature text,p_payload text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  b public.prospective_match_predictions%ROWTYPE;
  m public.compare_monitoring_models%ROWTYPE;
  g public.games%ROWTYPE;
  p jsonb := p_payload::jsonb;
  captured timestamptz := clock_timestamp();
  reference_time timestamptz;
  arm text; field text; value double precision; total double precision; affected integer;
BEGIN
  SELECT * INTO m FROM public.compare_monitoring_models WHERE signature=p_signature;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unregistered monitoring model'; END IF;
  SELECT * INTO b FROM public.prospective_match_predictions WHERE id=p_baseline FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing baseline'; END IF;
  IF EXISTS(SELECT 1 FROM public.compare_monitoring_forecasts WHERE baseline_forecast_id=p_baseline AND monitor_signature=p_signature) THEN
    RETURN false;
  END IF;
  SELECT * INTO g FROM public.games WHERE id=b.source_game_id FOR SHARE;
  IF NOT FOUND OR b.heuristic_prediction_status IS DISTINCT FROM 'completed'
    OR b.game_date <= (captured AT TIME ZONE 'UTC')::date
    OR g.game_date IS DISTINCT FROM b.game_date OR g.is_excluded IS DISTINCT FROM false
    OR g.home_score IS NOT NULL OR g.away_score IS NOT NULL
    OR g.home_team_master_id::text IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,home_team_master_id}'
    OR g.away_team_master_id::text IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,away_team_master_id}'
    OR g.provider_id::text IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,provider_id}'
    OR g.source_url IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,source_url}' THEN
    RAISE EXCEPTION 'Source fixture changed or deadline passed';
  END IF;
  reference_time := (p->>'reference_time')::timestamptz;
  IF reference_time IS NULL OR reference_time > captured OR reference_time < captured-interval '1 hour'
    OR p->>'model_signature' IS DISTINCT FROM m.manifest->>'model_signature'
    OR p->>'code_revision' IS DISTINCT FROM m.manifest->>'code_revision'
    OR p#>>'{receipt,algorithm_hash}' IS DISTINCT FROM m.manifest->>'algorithm_hash'
    OR p#>>'{receipt,research_source_sha256}' IS DISTINCT FROM m.manifest->>'research_hash'
    OR p#>'{receipt,aa_parity}' IS DISTINCT FROM 'true'::jsonb
    OR p#>>'{context,predictorVersion}' IS DISTINCT FROM m.manifest->>'model_version'
    OR p#>>'{context,teamAInput,team_id_master}' IS DISTINCT FROM b.home_team_master_id::text
    OR p#>>'{context,teamBInput,team_id_master}' IS DISTINCT FROM b.away_team_master_id::text
    OR jsonb_typeof(p#>'{context,frozenEvidence,games}') IS DISTINCT FROM 'array'
    OR jsonb_typeof(p#>'{context,calibration}') IS DISTINCT FROM 'object'
    OR p->'prediction' IS DISTINCT FROM p#>'{variants,1}' THEN
    RAISE EXCEPTION 'Incomplete or inconsistent monitoring inputs';
  END IF;
  FOREACH field IN ARRAY ARRAY['ageGroups','probability','margin','outcome','confidence'] LOOP
    IF jsonb_typeof(p#>ARRAY['context','calibration',field]) IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'Complete frozen calibration required';
    END IF;
  END LOOP;
  IF EXISTS(SELECT 1 FROM jsonb_array_elements(p#>'{context,frozenEvidence,games}') game
    WHERE game->>'game_date' IS NULL OR (game->>'game_date')::date >= (reference_time AT TIME ZONE 'UTC')::date) THEN
    RAISE EXCEPTION 'Future results in monitoring history';
  END IF;
  FOREACH arm IN ARRAY ARRAY['0','0.5','1','1.5'] LOOP
    total := 0;
    FOREACH field IN ARRAY ARRAY['winProbabilityA','drawProbability','winProbabilityB','blowout4PlusProbability'] LOOP
      IF jsonb_typeof(p#>ARRAY['variants',arm,field]) IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'Complete predictions required';
      END IF;
      value := (p#>>ARRAY['variants',arm,field])::double precision;
      IF value<0 OR value>1 THEN RAISE EXCEPTION 'Invalid probability'; END IF;
      IF field<>'blowout4PlusProbability' THEN total:=total+value; END IF;
    END LOOP;
    IF abs(total-1)>0.000000001
      OR jsonb_typeof(p#>ARRAY['variants',arm,'expectedMargin']) IS DISTINCT FROM 'number'
      OR jsonb_typeof(p#>ARRAY['variants',arm,'expectedScore','teamA']) IS DISTINCT FROM 'number'
      OR jsonb_typeof(p#>ARRAY['variants',arm,'expectedScore','teamB']) IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'Incomplete margins, scores or probabilities';
    END IF;
  END LOOP;
  captured:=clock_timestamp();
  IF b.game_date <= (captured AT TIME ZONE 'UTC')::date THEN RAISE EXCEPTION 'Match day began'; END IF;
  INSERT INTO public.compare_monitoring_forecasts VALUES(p_baseline,p_signature,p,
    encode(sha256(convert_to(p_payload,'UTF8')),'hex'),captured) ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS affected=ROW_COUNT;
  RETURN affected=1;
END; $$;

-- Date-wide protection also covers another model predicting the same held-out fixtures.
CREATE FUNCTION public.compare_monitor_results_open(p_day date) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT p_day < (statement_timestamp() AT TIME ZONE 'UTC')::date
    AND NOT EXISTS(SELECT 1 FROM public.compare_calibration_experiments e
      WHERE p_day BETWEEN e.development_start AND e.test_end
        AND e.test_end >= (statement_timestamp() AT TIME ZONE 'UTC')::date)
    AND NOT (p_day BETWEEN DATE '2026-11-14' AND DATE '2026-11-15'
      AND (statement_timestamp() AT TIME ZONE 'UTC')::date <= DATE '2026-11-15')
    AND NOT EXISTS(SELECT 1 FROM public.compare_sos_selections s
      WHERE p_day BETWEEN s.confirmation_start AND s.confirmation_end
        AND s.confirmation_end >= (statement_timestamp() AT TIME ZONE 'UTC')::date)
    AND NOT EXISTS(SELECT 1 FROM public.compare_challenger_manifests c
      WHERE p_day BETWEEN c.confirmation_start AND c.confirmation_end
        AND c.confirmation_end >= (statement_timestamp() AT TIME ZONE 'UTC')::date);
$$;

CREATE FUNCTION public.compare_monitor_clock() RETURNS text
LANGUAGE sql STABLE SET search_path=public,pg_temp AS $$
  SELECT to_char(statement_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"');
$$;
REVOKE ALL ON FUNCTION public.compare_monitor_clock() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.compare_monitor_clock() TO service_role;

CREATE FUNCTION public.compare_monitor_coverage(p_signature text) RETURNS SETOF jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT jsonb_build_object('day',b.game_date,'provider',b.provider_code,
    'cohort',coalesce(b.fixture_payload->>'cohort','unknown'),
    'baseline',count(*),'captured',count(f.baseline_forecast_id),
    'missing',count(*)-count(f.baseline_forecast_id))
  FROM public.compare_monitoring_models m JOIN public.prospective_match_predictions b
    ON b.game_date > (m.registered_at AT TIME ZONE 'UTC')::date
      AND b.game_date <= (statement_timestamp() AT TIME ZONE 'UTC')::date+7
      AND b.heuristic_prediction_status='completed' AND b.source_system='database_games'
  LEFT JOIN public.compare_monitoring_forecasts f ON f.baseline_forecast_id=b.id AND f.monitor_signature=m.signature
  WHERE m.signature=p_signature
  GROUP BY b.game_date,b.provider_code,b.fixture_payload->>'cohort'
  ORDER BY b.game_date,b.provider_code,b.fixture_payload->>'cohort';
$$;
REVOKE ALL ON FUNCTION public.compare_monitor_coverage(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.compare_monitor_coverage(text) TO service_role;

CREATE FUNCTION public.audit_compare_monitor_result(p_baseline uuid,p_signature text,p_status text,p_result jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  b public.prospective_match_predictions%ROWTYPE;
  g public.games%ROWTYPE;
  state jsonb; sha text; previous boolean; affected integer;
BEGIN
  SELECT * INTO b FROM public.prospective_match_predictions WHERE id=p_baseline;
  IF NOT FOUND OR NOT public.compare_monitor_results_open(b.game_date) THEN
    RAISE EXCEPTION 'Sealed monitoring results';
  END IF;
  SELECT * INTO g FROM public.games WHERE id=b.source_game_id FOR SHARE;
  IF p_result IS NOT NULL AND (g.id::text IS DISTINCT FROM p_result->>'id'
    OR g.home_score IS DISTINCT FROM (p_result->>'home_score')::integer
    OR g.away_score IS DISTINCT FROM (p_result->>'away_score')::integer
    OR g.is_excluded IS DISTINCT FROM (p_result->>'is_excluded')::boolean
    OR g.game_date IS DISTINCT FROM (p_result->>'game_date')::date
    OR g.home_team_master_id::text IS DISTINCT FROM p_result->>'home_team_master_id'
    OR g.away_team_master_id::text IS DISTINCT FROM p_result->>'away_team_master_id'
    OR g.provider_id::text IS DISTINCT FROM p_result->>'provider_id'
    OR g.source_url IS DISTINCT FROM p_result->>'source_url') THEN
    RAISE EXCEPTION 'Result changed during review';
  END IF;
  state:=jsonb_build_object('status',p_status,'game_id',g.id,'home_score',g.home_score,
    'away_score',g.away_score,'is_excluded',g.is_excluded,'game_date',g.game_date,
    'home',g.home_team_master_id,'away',g.away_team_master_id,'source_url',g.source_url,'provider',g.provider_id);
  sha:=encode(sha256(convert_to(state::text,'UTF8')),'hex');
  SELECT EXISTS(SELECT 1 FROM public.compare_monitor_result_audit
    WHERE baseline_forecast_id=p_baseline AND monitor_signature=p_signature) INTO previous;
  INSERT INTO public.compare_monitor_result_audit(baseline_forecast_id,monitor_signature,state_sha256,state)
    VALUES(p_baseline,p_signature,sha,state) ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS affected=ROW_COUNT;
  RETURN previous AND affected=1;
END; $$;
REVOKE ALL ON FUNCTION public.audit_compare_monitor_result(uuid,text,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.audit_compare_monitor_result(uuid,text,text,jsonb) TO service_role;

-- The reporting path receives no score or frozen context for sealed dates.
CREATE FUNCTION public.compare_monitor_review(p_signature text,p_offset integer DEFAULT 0,p_preview boolean DEFAULT false)
RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT jsonb_build_object('baseline_forecast_id',b.id,'game_date',b.game_date,
    'provider',b.provider_code,'group',b.evaluation_group_key,'group_kind',b.evaluation_group_kind,
    'open',public.compare_monitor_results_open(b.game_date),
    'captured_at',f.captured_at,'payload_sha256',f.payload_sha256,
    'fixture',CASE WHEN NOT p_preview AND public.compare_monitor_results_open(b.game_date) THEN to_jsonb(b)-'heuristic_prediction' ELSE NULL END,
    'payload',CASE WHEN NOT p_preview AND public.compare_monitor_results_open(b.game_date) THEN f.payload ELSE NULL END)
  FROM public.compare_monitoring_forecasts f JOIN public.prospective_match_predictions b ON b.id=f.baseline_forecast_id
  WHERE f.monitor_signature=p_signature ORDER BY b.game_date,b.id
  LIMIT 1000 OFFSET greatest(p_offset,0);
$$;

CREATE FUNCTION public.register_compare_sos_selection(p_signature text,p_multiplier numeric,p_report jsonb) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  m public.compare_monitoring_models%ROWTYPE;
  registered timestamptz:=clock_timestamp();
  first_day date:=(date_trunc('week',registered AT TIME ZONE 'UTC')+interval '1 week')::date;
BEGIN
  SELECT * INTO m FROM public.compare_monitoring_models WHERE signature=p_signature;
  IF NOT FOUND OR m.development_end >= (registered AT TIME ZONE 'UTC')::date
    OR NOT public.compare_monitor_results_open(m.development_start)
    OR NOT public.compare_monitor_results_open(m.development_end)
    OR p_multiplier NOT IN (0,0.5,1.5)
    OR p_report->>'status' IS DISTINCT FROM 'selected_for_confirmation'
    OR p_report->>'monitor_signature' IS DISTINCT FROM p_signature
    OR (p_report->>'selected')::numeric IS DISTINCT FROM p_multiplier
    OR coalesce((p_report->>'games')::integer,0)<1000 OR coalesce((p_report->>'groups')::integer,0)<20
    OR coalesce(p_report->>'dataset_sha256','') !~ '^[a-f0-9]{64}$' THEN
    RAISE EXCEPTION 'Insufficient or sealed development evidence';
  END IF;
  INSERT INTO public.compare_sos_selections VALUES(p_signature,p_multiplier,p_report,registered,first_day,first_day+27)
    ON CONFLICT DO NOTHING;
  RETURN FOUND;
END; $$;

REVOKE ALL ON FUNCTION public.register_compare_monitor(text),public.freeze_compare_monitor(uuid,text,text),
  public.compare_monitor_results_open(date),public.compare_monitor_review(text,integer,boolean),
  public.register_compare_sos_selection(text,numeric,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_compare_monitor(text),public.freeze_compare_monitor(uuid,text,text),
  public.compare_monitor_results_open(date),public.compare_monitor_review(text,integer,boolean),
  public.register_compare_sos_selection(text,numeric,jsonb) TO service_role;
