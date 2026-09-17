-- MatchBalance inquiries from /matchbalance. The owner alert email is not the record: a
-- filtered, bounced or deleted message would lose the lead, so this table is the source
-- of truth for what is waiting on a reply.

CREATE TABLE IF NOT EXISTS public.matchbalance_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    name TEXT NOT NULL,
    email TEXT NOT NULL,
    organization TEXT NOT NULL,
    tournament_name TEXT NOT NULL,
    event_dates TEXT NOT NULL,
    team_count INTEGER,
    bracket_review_date DATE,
    event_url TEXT,
    request_type TEXT NOT NULL,
    notes TEXT,

    source_ip_masked TEXT,
    status TEXT NOT NULL DEFAULT 'new'
);

-- Serves the Leads page's newest-first list and its last-seven-days count.
CREATE INDEX IF NOT EXISTS matchbalance_leads_created_at_idx
ON public.matchbalance_leads (created_at DESC);

-- Keep updated_at current on every row update
CREATE OR REPLACE FUNCTION update_matchbalance_leads_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = '';

DROP TRIGGER IF EXISTS update_matchbalance_leads_updated_at
    ON public.matchbalance_leads;

CREATE TRIGGER update_matchbalance_leads_updated_at
    BEFORE UPDATE ON public.matchbalance_leads
    FOR EACH ROW EXECUTE FUNCTION update_matchbalance_leads_updated_at();

COMMENT ON TABLE public.matchbalance_leads IS
  'Inquiries from tournament directors on /matchbalance. Written only by '
  '/api/matchbalance-inquiry through the service role, and read by the admin Leads page. '
  'Rows carry contact details, so no browser role can reach them.';

COMMENT ON COLUMN public.matchbalance_leads.request_type IS
  'What the director asked for (no CHECK by convention): sample | quote.';

COMMENT ON COLUMN public.matchbalance_leads.status IS
  'Pipeline stage (no CHECK by convention): new -> contacted -> sample_sent -> quoted -> won | lost.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project,
-- which is how team_merge_audit and team_link_audit reached the security advisory.
--
-- No browser role gets access: the public inquiry route's spam guards run before its
-- service-role insert, and a Data API grant would let anyone with the anon key skip them
-- or read every director's contact details.

ALTER TABLE public.matchbalance_leads ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "matchbalance_leads_deny_all" ON public.matchbalance_leads;
CREATE POLICY "matchbalance_leads_deny_all" ON public.matchbalance_leads
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "matchbalance_leads_deny_all" ON public.matchbalance_leads IS
  'Blocks all direct Data API access. The only writer is /api/matchbalance-inquiry, which '
  'uses the service role after its spam guards — a browser-reachable grant here would make '
  'those guards optional and expose director contact details.';

DROP POLICY IF EXISTS "matchbalance_leads_service_role_all" ON public.matchbalance_leads;
CREATE POLICY "matchbalance_leads_service_role_all" ON public.matchbalance_leads
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "matchbalance_leads_service_role_all" ON public.matchbalance_leads IS
  'Service role has full access: the inquiry route writes rows and the Leads page reads them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched. The uuid primary key has no
-- sequence, so there is no sequence grant to revoke.
REVOKE ALL ON public.matchbalance_leads FROM anon, authenticated;
