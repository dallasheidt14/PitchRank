-- Extend outreach_targets for the list-build pipeline: enrichment input,
-- personalization tokens for templating, and a dedupe safety net on contact.

ALTER TABLE outreach_targets
  ADD COLUMN IF NOT EXISTS source_domain TEXT;

ALTER TABLE outreach_targets
  ADD COLUMN IF NOT EXISTS personalization JSONB NOT NULL DEFAULT '{}'::jsonb;

-- DB safety net guaranteeing no two targets share an email. Primary dedupe is
-- Python-side on (segment, source_domain, org); this partial unique index backstops it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_outreach_targets_contact
  ON outreach_targets (lower(contact)) WHERE contact IS NOT NULL;

COMMENT ON COLUMN outreach_targets.status IS
    'Pipeline stage (no CHECK by convention). List build: queued -> verified | held (held = invalid/catch-all/no-email/gate-failed; terminal for the automated pipeline). After verified, outreach follows: sent -> replied -> linked | declined. The verified stage means the contact passed the address-verification gate; the verifier result itself is in verification_status.';

COMMENT ON COLUMN outreach_targets.source_domain IS
    'The org''s web domain: Hunter enrichment input and part of the Python-side dedupe key (segment, source_domain, org).';

COMMENT ON COLUMN outreach_targets.personalization IS
    'Scraped tokens for outreach templating (e.g. state, league_mix, a team/standing signal) plus enrichment metadata such as enrich_confidence. Defaults to {}.';
