-- Make get_national_rankings and get_state_rankings run as SECURITY DEFINER.
--
-- The previous migration (20260505000000) added an EXISTS subquery on
-- team_alias_map to compute has_modular11_alias. team_alias_map carries
-- a permissive RLS deny-all policy for anon/authenticated (see migration
-- 20240215000000_add_row_level_security.sql), so when the RPC was called
-- from the API route as the anon role the EXISTS lookup blew up at
-- execute time and the route returned 500 "Failed to fetch state rankings".
--
-- Switching the functions to SECURITY DEFINER makes them run as the
-- function owner (postgres), which sees through the RLS policy. This
-- doesn't expose any new data to the anon caller — the function still
-- returns only ranking rows; has_modular11_alias is just a boolean.
-- search_path is pinned to public + pg_temp to neutralize the standard
-- SECURITY DEFINER + search_path injection risk.

ALTER FUNCTION get_national_rankings(TEXT, TEXT, INT, INT)
  SECURITY DEFINER
  SET search_path = public, pg_temp;

ALTER FUNCTION get_state_rankings(TEXT, TEXT, TEXT, INT, INT)
  SECURITY DEFINER
  SET search_path = public, pg_temp;
