-- The browser roles read these tables and hold no write privilege on them, so each gets a read policy for
-- everyone alongside row level security, and every read that works today keeps working, rankings_view and the
-- invoker functions included. Row level security then also refuses INSERT, UPDATE and DELETE through a write
-- grant handed back by mistake; TRUNCATE ignores it, so there the revokes in 20261121000200 and 20261121000300
-- are the only guard.

-- Each table's ACCESS EXCLUSIVE lock is held until the file commits, and anon's 3s statement_timeout
-- counts the time a read waits behind it. So the busiest tables come last, and a lock that is not free
-- within a second fails the file rather than holding the earlier ones while it waits.
SET LOCAL lock_timeout = '1s';

-- No migration creates these four, so their statements run only where the table exists.
DO $$
BEGIN
    IF to_regclass('public.announcements') IS NOT NULL THEN
        ALTER TABLE public.announcements ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "announcements_public_read" ON public.announcements;
        CREATE POLICY "announcements_public_read" ON public.announcements FOR SELECT USING (true);
    END IF;

    IF to_regclass('public.team_momentum') IS NOT NULL THEN
        ALTER TABLE public.team_momentum ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "team_momentum_public_read" ON public.team_momentum;
        CREATE POLICY "team_momentum_public_read" ON public.team_momentum FOR SELECT USING (true);
    END IF;

    IF to_regclass('public.team_trajectory') IS NOT NULL THEN
        ALTER TABLE public.team_trajectory ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "team_trajectory_public_read" ON public.team_trajectory;
        CREATE POLICY "team_trajectory_public_read" ON public.team_trajectory FOR SELECT USING (true);
    END IF;

    IF to_regclass('public.game_history') IS NOT NULL THEN
        ALTER TABLE public.game_history ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS "game_history_public_read" ON public.game_history;
        CREATE POLICY "game_history_public_read" ON public.game_history FOR SELECT USING (true);
    END IF;
END
$$;

ALTER TABLE public.team_social_profiles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "team_social_profiles_public_read" ON public.team_social_profiles;
CREATE POLICY "team_social_profiles_public_read" ON public.team_social_profiles FOR SELECT USING (true);

ALTER TABLE public.team_merge_map ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "team_merge_map_public_read" ON public.team_merge_map;
CREATE POLICY "team_merge_map_public_read" ON public.team_merge_map FOR SELECT USING (true);

ALTER TABLE public.ranking_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "ranking_history_public_read" ON public.ranking_history;
CREATE POLICY "ranking_history_public_read" ON public.ranking_history FOR SELECT USING (true);

ALTER TABLE public.rankings_full ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "rankings_full_public_read" ON public.rankings_full;
CREATE POLICY "rankings_full_public_read" ON public.rankings_full FOR SELECT USING (true);
