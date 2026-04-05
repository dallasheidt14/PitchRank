-- Add Glicko-native fields to rankings_full so compare/prediction can use
-- the same rating and uncertainty data as the production ranking engine.

ALTER TABLE rankings_full
    ADD COLUMN IF NOT EXISTS glicko_rating FLOAT,
    ADD COLUMN IF NOT EXISTS glicko_rd FLOAT,
    ADD COLUMN IF NOT EXISTS glicko_volatility FLOAT;

COMMENT ON COLUMN rankings_full.glicko_rating IS 'Underlying Glicko-2 rating (mu) on the 1500-centered public scale.';
COMMENT ON COLUMN rankings_full.glicko_rd IS 'Underlying Glicko-2 rating deviation (RD/sigma). Lower means the rating is more certain.';
COMMENT ON COLUMN rankings_full.glicko_volatility IS 'Underlying Glicko-2 volatility parameter.';
