-- Add predictive fields to rankings_full table
-- These fields are computed by Layer 13 ML enhancer
-- exp_margin and exp_win_rate should ALWAYS exist
-- exp_goals_for and exp_goals_against are OPTIONAL (may be computed in view if not stored)

-- Add predictive fields if they don't exist
DO $$ 
BEGIN
    -- exp_margin: Expected margin of victory (always computed by Layer 13)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rankings_full' AND column_name = 'exp_margin'
    ) THEN
        ALTER TABLE rankings_full ADD COLUMN exp_margin FLOAT;
    END IF;

    -- exp_win_rate: Expected win probability (always computed by Layer 13 via logistic mapping)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rankings_full' AND column_name = 'exp_win_rate'
    ) THEN
        ALTER TABLE rankings_full ADD COLUMN exp_win_rate FLOAT;
    END IF;

    -- exp_goals_for: Expected goals for (optional - may be computed in view)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rankings_full' AND column_name = 'exp_goals_for'
    ) THEN
        ALTER TABLE rankings_full ADD COLUMN exp_goals_for FLOAT;
    END IF;

    -- exp_goals_against: Expected goals against (optional - may be computed in view)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'rankings_full' AND column_name = 'exp_goals_against'
    ) THEN
        ALTER TABLE rankings_full ADD COLUMN exp_goals_against FLOAT;
    END IF;
END $$;

COMMENT ON COLUMN rankings_full.exp_margin IS 'Expected margin of victory (goal units). Computed by Layer 13 ML enhancer. Positive = team expected to win, negative = team expected to lose.';
COMMENT ON COLUMN rankings_full.exp_win_rate IS 'Expected win probability (0.0-1.0). Computed by Layer 13 via logistic/sigmoid mapping of exp_margin.';
COMMENT ON COLUMN rankings_full.exp_goals_for IS 'Expected goals for (optional). May be computed in view if not stored.';
COMMENT ON COLUMN rankings_full.exp_goals_against IS 'Expected goals against (optional). May be computed in view if not stored.';

