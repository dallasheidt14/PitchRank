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
      applyToAllGames = true // Default to applying to all games
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

    // 3. Create or update alias mapping (upsert)
    // Ensure provider_team_id is a string (database column is TEXT)
    const providerTeamIdStr = String(opponentProviderId);

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

    // Check: Is the opponentProviderId matching home or away?
    const isOpponentHome = String(game.home_provider_id) === providerTeamIdStr;
    const isOpponentAway = String(game.away_provider_id) === providerTeamIdStr;

    // 4. FIRST: Always update the specific game the user clicked on (by ID)
    // This ensures the clicked game gets updated regardless of any type issues with provider_id matching
    if (isOpponentHome && game.home_team_master_id === null) {
      console.log('[link-opponent] Updating specific game (home team) by ID:', gameId);
      const { error: specificUpdateError } = await supabase
        .from('games')
        .update({ home_team_master_id: teamIdMaster })
        .eq('id', gameId);

      if (specificUpdateError) {
        console.error('[link-opponent] Failed to update specific game:', specificUpdateError);
      } else {
        specificGameUpdated = true;
        homeUpdated = 1;
        console.log('[link-opponent] Successfully updated specific game (home team)');
      }
    } else if (isOpponentAway && game.away_team_master_id === null) {
      console.log('[link-opponent] Updating specific game (away team) by ID:', gameId);
      const { error: specificUpdateError } = await supabase
        .from('games')
        .update({ away_team_master_id: teamIdMaster })
        .eq('id', gameId);

      if (specificUpdateError) {
        console.error('[link-opponent] Failed to update specific game:', specificUpdateError);
      } else {
        specificGameUpdated = true;
        awayUpdated = 1;
        console.log('[link-opponent] Successfully updated specific game (away team)');
      }
    } else {
      console.log('[link-opponent] Specific game already linked or no match:', {
        isOpponentHome,
        isOpponentAway,
        home_team_master_id: game.home_team_master_id,
        away_team_master_id: game.away_team_master_id,
      });
    }

    // 5. Optionally backfill OTHER games with this provider_id
    if (applyToAllGames) {
      console.log('[link-opponent] Provider ID match check:', {
        providerTeamIdStr,
        game_home_provider_id: game.home_provider_id,
        game_away_provider_id: game.away_provider_id,
        isOpponentHome,
        isOpponentAway,
        home_already_linked: game.home_team_master_id !== null,
        away_already_linked: game.away_team_master_id !== null,
      });

      // Build queries with proper provider_id handling
      // Note: .eq('col', null) doesn't work in SQL (NULL = NULL is false)
      // So we need to use .is() for null values
      const providerIdIsNull = game.provider_id === null;

      // Count and update games where opponent is HOME team
      const homeCountQuery = providerIdIsNull
        ? supabase.from('games').select('id', { count: 'exact', head: true })
            .eq('home_provider_id', providerTeamIdStr)
            .is('home_team_master_id', null)
            .is('provider_id', null)
        : supabase.from('games').select('id', { count: 'exact', head: true })
            .eq('home_provider_id', providerTeamIdStr)
            .is('home_team_master_id', null)
            .eq('provider_id', game.provider_id);
      const { count: homeCount, error: homeCountError } = await homeCountQuery;
      console.log('[link-opponent] Home count query result:', { homeCount, homeCountError });

      // Update games where opponent is HOME team
      const homeUpdateQuery = providerIdIsNull
        ? supabase.from('games').update({ home_team_master_id: teamIdMaster })
            .eq('home_provider_id', providerTeamIdStr)
            .is('home_team_master_id', null)
            .is('provider_id', null)
            .select('id')
        : supabase.from('games').update({ home_team_master_id: teamIdMaster })
            .eq('home_provider_id', providerTeamIdStr)
            .is('home_team_master_id', null)
            .eq('provider_id', game.provider_id)
            .select('id');
      const { error: homeUpdateError, data: homeUpdateData } = await homeUpdateQuery;
      console.log('[link-opponent] Home update result:', { homeUpdateError, updatedCount: homeUpdateData?.length });

      if (homeUpdateError) {
        console.error('[link-opponent] Failed to update home games:', homeUpdateError);
        // Don't fail - alias was created, just log the error
      } else {
        // Add to homeUpdated (don't overwrite - we may have already updated the specific game)
        homeUpdated += homeUpdateData?.length || 0;
      }

      // Count games where opponent is AWAY team
      const awayCountQuery = providerIdIsNull
        ? supabase.from('games').select('id', { count: 'exact', head: true })
            .eq('away_provider_id', providerTeamIdStr)
            .is('away_team_master_id', null)
            .is('provider_id', null)
        : supabase.from('games').select('id', { count: 'exact', head: true })
            .eq('away_provider_id', providerTeamIdStr)
            .is('away_team_master_id', null)
            .eq('provider_id', game.provider_id);
      const { count: awayCount, error: awayCountError } = await awayCountQuery;
      console.log('[link-opponent] Away count query result:', { awayCount, awayCountError });

      // Update games where opponent is AWAY team
      const awayUpdateQuery = providerIdIsNull
        ? supabase.from('games').update({ away_team_master_id: teamIdMaster })
            .eq('away_provider_id', providerTeamIdStr)
            .is('away_team_master_id', null)
            .is('provider_id', null)
            .select('id')
        : supabase.from('games').update({ away_team_master_id: teamIdMaster })
            .eq('away_provider_id', providerTeamIdStr)
            .is('away_team_master_id', null)
            .eq('provider_id', game.provider_id)
            .select('id');
      const { error: awayUpdateError, data: awayUpdateData } = await awayUpdateQuery;
      console.log('[link-opponent] Away update result:', { awayUpdateError, updatedCount: awayUpdateData?.length });

      if (awayUpdateError) {
        console.error('[link-opponent] Failed to update away games:', awayUpdateError);
        // Don't fail - alias was created, just log the error
      } else {
        // Add to awayUpdated (don't overwrite - we may have already updated the specific game)
        awayUpdated += awayUpdateData?.length || 0;
      }

      gamesUpdated = homeUpdated + awayUpdated;
      console.log('[link-opponent] Total games updated:', { homeUpdated, awayUpdated, gamesUpdated });

      // 5. Create audit log entry
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
        // Don't fail - the main operation succeeded
      }
    } else {
      // If not applying to all games, just count the specific game update
      gamesUpdated = specificGameUpdated ? 1 : 0;
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
      // Debug info to help diagnose issues
      debug: {
        gameId,
        opponentProviderId,
        teamIdMaster,
        specificGameUpdated,
        isOpponentHome,
        isOpponentAway,
        game: {
          provider_id: game.provider_id,
          home_provider_id: game.home_provider_id,
          away_provider_id: game.away_provider_id,
          home_team_master_id: game.home_team_master_id,
          away_team_master_id: game.away_team_master_id,
        },
        homeUpdated,
        awayUpdated,
      }
    });
  } catch (error) {
    console.error('[link-opponent] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
