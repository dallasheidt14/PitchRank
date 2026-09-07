-- Record which teams a signed-in subscriber actually opened.
--
-- Every scrape selector is fixed-N and behaviour-blind: yesterday-games, active-teams,
-- discovery and safety-net all pick teams from fixture dates and scrape recency. The one
-- interest-driven job, enqueue_user_interest_teams, reads standing signals only —
-- watchlists, report-card leads, and the one-off "find missing game" click.
--
-- A page view is the highest-volume interest signal there is and nothing recorded it.
-- Vercel's runtime logs are the only prior trace and cannot serve as a source: their
-- aggregate API caps grouped output at 25 rows per query and retains for days.
--
-- One row per view, not per team: the daily enqueue dedupes, and keeping the repeats
-- makes "how often" answerable later without changing the write path.

CREATE TABLE IF NOT EXISTS team_page_views (
    id BIGSERIAL PRIMARY KEY,

    team_id_master UUID NOT NULL,

    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The daily enqueue's only read: every view inside its window.
CREATE INDEX IF NOT EXISTS idx_team_page_views_viewed_at
ON team_page_views(viewed_at DESC);

-- Postgres does not index a referencing column for you, so without this the ON DELETE
-- CASCADE above sequential-scans a table that grows by one row per page view, forever,
-- every time an account is deleted.
CREATE INDEX IF NOT EXISTS idx_team_page_views_user_id
ON team_page_views(user_id);

COMMENT ON TABLE team_page_views IS
  'Append-only record of premium team-page views, written by /api/track-team-view and '
  'drained daily by scripts/enqueue_viewed_teams.py. team_id_master carries no foreign '
  'key, matching team_state_probe_log: the observation outlives whatever happens to the '
  'team row, and a merge would otherwise orphan history the enqueue job resolves anyway.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project,
-- which is how team_merge_audit and team_link_audit reached the security advisory.
--
-- No grant to authenticated, deliberately. An earlier revision let the browser insert its
-- own rows under a WITH CHECK (auth.uid() = user_id) policy. That makes attribution
-- unforgeable but leaves the route optional: any signed-in account — including a free one
-- — can take the public anon key and POST straight to /rest/v1/team_page_views, skipping
-- requirePremium and the rate limit, with team_id_master constrained by nothing. The route
-- writes with the service role instead, so the premium check is the only way in.

ALTER TABLE team_page_views ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_page_views_deny_all" ON team_page_views;
CREATE POLICY "team_page_views_deny_all" ON team_page_views
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_page_views_deny_all" ON team_page_views IS
  'Blocks all direct Data API access. The only writer is /api/track-team-view, which uses '
  'the service role after checking premium — a browser-reachable grant here would make '
  'that check bypassable.';

DROP POLICY IF EXISTS "team_page_views_service_role_all" ON team_page_views;
CREATE POLICY "team_page_views_service_role_all" ON team_page_views
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_page_views_service_role_all" ON team_page_views IS
  'Service role has full access: the route writes rows and the daily enqueue reads them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched.
REVOKE ALL ON public.team_page_views FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.team_page_views_id_seq FROM anon, authenticated;
