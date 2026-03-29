import { requirePremium } from '@/lib/api/requirePremium';
import { NextResponse } from 'next/server';

/**
 * POST /api/watchlist/remove
 *
 * Removes a team from the user's default watchlist.
 *
 * Body: { teamIdMaster: string }
 */
export async function POST(req: Request) {
  try {
    const auth = await requirePremium();
    if (auth.error) return auth.error;
    const { user, supabase } = auth;

    // Parse request body
    const body = await req.json();
    const { teamIdMaster } = body;

    if (!teamIdMaster || typeof teamIdMaster !== 'string') {
      return NextResponse.json({ error: 'teamIdMaster is required' }, { status: 400 });
    }

    // Get user's default watchlist
    const { data: watchlist, error: watchlistError } = await supabase
      .from('watchlists')
      .select('id')
      .eq('user_id', user.id)
      .eq('is_default', true)
      .single();

    if (watchlistError && watchlistError.code !== 'PGRST116') {
      console.error('Error fetching watchlist:', watchlistError);
      return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
    }

    // Fallback: if no default watchlist found, try to find the most recent one
    let resolvedWatchlist = watchlist;
    if (!resolvedWatchlist) {
      const { data: fallbackWatchlist } = await supabase
        .from('watchlists')
        .select('id')
        .eq('user_id', user.id)
        .order('created_at', { ascending: false })
        .limit(1)
        .single();

      resolvedWatchlist = fallbackWatchlist;
    }

    if (!resolvedWatchlist) {
      // No watchlist exists at all, nothing to remove
      return NextResponse.json({
        success: true,
        message: 'No watchlist exists',
      });
    }

    // Remove team from watchlist
    const { error: removeError } = await supabase
      .from('watchlist_items')
      .delete()
      .eq('watchlist_id', resolvedWatchlist.id)
      .eq('team_id_master', teamIdMaster);

    if (removeError) {
      console.error('Error removing team from watchlist:', removeError);
      return NextResponse.json({ error: 'Failed to remove team from watchlist' }, { status: 500 });
    }

    return NextResponse.json({
      success: true,
      message: 'Team removed from watchlist',
      teamIdMaster,
    });
  } catch (error) {
    console.error('Watchlist remove error:', error);
    return NextResponse.json({ error: 'Failed to remove team from watchlist' }, { status: 500 });
  }
}
