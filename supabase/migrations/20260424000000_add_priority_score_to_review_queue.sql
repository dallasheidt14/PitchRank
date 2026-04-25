-- Add priority_score column to team_match_review_queue to preserve true
-- classifier confidence past the DECIMAL(3,2) CHECK (< 0.90) clamp applied
-- to confidence_score. The review UI should prefer priority_score for sort
-- order so reviewers see the most-confident candidates first, even though
-- all scraper-written rows share confidence_score = 0.89 (the largest
-- representable value that survives the 0.75 <= x < 0.90 CHECK).

ALTER TABLE team_match_review_queue
  ADD COLUMN IF NOT EXISTS priority_score DOUBLE PRECISION;

COMMENT ON COLUMN team_match_review_queue.priority_score IS
  'True classifier score preserved past the DECIMAL(3,2) confidence_score CHECK clamp. Review UI should prefer this for sort order.';

CREATE INDEX IF NOT EXISTS idx_match_review_priority_score
  ON team_match_review_queue(priority_score DESC NULLS LAST);
