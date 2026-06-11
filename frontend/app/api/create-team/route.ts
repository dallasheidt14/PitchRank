import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'crypto';
import { requireAdmin } from '@/lib/supabase/admin';
import { createServiceSupabase } from '@/lib/supabase/service';
import { parseJsonBody } from '@/lib/api/parseJsonBody';

/**
 * Create a new team and link it to an unknown opponent
 * Creates team record, alias mapping, and backfills affected games
 */
export async function POST(request: NextRequest) {
  try {
    const auth = await requireAdmin();
    if (auth.error) return auth.error;

    const body = await parseJsonBody<{
      gameId: string;
      opponentProviderId: string;
      teamName: string;
      clubName?: string;
      ageGroup: string;
      gender: string;
      stateCode?: string;
    }>(request);
    if (body.error) return body.error;

    const { gameId, opponentProviderId, teamName, clubName, ageGroup, gender, stateCode } = body.data;

    // Validate required fields
    if (!gameId || !opponentProviderId || !teamName || !ageGroup || !gender) {
      return NextResponse.json(
        { error: 'Missing required fields: gameId, opponentProviderId, teamName, ageGroup, and gender' },
        { status: 400 }
      );
    }

    // Validate gender
    if (gender !== 'Male' && gender !== 'Female') {
      return NextResponse.json({ error: 'Gender must be "Male" or "Female"' }, { status: 400 });
    }

    // Validate age group format
    if (!/^u\d{1,2}$/i.test(ageGroup)) {
      return NextResponse.json({ error: 'Age group must be in format like "u10", "u11", etc.' }, { status: 400 });
    }

    const supabase = createServiceSupabase();

    // 1. Get the provider_id from the game
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('provider_id, home_provider_id, away_provider_id')
      .eq('id', gameId)
      .single();

    if (gameError || !game) {
      console.error('[create-team] Game not found:', gameError);
      return NextResponse.json({ error: 'Game not found' }, { status: 404 });
    }

    // Validate that opponentProviderId is actually referenced by this game
    const providerTeamIdCheck = String(opponentProviderId);
    if (
      String(game.home_provider_id) !== providerTeamIdCheck &&
      String(game.away_provider_id) !== providerTeamIdCheck
    ) {
      return NextResponse.json({ error: 'opponentProviderId does not match any team in this game' }, { status: 400 });
    }

    // 2. Generate new team_id_master
    const teamIdMaster = randomUUID();
    const providerTeamIdStr = String(opponentProviderId);

    // 3. Create the team
    const { error: teamError } = await supabase.from('teams').insert({
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
      return NextResponse.json({ error: 'Failed to create team' }, { status: 500 });
    }

    // 4. Create alias mapping
    const { error: aliasError } = await supabase.from('team_alias_map').upsert(
      {
        provider_id: game.provider_id,
        provider_team_id: providerTeamIdStr,
        team_id_master: teamIdMaster,
        match_method: 'manual',
        match_confidence: 1.0,
        review_status: 'approved',
      },
      {
        onConflict: 'provider_id,provider_team_id',
      }
    );

    if (aliasError) {
      console.error('[create-team] Failed to create alias:', aliasError);
      // Team was created but alias failed - still useful
      return NextResponse.json({ error: 'Team created but alias mapping failed' }, { status: 500 });
    }

    // 5. Backfill games
    let gamesUpdated = 0;
    let homeUpdated = 0;
    let awayUpdated = 0;
    const providerIdIsNull = game.provider_id === null;

    // Update games where opponent is HOME team
    let homeUpdateQuery = supabase
      .from('games')
      .update({ home_team_master_id: teamIdMaster })
      .eq('home_provider_id', providerTeamIdStr)
      .is('home_team_master_id', null);
    homeUpdateQuery = providerIdIsNull
      ? homeUpdateQuery.is('provider_id', null)
      : homeUpdateQuery.eq('provider_id', game.provider_id);
    const { error: homeUpdateError, data: homeUpdateData } = await homeUpdateQuery.select('id');

    if (homeUpdateError) {
      console.error('[create-team] Failed to update home games:', homeUpdateError);
    } else {
      homeUpdated = homeUpdateData?.length || 0;
    }

    // Update games where opponent is AWAY team
    let awayUpdateQuery = supabase
      .from('games')
      .update({ away_team_master_id: teamIdMaster })
      .eq('away_provider_id', providerTeamIdStr)
      .is('away_team_master_id', null);
    awayUpdateQuery = providerIdIsNull
      ? awayUpdateQuery.is('provider_id', null)
      : awayUpdateQuery.eq('provider_id', game.provider_id);
    const { error: awayUpdateError, data: awayUpdateData } = await awayUpdateQuery.select('id');

    if (awayUpdateError) {
      console.error('[create-team] Failed to update away games:', awayUpdateError);
    } else {
      awayUpdated = awayUpdateData?.length || 0;
    }

    gamesUpdated = homeUpdated + awayUpdated;

    // 6. Create audit log entry
    const { error: auditError } = await supabase.from('team_link_audit').insert({
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

    // 7. Schedule-driven-scraping hook: enqueue at priority 1 if this is a
    //    GotSport team. Admin-initiated team creation deserves a near-immediate
    //    scrape — process_missing_games drains the queue at 200/15min so the
    //    new team's schedule should land within a single drain cycle.
    //    Other providers are out of scope; the queue is GotSport-only for now.
    //
    //    The whole block is wrapped so a transient Supabase failure here can't
    //    return a 500 to an admin whose team was already successfully created,
    //    aliased, backfilled, and audited. If the enqueue misses, the safety-net
    //    sweep (priority 4, weekly) picks the team up.
    if (game.provider_id) {
      try {
        const { data: providerRow } = await supabase
          .from('providers')
          .select('code')
          .eq('id', game.provider_id)
          .single();

        if (providerRow?.code === 'gotsport') {
          const { error: enqueueError } = await supabase.rpc('enqueue_scrape_request', {
            p_team_id_master: teamIdMaster,
            p_team_name: teamName.trim(),
            p_provider_id: game.provider_id,
            p_provider_team_id: providerTeamIdStr,
            p_game_date: new Date().toISOString().slice(0, 10),
            p_request_type: 'new_team',
            p_priority: 1,
          });
          if (enqueueError) {
            console.error('[create-team] Enqueue failed (non-fatal):', enqueueError);
          }
        }
      } catch (enqueueException) {
        console.error('[create-team] Enqueue threw (non-fatal):', enqueueException);
      }
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
    return NextResponse.json({ error: 'An unexpected error occurred' }, { status: 500 });
  }
}
