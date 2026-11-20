-- Only the service role writes these tables, and row level security is off on each, so the grant alone
-- decides who may write.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON public.rankings_full, public.ranking_history, public.team_merge_map, public.team_social_profiles
    FROM anon, authenticated;

-- No migration creates these three, so their statements run only where the table exists.
DO $$
BEGIN
    IF to_regclass('public.team_momentum') IS NOT NULL THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.team_momentum FROM anon, authenticated;
    END IF;

    IF to_regclass('public.team_trajectory') IS NOT NULL THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.team_trajectory FROM anon, authenticated;
    END IF;

    IF to_regclass('public.game_history') IS NOT NULL THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.game_history FROM anon, authenticated;
    END IF;
END
$$;

-- These write as their owner, so their own grant decides who may call them. A new function is
-- executable by PUBLIC and, through pg_default_acl, by anon and authenticated directly, so all three
-- are revoked.
REVOKE EXECUTE ON FUNCTION public.backfill_total_game_stats() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.batch_backfill_null_scores(jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.batch_upsert_game_explainability(jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.batch_update_ml_overperformance(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.backfill_total_game_stats() TO service_role;
GRANT EXECUTE ON FUNCTION public.batch_backfill_null_scores(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.batch_upsert_game_explainability(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.batch_update_ml_overperformance(jsonb) TO service_role;

-- The signup form only adds a row; nothing on the site reads subscribers back.
DROP POLICY IF EXISTS "Allow authenticated reads" ON public.newsletter_subscribers;
