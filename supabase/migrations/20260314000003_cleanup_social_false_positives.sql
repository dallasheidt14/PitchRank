-- Migration: Cleanup Phase 1 Instagram false positives
-- Strategy:
--   1. Preview single-token club names that were auto_approved (run SELECT first to verify)
--   2. Downgrade single-token club handles to needs_review (conservative, not outright reject)
--   3. Reject a small list of known-bad handles

-- ─── STEP 1: Preview (run this SELECT first to sanity-check scope) ───────────
-- SELECT
--   regexp_replace(query_used, '^[^"]*"([^"]*)".*$', '\1') AS club_name,
--   handle,
--   confidence_score,
--   review_status,
--   COUNT(DISTINCT team_id) AS team_count
-- FROM team_social_profiles
-- WHERE platform = 'instagram'
--   AND profile_level = 'club'
--   AND review_status = 'auto_approved'
--   AND regexp_replace(query_used, '^[^"]*"([^"]*)".*$', '\1') NOT LIKE '% %'
-- GROUP BY club_name, handle, confidence_score, review_status
-- ORDER BY confidence_score DESC, team_count DESC;


-- ─── STEP 2: Downgrade single-token club auto_approved → needs_review ────────
-- Single-word club names (e.g. "Alba", "Ajax", "United") can trivially score 1.0
-- on an unrelated celebrity or brand account. Force human review for all of them.
UPDATE team_social_profiles
SET
  review_status = 'needs_review',
  last_checked_at = now()
WHERE platform   = 'instagram'
  AND profile_level = 'club'
  AND review_status = 'auto_approved'
  AND regexp_replace(query_used, '^[^"]*"([^"]*)".*$', '\1') NOT LIKE '% %';


-- ─── STEP 3: Reject known bad handles ────────────────────────────────────────
-- These were confirmed false positives during the Phase 1 run.
-- Extend this list if you spot more via the review queue.
UPDATE team_social_profiles
SET
  review_status = 'rejected',
  last_checked_at = now()
WHERE platform   = 'instagram'
  AND profile_level = 'club'
  AND handle IN (
    'jessicaalba',
    'popular'
    -- add more here as you find them in the review queue
  );


-- ─── VERIFY ──────────────────────────────────────────────────────────────────
SELECT
  review_status,
  COUNT(*)          AS records,
  COUNT(DISTINCT team_id) AS teams
FROM team_social_profiles
WHERE platform = 'instagram'
  AND profile_level = 'club'
GROUP BY review_status
ORDER BY records DESC;
