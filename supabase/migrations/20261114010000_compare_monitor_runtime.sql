-- Preserve all existing forecasts. Null calibration is an explicit, verified runtime fallback.
CREATE OR REPLACE FUNCTION public.register_compare_monitor(p_manifest text) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  m jsonb := p_manifest::jsonb;
  field text;
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
  IF m ? 'runtime_profile' THEN
    IF m#>>'{runtime_profile,origin}' IS DISTINCT FROM 'https://www.pitchrank.io/api/match-prediction'
      OR m#>>'{runtime_profile,algorithm_hash}' IS DISTINCT FROM m->>'algorithm_hash'
      OR coalesce(m#>>'{runtime_profile,calibration_sha256}','') !~ '^[a-f0-9]{64}$'
      OR coalesce(m#>>'{runtime_profile,input_source_hash}','') !~ '^[a-f0-9]{64}$'
      OR jsonb_typeof(m#>'{runtime_profile,calibration,ageGroups}') IS DISTINCT FROM 'object' THEN
      RAISE EXCEPTION 'Invalid production runtime profile';
    END IF;
    FOR field IN SELECT unnest(ARRAY['ageGroups','probability','margin','outcome','confidence']) LOOP
      IF coalesce(jsonb_typeof(m#>ARRAY['runtime_profile','calibration',field]),'missing') NOT IN ('object','null') THEN
        RAISE EXCEPTION 'Incomplete production runtime profile';
      END IF;
    END LOOP;
  END IF;
  INSERT INTO public.compare_monitoring_models VALUES(sig,m,captured,first_day,first_day+27)
    ON CONFLICT DO NOTHING;
  RETURN sig;
END; $$;

CREATE OR REPLACE FUNCTION public.freeze_compare_monitor(p_baseline uuid,p_signature text,p_payload text) RETURNS boolean
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
  IF m.manifest ? 'runtime_profile' THEN
    IF p->'runtime_profile' IS DISTINCT FROM m.manifest->'runtime_profile'
      OR p#>'{context,calibration}' IS DISTINCT FROM m.manifest#>'{runtime_profile,calibration}'
      OR coalesce(p#>>'{runtime_observation,deployment_revision}','') !~ '^[a-f0-9]{40}$'
      OR (p#>>'{runtime_observation,observed_at}')::timestamptz IS NULL
      OR (p#>>'{runtime_observation,observed_at}')::timestamptz < captured-interval '15 minutes'
      OR (p#>>'{runtime_observation,observed_at}')::timestamptz > captured+interval '1 minute' THEN
      RAISE EXCEPTION 'Production runtime differs from frozen profile';
    END IF;
  END IF;
  FOREACH field IN ARRAY ARRAY['ageGroups','probability','margin','outcome','confidence'] LOOP
    IF jsonb_typeof(p#>ARRAY['context','calibration',field]) IS DISTINCT FROM 'object'
      AND NOT (m.manifest ? 'runtime_profile' AND jsonb_typeof(p#>ARRAY['context','calibration',field])='null') THEN
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

