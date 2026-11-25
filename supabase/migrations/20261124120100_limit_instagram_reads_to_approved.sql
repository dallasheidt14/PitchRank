-- The site shows approved Instagram handles alone, through team_instagram_handles, which runs as its owner,
-- and the admin review page reads the handles awaiting review with the service key. So the browser roles read
-- approved handles only, and nothing of team_instagram_review_queue, which lists those awaiting review.
SET LOCAL lock_timeout = '1s';

DROP POLICY IF EXISTS "team_social_profiles_public_read" ON public.team_social_profiles;
DROP POLICY IF EXISTS "team_social_profiles_approved_read" ON public.team_social_profiles;
CREATE POLICY "team_social_profiles_approved_read" ON public.team_social_profiles
    FOR SELECT USING (review_status IN ('auto_approved', 'confirmed'));

REVOKE ALL ON public.team_instagram_review_queue FROM anon, authenticated;
