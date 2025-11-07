-- Deprecate state_rank column in current_rankings table
-- state_rank is now derived dynamically via state_rankings view
-- This column is retained for backward compatibility only

COMMENT ON COLUMN current_rankings.state_rank IS 
'Deprecated — state_rank is now derived dynamically via state_rankings view. This column is retained for backward compatibility only.';

