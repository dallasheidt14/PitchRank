-- Only the service role writes announcements. No migration in this folder creates the table, so this
-- runs only where it exists.
DO $$
BEGIN
    IF to_regclass('public.announcements') IS NOT NULL THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.announcements FROM anon, authenticated;
    END IF;
END
$$;
