import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

export async function POST(request: NextRequest) {
  try {
    // Check for service key
    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    if (!serviceKey) {
      console.error('[scrape-missing-game] Missing SUPABASE_SERVICE_KEY environment variable');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
    if (!supabaseUrl) {
      console.error('[scrape-missing-game] Missing NEXT_PUBLIC_SUPABASE_URL environment variable');
      return NextResponse.json(
        { error: 'Server configuration error' },
        { status: 500 }
      );
    }

    // Parse request body
    let requestBody;
    try {
      requestBody = await request.json();
    } catch (err) {
      return NextResponse.json(
        { error: 'Invalid request body' },
        { status: 400 }
      );
    }

    // Validate required fields
    const { teamId, teamName, gameDate } = requestBody;
    if (!teamId || !teamName || !gameDate) {
      return NextResponse.json(
        { error: 'Missing required fields: teamId, teamName, and gameDate are required' },
        { status: 400 }
      );
    }

    // Validate date format and ensure it's not in the future
    let parsedDate: Date;
    try {
      parsedDate = new Date(gameDate);
      if (isNaN(parsedDate.getTime())) {
        return NextResponse.json(
          { error: 'Invalid date format' },
          { status: 400 }
        );
      }
    } catch (err) {
      return NextResponse.json(
        { error: 'Invalid date format' },
        { status: 400 }
      );
    }

    // Check if date is in the future
    if (parsedDate > new Date()) {
      return NextResponse.json(
        { error: 'Game date cannot be in the future' },
        { status: 400 }
      );
    }

    // Create Supabase client with service key
    const supabase = createClient(supabaseUrl, serviceKey);

    // Fetch team details to get provider_id and provider_team_id
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('provider_id, provider_team_id')
      .eq('team_id_master', teamId)
      .single();

    if (teamError || !team) {
      console.error('[scrape-missing-game] Team not found:', teamError);
      return NextResponse.json(
        { error: 'Team not found' },
        { status: 400 }
      );
    }

    // Check team_alias_map for a GotSport alias that may be more up-to-date
    // than the teams table (e.g., when a team was linked via game history)
    let providerId = team.provider_id;
    let providerTeamId = team.provider_team_id;

    // Look up the GotSport provider ID
    const { data: gotsportProvider } = await supabase
      .from('providers')
      .select('id')
      .eq('code', 'gotsport')
      .single();

    if (gotsportProvider) {
      // Check for a manually-approved GotSport alias (from link-opponent)
      const { data: aliases } = await supabase
        .from('team_alias_map')
        .select('provider_id, provider_team_id')
        .eq('team_id_master', teamId)
        .eq('provider_id', gotsportProvider.id)
        .eq('review_status', 'approved')
        .order('created_at', { ascending: false })
        .limit(1);

      if (aliases && aliases.length > 0) {
        const alias = aliases[0];
        // Use the alias if it differs from the teams table
        // (alias is likely more up-to-date, especially for manually linked teams)
        if (alias.provider_team_id !== team.provider_team_id) {
          console.log(`[scrape-missing-game] Using GotSport alias ${alias.provider_team_id} instead of teams table ${team.provider_team_id}`);
          providerId = alias.provider_id;
          providerTeamId = alias.provider_team_id;
        }
      }
    }

    // Insert scrape request
    const { data: insertData, error: insertError } = await supabase
      .from('scrape_requests')
      .insert({
        team_id_master: teamId,
        team_name: teamName,
        provider_id: providerId,
        provider_team_id: providerTeamId,
        game_date: gameDate,
        status: 'pending',
        request_type: 'missing_game',
      })
      .select('id')
      .single();

    if (insertError) {
      console.error('[scrape-missing-game] Database error:', insertError);
      return NextResponse.json(
        { error: 'Failed to create scrape request' },
        { status: 500 }
      );
    }

    return NextResponse.json({
      success: true,
      requestId: insertData.id,
    });
  } catch (error) {
    console.error('[scrape-missing-game] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}

