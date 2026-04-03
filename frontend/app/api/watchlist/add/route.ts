import { requirePremium } from '@/lib/api/requirePremium';
import { NextResponse } from 'next/server';

/**
 * POST /api/watchlist/add
 *
 * Adds a team to the user's default watchlist.
 * Creates the watchlist if it doesn't exist.
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

    // Validate team exists
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, team_name')
      .eq('team_id_master', teamIdMaster)
      .single();

    if (teamError || !team) {
      return NextResponse.json({ error: 'Team not found' }, { status: 404 });
    }

    // Get or create default watchlist
    let watchlistId: string;

    const fetchResult = await supabase
      .from('watchlists')
      .select('id')
      .eq('user_id', user.id)
      .eq('is_default', true)
      .single();

    const fetchError = fetchResult.error;
    let existingWatchlist = fetchResult.data;

    if (fetchError && fetchError.code !== 'PGRST116') {
      console.error('[Watchlist Add] Error fetching watchlist:', fetchError);
      return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
    }

    // If no default watchlist found, use most recent watchlist (fallback)
    // This prevents creating duplicate watchlists when is_default flag is missing
    if (!existingWatchlist && fetchError?.code === 'PGRST116') {
      const { data: watchlists, error: listError } = await supabase
        .from('watchlists')
        .select('id')
        .eq('user_id', user.id)
        .order('created_at', { ascending: false })
        .limit(1);

      if (!listError && watchlists && watchlists.length > 0) {
        existingWatchlist = watchlists[0];
      }
    }

    if (existingWatchlist) {
      watchlistId = existingWatchlist.id;
    } else {
      // Create default watchlist
      const { data: newWatchlist, error: createError } = await supabase
        .from('watchlists')
        .insert({
          user_id: user.id,
          name: 'My Watchlist',
          is_default: true,
        })
        .select('id')
        .single();

      if (createError || !newWatchlist) {
        console.error('[Watchlist Add] Error creating watchlist:', createError);
        return NextResponse.json({ error: 'Failed to create watchlist' }, { status: 500 });
      }

      watchlistId = newWatchlist.id;
    }

    // Add team to watchlist (upsert to handle duplicates gracefully)
    const { error: addError } = await supabase
      .from('watchlist_items')
      .upsert(
        {
          watchlist_id: watchlistId,
          team_id_master: teamIdMaster,
        },
        {
          onConflict: 'watchlist_id,team_id_master',
          ignoreDuplicates: false, // Changed to false to see if item was actually inserted
        }
      )
      .select();

    if (addError) {
      console.error('[Watchlist Add] Error adding team to watchlist:', addError);
      return NextResponse.json({ error: 'Failed to add team to watchlist' }, { status: 500 });
    }

    return NextResponse.json({
      success: true,
      message: `Added ${team.team_name} to watchlist`,
      teamIdMaster,
      watchlistId,
    });
  } catch (error) {
    console.error('Watchlist add error:', error);
    return NextResponse.json({ error: 'Failed to add team to watchlist' }, { status: 500 });
  }
}
