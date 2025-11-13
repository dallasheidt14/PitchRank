import { supabase } from './supabaseClient';
import type {
  Team,
  Game,
  RankingWithTeam,
  TeamTrajectory,
  GameWithTeams,
} from './types';

/**
 * API functions for interacting with Supabase
 * These functions wrap Supabase queries and can be used with React Query
 * All functions are fully typed using TypeScript interfaces
 */

export const api = {
  // getRankings has been removed - use useRankings hook from @/hooks/useRankings instead
  // This function is deprecated and will be removed in a future version

  /**
   * Get a single team by team_id_master UUID
   * @param id - team_id_master UUID
   * @returns Team object
   */
  async getTeam(id: string): Promise<Team> {
    console.log('[api.getTeam] Fetching team with id:', id);
    
    const { data, error } = await supabase
      .from('teams')
      .select('*')
      .eq('team_id_master', id)
      .maybeSingle();

    if (error) {
      console.error('[api.getTeam] Supabase error:', error);
      console.error('[api.getTeam] Error details:', {
        message: error.message,
        details: error.details,
        hint: error.hint,
        code: error.code,
      });
      throw error;
    }

    if (!data) {
      console.warn('[api.getTeam] No team found with id:', id);
      throw new Error(`Team with id ${id} not found`);
    }

    console.log('[api.getTeam] Successfully fetched team:', data.team_name);
    return data as Team;
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
   * @returns Array of games with team names
   */
  async getTeamGames(id: string, limit: number = 50): Promise<GameWithTeams[]> {
    // Get games where team is either home or away
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('*')
      .or(`home_team_master_id.eq.${id},away_team_master_id.eq.${id}`)
      .order('game_date', { ascending: false })
      .limit(limit);

    if (gamesError) {
      console.error('Error fetching team games:', gamesError);
      throw gamesError;
    }

    if (!games || games.length === 0) {
      return [];
    }

    // Get team names for home and away teams
    const teamIds = new Set<string>();
    games.forEach((game: Game) => {
      if (game.home_team_master_id) teamIds.add(game.home_team_master_id);
      if (game.away_team_master_id) teamIds.add(game.away_team_master_id);
    });

    const { data: teams, error: teamsError } = await supabase
      .from('teams')
      .select('team_id_master, team_name')
      .in('team_id_master', Array.from(teamIds));

    if (teamsError) {
      console.error('Error fetching team names:', teamsError);
      // Continue without team names rather than failing
    }

    const teamMap = new Map<string, string>();
    teams?.forEach((team: { team_id_master: string; team_name: string }) => {
      teamMap.set(team.team_id_master, team.team_name);
    });

    // Enrich games with team names
    return games.map((game: Game) => ({
      ...game,
      home_team_name: game.home_team_master_id
        ? teamMap.get(game.home_team_master_id)
        : undefined,
      away_team_name: game.away_team_master_id
        ? teamMap.get(game.away_team_master_id)
        : undefined,
    })) as GameWithTeams[];
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

