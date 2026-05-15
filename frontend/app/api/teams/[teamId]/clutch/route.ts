import { requirePremium } from '@/lib/api/requirePremium';
import { NextResponse } from 'next/server';

/**
 * GET /api/teams/[teamId]/clutch
 *
 * Returns the team's record in close vs. blowout games, bucketed by goal
 * differential. Draws (margin 0) are excluded — clutch implies a result.
 * Premium-only endpoint.
 */
export async function GET(req: Request, { params }: { params: Promise<{ teamId: string }> }) {
  try {
    const { teamId } = await params;
    const auth = await requirePremium();
    if (auth.error) return auth.error;
    const { supabase } = auth;

    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(teamId)) {
      return NextResponse.json({ error: 'Invalid team ID' }, { status: 400 });
    }

    // Resolve merged team IDs so games stored under deprecated IDs are included
    // (mirrors /api/insights/[teamId]).
    const { data: incomingMerge } = await supabase
      .from('team_merge_map')
      .select('canonical_team_id')
      .eq('deprecated_team_id', teamId)
      .maybeSingle();
    const canonicalTeamId = (incomingMerge as { canonical_team_id?: string } | null)?.canonical_team_id ?? teamId;

    const { data: mergedTeams } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id')
      .eq('canonical_team_id', canonicalTeamId);

    const teamIdsToQuery = new Set<string>([canonicalTeamId, teamId]);
    ((mergedTeams || []) as { deprecated_team_id: string | null }[]).forEach((m) => {
      if (m.deprecated_team_id) teamIdsToQuery.add(m.deprecated_team_id);
    });
    const teamIdList = Array.from(teamIdsToQuery);

    const orConditions = teamIdList
      .map((tid) => `home_team_master_id.eq.${tid},away_team_master_id.eq.${tid}`)
      .join(',');

    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('home_team_master_id, away_team_master_id, home_score, away_score, game_date')
      .or(orConditions)
      .eq('is_excluded', false)
      .not('home_score', 'is', null)
      .not('away_score', 'is', null)
      .order('game_date', { ascending: false })
      .limit(30);

    if (gamesError) {
      console.error('Error fetching games for clutch factor:', gamesError);
      return NextResponse.json({ error: 'Failed to load games' }, { status: 500 });
    }

    type GameRow = {
      home_team_master_id: string | null;
      away_team_master_id: string | null;
      home_score: number | null;
      away_score: number | null;
    };

    const buckets = {
      oneGoal: { wins: 0, losses: 0 },
      twoGoal: { wins: 0, losses: 0 },
      threePlus: { wins: 0, losses: 0 },
    };

    ((games || []) as GameRow[]).forEach((game) => {
      if (game.home_score === null || game.away_score === null) return;
      const isHome = game.home_team_master_id !== null && teamIdsToQuery.has(game.home_team_master_id);
      const teamScore = isHome ? game.home_score : game.away_score;
      const oppScore = isHome ? game.away_score : game.home_score;
      const margin = Math.abs(teamScore - oppScore);
      if (margin === 0) return;

      const bucket = margin === 1 ? buckets.oneGoal : margin === 2 ? buckets.twoGoal : buckets.threePlus;
      if (teamScore > oppScore) {
        bucket.wins++;
      } else {
        bucket.losses++;
      }
    });

    const toLine = (b: { wins: number; losses: number }) => {
      const total = b.wins + b.losses;
      return {
        wins: b.wins,
        losses: b.losses,
        winPct: total > 0 ? b.wins / total : null,
      };
    };

    return NextResponse.json({
      oneGoal: toLine(buckets.oneGoal),
      twoGoal: toLine(buckets.twoGoal),
      threePlus: toLine(buckets.threePlus),
    });
  } catch (error) {
    console.error('Clutch factor error:', error);
    return NextResponse.json({ error: 'Failed to compute clutch factor' }, { status: 500 });
  }
}
