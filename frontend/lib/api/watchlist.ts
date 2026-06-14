import type { PostgrestError, SupabaseClient } from '@supabase/supabase-js';

export interface WatchlistRow {
  id: string;
  name: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Resolve a user's default watchlist: the `is_default` row if present, otherwise
 * the most-recently-created watchlist (covers rows where the flag was never set),
 * otherwise null.
 *
 * A non-"no rows" (PGRST116) error on the primary lookup is returned for the
 * caller to surface as a 500; a failed *fallback* lookup yields null rather than
 * an error (callers that need a watchlist create one).
 *
 * Consolidates a resolution block that had drifted across the watchlist
 * GET/add/init/remove routes.
 */
export async function resolveDefaultWatchlist<T extends { id: string } = WatchlistRow>(
  supabase: SupabaseClient,
  userId: string,
  columns = '*'
): Promise<{ watchlist: T | null; error: PostgrestError | null }> {
  const primary = await supabase
    .from('watchlists')
    .select(columns)
    .eq('user_id', userId)
    .eq('is_default', true)
    .single();

  if (primary.error && primary.error.code !== 'PGRST116') {
    return { watchlist: null, error: primary.error };
  }
  if (primary.data) {
    return { watchlist: primary.data as unknown as T, error: null };
  }

  const fallback = await supabase
    .from('watchlists')
    .select(columns)
    .eq('user_id', userId)
    .order('created_at', { ascending: false })
    .limit(1);

  return { watchlist: (fallback.data?.[0] as unknown as T) ?? null, error: null };
}
