import { checkRateLimit } from '@/lib/api/rateLimit';
import { requirePremium } from '@/lib/api/requirePremium';
import { resolveDefaultWatchlist } from '@/lib/api/watchlist';
import { createServiceSupabase } from '@/lib/supabase/service';
import { isValidUuid } from '@/lib/validation';
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

    // Validate UUID, as /api/watchlist/remove does: the value reaches a PostgREST
    // .eq() filter and then an RPC argument, so reject anything shaped otherwise.
    if (!isValidUuid(teamIdMaster)) {
      return NextResponse.json({ error: 'Invalid team ID format' }, { status: 400 });
    }

    // Validate team exists
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, provider_id, provider_team_id')
      .eq('team_id_master', teamIdMaster)
      .single();

    if (teamError || !team) {
      return NextResponse.json({ error: 'Team not found' }, { status: 404 });
    }

    // Get or create default watchlist
    let watchlistId: string;

    const { watchlist: existingWatchlist, error: fetchError } = await resolveDefaultWatchlist<{ id: string }>(
      supabase,
      user.id,
      'id'
    );

    if (fetchError) {
      console.error('[Watchlist Add] Error fetching watchlist:', fetchError);
      return NextResponse.json({ error: 'Failed to fetch watchlist' }, { status: 500 });
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

    await enqueueWatchlistScrape(user.id, team);

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

/**
 * Queue a scrape for a team the moment a user watchlists it.
 *
 * A watchlist entry is the strongest interest signal the site records, and until
 * now nothing acted on it at click time: the only reader is the weekly
 * enqueue_user_interest_teams.py pass, so a team saved on Monday waited up to six
 * days for its first refresh. The daily viewed-teams job does not close that gap
 * either — /api/track-team-view only records a view for a signed-in subscriber, so
 * a trial user's localStorage watchlist, migrated to Supabase by
 * useWatchlistMigration on their first premium visit, carries teams that were
 * starred while they were free and therefore have no view row at all.
 *
 * Priority 1, matching the other user-driven producers (missing_game, new_team).
 * The RPC is an idempotent UPSERT keyed on one pending row per team and promotes
 * priority via LEAST, so re-adding a team costs nothing. A team already holding a
 * pending priority-1 row is left alone — see the comment on the lookup below.
 *
 * Never fatal: the team is already on the watchlist by the time this runs, and a
 * missed enqueue is picked up by the weekly interest pass.
 */
async function enqueueWatchlistScrape(
  userId: string,
  team: {
    team_id_master: string;
    team_name: string | null;
    provider_id: string | null;
    provider_team_id: string | null;
  }
): Promise<void> {
  // A team with no provider of its own is unservable: process_missing_games
  // validates the queue row before it reaches the GotSport-alias fallback, so
  // enqueueing one buys a failed queue item. Same rule as enqueue_viewed_teams.py.
  if (!team.provider_id) return;

  // Every row lands at priority 1, ahead of the automated priority 2-4 producers
  // that share the same 40-per-15-minute drain. The RPC keeps one pending row per
  // team, so this caps distinct teams per hour rather than rows. Set well above a
  // real watchlist migration (tens of teams) and far below a scripted sweep. The
  // watchlist add itself is never rejected on this count — only the scrape is
  // skipped, and the weekly interest pass still collects the team.
  if (!checkRateLimit(`watchlist-enqueue:${userId}`, 100, 3_600_000)) {
    console.warn('[Watchlist Add] Enqueue rate limit hit, skipping scrape request');
    return;
  }

  try {
    const supabase = createServiceSupabase();

    // Leave an existing pending priority-1 row alone. The RPC's UPDATE branch sets
    // game_date = COALESCE(p_game_date, game_date), and we always pass a date, so
    // enqueueing over a user's own "find missing game" request would move that
    // row's +/-90 day window off the date they asked about and onto today.
    //
    // Priority 1 is the proxy for "a user chose this date", exactly as
    // scripts/enqueue_helpers.teams_with_pending_user_request reasons: the UPDATE
    // branch does not touch request_type, so a row's type cannot be trusted to say
    // who wrote it. The other priority-1 producers all anchor on today, so skipping
    // them costs nothing beyond a re-anchor the team does not need — it is already
    // at the front of the queue.
    const { data: pending, error: pendingError } = await supabase
      .from('scrape_requests')
      .select('id')
      .eq('team_id_master', team.team_id_master)
      .eq('status', 'pending')
      .eq('priority', 1)
      .limit(1);

    // A failed lookup is not a licence to overwrite: we cannot tell whether a
    // user's row is there, so leave the queue as it is.
    if (pendingError) {
      console.error('[Watchlist Add] Pending-request lookup failed, skipping enqueue:', pendingError);
      return;
    }
    if (pending && pending.length > 0) return;

    const { error } = await supabase.rpc('enqueue_scrape_request', {
      p_team_id_master: team.team_id_master,
      p_team_name: team.team_name,
      p_provider_id: team.provider_id,
      p_provider_team_id: team.provider_team_id,
      // scrape_requests.game_date is NOT NULL and the processor scrapes a +/-90 day
      // window around it, so today's date covers the season either side of the save.
      p_game_date: new Date().toISOString().slice(0, 10),
      p_request_type: 'watchlist_add',
      p_priority: 1,
    });
    if (error) {
      console.error('[Watchlist Add] Enqueue failed (non-fatal):', error);
    }
  } catch (enqueueException) {
    console.error('[Watchlist Add] Enqueue threw (non-fatal):', enqueueException);
  }
}
