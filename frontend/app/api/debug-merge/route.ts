import { NextRequest, NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';

/**
 * GET /api/debug-merge?team=<uuid>
 * Diagnostic: check merge map, games, and alias data for a team
 */
export async function GET(request: NextRequest) {
  const teamId = request.nextUrl.searchParams.get('team');
  if (!teamId) {
    return NextResponse.json({ error: 'Missing ?team= param' }, { status: 400 });
  }

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!supabaseUrl || !supabaseAnonKey) {
    return NextResponse.json({ error: 'Missing env' }, { status: 500 });
  }

  const supabase = createClient(supabaseUrl, supabaseAnonKey);

  // Check merge map in both directions, team info, and games
  const [asDeprecated, asCanonical, teamInfo, homeGames, awayGames] = await Promise.all([
    supabase
      .from('team_merge_map')
      .select('id,deprecated_team_id,canonical_team_id,created_at')
      .eq('deprecated_team_id', teamId),
    supabase
      .from('team_merge_map')
      .select('id,deprecated_team_id,canonical_team_id,created_at')
      .eq('canonical_team_id', teamId),
    supabase
      .from('teams')
      .select('team_id_master,team_name,club_name,is_deprecated')
      .eq('team_id_master', teamId)
      .maybeSingle(),
    supabase
      .from('games')
      .select('id,game_date,competition,home_score,away_score,home_team_master_id,away_team_master_id,is_excluded')
      .eq('home_team_master_id', teamId)
      .eq('is_excluded', false)
      .ilike('competition', '%Playmaker%')
      .order('game_date', { ascending: false })
      .limit(10),
    supabase
      .from('games')
      .select('id,game_date,competition,home_score,away_score,home_team_master_id,away_team_master_id,is_excluded')
      .eq('away_team_master_id', teamId)
      .eq('is_excluded', false)
      .ilike('competition', '%Playmaker%')
      .order('game_date', { ascending: false })
      .limit(10),
  ]);

  return NextResponse.json({
    teamId,
    team: teamInfo.data,
    mergeMap: {
      asDeprecated: asDeprecated.data || [],
      asCanonical: asCanonical.data || [],
    },
    playmakerGames: {
      asHome: homeGames.data || [],
      asAway: awayGames.data || [],
    },
  });
}
