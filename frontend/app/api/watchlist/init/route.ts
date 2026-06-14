import { requirePremium } from '@/lib/api/requirePremium';
import { resolveDefaultWatchlist } from '@/lib/api/watchlist';
import { NextResponse } from 'next/server';

/**
 * POST /api/watchlist/init
 *
 * Initializes a user's default watchlist if one doesn't exist.
 * Creates a new "My Watchlist" if the user is premium and has no watchlist.
 *
 * Returns: { watchlist: Watchlist } or { error: string }
 */
export async function POST() {
  try {
    const auth = await requirePremium();
    if (auth.error) return auth.error;
    const { user, supabase } = auth;

    // Resolve the user's default watchlist (falls back to most-recent).
    const { watchlist: existingWatchlist, error: fetchError } = await resolveDefaultWatchlist(supabase, user.id);

    if (fetchError) {
      console.error('Error fetching watchlist:', fetchError);
      return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
    }

    // If watchlist exists, return it
    if (existingWatchlist) {
      return NextResponse.json({ watchlist: existingWatchlist });
    }

    // Create default watchlist
    const { data: newWatchlist, error: createError } = await supabase
      .from('watchlists')
      .insert({
        user_id: user.id,
        name: 'My Watchlist',
        is_default: true,
      })
      .select()
      .single();

    if (createError) {
      console.error('Error creating watchlist:', createError);
      return NextResponse.json({ error: 'Failed to create watchlist' }, { status: 500 });
    }

    return NextResponse.json({ watchlist: newWatchlist });
  } catch (error) {
    console.error('Watchlist init error:', error);
    return NextResponse.json({ error: 'Failed to initialize watchlist' }, { status: 500 });
  }
}
