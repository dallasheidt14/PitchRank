import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * Preview API for linking unknown opponent
 * Shows how many games would be affected before applying changes
 */
export async function POST(request: NextRequest) {
  try {
    const serviceKey = process.env.SUPABASE_SERVICE_KEY;
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;

    if (!serviceKey || !supabaseUrl) {
      console.error('[link-opponent/preview] Missing environment variables');
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

    const { gameId, opponentProviderId } = requestBody;

    if (!gameId || !opponentProviderId) {
      return NextResponse.json(
        { error: 'Missing required fields: gameId and opponentProviderId' },
        { status: 400 }
      );
    }

    const supabase = createClient(supabaseUrl, serviceKey);

    // Get the provider_id from the game
    const { data: game, error: gameError } = await supabase
      .from('games')
      .select('provider_id')
      .eq('id', gameId)
      .single();

    if (gameError || !game) {
      console.error('[link-opponent/preview] Game not found:', gameError);
      return NextResponse.json(
        { error: 'Game not found' },
        { status: 404 }
      );
    }

    // Get the provider name for display
    let providerName = 'Unknown';
    if (game.provider_id) {
      const { data: provider } = await supabase
        .from('providers')
        .select('name, code')
        .eq('id', game.provider_id)
        .single();

      if (provider) {
        providerName = provider.name || provider.code || 'Unknown';
      }
    }

    // Count games that would be affected
    const { data: homeGames, error: homeError } = await supabase
      .from('games')
      .select('id, game_date, home_score, away_score, competition, home_team_master_id, away_team_master_id')
      .eq('home_provider_id', opponentProviderId)
      .eq('provider_id', game.provider_id)
      .is('home_team_master_id', null)
      .order('game_date', { ascending: false })
      .limit(20);

    const { data: awayGames, error: awayError } = await supabase
      .from('games')
      .select('id, game_date, home_score, away_score, competition, home_team_master_id, away_team_master_id')
      .eq('away_provider_id', opponentProviderId)
      .eq('provider_id', game.provider_id)
      .is('away_team_master_id', null)
      .order('game_date', { ascending: false })
      .limit(20);

    if (homeError || awayError) {
      console.error('[link-opponent/preview] Query error:', homeError || awayError);
      return NextResponse.json(
        { error: 'Failed to query games' },
        { status: 500 }
      );
    }

    // Get team names for the affected games to show context
    const teamIds = new Set<string>();
    [...(homeGames || []), ...(awayGames || [])].forEach((g) => {
      if (g.home_team_master_id) teamIds.add(g.home_team_master_id);
      if (g.away_team_master_id) teamIds.add(g.away_team_master_id);
    });

    let teamNames: Record<string, string> = {};
    if (teamIds.size > 0) {
      const { data: teams } = await supabase
        .from('teams')
        .select('team_id_master, team_name')
        .in('team_id_master', Array.from(teamIds));

      if (teams) {
        teamNames = Object.fromEntries(
          teams.map((t: { team_id_master: string; team_name: string }) => [t.team_id_master, t.team_name])
        );
      }
    }

    // Define game type for formatting
    type GameRecord = {
      id: string;
      game_date: string;
      home_score: number | null;
      away_score: number | null;
      competition: string | null;
      home_team_master_id: string | null;
      away_team_master_id: string | null;
    };

    // Format games for preview
    const formatGame = (g: GameRecord, isHome: boolean) => ({
      id: g.id,
      gameDate: g.game_date,
      score: g.home_score !== null && g.away_score !== null
        ? `${g.home_score} - ${g.away_score}`
        : 'No score',
      competition: g.competition || 'Unknown',
      opponentPosition: isHome ? 'home' : 'away',
      otherTeam: isHome
        ? (g.away_team_master_id ? teamNames[g.away_team_master_id] || 'Unknown' : 'Unknown')
        : (g.home_team_master_id ? teamNames[g.home_team_master_id] || 'Unknown' : 'Unknown'),
    });

    const affectedGames = [
      ...(homeGames || []).map((g: GameRecord) => formatGame(g, true)),
      ...(awayGames || []).map((g: GameRecord) => formatGame(g, false)),
    ].sort((a, b) => new Date(b.gameDate).getTime() - new Date(a.gameDate).getTime());

    // Get total count (could be more than 20)
    const { count: homeCount } = await supabase
      .from('games')
      .select('id', { count: 'exact', head: true })
      .eq('home_provider_id', opponentProviderId)
      .eq('provider_id', game.provider_id)
      .is('home_team_master_id', null);

    const { count: awayCount } = await supabase
      .from('games')
      .select('id', { count: 'exact', head: true })
      .eq('away_provider_id', opponentProviderId)
      .eq('provider_id', game.provider_id)
      .is('away_team_master_id', null);

    return NextResponse.json({
      success: true,
      opponentProviderId,
      providerId: game.provider_id,
      providerName,
      totalGamesAffected: (homeCount || 0) + (awayCount || 0),
      asHomeTeam: homeCount || 0,
      asAwayTeam: awayCount || 0,
      previewGames: affectedGames.slice(0, 10), // Show first 10 for preview
    });
  } catch (error) {
    console.error('[link-opponent/preview] Unexpected error:', error);
    return NextResponse.json(
      { error: 'An unexpected error occurred' },
      { status: 500 }
    );
  }
}
