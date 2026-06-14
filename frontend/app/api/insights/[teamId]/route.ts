import { requirePremium } from '@/lib/api/requirePremium';
import { resolveMergedTeamIds } from '@/lib/team-merge';
import { isValidUuid } from '@/lib/validation';
import { NextResponse } from 'next/server';
import { generateAllInsights, type InsightInputData, type TeamInsightsResponse } from '@/lib/insights';

/**
 * GET /api/insights/[teamId]
 *
 * Generates team insights based on performance data.
 * Premium-only endpoint.
 *
 * Returns:
 * - Season Truth Summary (narrative)
 * - Consistency Score (0-100)
 * - Persona Label (Giant Killer, Flat Track Bully, Gatekeeper, Wildcard)
 */
export async function GET(req: Request, { params }: { params: Promise<{ teamId: string }> }) {
  try {
    const { teamId } = await params;
    const auth = await requirePremium();
    if (auth.error) return auth.error;
    const { supabase } = auth;

    // Validate team ID format
    if (!isValidUuid(teamId)) {
      return NextResponse.json({ error: 'Invalid team ID' }, { status: 400 });
    }

    // Fetch team data
    const { data: team, error: teamError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, state_code, gender')
      .eq('team_id_master', teamId)
      .single();

    if (teamError || !team) {
      return NextResponse.json({ error: 'Team not found' }, { status: 404 });
    }

    // Fetch ranking data including v53e metrics (offense_norm, defense_norm, perf_centered)
    const { data: ranking, error: rankingError } = await supabase
      .from('rankings_view')
      .select('*, offense_norm, defense_norm, perf_centered')
      .eq('team_id_master', teamId)
      .single();

    if (rankingError && rankingError.code !== 'PGRST116') {
      console.error('Error fetching ranking:', rankingError);
    }

    // Resolve merged team IDs so games stored under deprecated IDs are included
    // (without this, streak/consistency stop at the first pre-merge gap).
    const { teamIdsToQuery, teamIdList } = await resolveMergedTeamIds(supabase, teamId);

    // Fetch games with opponent rankings (across canonical + all merged team IDs)
    const orConditions = teamIdList
      .map((tid) => `home_team_master_id.eq.${tid},away_team_master_id.eq.${tid}`)
      .join(',');
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('game_date, home_team_master_id, away_team_master_id, home_score, away_score')
      .or(orConditions)
      .eq('is_excluded', false)
      .order('game_date', { ascending: false })
      .limit(50);

    if (gamesError) {
      console.error('Error fetching games:', gamesError);
    }

    // Define types for the database responses
    type GameRow = {
      game_date: string;
      home_team_master_id: string | null;
      away_team_master_id: string | null;
      home_score: number | null;
      away_score: number | null;
    };

    type OpponentRankingRow = {
      team_id_master: string;
      rank_in_cohort_final: number | null;
      power_score_final: number | null;
    };

    type RankingHistoryRow = {
      snapshot_date: string;
      rank_in_cohort: number;
      rank_in_cohort_ml: number | null;
      rank_in_cohort_final: number | null;
      power_score_final: number | null;
    };

    type CohortRow = {
      power_score_final: number | null;
    };

    // Get opponent team IDs for ranking lookup
    // Use the merged-id set so a game scraped under a deprecated id still
    // identifies the opponent correctly.
    const opponentIds = new Set<string>();
    ((games || []) as GameRow[]).forEach((game: GameRow) => {
      const homeIsTeam = game.home_team_master_id !== null && teamIdsToQuery.has(game.home_team_master_id);
      const oppId = homeIsTeam ? game.away_team_master_id : game.home_team_master_id;
      if (oppId) opponentIds.add(oppId);
    });

    // Fetch opponent rankings (guard: empty .in() returns all rows in PostgREST)
    let opponentRankings: OpponentRankingRow[] | null = null;
    let oppRankError: { message: string } | null = null;
    if (opponentIds.size > 0) {
      const result = await supabase
        .from('rankings_view')
        .select('team_id_master, rank_in_cohort_final, power_score_final')
        .in('team_id_master', Array.from(opponentIds));
      opponentRankings = result.data as OpponentRankingRow[] | null;
      oppRankError = result.error;
    }

    if (oppRankError) {
      console.error('Error fetching opponent rankings:', oppRankError);
    }

    const oppRankMap = new Map(
      ((opponentRankings || []) as OpponentRankingRow[]).map((opp: OpponentRankingRow) => [
        opp.team_id_master,
        { rank: opp.rank_in_cohort_final, power: opp.power_score_final },
      ])
    );

    // Fetch ranking history
    const { data: rankingHistory, error: historyError } = await supabase
      .from('ranking_history')
      .select('snapshot_date, rank_in_cohort, rank_in_cohort_ml, rank_in_cohort_final, power_score_final')
      .eq('team_id', teamId)
      .order('snapshot_date', { ascending: false })
      .limit(30);

    if (historyError && historyError.code !== 'PGRST116') {
      console.error('Error fetching ranking history:', historyError);
    }

    // PostgREST caps un-ranged selects at 1,000 rows, which silently truncates
    // large cohorts and skews totals/percentiles/medians — page through the set
    const cohortPageSize = 1000;
    async function fetchAllRows<T>(
      buildPage: (from: number, to: number) => PromiseLike<{ data: unknown; error: { message: string } | null }>
    ): Promise<T[] | null> {
      const rows: T[] = [];
      for (let offset = 0; ; offset += cohortPageSize) {
        const { data, error } = await buildPage(offset, offset + cohortPageSize - 1);
        if (error) {
          console.error('Error fetching cohort page:', error);
          return null;
        }
        const batch = (data ?? []) as T[];
        rows.push(...batch);
        if (batch.length < cohortPageSize) break;
      }
      return rows;
    }

    // Get cohort statistics for context
    let cohortStats = {
      totalTeams: 100,
      medianPowerScore: 50,
      percentile: 50,
    };

    if (ranking?.age && ranking?.gender) {
      // Only include Active teams in cohort stats to match v53e ranking logic
      // v53e only assigns rank_in_cohort to Active teams (8+ games in 180 days)
      const cohortData = await fetchAllRows<CohortRow>((from, to) =>
        supabase
          .from('rankings_view')
          .select('power_score_final')
          .eq('age', ranking.age)
          .eq('gender', ranking.gender)
          .eq('status', 'Active')
          .order('power_score_final', { ascending: false })
          .range(from, to)
      );

      if (cohortData && cohortData.length > 0) {
        const scores = (cohortData as CohortRow[])
          .map((d: CohortRow) => d.power_score_final)
          .filter((s: number | null): s is number => s !== null);
        const totalTeams = scores.length;
        const medianPowerScore = scores[Math.floor(scores.length / 2)] || 50;

        // Calculate percentile of current team
        const currentPower = ranking?.power_score_final || 0;
        const teamsBelow = scores.filter((s: number) => s < currentPower).length;
        const percentile = Math.round((teamsBelow / totalTeams) * 100);

        cohortStats = {
          totalTeams,
          medianPowerScore,
          percentile,
        };
      }
    }

    // State-cohort rank (for state-leaderboard persona trait)
    let stateCohort: InsightInputData['stateCohort'] = null;
    if (team.state_code && ranking?.age && ranking?.gender) {
      const stateCohortData = await fetchAllRows<{ team_id_master: string; power_score_final: number | null }>(
        (from, to) =>
          supabase
            .from('rankings_view')
            .select('team_id_master, power_score_final')
            .eq('age', ranking.age)
            .eq('gender', ranking.gender)
            .eq('state', team.state_code)
            .eq('status', 'Active')
            .order('power_score_final', { ascending: false })
            .range(from, to)
      );

      if (stateCohortData && stateCohortData.length >= 5) {
        const idx = stateCohortData.findIndex((r) => r.team_id_master === teamId);
        if (idx >= 0) {
          stateCohort = { rank: idx + 1, totalTeams: stateCohortData.length };
        }
      }
    }

    // Build insight input data
    const insightData: InsightInputData = {
      team: {
        team_id_master: team.team_id_master,
        team_name: team.team_name,
        state: team.state_code,
        age: ranking?.age || null,
        gender: (ranking?.gender || (team.gender === 'Male' ? 'M' : 'F')) as 'M' | 'F' | 'B' | 'G',
      },
      ranking: {
        rank_in_cohort_final: ranking?.rank_in_cohort_final ?? null,
        power_score_final: ranking?.power_score_final ?? null,
        sos_norm: ranking?.sos_norm ?? null,
        wins: ranking?.wins ?? 0,
        losses: ranking?.losses ?? 0,
        draws: ranking?.draws ?? 0,
        games_played: ranking?.games_played ?? 0,
        rank_change_7d: ranking?.rank_change_7d ?? null,
        rank_change_30d: ranking?.rank_change_30d ?? null,
        // v53e metrics for improved insights
        offense_norm: ranking?.offense_norm ?? null,
        defense_norm: ranking?.defense_norm ?? null,
        perf_centered: ranking?.perf_centered ?? null,
      },
      games: ((games || []) as GameRow[]).map((game: GameRow) => {
        const homeIsTeam = game.home_team_master_id !== null && teamIdsToQuery.has(game.home_team_master_id);
        const oppId = homeIsTeam ? game.away_team_master_id : game.home_team_master_id;
        const oppData = oppId ? oppRankMap.get(oppId) : null;

        // Normalize the team's side to the canonical team_id_master so downstream
        // streak/consistency logic (which compares with `===`) treats games scraped
        // under any merged team id as the same team.
        const home_team_master_id = homeIsTeam ? team.team_id_master : game.home_team_master_id;
        const away_team_master_id = homeIsTeam ? game.away_team_master_id : team.team_id_master;

        return {
          game_date: game.game_date,
          home_team_master_id,
          away_team_master_id,
          home_score: game.home_score,
          away_score: game.away_score,
          opponent_rank: oppData?.rank ?? null,
          opponent_power_score: oppData?.power ?? null,
        };
      }),
      rankingHistory: ((rankingHistory || []) as RankingHistoryRow[]).map((h: RankingHistoryRow) => ({
        snapshot_date: h.snapshot_date,
        rank_in_cohort_final: h.rank_in_cohort_final ?? undefined,
        rank_in_cohort_ml: h.rank_in_cohort_ml ?? undefined,
        rank_in_cohort: h.rank_in_cohort,
        power_score_final: h.power_score_final,
      })),
      cohortStats,
      stateCohort,
    };

    // Generate insights
    const insights: TeamInsightsResponse = generateAllInsights(insightData);

    return NextResponse.json(insights);
  } catch (error) {
    console.error('Insights generation error:', error);
    return NextResponse.json({ error: 'Failed to generate insights' }, { status: 500 });
  }
}
