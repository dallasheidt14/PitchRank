import { requirePremium } from '@/lib/api/requirePremium';
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

    // Check if user already has a default watchlist
    let { data: existingWatchlist, error: fetchError } = await supabase
      .from('watchlists')
      .select('*')
      .eq('user_id', user.id)
      .eq('is_default', true)
      .single();

    if (fetchError && fetchError.code !== 'PGRST116') {
      // PGRST116 = no rows returned, which is expected if no watchlist exists
      console.error('Error fetching watchlist:', fetchError);
      return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
    }

    // If no default watchlist found, use most recent watchlist (fallback)
    // This prevents creating duplicate watchlists when is_default flag is missing
    if (!existingWatchlist && fetchError?.code === 'PGRST116') {
      console.log('[Watchlist Init] No default watchlist found, trying most recent');
      const { data: watchlists, error: listError } = await supabase
        .from('watchlists')
        .select('*')
        .eq('user_id', user.id)
        .order('created_at', { ascending: false })
        .limit(1);

      if (!listError && watchlists && watchlists.length > 0) {
        existingWatchlist = watchlists[0];
        console.log('[Watchlist Init] Using most recent watchlist as fallback:', existingWatchlist.id);
      }
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
