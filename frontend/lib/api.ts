import { supabase } from './supabaseClient';
import { normalizeAgeGroup } from './utils';
import type {
  Team,
  Game,
  RankingWithTeam,
  TeamTrajectory,
  GameWithTeams,
  TeamWithRanking,
} from './types';
import type { TeamPredictive } from '@/types/TeamPredictive';

/**
 * API functions for interacting with Supabase
 * These functions wrap Supabase queries and can be used with React Query
 * All functions are fully typed using TypeScript interfaces
 */

export const api = {
  /**
   * Get rankings filtered by region, age group, and gender
   * @param region - State code (2 letters) or null/undefined for national rankings
   * @param ageGroup - Age group filter (e.g., 'u10', 'u11') - will be normalized to integer
   * @param gender - Gender filter ('M', 'F', 'B', 'G')
   * @returns Array of RankingWithTeam objects
   */
  async getRankings(
    region?: string | null,
    ageGroup?: string,
    gender?: 'M' | 'F' | 'B' | 'G' | null
  ): Promise<RankingWithTeam[]> {
    const table = region ? 'state_rankings_view' : 'rankings_view';
    let query = supabase.from(table).select('*');

    if (ageGroup) {
      // Normalize age group to integer
      const normalizedAge = normalizeAgeGroup(ageGroup);
      if (normalizedAge !== null) {
        query = query.eq('age', normalizedAge);
      }
    }

    if (gender) {
      query = query.eq('gender', gender);
    }

    if (region) {
      query = query.eq('state', region.toUpperCase());
    }

    // Sort by ML-adjusted score
    query = query.order('power_score_final', { ascending: false });

    const { data, error } = await query;

    if (error) {
      console.error(`Error fetching rankings from ${table}:`, error);
      throw error;
    }

    return (data || []) as RankingWithTeam[];
  },

  /**
   * Get a single team by team_id_master UUID with ranking data
   * @param id - team_id_master UUID
   * @returns TeamWithRanking object (Team + Ranking data from rankings_view)
   */
  async getTeam(id: string): Promise<TeamWithRanking> {
    console.log('[api.getTeam] Fetching team with id:', id);
    
    // Fetch team data
    const { data: teamData, error: teamError } = await supabase
      .from('teams')
      .select('*')
      .eq('team_id_master', id)
      .maybeSingle();

    if (teamError) {
      console.error('[api.getTeam] Supabase error:', teamError);
      console.error('[api.getTeam] Error details:', {
        message: teamError.message,
        details: teamError.details,
        hint: teamError.hint,
        code: teamError.code,
      });
      throw teamError;
    }

    if (!teamData) {
      console.warn('[api.getTeam] No team found with id:', id);
      throw new Error(`Team with id ${id} not found`);
    }

    // Fetch ranking data from rankings_view with explicit field list
    const { data: rankingData, error: rankingError } = await supabase
      .from('rankings_view')
      .select('team_id_master, state, age, gender, power_score_final, sos_norm, offense_norm, defense_norm, games_played, wins, losses, draws, win_percentage, rank_in_cohort_final')
      .eq('team_id_master', id)
      .maybeSingle();

    if (rankingError) {
      console.warn('[api.getTeam] Error fetching ranking data:', rankingError);
      // Continue without ranking data rather than failing
    }

    console.log('[api.getTeam] Successfully fetched team:', teamData.team_name);
    console.log('[api.getTeam] Team data structure:', {
      hasId: !!teamData.id,
      hasTeamIdMaster: !!teamData.team_id_master,
      hasTeamName: !!teamData.team_name,
      hasRanking: !!rankingData,
      keys: Object.keys(teamData),
    });
    if (rankingData) {
      console.log('[api.getTeam] Ranking data received:', {
        rank_in_cohort_final: rankingData.rank_in_cohort_final,
        win_percentage: rankingData.win_percentage,
        wins: rankingData.wins,
        losses: rankingData.losses,
        draws: rankingData.draws,
        games_played: rankingData.games_played,
        power_score_final: rankingData.power_score_final,
        sos_norm: rankingData.sos_norm,
        allKeys: Object.keys(rankingData),
      });
    } else {
      console.warn('[api.getTeam] No ranking data found for team:', teamData.team_name);
    }
    
    // Ensure all required Team fields exist
    const team: Team = {
      id: teamData.id,
      team_id_master: teamData.team_id_master,
      provider_team_id: teamData.provider_team_id,
      provider_id: teamData.provider_id,
      team_name: teamData.team_name,
      club_name: teamData.club_name,
      state: teamData.state,
      state_code: teamData.state_code,
      age_group: teamData.age_group,
      birth_year: teamData.birth_year,
      gender: teamData.gender as 'Male' | 'Female',
      created_at: teamData.created_at,
      updated_at: teamData.updated_at,
      last_scraped_at: teamData.last_scraped_at,
    };

    // Merge ranking data if available (match TeamWithRanking contract)
    // Note: rank_in_state_final is NOT in rankings_view, only state_rankings_view
    const teamWithRanking: TeamWithRanking = {
      ...team,
      ...(rankingData && {
        state: rankingData.state ?? team.state,
        age: rankingData.age ?? (team.age_group ? normalizeAgeGroup(team.age_group) : null),
        gender: rankingData.gender ?? (team.gender === 'Male' ? 'M' : team.gender === 'Female' ? 'F' : 'M') as 'M' | 'F' | 'B' | 'G',
        power_score_final: rankingData.power_score_final ?? null,
        sos_norm: rankingData.sos_norm ?? null,
        offense_norm: rankingData.offense_norm ?? null,
        defense_norm: rankingData.defense_norm ?? null,
        games_played: rankingData.games_played ?? 0,
        wins: rankingData.wins ?? 0,
        losses: rankingData.losses ?? 0,
        draws: rankingData.draws ?? 0,
        win_percentage: rankingData.win_percentage ?? null,
        rank_in_cohort_final: rankingData.rank_in_cohort_final ?? null,
        // rank_in_state_final comes from state view, not this call
      }),
    };
    
    console.log('[api.getTeam] Returning team data:', teamWithRanking.team_name);
    return teamWithRanking;
  },

  /**
   * Get team trajectory - performance over time periods
   * This aggregates games into time periods to show trends
   * @param id - team_id_master UUID
   * @param periodDays - Number of days per period (default: 30)
   * @returns Array of trajectory data points
   */
  async getTeamTrajectory(
    id: string,
    periodDays: number = 30
  ): Promise<TeamTrajectory[]> {
    // Get all games for the team
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('*')
      .or(`home_team_master_id.eq.${id},away_team_master_id.eq.${id}`)
      .order('game_date', { ascending: true });

    if (gamesError) {
      console.error('Error fetching team games for trajectory:', gamesError);
      throw gamesError;
    }

    if (!games || games.length === 0) {
      return [];
    }

    // Group games into time periods and calculate metrics
    const trajectory: TeamTrajectory[] = [];
    const sortedGames = (games as Game[]).sort(
      (a, b) => new Date(a.game_date).getTime() - new Date(b.game_date).getTime()
    );

    let periodStart = new Date(sortedGames[0].game_date);
    let periodGames: Game[] = [];

    for (const game of sortedGames) {
      const gameDate = new Date(game.game_date);
      const daysDiff =
        (gameDate.getTime() - periodStart.getTime()) / (1000 * 60 * 60 * 24);

      if (daysDiff >= periodDays && periodGames.length > 0) {
        // Calculate metrics for this period
        const metrics = calculatePeriodMetrics(periodGames, id);
        trajectory.push({
          team_id: id,
          period_start: periodStart.toISOString(),
          period_end: new Date(
            periodStart.getTime() + periodDays * 24 * 60 * 60 * 1000
          ).toISOString(),
          ...metrics,
        });

        // Start new period
        periodStart = gameDate;
        periodGames = [game];
      } else {
        periodGames.push(game);
      }
    }

    // Add final period
    if (periodGames.length > 0) {
      const metrics = calculatePeriodMetrics(periodGames, id);
      trajectory.push({
        team_id: id,
        period_start: periodStart.toISOString(),
        period_end: new Date().toISOString(),
        ...metrics,
      });
    }

    return trajectory;
  },

  /**
   * Get games for a specific team
   * @param id - team_id_master UUID
   * @param limit - Maximum number of games to return (default: 50)
   * @returns Object with games array and lastScrapedAt date
   */
  async getTeamGames(id: string, limit: number = 50): Promise<{
    games: GameWithTeams[];
    lastScrapedAt: string | null;
  }> {
    console.log('[api.getTeamGames] Fetching games for team:', id, 'limit:', limit);
    
    // Get games where team is either home or away
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('*')
      .or(`home_team_master_id.eq.${id},away_team_master_id.eq.${id}`)
      .order('game_date', { ascending: false })
      .limit(limit);

    if (gamesError) {
      console.error('[api.getTeamGames] Error fetching team games:', gamesError);
      throw gamesError;
    }

    console.log('[api.getTeamGames] Raw games data:', {
      gamesCount: games?.length ?? 0,
      hasGames: !!games && games.length > 0,
      firstGame: games?.[0] ? { id: games[0].id, date: games[0].game_date } : null,
    });

    if (!games || games.length === 0) {
      console.log('[api.getTeamGames] No games found for team:', id);
      return { games: [], lastScrapedAt: null };
    }

    // Find the most recent scraped_at date
    const mostRecentScrapedAt = games.reduce((latest, game) => {
      if (!game.scraped_at) return latest;
      if (!latest) return game.scraped_at;
      return new Date(game.scraped_at) > new Date(latest) 
        ? game.scraped_at 
        : latest;
    }, null as string | null);

    // Get team names for home and away teams
    const teamIds = new Set<string>();
    games.forEach((game: Game) => {
      if (game.home_team_master_id) teamIds.add(game.home_team_master_id);
      if (game.away_team_master_id) teamIds.add(game.away_team_master_id);
    });

    const { data: teams, error: teamsError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, club_name')
      .in('team_id_master', Array.from(teamIds));

    if (teamsError) {
      console.error('Error fetching team names:', teamsError);
      // Continue without team names rather than failing
    }

    const teamNameMap = new Map<string, string>();
    const teamClubMap = new Map<string, string | null>();
    teams?.forEach((team: { team_id_master: string; team_name: string; club_name: string | null }) => {
      teamNameMap.set(team.team_id_master, team.team_name);
      teamClubMap.set(team.team_id_master, team.club_name);
    });

    // Enrich games with team names and club names
    const enrichedGames = games.map((game: Game) => ({
      ...game,
      home_team_name: game.home_team_master_id
        ? teamNameMap.get(game.home_team_master_id)
        : undefined,
      away_team_name: game.away_team_master_id
        ? teamNameMap.get(game.away_team_master_id)
        : undefined,
      home_team_club_name: game.home_team_master_id
        ? teamClubMap.get(game.home_team_master_id)
        : undefined,
      away_team_club_name: game.away_team_master_id
        ? teamClubMap.get(game.away_team_master_id)
        : undefined,
    })) as GameWithTeams[];

    const result = {
      games: enrichedGames,
      lastScrapedAt: mostRecentScrapedAt,
    };
    
    console.log('[api.getTeamGames] Returning enriched games:', {
      gamesCount: result.games.length,
      lastScrapedAt: result.lastScrapedAt,
    });
    
    return result;
  },

  /**
   * Get common opponents between two teams
   * @param team1Id - First team's team_id_master UUID
   * @param team2Id - Second team's team_id_master UUID
   * @returns Array of common opponents with game results
   */
  async getCommonOpponents(team1Id: string, team2Id: string): Promise<Array<{
    opponent_id: string;
    opponent_name: string;
    team1_result: 'W' | 'L' | 'D' | null;
    team2_result: 'W' | 'L' | 'D' | null;
    team1_score: number | null;
    team2_score: number | null;
    opponent_score_team1: number | null;
    opponent_score_team2: number | null;
    game_date: string;
  }>> {
    // Get all games for team1
    const { data: team1Games, error: team1Error } = await supabase
      .from('games')
      .select('*')
      .or(`home_team_master_id.eq.${team1Id},away_team_master_id.eq.${team1Id}`)
      .order('game_date', { ascending: false });

    if (team1Error) {
      console.error('Error fetching team1 games:', team1Error);
      throw team1Error;
    }

    // Get all games for team2
    const { data: team2Games, error: team2Error } = await supabase
      .from('games')
      .select('*')
      .or(`home_team_master_id.eq.${team2Id},away_team_master_id.eq.${team2Id}`)
      .order('game_date', { ascending: false });

    if (team2Error) {
      console.error('Error fetching team2 games:', team2Error);
      throw team2Error;
    }

    // Find common opponents
    const team1Opponents = new Map<string, Game>();
    (team1Games as Game[]).forEach((game) => {
      const opponentId = game.home_team_master_id === team1Id 
        ? game.away_team_master_id 
        : game.home_team_master_id;
      if (opponentId && opponentId !== team2Id) {
        if (!team1Opponents.has(opponentId)) {
          team1Opponents.set(opponentId, game);
        }
      }
    });

    const team2Opponents = new Map<string, Game>();
    (team2Games as Game[]).forEach((game) => {
      const opponentId = game.home_team_master_id === team2Id 
        ? game.away_team_master_id 
        : game.home_team_master_id;
      if (opponentId && opponentId !== team1Id) {
        if (!team2Opponents.has(opponentId)) {
          team2Opponents.set(opponentId, game);
        }
      }
    });

    // Find intersection
    const commonOpponentIds = Array.from(team1Opponents.keys()).filter(id => 
      team2Opponents.has(id)
    );

    // Get team names
    const { data: teams } = await supabase
      .from('teams')
      .select('team_id_master, team_name')
      .in('team_id_master', commonOpponentIds);

    const teamMap = new Map<string, string>();
    teams?.forEach((team: { team_id_master: string; team_name: string }) => {
      teamMap.set(team.team_id_master, team.team_name);
    });

    // Build result
    return commonOpponentIds.map(opponentId => {
      const team1Game = team1Opponents.get(opponentId)!;
      const team2Game = team2Opponents.get(opponentId)!;
      
      const team1IsHome = team1Game.home_team_master_id === team1Id;
      const team2IsHome = team2Game.home_team_master_id === team2Id;
      
      const team1Score = team1IsHome ? team1Game.home_score : team1Game.away_score;
      const team1OpponentScore = team1IsHome ? team1Game.away_score : team1Game.home_score;
      const team2Score = team2IsHome ? team2Game.home_score : team2Game.away_score;
      const team2OpponentScore = team2IsHome ? team2Game.away_score : team2Game.home_score;

      const getResult = (teamScore: number | null, oppScore: number | null): 'W' | 'L' | 'D' | null => {
        if (teamScore === null || oppScore === null) return null;
        if (teamScore > oppScore) return 'W';
        if (teamScore < oppScore) return 'L';
        return 'D';
      };

      return {
        opponent_id: opponentId,
        opponent_name: teamMap.get(opponentId) || 'Unknown',
        team1_result: getResult(team1Score, team1OpponentScore),
        team2_result: getResult(team2Score, team2OpponentScore),
        team1_score: team1Score,
        team2_score: team2Score,
        opponent_score_team1: team1OpponentScore,
        opponent_score_team2: team2OpponentScore,
        game_date: team1Game.game_date,
      };
    });
  },

  /**
   * Get predictive match result data for a team
   * @param teamId - team_id_master UUID
   * @returns TeamPredictive object or null if not available
   */
  async getPredictive(teamId: string): Promise<TeamPredictive | null> {
    const { data, error } = await supabase
      .from('team_predictive_view')
      .select('*')
      .eq('team_id_master', teamId)
      .maybeSingle();

    if (error) {
      // Gracefully handle errors (view may not exist in staging/local)
      console.warn('[api.getPredictive] Error fetching predictive data:', error);
      return null;
    }

    // Return null if no data (prevents ComparePanel crash)
    if (!data) return null;

    return data as TeamPredictive;
  },
};

/**
 * Helper function to calculate metrics for a period of games
 */
function calculatePeriodMetrics(
  games: Game[],
  teamId: string
): Omit<TeamTrajectory, 'team_id' | 'period_start' | 'period_end'> {
  let wins = 0;
  let losses = 0;
  let draws = 0;
  let goalsFor = 0;
  let goalsAgainst = 0;

  games.forEach((game) => {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const opponentScore = isHome ? game.away_score : game.home_score;

    if (teamScore !== null && opponentScore !== null) {
      goalsFor += teamScore;
      goalsAgainst += opponentScore;

      if (teamScore > opponentScore) {
        wins++;
      } else if (teamScore < opponentScore) {
        losses++;
      } else {
        draws++;
      }
    }
  });

  const gamesPlayed = wins + losses + draws;
  const winPercentage =
    gamesPlayed > 0 ? (wins / gamesPlayed) * 100 : 0;
  const avgGoalsFor = gamesPlayed > 0 ? goalsFor / gamesPlayed : 0;
  const avgGoalsAgainst = gamesPlayed > 0 ? goalsAgainst / gamesPlayed : 0;

  return {
    games_played: gamesPlayed,
    wins,
    losses,
    draws,
    goals_for: goalsFor,
    goals_against: goalsAgainst,
    win_percentage: winPercentage,
    avg_goals_for: avgGoalsFor,
    avg_goals_against: avgGoalsAgainst,
  };
}

