-- Let the weekly team cleanup's review page carry duplicate-team pairs: a card and an undo request may name
-- the merges stage, and a pair card records whether the owner chose to keep the other row of the pair.
--
-- Both stage CHECKs were declared inline, so Postgres named them <table>_stage_check. Dropping and re-adding
-- each in one ALTER keeps its table checked throughout, and a re-run finds the same state.

ALTER TABLE team_cleanup_cards
    DROP CONSTRAINT IF EXISTS team_cleanup_cards_stage_check,
    ADD CONSTRAINT team_cleanup_cards_stage_check CHECK (stage IN ('clubs', 'states', 'ages', 'merges')),
    -- True when the owner keeps the row the pair would retire; false on every single-team card.
    ADD COLUMN IF NOT EXISTS swap BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE team_cleanup_requests
    DROP CONSTRAINT IF EXISTS team_cleanup_requests_stage_check,
    ADD CONSTRAINT team_cleanup_requests_stage_check CHECK (stage IN ('clubs', 'states', 'ages', 'merges'));

-- No grant or policy change: RLS policies govern whole rows, and after the REVOKE ALL, anon and authenticated
-- hold no table privilege a new column could inherit.
