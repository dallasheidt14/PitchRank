-- Create table for tracking outreach targets across the authority/backlink program
-- One row per target contact, carrying verification state and a send-lifecycle status

CREATE TABLE IF NOT EXISTS outreach_targets (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  segment TEXT NOT NULL,
  org TEXT,
  contact TEXT,
  verification_status TEXT DEFAULT 'unverified',
  status TEXT DEFAULT 'queued',
  link_url TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hot partial index on the queued backlog + segment filtering
CREATE INDEX IF NOT EXISTS idx_outreach_targets_status ON outreach_targets(status) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_outreach_targets_segment ON outreach_targets(segment);

-- Keep updated_at current on every row update
CREATE OR REPLACE FUNCTION update_outreach_targets_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = '';

DROP TRIGGER IF EXISTS update_outreach_targets_updated_at
    ON outreach_targets;

CREATE TRIGGER update_outreach_targets_updated_at
    BEFORE UPDATE ON outreach_targets
    FOR EACH ROW EXECUTE FUNCTION update_outreach_targets_updated_at();

-- Rows carry contact PII and are written/read only by server-side jobs (service role).
-- Enable RLS and grant no anon/authenticated access so the Data API never exposes contacts.
ALTER TABLE outreach_targets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access" ON outreach_targets
  FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE outreach_targets IS
    'Outreach funnel tracking for the backlink/AI-citation authority program: one row per target contact, with verification and send lifecycle.';

COMMENT ON COLUMN outreach_targets.status IS
    'Pipeline stage (no CHECK by convention): queued -> verified -> sent -> replied -> linked | declined. The verified stage means the contact passed the address-verification gate; the verifier result itself is in verification_status.';
