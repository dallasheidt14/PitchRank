import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { randomUUID } from 'crypto';

/**
 * Create a new team and link it to an unknown opponent
 * Creates team record, alias mapping, and backfills affected games
 */
export async function POST(request: NextRequest) {
  try {
    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;

    if (!serviceKey || !supabaseUrl) {
      console.error('[create-team] Missing environment variables');
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
      teamName,
      clubName,
      ageGroup,
      gender,
      stateCode,
    } = requestBody;

    // Validate required fields
    if (!gameId || !opponentProviderId || !teamName || !ageGroup || !gender) {
      return NextResponse.json(
        { error: 'Missing required fields: gameId, opponentProviderId, teamName, ageGroup, and gender' },
        { status: 400 }
      );
    }

    // Validate gender
    if (gender !== 'Male' && gender !== 'Female') {
      return NextResponse.json(
        { error: 'Gender must be "Male" or "Female"' },
        { status: 400 }
      );
    }

    // Validate age group format
    if (!/^u\d{1,2}$/i.test(ageGroup)) {
      return NextResponse.json(
        { error: 'Age group must be in format like "u10", "u11", etc.' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    // 1. Get the provider_id from the game
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('provider_id, home_provider_id, away_provider_id')
      .eq('id', gameId)
      .single();

    if (gameError || !game) {
      console.error('[create-team] Game not found:', gameError);
      return NextResponse.json(
        { error: 'Game not found' },
        { status: 404 }
      );
    }

    // 2. Generate new team_id_master
    const teamIdMaster = randomUUID();
    const providerTeamIdStr = String(opponentProviderId);

    // 3. Create the team
    const { error: teamError } = await supabase
      .from('teams')
      .insert({
        team_id_master: teamIdMaster,
        provider_team_id: providerTeamIdStr,
        provider_id: game.provider_id,
        team_name: teamName.trim(),
        club_name: clubName?.trim() || null,
        age_group: ageGroup.toLowerCase(),
        gender: gender,
        state_code: stateCode || null,
        state: stateCode || null,
      });

    if (teamError) {
      console.error('[create-team] Failed to create team:', teamError);
      return NextResponse.json(
        { error: `Failed to create team: ${teamError.message}` },
        { status: 500 }
      );
    }

    // 4. Create alias mapping
    const { error: aliasError } = await supabase
      .from('team_alias_map')
      .upsert({
        provider_id: game.provider_id,
        provider_team_id: providerTeamIdStr,
        team_id_master: teamIdMaster,
        match_method: 'manual',
        match_confidence: 1.0,
        review_status: 'approved',
      }, {
        onConflict: 'provider_id,provider_team_id'
      });

    if (aliasError) {
      console.error('[create-team] Failed to create alias:', aliasError);
      // Team was created but alias failed - still useful
      return NextResponse.json(
        { error: `Team created but alias mapping failed: ${aliasError.message}` },
        { status: 500 }
      );
    }

    // 5. Backfill games
    let gamesUpdated = 0;
    let homeUpdated = 0;
    let awayUpdated = 0;

    // Count games where opponent is HOME team first
    const { count: homeCount } = await supabase
      .from('games')
      .select('id', { count: 'exact', head: true })
      .eq('home_provider_id', providerTeamIdStr)
      .eq('provider_id', game.provider_id)
      .is('home_team_master_id', null);

    // Update games where opponent is HOME team
    const { error: homeUpdateError } = await supabase
      .from('games')
      .update({ home_team_master_id: teamIdMaster })
      .eq('home_provider_id', providerTeamIdStr)
      .eq('provider_id', game.provider_id)
      .is('home_team_master_id', null);

    if (homeUpdateError) {
      console.error('[create-team] Failed to update home games:', homeUpdateError);
    } else {
      homeUpdated = homeCount || 0;
    }

    // Count games where opponent is AWAY team first
    const { count: awayCount } = await supabase
      .from('games')
      .select('id', { count: 'exact', head: true })
      .eq('away_provider_id', providerTeamIdStr)
      .eq('provider_id', game.provider_id)
      .is('away_team_master_id', null);

    // Update games where opponent is AWAY team
    const { error: awayUpdateError } = await supabase
      .from('games')
      .update({ away_team_master_id: teamIdMaster })
      .eq('away_provider_id', providerTeamIdStr)
      .eq('provider_id', game.provider_id)
      .is('away_team_master_id', null);

    if (awayUpdateError) {
      console.error('[create-team] Failed to update away games:', awayUpdateError);
    } else {
      awayUpdated = awayCount || 0;
    }

    gamesUpdated = homeUpdated + awayUpdated;

    // 6. Create audit log entry
    const { error: auditError } = await supabase
      .from('team_link_audit')
      .insert({
        provider_team_id: providerTeamIdStr,
        team_id_master: teamIdMaster,
        provider_id: game.provider_id,
        games_updated: gamesUpdated,
        linked_by: 'frontend_user',
        notes: `Created new team "${teamName}" (${ageGroup} ${gender}). Home: ${homeUpdated}, Away: ${awayUpdated}`,
      });

    if (auditError) {
      console.error('[create-team] Failed to create audit log:', auditError);
      // Don't fail - the main operation succeeded
    }

    return NextResponse.json({
      success: true,
      teamIdMaster,
      teamName,
      gamesUpdated,
      message: `Successfully created team "${teamName}" and linked ${gamesUpdated} game(s)`,
    });
  } catch (error) {
    console.error('[create-team] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
