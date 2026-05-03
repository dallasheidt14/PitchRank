-- Add distinction column to teams table for squad-level identity within a cohort.
-- Composite squad distinguisher within (club_name, age_group, league, gender):
-- color, numeral, word, coach last name, direction. Lowercase tokens joined
-- with "|", ordered by category priority. NULL when team_name has no
-- distinguisher (single squad in cohort).
ALTER TABLE teams ADD COLUMN IF NOT EXISTS distinction TEXT;

COMMENT ON COLUMN teams.distinction IS
  'Composite squad distinguisher within (club, age, league, gender). '
  'Lowercase tokens joined with "|", ordered by category priority. '
  'NULL when team_name has no distinguisher (single squad in cohort).';

-- Composite index supports the canonical team-identity lookup
-- (club_name, state_code, age_group, league, gender, distinction).
-- state_code disambiguates clubs that share a literal name across states
-- (e.g., 'FC Stars' exists in MA, NH, IL, NJ, ME, NY, RI as distinct clubs).
CREATE INDEX IF NOT EXISTS idx_teams_distinction
  ON teams (club_name, state_code, age_group, league, gender, distinction);
