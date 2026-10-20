-- Keep a running scrape protected when a worker changes pending to processing.
-- Existing duplicates must be investigated, never silently deleted by rollout.
CREATE UNIQUE INDEX IF NOT EXISTS idx_scrape_requests_active_team
  ON public.scrape_requests (team_id_master)
  WHERE status IN ('pending', 'processing');

-- Persist adoption as well as insertion: a lost RPC response must remain
-- recoverable even when the adopted request completes before the caller retries.
CREATE TABLE IF NOT EXISTS public.scrape_request_intents (
  intent_id uuid PRIMARY KEY,
  request_id uuid NOT NULL REFERENCES public.scrape_requests(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.scrape_request_intents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.scrape_request_intents FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON public.scrape_request_intents TO service_role;
DROP POLICY IF EXISTS scrape_request_intents_service ON public.scrape_request_intents;
CREATE POLICY scrape_request_intents_service ON public.scrape_request_intents
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE OR REPLACE FUNCTION public.enqueue_scrape_request_once(
  p_intent_id uuid,
  p_team_id_master uuid,
  p_team_name text,
  p_provider_id uuid,
  p_provider_team_id text,
  p_game_date date,
  p_request_type text,
  p_priority smallint
)
RETURNS SETOF public.scrape_requests
LANGUAGE plpgsql
SET search_path = public, pg_temp
SET lock_timeout = '5s'
AS $$
DECLARE
  v_team uuid;
  v_row public.scrape_requests%ROWTYPE;
BEGIN
  IF p_intent_id IS NULL OR p_team_id_master IS NULL OR p_provider_id IS NULL
     OR nullif(trim(p_provider_team_id), '') IS NULL OR p_game_date IS NULL
     OR p_priority IS NULL OR p_priority NOT BETWEEN 1 AND 5 THEN
    RAISE EXCEPTION 'Incomplete scrape request' USING ERRCODE = '22023';
  END IF;

  -- Serializes the read/adopt/insert with ALL queue writers, including direct
  -- inserts and worker claims. The active index also protects later direct writes.
  LOCK TABLE public.scrape_requests IN SHARE ROW EXCLUSIVE MODE;
  SELECT sr.* INTO v_row
  FROM public.scrape_request_intents i
  JOIN public.scrape_requests sr ON sr.id = i.request_id
  WHERE i.intent_id = p_intent_id;
  IF FOUND THEN
    RETURN NEXT v_row;
    RETURN;
  END IF;

  SELECT coalesce((SELECT canonical_team_id FROM public.team_merge_map
                   WHERE deprecated_team_id = p_team_id_master), p_team_id_master) INTO v_team;
  -- Also recognizes requests written before a merge and legacy client UUIDs.
  SELECT sr.* INTO v_row FROM public.scrape_requests sr
  LEFT JOIN public.team_merge_map mm ON mm.deprecated_team_id = sr.team_id_master
  WHERE sr.id = p_intent_id OR
    (sr.status IN ('pending', 'processing') AND coalesce(mm.canonical_team_id, sr.team_id_master) = v_team)
  ORDER BY (sr.id = p_intent_id) DESC,
    (sr.provider_id = p_provider_id AND sr.provider_team_id = p_provider_team_id
     AND (p_request_type = 'missing_game' OR sr.game_date <= p_game_date)
     AND p_game_date BETWEEN sr.game_date - 90 AND sr.game_date + 90) DESC NULLS LAST,
    sr.requested_at, sr.id
  LIMIT 1;

  IF NOT FOUND THEN
    INSERT INTO public.scrape_requests
      (id, team_id_master, team_name, provider_id, provider_team_id, game_date, request_type, priority, status)
    VALUES (p_intent_id, v_team, p_team_name, p_provider_id, p_provider_team_id,
            p_game_date, p_request_type, p_priority, 'pending')
    RETURNING * INTO v_row;
  ELSIF v_row.status = 'pending' AND v_row.provider_id = p_provider_id
        AND v_row.provider_team_id = p_provider_team_id
        AND (p_request_type = 'missing_game' OR v_row.game_date <= p_game_date)
        AND p_game_date BETWEEN v_row.game_date - 90 AND v_row.game_date + 90 THEN
    -- Never rewrite an adopted request's registration, date, or FIFO position.
    UPDATE public.scrape_requests SET priority = least(priority, p_priority)
    WHERE id = v_row.id RETURNING * INTO v_row;
  END IF;

  INSERT INTO public.scrape_request_intents (intent_id, request_id)
  VALUES (p_intent_id, v_row.id) ON CONFLICT (intent_id) DO NOTHING;
  -- An incompatible row is returned unchanged so MatchBalance can show a
  -- conflict, rather than falsely claiming another scrape was requested.
  RETURN NEXT v_row;
END;
$$;
REVOKE EXECUTE ON FUNCTION public.enqueue_scrape_request_once(uuid, uuid, text, uuid, text, date, text, smallint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_scrape_request_once(uuid, uuid, text, uuid, text, date, text, smallint)
  TO service_role;

-- Preserve the existing RPC signature and UUID return value for other producers.
-- Reuse compatible work, including processing work; reject conflicting sources
-- explicitly instead of changing a request another operator already accepted.
CREATE OR REPLACE FUNCTION public.enqueue_scrape_request(
  p_team_id_master uuid, p_team_name text, p_provider_id uuid,
  p_provider_team_id text, p_game_date date, p_request_type text, p_priority smallint
)
RETURNS uuid
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_row public.scrape_requests%ROWTYPE;
BEGIN
  SELECT * INTO v_row FROM public.enqueue_scrape_request_once(
    gen_random_uuid(), p_team_id_master, p_team_name, p_provider_id,
    p_provider_team_id, p_game_date, p_request_type, p_priority);
  IF v_row.provider_id IS DISTINCT FROM p_provider_id
     OR v_row.provider_team_id IS DISTINCT FROM p_provider_team_id
     OR (p_request_type IS DISTINCT FROM 'missing_game' AND v_row.game_date > p_game_date)
     OR p_game_date NOT BETWEEN v_row.game_date - 90 AND v_row.game_date + 90 THEN
    RAISE EXCEPTION 'An active scrape uses a different source or date; request unchanged'
      USING ERRCODE = '23505';
  END IF;
  -- The operator repair script counts a returned UUID as successfully queued.
  -- A dead worker must be retired explicitly before it can be requeued.
  IF v_row.status = 'processing' AND v_row.processed_at < now() - interval '24 hours' THEN
    RAISE EXCEPTION 'Retire the stranded processing request before requeueing this team'
      USING ERRCODE = '55000';
  END IF;
  RETURN v_row.id;
END;
$$;
REVOKE EXECUTE ON FUNCTION public.enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint)
  TO service_role;

COMMENT ON FUNCTION public.enqueue_scrape_request(uuid, text, uuid, text, date, text, smallint) IS
  'Atomically reuse compatible pending or processing work without replacing its source or date. Conflicts raise 23505.';
NOTIFY pgrst, 'reload schema';
