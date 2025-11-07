-- Deprecate calculate_state_rankings() function
-- State rankings are now derived directly by filtering national_rankings by state_code
-- Use the state_rankings SQL view instead

COMMENT ON FUNCTION calculate_state_rankings() IS 
'DEPRECATED: State rankings are now derived directly by filtering national_rankings by state_code. Use the state_rankings SQL view instead. This function is retained for backward compatibility only.';

