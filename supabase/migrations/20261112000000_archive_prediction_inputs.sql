-- Append-only provenance index. Historical dates are never backfilled as availability.
CREATE TABLE IF NOT EXISTS public.prediction_input_archives (
  manifest_sha256 text PRIMARY KEY CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
  source_revision text NOT NULL CHECK (source_revision ~ '^[0-9a-f]{40}$'),
  manifest_path text NOT NULL UNIQUE,
  capture_started_at timestamptz NOT NULL,
  capture_finished_at timestamptz NOT NULL,
  object_count integer NOT NULL CHECK (object_count > 0),
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK (manifest_path = 'runs/' || manifest_sha256 || '/manifest.json'),
  CHECK (capture_started_at <= capture_finished_at),
  CHECK (capture_finished_at <= recorded_at)
);

ALTER TABLE public.prediction_input_archives ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.prediction_input_archives FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.prediction_input_archives TO service_role;

CREATE OR REPLACE FUNCTION public.guard_prediction_input_archive() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Prediction input archives are immutable';
  END IF;
  NEW.recorded_at := clock_timestamp();
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_prediction_input_archive() FROM PUBLIC, anon, authenticated, service_role;
DROP TRIGGER IF EXISTS guard_prediction_input_archive ON public.prediction_input_archives;
CREATE TRIGGER guard_prediction_input_archive
BEFORE INSERT OR UPDATE OR DELETE ON public.prediction_input_archives
FOR EACH ROW EXECUTE FUNCTION public.guard_prediction_input_archive();

-- Browser roles cannot access archive inputs or models.
INSERT INTO storage.buckets (id, name, public)
VALUES ('prediction-input-archives', 'prediction-input-archives', false)
ON CONFLICT (id) DO NOTHING;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM storage.buckets
             WHERE id = 'prediction-input-archives' AND public IS DISTINCT FROM false) THEN
    RAISE EXCEPTION 'Prediction input archive bucket must be private';
  END IF;
END; $$;

-- Restrictive policies also defeat unrelated permissive policies on shared storage.
DROP POLICY IF EXISTS prediction_input_objects_private ON storage.objects;
CREATE POLICY prediction_input_objects_private ON storage.objects AS RESTRICTIVE
FOR ALL TO anon, authenticated
USING (bucket_id <> 'prediction-input-archives')
WITH CHECK (bucket_id <> 'prediction-input-archives');
DROP POLICY IF EXISTS prediction_input_bucket_private ON storage.buckets;
CREATE POLICY prediction_input_bucket_private ON storage.buckets AS RESTRICTIVE
FOR ALL TO anon, authenticated
USING (id <> 'prediction-input-archives')
WITH CHECK (id <> 'prediction-input-archives');
