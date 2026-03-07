import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * Link unknown opponent to a team
 * Creates alias mapping and optionally backfills all affected games
 */
export async function POST(request: NextRequest) {
  try {
    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;

    if (!serviceKey || !supabaseUrl) {
      console.error('[link-opponent] Missing environment variables');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    // Parse request body
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
      applyToAllGames = true,
    } = requestBody;

    if (!gameId || !opponentProviderId || !teamIdMaster) {
      return NextResponse.json(
        { error: 'Missing required fields: gameId, opponentProviderId, and teamIdMaster' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    // 1. Validate that the team exists
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, age_group, gender')
      .eq('team_id_master', teamIdMaster)
      .single();

    if (teamError || !team) {
      console.error('[link-opponent] Team not found:', teamError);
      return NextResponse.json(
        { error: 'Team not found' },
        { status: 404 }
      );
    }

    // 2. Get the provider_id from the game
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('id, provider_id, home_provider_id, away_provider_id, home_team_master_id, away_team_master_id')
      .eq('id', gameId)
      .single();

    if (gameError || !game) {
      console.error('[link-opponent] Game not found:', gameError);
      return NextResponse.json(
        { error: 'Game not found' },
        { status: 404 }
      );
    }

    // Debug logging to understand the data
    console.log('[link-opponent] Debug info:', {
      gameId,
      opponentProviderId,
      opponentProviderIdType: typeof opponentProviderId,
      teamIdMaster,
      game: {
        id: game.id,
        provider_id: game.provider_id,
        home_provider_id: game.home_provider_id,
        home_provider_id_type: typeof game.home_provider_id,
        away_provider_id: game.away_provider_id,
        away_provider_id_type: typeof game.away_provider_id,
        home_team_master_id: game.home_team_master_id,
        away_team_master_id: game.away_team_master_id,
      }
    });

    // Ensure provider_team_id is a string (database column is TEXT)
    const providerTeamIdStr = String(opponentProviderId);

    // Check: Is the opponentProviderId matching home or away?
    const isOpponentHome = String(game.home_provider_id) === providerTeamIdStr;
    const isOpponentAway = String(game.away_provider_id) === providerTeamIdStr;

    // EARLY CHECK: Verify the opponent is actually unlinked before proceeding
    // This prevents the confusing case where we return "success" but nothing updates
    if (isOpponentHome && game.home_team_master_id !== null) {
      console.log('[link-opponent] Home team already linked:', game.home_team_master_id);
      return NextResponse.json(
        {
          error: 'This opponent is already linked to a team',
          details: 'The home team position is already filled. If this is incorrect, please contact support.'
        },
        { status: 400 }
      );
    }
    if (isOpponentAway && game.away_team_master_id !== null) {
      console.log('[link-opponent] Away team already linked:', game.away_team_master_id);
      return NextResponse.json(
        {
          error: 'This opponent is already linked to a team',
          details: 'The away team position is already filled. If this is incorrect, please contact support.'
        },
        { status: 400 }
      );
    }
    if (!isOpponentHome && !isOpponentAway) {
      console.log('[link-opponent] Provider ID mismatch:', {
        opponentProviderId: providerTeamIdStr,
        home_provider_id: String(game.home_provider_id),
        away_provider_id: String(game.away_provider_id),
      });
      return NextResponse.json(
        {
          error: 'Provider ID does not match any team in this game',
          details: 'The opponent provider ID does not match the home or away provider ID for this game.'
        },
        { status: 400 }
      );
    }

    // 3. Create or update alias mapping (upsert)

    const { error: aliasError } = await supabase
      .from('team_alias_map')
      .upsert({
        provider_id: game.provider_id,
        provider_team_id: providerTeamIdStr,
        team_id_master: teamIdMaster,
        match_method: 'manual',  // Valid values: auto, manual, import, direct_id, fuzzy_auto, fuzzy_review
        match_confidence: 1.0,
        review_status: 'approved',
      }, {
        onConflict: 'provider_id,provider_team_id'
      });

    if (aliasError) {
      console.error('[link-opponent] Failed to create alias:', aliasError);
      return NextResponse.json(
        { error: `Failed to create team alias mapping: ${aliasError.message}` },
        { status: 500 }
      );
    }

    let gamesUpdated = 0;
    let homeUpdated = 0;
    let awayUpdated = 0;
    let specificGameUpdated = false;
    let verificationResult: { home_team_master_id?: string | null; away_team_master_id?: string | null } | null = null;

    // Note: isOpponentHome, isOpponentAway are already defined above
    // At this point, we know the opponent needs linking (validated in early check)

    console.log('[link-opponent] Pre-update check:', {
      isOpponentHome,
      isOpponentAway,
      home_team_master_id_value: game.home_team_master_id,
      away_team_master_id_value: game.away_team_master_id,
    });

    // 4. FIRST: Always update the specific game the user clicked on (by ID)
    // This ensures the clicked game gets updated regardless of any type issues with provider_id matching
    if (isOpponentHome) {
      console.log('[link-opponent] Updating specific game (home team) by ID:', gameId);

      // Try using RPC function first (handles immutability properly)
      const { error: rpcError, data: rpcData } = await supabase.rpc('link_game_team', {
        p_game_id: gameId,
        p_team_id_master: teamIdMaster,
        p_is_home_team: true
      });

      let specificUpdateError = rpcError;
      let updateData = rpcData ? [{ id: gameId }] : null;

      // If RPC function doesn't exist, fall back to direct update
      if (rpcError?.code === '42883' || rpcError?.message?.includes('function') || rpcError?.message?.includes('does not exist')) {
        console.log('[link-opponent] RPC function not found, trying direct update');
        const directResult = await supabase
          .from('games')
          .update({ home_team_master_id: teamIdMaster })
          .eq('id', gameId)
          .select('id');
        specificUpdateError = directResult.error;
        updateData = directResult.data;
      }

      console.log('[link-opponent] Specific game update result:', { specificUpdateError, updateData });

      if (specificUpdateError) {
        console.error('[link-opponent] Failed to update specific game:', specificUpdateError);
        return NextResponse.json(
          {
            error: `Database update failed: ${specificUpdateError.message}`,
            details: 'The game could not be updated. This may be due to database constraints.'
          },
          { status: 500 }
        );
      }

      // Verify the update by re-fetching the game
      const { data: verifyGame, error: verifyError } = await supabase
        .from('games')
        .select('id, home_team_master_id')
        .eq('id', gameId)
        .single();

      verificationResult = verifyGame;
      // Use String() comparison to handle potential UUID format differences
      const updateActuallyWorked = String(verifyGame?.home_team_master_id) === String(teamIdMaster);
      console.log('[link-opponent] Verification after update:', {
        verifyGame,
        verifyError,
        teamIdMaster,
        teamIdMasterType: typeof teamIdMaster,
        verifyGameHomeId: verifyGame?.home_team_master_id,
        verifyGameHomeIdType: typeof verifyGame?.home_team_master_id,
        updateActuallyWorked
      });

      if (verifyError) {
        console.error('[link-opponent] Failed to verify update:', verifyError);
      }

      if (updateActuallyWorked) {
        // Trust the verification SELECT
        specificGameUpdated = true;
        homeUpdated = 1;
        console.log('[link-opponent] Successfully updated specific game (home team) - verified');
      } else if (updateData && updateData.length > 0) {
        // Update reported rows affected but verification failed - database trigger may have blocked
        console.warn('[link-opponent] Update reported success but verification failed - possible trigger issue');
        specificGameUpdated = true;
        homeUpdated = 1;
      } else {
        // Update failed completely - return error instead of continuing
        console.error('[link-opponent] Update failed - no rows affected and verification failed');
        return NextResponse.json(
          {
            error: 'Game update failed - database rejected the change',
            details: 'The update was rejected by the database. The game may be marked as immutable or there may be a constraint violation.'
          },
          { status: 500 }
        );
      }
    } else {
      // isOpponentAway must be true (validated in early check)
      console.log('[link-opponent] Updating specific game (away team) by ID:', gameId);

      // Try using RPC function first (handles immutability properly)
      const { error: rpcError, data: rpcData } = await supabase.rpc('link_game_team', {
        p_game_id: gameId,
        p_team_id_master: teamIdMaster,
        p_is_home_team: false
      });

      let specificUpdateError = rpcError;
      let updateData = rpcData ? [{ id: gameId }] : null;

      // If RPC function doesn't exist, fall back to direct update
      if (rpcError?.code === '42883' || rpcError?.message?.includes('function') || rpcError?.message?.includes('does not exist')) {
        console.log('[link-opponent] RPC function not found, trying direct update');
        const directResult = await supabase
          .from('games')
          .update({ away_team_master_id: teamIdMaster })
          .eq('id', gameId)
          .select('id');
        specificUpdateError = directResult.error;
        updateData = directResult.data;
      }

      console.log('[link-opponent] Specific game update result:', { specificUpdateError, updateData });

      if (specificUpdateError) {
        console.error('[link-opponent] Failed to update specific game:', specificUpdateError);
        return NextResponse.json(
          {
            error: `Database update failed: ${specificUpdateError.message}`,
            details: 'The game could not be updated. This may be due to database constraints.'
          },
          { status: 500 }
        );
      }

      // Verify the update by re-fetching the game
      const { data: verifyGame, error: verifyError } = await supabase
        .from('games')
        .select('id, away_team_master_id')
        .eq('id', gameId)
        .single();

      verificationResult = verifyGame;
      // Use String() comparison to handle potential UUID format differences
      const updateActuallyWorked = String(verifyGame?.away_team_master_id) === String(teamIdMaster);
      console.log('[link-opponent] Verification after update:', {
        verifyGame,
        verifyError,
        teamIdMaster,
        teamIdMasterType: typeof teamIdMaster,
        verifyGameAwayId: verifyGame?.away_team_master_id,
        verifyGameAwayIdType: typeof verifyGame?.away_team_master_id,
        updateActuallyWorked
      });

      if (verifyError) {
        console.error('[link-opponent] Failed to verify update:', verifyError);
      }

      if (updateActuallyWorked) {
        // Trust the verification SELECT
        specificGameUpdated = true;
        awayUpdated = 1;
        console.log('[link-opponent] Successfully updated specific game (away team) - verified');
      } else if (updateData && updateData.length > 0) {
        // Update reported rows affected but verification failed - database trigger may have blocked
        console.warn('[link-opponent] Update reported success but verification failed - possible trigger issue');
        specificGameUpdated = true;
        awayUpdated = 1;
      } else {
        // Update failed completely - return error instead of continuing
        console.error('[link-opponent] Update failed - no rows affected and verification failed');
        return NextResponse.json(
          {
            error: 'Game update failed - database rejected the change',
            details: 'The update was rejected by the database. The game may be marked as immutable or there may be a constraint violation.'
          },
          { status: 500 }
        );
      }
    }

    // 5. Backfill OTHER games with this provider_team_id (only the unknown side)
    if (applyToAllGames) {
      // Only update the side that matches the unknown opponent's provider_team_id.
      // If isOpponentHome for the clicked game, the opponent's provider_team_id is home_provider_id.
      // But in OTHER games, the same provider_team_id could appear on either side.
      // We update both sides where null, BUT we must not fill in both sides of the
      // same physical game (which can exist as two records scraped from each team).

      const providerIdIsNull = game.provider_id === null;

      // Update games where opponent is HOME team and home_team_master_id is NULL
      let homeQuery = supabase
        .from('games')
        .update({ home_team_master_id: teamIdMaster })
        .eq('home_provider_id', providerTeamIdStr)
        .is('home_team_master_id', null)
        .neq('id', gameId);
      homeQuery = providerIdIsNull
        ? homeQuery.is('provider_id', null)
        : homeQuery.eq('provider_id', game.provider_id);
      const { error: homeUpdateError, data: homeUpdateData } = await homeQuery.select('id');

      if (homeUpdateError) {
        console.error('[link-opponent] Failed to update home games:', homeUpdateError);
      } else {
        homeUpdated += homeUpdateData?.length || 0;
      }

      // Update games where opponent is AWAY team and away_team_master_id is NULL
      let awayQuery = supabase
        .from('games')
        .update({ away_team_master_id: teamIdMaster })
        .eq('away_provider_id', providerTeamIdStr)
        .is('away_team_master_id', null)
        .neq('id', gameId);
      awayQuery = providerIdIsNull
        ? awayQuery.is('provider_id', null)
        : awayQuery.eq('provider_id', game.provider_id);
      const { error: awayUpdateError, data: awayUpdateData } = await awayQuery.select('id');

      if (awayUpdateError) {
        console.error('[link-opponent] Failed to update away games:', awayUpdateError);
      } else {
        awayUpdated += awayUpdateData?.length || 0;
      }

      gamesUpdated = (specificGameUpdated ? 1 : 0) + homeUpdated + awayUpdated;
      console.log('[link-opponent] Total games updated:', { homeUpdated, awayUpdated, gamesUpdated });
    } else {
      gamesUpdated = specificGameUpdated ? 1 : 0;
    }

    // 6. Create audit log entry
    const { error: auditError } = await supabase
      .from('team_link_audit')
      .insert({
        provider_team_id: providerTeamIdStr,
        team_id_master: teamIdMaster,
        provider_id: game.provider_id,
        games_updated: gamesUpdated,
        linked_by: 'frontend_user',
        notes: `Home: ${homeUpdated}, Away: ${awayUpdated}`,
      });

    if (auditError) {
      console.error('[link-opponent] Failed to create audit log:', auditError);
    }

    return NextResponse.json({
      success: true,
      teamName: team.team_name,
      teamClubName: team.club_name,
      gamesUpdated,
      aliasCreated: true,
      message: gamesUpdated > 0
        ? `Successfully linked ${gamesUpdated} game(s) to ${team.team_name}`
        : `Alias created for ${team.team_name}. Future games will be linked automatically.`,
    });
  } catch (error) {
    console.error('[link-opponent] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
