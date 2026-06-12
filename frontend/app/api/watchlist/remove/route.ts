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

    // Validate UUID — teamIdMaster is interpolated into the .or() filter below,
    // so reject anything that could carry PostgREST filter syntax
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(teamIdMaster)) {
      return NextResponse.json({ error: 'Invalid team ID format' }, { status: 400 });
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

    // The GET /api/watchlist response resolves deprecated team_id_master values
    // to canonical via team_merge_map, so the UI may post the canonical ID even
    // when the underlying watchlist_items row stores the deprecated ID (or vice
    // versa). Look up all related IDs and delete every matching row so Remove
    // works regardless of which side of the merge the stored row is on.
    const { data: mergeRows, error: mergeError } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id, canonical_team_id')
      .or(`deprecated_team_id.eq.${teamIdMaster},canonical_team_id.eq.${teamIdMaster}`);

    if (mergeError) {
      console.error('[Watchlist Remove] Error fetching merge map:', mergeError);
    }

    const idsToDelete = new Set<string>([teamIdMaster]);
    for (const row of (mergeRows || []) as { deprecated_team_id: string; canonical_team_id: string }[]) {
      if (row.deprecated_team_id) idsToDelete.add(row.deprecated_team_id);
      if (row.canonical_team_id) idsToDelete.add(row.canonical_team_id);
    }

    const { error: removeError } = await supabase
      .from('watchlist_items')
      .delete()
      .eq('watchlist_id', resolvedWatchlist.id)
      .in('team_id_master', Array.from(idsToDelete));

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
