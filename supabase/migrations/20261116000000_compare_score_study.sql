-- Score-only confirmation pairs reference immutable current Compare inputs, never the older ledger predictor.
CREATE TABLE public.compare_score_studies (
  signature text PRIMARY KEY CHECK (signature ~ '^[a-f0-9]{64}$'),
  manifest jsonb NOT NULL, registered_at timestamptz NOT NULL,
  monitor_signature text NOT NULL REFERENCES public.compare_monitoring_models(signature),
  capture_start date NOT NULL, capture_end date NOT NULL, review_not_before date NOT NULL,
  CHECK (capture_end=capture_start+27 AND review_not_before>capture_end)
);
CREATE TABLE public.compare_score_forecasts (
  study_signature text NOT NULL REFERENCES public.compare_score_studies(signature),
  baseline_forecast_id uuid NOT NULL,
  monitor_signature text NOT NULL,
  payload jsonb NOT NULL, payload_sha256 text NOT NULL, captured_at timestamptz NOT NULL,
  PRIMARY KEY (study_signature,baseline_forecast_id),
  FOREIGN KEY (baseline_forecast_id,monitor_signature)
    REFERENCES public.compare_monitoring_forecasts(baseline_forecast_id,monitor_signature)
);
ALTER TABLE public.compare_score_studies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.compare_score_forecasts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.compare_score_studies,public.compare_score_forecasts FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.compare_score_studies,public.compare_score_forecasts TO service_role;
CREATE TRIGGER immutable_compare_score_studies BEFORE UPDATE OR DELETE ON public.compare_score_studies
  FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();
CREATE TRIGGER immutable_compare_score_forecasts BEFORE UPDATE OR DELETE ON public.compare_score_forecasts
  FOR EACH ROW EXECUTE FUNCTION public.keep_compare_experiment_immutable();

CREATE FUNCTION public.register_compare_score_study(p_manifest text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  m jsonb:=p_manifest::jsonb;
  sig text:=encode(sha256(convert_to(p_manifest,'UTF8')),'hex');
  model public.compare_monitoring_models%ROWTYPE;
  captured timestamptz;
  first_day date;
BEGIN
  -- A lost registration response can be retried without changing its original receipt or window.
  IF EXISTS(SELECT 1 FROM public.compare_score_studies WHERE signature=sig) THEN RETURN sig; END IF;
  SELECT * INTO model FROM public.compare_monitoring_models WHERE signature=m->>'monitor_signature';
  IF NOT FOUND OR model.manifest->>'model_signature' IS DISTINCT FROM m->>'baseline_model_signature' THEN
    RAISE EXCEPTION 'Unknown current baseline';
  END IF;
  captured:=clock_timestamp();
  first_day:=(date_trunc('week',captured AT TIME ZONE 'UTC')+interval '1 week')::date;
  IF m->>'kind' IS DISTINCT FROM 'compare_score_confirmation_v1' OR m->>'schema_version' IS DISTINCT FROM '1'
    OR (m->>'capture_start')::date IS DISTINCT FROM first_day
    OR (m->>'capture_end')::date IS DISTINCT FROM first_day+27
    OR (m->>'review_not_before')::date IS NULL
    OR (m->>'review_not_before')::date<=first_day+27
    OR (m->>'review_not_before')::date<DATE '2027-01-11'
    OR m->'production_promotion' IS DISTINCT FROM 'false'::jsonb
    OR m->>'entrypoint' IS DISTINCT FROM 'scripts/capture_compare_score_study.py'
    OR coalesce(m->>'code_revision','') !~ '^[a-f0-9]{40}$'
    OR jsonb_typeof(m->'execution_hashes') IS DISTINCT FROM 'object'
    OR coalesce(m#>>'{execution_hashes,scripts/capture_compare_score_study.py}','') !~ '^[a-f0-9]{64}$'
    OR EXISTS(SELECT 1 FROM jsonb_each_text(m->'execution_hashes') h WHERE h.value !~ '^[a-f0-9]{64}$')
    OR m#>>'{artifact,bucket}' IS DISTINCT FROM 'prediction-input-archives'
    OR coalesce(m#>>'{artifact,object}','') !~ '^compare-score-research/[0-9]{4}-[0-9]{2}-[0-9]{2}/[a-f0-9]{64}\.zip$'
    OR coalesce(m#>>'{artifact,zip_sha256}','') !~ '^[a-f0-9]{64}$'
    OR coalesce(m#>>'{artifact,model_sha256}','') !~ '^[a-f0-9]{64}$'
    OR m#>>'{artifact,model_member}' IS DISTINCT FROM 'prospective/fitted-model.json'
    OR m#>>'{artifact,training_member}' IS DISTINCT FROM 'prospective/training-games.json'
    OR m#>'{fit_receipt,optimizer_success}' IS DISTINCT FROM 'true'::jsonb
    OR m#>>'{fit_receipt,penalty}' IS DISTINCT FROM '4'
    OR m#>>'{fit_receipt,half_life}' IS DISTINCT FROM '60'
    OR coalesce(m#>>'{fit_receipt,data_sha256}','') !~ '^[a-f0-9]{64}$'
    OR (m#>>'{fit_receipt,latest_training_game}')::date IS NULL
    OR (m#>>'{fit_receipt,cutoff}')::date IS NULL
    OR (m#>>'{fit_receipt,latest_training_game}')::date >= (m#>>'{fit_receipt,cutoff}')::date
    OR (m#>>'{fit_receipt,cutoff}')::date > first_day
    OR m#>>'{policy,minimum_pairs}' IS DISTINCT FROM '1000'
    OR m#>>'{policy,minimum_groups}' IS DISTINCT FROM '20'
    OR m#>>'{policy,primary_candidate}' IS DISTINCT FROM 'blend_25'
    OR m#>>'{policy,secondary_candidate}' IS DISTINCT FROM 'tail_guard_full'
    OR m#>>'{policy,primary_metric}' IS DISTINCT FROM 'mean_absolute_goals_per_team'
    OR m#>'{policy,bootstrap}' IS DISTINCT FROM
      '{"unit":"match_group","repetitions":10000,"seed":20261123,"confidence":0.95}'::jsonb
    OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(m->'candidates') key)
      IS DISTINCT FROM ARRAY['baseline','blend_25','tail_guard_full']
    OR m#>>'{candidates,blend_25,challenger_weight}' IS DISTINCT FROM '0.25'
    OR m#>'{candidates,tail_guard_full,preserve_four_goal_risk}' IS DISTINCT FROM 'true'::jsonb THEN
    RAISE EXCEPTION 'Invalid fixed score-study manifest';
  END IF;
  captured:=clock_timestamp();
  IF (captured AT TIME ZONE 'UTC')::date>=first_day THEN RAISE EXCEPTION 'Registration deadline passed'; END IF;
  INSERT INTO public.compare_score_studies VALUES(sig,m,captured,model.signature,first_day,first_day+27,
    (m->>'review_not_before')::date) ON CONFLICT DO NOTHING;
  RETURN sig;
END; $$;

-- The queue returns frozen pregame inputs only; target scores are neither selected nor returned.
CREATE FUNCTION public.compare_score_capture_queue(p_signature text,p_after uuid DEFAULT NULL,p_limit integer DEFAULT 500)
RETURNS SETOF jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT jsonb_build_object('baseline_forecast_id',b.id,'source_game_id',b.source_game_id,'game_date',b.game_date,
    'monitor_signature',f.monitor_signature,'parent_payload_sha256',f.payload_sha256,
    'parent_captured_at',f.captured_at,'parent_payload',f.payload)
  FROM public.compare_score_studies s JOIN public.compare_monitoring_forecasts f ON f.monitor_signature=s.monitor_signature
  JOIN public.prospective_match_predictions b ON b.id=f.baseline_forecast_id
  WHERE s.signature=p_signature AND b.game_date BETWEEN s.capture_start AND s.capture_end
    AND b.game_date>(statement_timestamp() AT TIME ZONE 'UTC')::date
    AND (p_after IS NULL OR b.id>p_after)
    AND NOT EXISTS(SELECT 1 FROM public.compare_score_forecasts c
      WHERE c.study_signature=s.signature AND c.baseline_forecast_id=b.id)
  ORDER BY b.id LIMIT greatest(0,least(p_limit,500));
$$;

CREATE FUNCTION public.freeze_compare_score_forecast(p_signature text,p_baseline uuid,p_payload text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  s public.compare_score_studies%ROWTYPE; b public.prospective_match_predictions%ROWTYPE;
  f public.compare_monitoring_forecasts%ROWTYPE; g public.games%ROWTYPE;
  p jsonb:=p_payload::jsonb; arm text; field text; value numeric; total numeric; decision text;
  captured timestamptz; affected integer;
BEGIN
  SELECT * INTO s FROM public.compare_score_studies WHERE signature=p_signature;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unregistered score study'; END IF;
  SELECT * INTO b FROM public.prospective_match_predictions WHERE id=p_baseline FOR SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing baseline'; END IF;
  IF EXISTS(SELECT 1 FROM public.compare_score_forecasts WHERE study_signature=p_signature AND baseline_forecast_id=p_baseline) THEN
    RETURN false;
  END IF;
  SELECT * INTO f FROM public.compare_monitoring_forecasts
    WHERE baseline_forecast_id=p_baseline AND monitor_signature=s.monitor_signature;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing current Compare parent'; END IF;
  SELECT * INTO g FROM public.games WHERE id=b.source_game_id FOR SHARE;
  captured:=clock_timestamp();
  IF NOT FOUND OR b.game_date NOT BETWEEN s.capture_start AND s.capture_end
    OR b.game_date<=(captured AT TIME ZONE 'UTC')::date
    OR g.game_date IS DISTINCT FROM b.game_date OR g.is_excluded IS DISTINCT FROM false
    OR g.home_score IS NOT NULL OR g.away_score IS NOT NULL
    OR g.home_team_master_id::text IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,home_team_master_id}'
    OR g.away_team_master_id::text IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,away_team_master_id}'
    OR g.provider_id::text IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,provider_id}'
    OR g.source_url IS DISTINCT FROM b.fixture_payload#>>'{source_snapshot,source_url}' THEN
    RAISE EXCEPTION 'Source fixture changed or deadline passed';
  END IF;
  IF p->>'schema_version' IS DISTINCT FROM '1' OR p->>'study_signature' IS DISTINCT FROM p_signature
    OR p->>'baseline_payload_sha256' IS DISTINCT FROM f.payload_sha256
    OR p->>'model_sha256' IS DISTINCT FROM s.manifest#>>'{artifact,model_sha256}'
    OR p->>'code_revision' IS DISTINCT FROM s.manifest->>'code_revision'
    OR p->'execution_hashes' IS DISTINCT FROM s.manifest->'execution_hashes'
    OR p#>'{candidates,baseline,prediction}' IS DISTINCT FROM f.payload->'prediction'
    OR p#>>'{candidates,baseline,status}' IS DISTINCT FROM 'baseline_control'
    OR coalesce(p->>'eligibility','') NOT IN ('eligible','cross_cohort_fallback','unseen_team_fallback','unseen_cohort_fallback')
    OR (p->>'eligibility'='eligible' AND (jsonb_typeof(p->'learned_rates') IS DISTINCT FROM 'array'
      OR jsonb_array_length(p->'learned_rates')<>2))
    OR (p->>'eligibility'<>'eligible' AND p->'learned_rates' IS DISTINCT FROM 'null'::jsonb) THEN
    RAISE EXCEPTION 'Inconsistent score provenance';
  END IF;
  IF p->>'eligibility'='eligible' AND EXISTS(SELECT 1 FROM jsonb_array_elements(p->'learned_rates') r
    WHERE jsonb_typeof(r)<>'number' OR r::numeric<0.15 OR r::numeric>7.5) THEN
    RAISE EXCEPTION 'Invalid frozen learned rates';
  END IF;
  FOREACH arm IN ARRAY ARRAY['baseline','blend_25','tail_guard_full'] LOOP
    total:=0;
    FOREACH field IN ARRAY ARRAY['winProbabilityA','drawProbability','winProbabilityB','blowout4PlusProbability'] LOOP
      IF jsonb_typeof(p#>ARRAY['candidates',arm,'prediction',field]) IS DISTINCT FROM 'number' THEN
        RAISE EXCEPTION 'Complete score probabilities required';
      END IF;
      value:=(p#>>ARRAY['candidates',arm,'prediction',field])::numeric;
      IF value<0 OR value>1 THEN RAISE EXCEPTION 'Invalid probability'; END IF;
      IF field<>'blowout4PlusProbability' THEN
        total:=total+value;
        IF p#>ARRAY['candidates',arm,'prediction',field] IS DISTINCT FROM f.payload#>ARRAY['prediction',field] THEN
          RAISE EXCEPTION 'Winner probabilities must remain unchanged';
        END IF;
      END IF;
    END LOOP;
    decision:=p#>>ARRAY['candidates',arm,'prediction','predictedWinner'];
    IF abs(total-1)>0.000000000001 OR decision IS NULL OR decision NOT IN ('team_a','draw','team_b')
      OR decision IS DISTINCT FROM f.payload#>>'{prediction,predictedWinner}'
      OR jsonb_typeof(p#>ARRAY['candidates',arm,'prediction','expectedMargin']) IS DISTINCT FROM 'number' THEN
      RAISE EXCEPTION 'Outcome decision or margin differs';
    END IF;
    FOREACH field IN ARRAY ARRAY['teamA','teamB'] LOOP
      IF jsonb_typeof(p#>ARRAY['candidates',arm,'prediction','expectedGoals',field]) IS DISTINCT FROM 'number'
        OR (p#>>ARRAY['candidates',arm,'prediction','expectedGoals',field])::numeric<=0
        OR coalesce(p#>>ARRAY['candidates',arm,'prediction','expectedScore',field],'') !~ '^[0-9]+$' THEN
        RAISE EXCEPTION 'Complete goal and integer score outputs required';
      END IF;
    END LOOP;
    IF arm<>'baseline' AND ((p->>'eligibility'='eligible' AND p#>>ARRAY['candidates',arm,'status'] IS DISTINCT FROM 'applied')
      OR (p->>'eligibility'<>'eligible' AND (p#>>ARRAY['candidates',arm,'status'] IS DISTINCT FROM p->>'eligibility'
        OR p#>ARRAY['candidates',arm,'prediction'] IS DISTINCT FROM f.payload->'prediction'))) THEN
      RAISE EXCEPTION 'Fallback must preserve the complete baseline';
    END IF;
  END LOOP;
  IF p#>'{candidates,tail_guard_full,prediction,blowout4PlusProbability}'
    IS DISTINCT FROM f.payload#>'{prediction,blowout4PlusProbability}' THEN
    RAISE EXCEPTION 'Protected candidate changed blowout risk';
  END IF;
  captured:=clock_timestamp();
  IF b.game_date<=(captured AT TIME ZONE 'UTC')::date THEN RAISE EXCEPTION 'Match day began'; END IF;
  INSERT INTO public.compare_score_forecasts VALUES(p_signature,p_baseline,s.monitor_signature,p,
    encode(sha256(convert_to(p_payload,'UTF8')),'hex'),captured) ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS affected=ROW_COUNT;
  RETURN affected=1;
END; $$;

-- Keep every existing date-wide restriction and add the registered score-study review date.
CREATE OR REPLACE FUNCTION public.compare_monitor_results_open(p_day date) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT p_day < (statement_timestamp() AT TIME ZONE 'UTC')::date
    AND NOT EXISTS(SELECT 1 FROM public.compare_calibration_experiments e
      WHERE p_day BETWEEN e.development_start AND e.test_end AND e.test_end >= (statement_timestamp() AT TIME ZONE 'UTC')::date)
    AND NOT (p_day BETWEEN DATE '2026-11-14' AND DATE '2026-11-15'
      AND (statement_timestamp() AT TIME ZONE 'UTC')::date <= DATE '2026-11-15')
    AND NOT EXISTS(SELECT 1 FROM public.compare_sos_selections s
      WHERE p_day BETWEEN s.confirmation_start AND s.confirmation_end AND s.confirmation_end >= (statement_timestamp() AT TIME ZONE 'UTC')::date)
    AND NOT EXISTS(SELECT 1 FROM public.compare_challenger_manifests c
      WHERE p_day BETWEEN c.confirmation_start AND c.confirmation_end AND c.confirmation_end >= (statement_timestamp() AT TIME ZONE 'UTC')::date)
    AND NOT EXISTS(SELECT 1 FROM public.compare_score_studies s
      WHERE p_day BETWEEN s.capture_start AND s.capture_end AND s.review_not_before > (statement_timestamp() AT TIME ZONE 'UTC')::date);
$$;

CREATE FUNCTION public.compare_score_coverage(p_signature text) RETURNS SETOF jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT jsonb_build_object('day',b.game_date,'baseline',count(*),'current_captured',count(f.baseline_forecast_id),
    'paired',count(c.baseline_forecast_id),'missing_current',count(*)-count(f.baseline_forecast_id),
    'missing_score',count(f.baseline_forecast_id)-count(c.baseline_forecast_id))
  FROM public.compare_score_studies s JOIN public.prospective_match_predictions b
    ON b.game_date BETWEEN s.capture_start AND s.capture_end AND b.heuristic_prediction_status='completed'
  LEFT JOIN public.compare_monitoring_forecasts f ON f.baseline_forecast_id=b.id AND f.monitor_signature=s.monitor_signature
  LEFT JOIN public.compare_score_forecasts c ON c.study_signature=s.signature AND c.baseline_forecast_id=b.id
  WHERE s.signature=p_signature AND b.game_date BETWEEN s.capture_start AND s.capture_end
  GROUP BY b.game_date ORDER BY b.game_date;
$$;

CREATE FUNCTION public.compare_score_review_open(p_signature text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  SELECT (statement_timestamp() AT TIME ZONE 'UTC')::date>=s.review_not_before
    AND s.capture_end<(statement_timestamp() AT TIME ZONE 'UTC')::date
    AND NOT EXISTS(SELECT 1 FROM generate_series(s.capture_start,s.capture_end,interval '1 day') d
      WHERE NOT public.compare_monitor_results_open(d::date))
  FROM public.compare_score_studies s WHERE s.signature=p_signature;
$$;

CREATE FUNCTION public.compare_score_review(p_signature text,p_after uuid DEFAULT NULL,p_limit integer DEFAULT 500,
  p_preview boolean DEFAULT true) RETURNS SETOF jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE s public.compare_score_studies%ROWTYPE; released boolean;
BEGIN
  SELECT * INTO s FROM public.compare_score_studies WHERE signature=p_signature;
  IF NOT FOUND THEN RAISE EXCEPTION 'Unknown score study'; END IF;
  released:=public.compare_score_review_open(p_signature);
  -- The sealed branch never touches games and omits all target scores and frozen contexts.
  IF NOT released OR p_preview THEN
    RETURN QUERY SELECT jsonb_build_object('open',released,'preview',p_preview,
      'captured',(SELECT count(*) FROM public.compare_score_forecasts WHERE study_signature=p_signature),
      'review_not_before',s.review_not_before);
    RETURN;
  END IF;
  RETURN QUERY
    SELECT jsonb_build_object('open',true,'baseline_forecast_id',b.id,'source_game_id',b.source_game_id,
      'game_date',b.game_date,'fixture_payload',b.fixture_payload,'payload',c.payload,
      'group',b.evaluation_group_key,'group_kind',b.evaluation_group_kind,
      'provider',b.provider_code,'source_event_id',b.source_event_id,
      'payload_sha256',c.payload_sha256,'captured_at',c.captured_at,
      'result',CASE WHEN g.id IS NOT NULL AND g.is_excluded IS FALSE
        AND g.provider_id::text IS NOT DISTINCT FROM b.fixture_payload#>>'{source_snapshot,provider_id}'
        AND g.source_url IS NOT DISTINCT FROM b.fixture_payload#>>'{source_snapshot,source_url}'
        AND g.home_team_master_id::text IS NOT DISTINCT FROM b.fixture_payload#>>'{source_snapshot,home_team_master_id}'
        AND g.away_team_master_id::text IS NOT DISTINCT FROM b.fixture_payload#>>'{source_snapshot,away_team_master_id}'
        THEN jsonb_build_object('home_score',g.home_score,'away_score',g.away_score) ELSE NULL END)
    FROM public.compare_score_forecasts c JOIN public.prospective_match_predictions b ON b.id=c.baseline_forecast_id
    -- A corrected source date cannot expose a protected match from another day.
    LEFT JOIN public.games g ON g.id=b.source_game_id AND g.game_date=b.game_date
    WHERE c.study_signature=p_signature AND (p_after IS NULL OR b.id>p_after)
    ORDER BY b.id LIMIT greatest(0,least(p_limit,500));
END; $$;

REVOKE ALL ON FUNCTION public.register_compare_score_study(text),public.compare_score_capture_queue(text,uuid,integer),
  public.freeze_compare_score_forecast(text,uuid,text),public.compare_score_coverage(text),
  public.compare_score_review(text,uuid,integer,boolean),public.compare_score_review_open(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_compare_score_study(text),public.compare_score_capture_queue(text,uuid,integer),
  public.freeze_compare_score_forecast(text,uuid,text),public.compare_score_coverage(text),
  public.compare_score_review(text,uuid,integer,boolean),public.compare_score_review_open(text) TO service_role;
