-- Teams the weekly rankings run leaves out, along with every game they played.
--
-- fetch_games_for_rankings (src/rankings/data_adapter.py) drops a game when either side is
-- listed here, so a listed team is never ranked and never shapes an opponent's rating.
-- scripts/exclude_english_teams.py writes the rows from a snapshot a person has reviewed.
--
-- games.is_excluded cannot do this job: it hides games already stored, and a listed team's
-- new fixtures keep arriving with every scrape.

CREATE TABLE IF NOT EXISTS team_ranking_exclusions (
    team_id_master UUID PRIMARY KEY,

    reason TEXT NOT NULL,

    evidence JSONB,

    excluded_by TEXT NOT NULL,

    excluded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE team_ranking_exclusions IS
  'Teams kept out of the rankings, read by fetch_games_for_rankings on every run. '
  'team_id_master carries no foreign key, matching team_state_probe_log. '
  'Deleting a row restores the team on the next ranking run.';

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
--
-- pg_default_acl grants arwdDxtm to anon on every new public relation in this project, so
-- without these a browser could add or remove teams from the rankings.

ALTER TABLE team_ranking_exclusions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "team_ranking_exclusions_deny_all" ON team_ranking_exclusions;
CREATE POLICY "team_ranking_exclusions_deny_all" ON team_ranking_exclusions
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);

COMMENT ON POLICY "team_ranking_exclusions_deny_all" ON team_ranking_exclusions IS
  'Blocks all direct Data API access. Only the service role reads or writes the list.';

DROP POLICY IF EXISTS "team_ranking_exclusions_service_role_all" ON team_ranking_exclusions;
CREATE POLICY "team_ranking_exclusions_service_role_all" ON team_ranking_exclusions
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

COMMENT ON POLICY "team_ranking_exclusions_service_role_all" ON team_ranking_exclusions IS
  'Service role has full access: the operator script writes rows and the ranking run reads them.';

-- RLS governs SELECT, INSERT, UPDATE and DELETE and nothing else, so the deny-all policy
-- leaves the TRUNCATE in that default grant untouched. The uuid key has no sequence to revoke.
REVOKE ALL ON public.team_ranking_exclusions FROM anon, authenticated;
