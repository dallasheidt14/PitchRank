import { describe, it, expect, vi } from 'vitest';
import { resolveDefaultWatchlist } from '../watchlist';

type QueryResult = { data: unknown; error: unknown };

// supabase-like stub: chainable methods return the builder; the primary lookup
// terminates on `.single()`, the fallback on `.limit()`.
function makeSupabase(primary: QueryResult, fallback: QueryResult = { data: [], error: null }) {
  const from = vi.fn(() => {
    const builder: Record<string, unknown> = {};
    for (const m of ['select', 'eq', 'order']) builder[m] = vi.fn(() => builder);
    builder.single = vi.fn(() => Promise.resolve(primary));
    builder.limit = vi.fn(() => Promise.resolve(fallback));
    return builder;
  });
  return { from } as unknown as Parameters<typeof resolveDefaultWatchlist>[0];
}

describe('resolveDefaultWatchlist', () => {
  it('returns the default watchlist when present (no fallback)', async () => {
    const supabase = makeSupabase({ data: { id: 'wl-1' }, error: null });
    const { watchlist, error } = await resolveDefaultWatchlist(supabase, 'user-1');
    expect(watchlist).toEqual({ id: 'wl-1' });
    expect(error).toBeNull();
  });

  it('surfaces a non-PGRST116 primary error for the caller to 500', async () => {
    const dbError = { code: '42501', message: 'permission denied' };
    const supabase = makeSupabase({ data: null, error: dbError });
    const { watchlist, error } = await resolveDefaultWatchlist(supabase, 'user-1');
    expect(watchlist).toBeNull();
    expect(error).toEqual(dbError);
  });

  it('falls back to the most-recent watchlist when no default row exists', async () => {
    const supabase = makeSupabase({ data: null, error: { code: 'PGRST116' } }, { data: [{ id: 'wl-2' }], error: null });
    const { watchlist, error } = await resolveDefaultWatchlist(supabase, 'user-1');
    expect(watchlist).toEqual({ id: 'wl-2' });
    expect(error).toBeNull();
  });

  it('returns null when the user has no watchlists at all', async () => {
    const supabase = makeSupabase({ data: null, error: { code: 'PGRST116' } }, { data: [], error: null });
    const { watchlist, error } = await resolveDefaultWatchlist(supabase, 'user-1');
    expect(watchlist).toBeNull();
    expect(error).toBeNull();
  });
});
