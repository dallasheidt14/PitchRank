import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { requireAdmin } from '@/lib/supabase/admin';

/**
 * Unlink an incorrectly linked opponent from a game
 * Removes the team_master_id from the game and optionally removes the alias mapping
 */
export async function POST(request: NextRequest) {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;

    if (!serviceKey || !supabaseUrl) {
      console.error('[unlink-opponent] Missing environment variables');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    let requestBody;
    try {
      requestBody = await request.json();
    } catch {
      return NextResponse.json(
        { error: 'Invalid request body' },
        { status: 400 }
      );
    }

    const {
      gameId,
      opponentProviderId,
      teamIdMaster,
      unlinkAllGames = true,
    } = requestBody;

    if (!gameId || !opponentProviderId || !teamIdMaster) {
      return NextResponse.json(
        { error: 'Missing required fields: gameId, opponentProviderId, and teamIdMaster' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    // 1. Get the game to determine which side the opponent is on
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('id, provider_id, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id')
      .eq('id', gameId)
      .single();

    if (gameError || !game) {
      console.error('[unlink-opponent] Game not found:', gameError);
      return NextResponse.json(
        { error: 'Game not found' },
        { status: 404 }
      );
    }

    const providerTeamIdStr = String(opponentProviderId);
    const isOpponentHome = String(game.home_provider_id) === providerTeamIdStr;
    const isOpponentAway = String(game.away_provider_id) === providerTeamIdStr;

    if (!isOpponentHome && !isOpponentAway) {
      return NextResponse.json(
        { error: 'Provider ID does not match any team in this game' },
        { status: 400 }
      );
    }

    // Verify the team is actually linked to the expected team
    const currentMasterId = isOpponentHome ? game.home_team_master_id : game.away_team_master_id;
    if (currentMasterId !== teamIdMaster) {
      return NextResponse.json(
        {
          error: 'Team mismatch',
          details: `Expected team ${teamIdMaster} but found ${currentMasterId}. The game may have already been updated.`
        },
        { status: 400 }
      );
    }

    let gamesUpdated = 0;

    // 2. Unlink the specific game using RPC function
    const { error: rpcError } = await supabase.rpc('unlink_game_team', {
      p_game_id: gameId,
      p_team_id_master: teamIdMaster,
      p_is_home_team: isOpponentHome,
    });

    let specificUpdateError = rpcError;

    // If RPC function doesn't exist, fall back to direct update
    if (rpcError?.code === '42883' || rpcError?.message?.includes('does not exist')) {
      console.log('[unlink-opponent] RPC function not found, trying direct update');
      const updateField = isOpponentHome
        ? { home_team_master_id: null }
        : { away_team_master_id: null };
      const { error: directError } = await supabase
        .from('games')
        .update(updateField)
        .eq('id', gameId);
      specificUpdateError = directError;
    }

    if (specificUpdateError) {
      console.error('[unlink-opponent] Failed to unlink game:', specificUpdateError);
      return NextResponse.json(
        { error: `Failed to unlink game: ${specificUpdateError.message}` },
        { status: 500 }
      );
    }

    gamesUpdated = 1;

    // 3. Optionally unlink ALL games with this provider_team_id linked to this team
    if (unlinkAllGames) {
      // Unlink games where opponent is HOME team
      const { data: homeUnlinked } = await supabase
        .from('games')
        .update({ home_team_master_id: null })
        .eq('home_provider_id', providerTeamIdStr)
        .eq('home_team_master_id', teamIdMaster)
        .eq('provider_id', game.provider_id)
        .neq('id', gameId)
        .select('id');

      // Unlink games where opponent is AWAY team
      const { data: awayUnlinked } = await supabase
        .from('games')
        .update({ away_team_master_id: null })
        .eq('away_provider_id', providerTeamIdStr)
        .eq('away_team_master_id', teamIdMaster)
        .eq('provider_id', game.provider_id)
        .neq('id', gameId)
        .select('id');

      gamesUpdated += (homeUnlinked?.length || 0) + (awayUnlinked?.length || 0);
    }

    // 4. Remove the alias mapping
    const { error: aliasDeleteError } = await supabase
      .from('team_alias_map')
      .delete()
      .eq('provider_id', game.provider_id)
      .eq('provider_team_id', providerTeamIdStr)
      .eq('team_id_master', teamIdMaster);

    if (aliasDeleteError) {
      console.error('[unlink-opponent] Failed to delete alias (non-fatal):', aliasDeleteError);
    }

    // 5. Create audit log entry
    const { error: auditError } = await supabase
      .from('team_link_audit')
      .insert({
        provider_team_id: providerTeamIdStr,
        team_id_master: teamIdMaster,
        provider_id: game.provider_id,
        games_updated: gamesUpdated,
        linked_by: 'frontend_user',
        reverted_at: new Date().toISOString(),
        reverted_by: 'frontend_user',
        notes: `Unlinked ${gamesUpdated} game(s). Alias removed: ${!aliasDeleteError}`,
      });

    if (auditError) {
      console.error('[unlink-opponent] Failed to create audit log:', auditError);
    }

    return NextResponse.json({
      success: true,
      gamesUpdated,
      aliasRemoved: !aliasDeleteError,
      message: `Successfully unlinked ${gamesUpdated} game(s)`,
    });
  } catch (error) {
    console.error('[unlink-opponent] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
