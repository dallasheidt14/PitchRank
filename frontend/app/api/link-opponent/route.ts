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
      .select('provider_id, home_provider_id, away_provider_id')
      .eq('id', gameId)
      .single();

    if (gameError || !game) {
      console.error('[link-opponent] Game not found:', gameError);
      return NextResponse.json(
        { error: 'Game not found' },
        { status: 404 }
      );
    }

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

    // 4. Optionally backfill all games with this provider_id
    if (applyToAllGames) {
      // Helper to build query with proper provider_id handling
      // Note: .eq('col', null) doesn't work in SQL (NULL = NULL is false)
      // So we need to use .is() for null values
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const addProviderFilter = <T extends { is: (col: string, val: null) => T; eq: (col: string, val: string) => T }>(query: T): T => {
        if (game.provider_id === null) {
          return query.is('provider_id', null);
        }
        return query.eq('provider_id', game.provider_id);
      };

      // Count games where opponent is HOME team first
      let homeCountQuery = supabase
        .from('games')
        .select('id', { count: 'exact', head: true })
        .eq('home_provider_id', providerTeamIdStr)
        .is('home_team_master_id', null);
      homeCountQuery = addProviderFilter(homeCountQuery);
      const { count: homeCount } = await homeCountQuery;

      // Update games where opponent is HOME team
      let homeUpdateQuery = supabase
        .from('games')
        .update({ home_team_master_id: teamIdMaster })
        .eq('home_provider_id', providerTeamIdStr)
        .is('home_team_master_id', null);
      homeUpdateQuery = addProviderFilter(homeUpdateQuery);
      const { error: homeUpdateError } = await homeUpdateQuery;

      if (homeUpdateError) {
        console.error('[link-opponent] Failed to update home games:', homeUpdateError);
        // Don't fail - alias was created, just log the error
      } else {
        homeUpdated = homeCount || 0;
      }

      // Count games where opponent is AWAY team first
      let awayCountQuery = supabase
        .from('games')
        .select('id', { count: 'exact', head: true })
        .eq('away_provider_id', providerTeamIdStr)
        .is('away_team_master_id', null);
      awayCountQuery = addProviderFilter(awayCountQuery);
      const { count: awayCount } = await awayCountQuery;

      // Update games where opponent is AWAY team
      let awayUpdateQuery = supabase
        .from('games')
        .update({ away_team_master_id: teamIdMaster })
        .eq('away_provider_id', providerTeamIdStr)
        .is('away_team_master_id', null);
      awayUpdateQuery = addProviderFilter(awayUpdateQuery);
      const { error: awayUpdateError } = await awayUpdateQuery;

      if (awayUpdateError) {
        console.error('[link-opponent] Failed to update away games:', awayUpdateError);
        // Don't fail - alias was created, just log the error
      } else {
        awayUpdated = awayCount || 0;
      }

      gamesUpdated = homeUpdated + awayUpdated;

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
