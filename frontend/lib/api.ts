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
  /**
   * Get rankings filtered by region (state_code), age group, and gender
   * @param region - State code (2 letters) or null/undefined for national rankings
   * @param ageGroup - Age group filter (e.g., 'u10', 'u11')
   * @param gender - Gender filter ('Male' or 'Female')
   * @returns Array of rankings with team details
   */
  async getRankings(
    region?: string | null,
    ageGroup?: string,
    gender?: 'Male' | 'Female'
  ): Promise<RankingWithTeam[]> {
    // Use the rankings_by_age_gender view which joins teams and current_rankings
    let query = supabase
      .from('rankings_by_age_gender')
      .select('*')
      .order('national_rank', { ascending: true, nullsFirst: false });

    if (region) {
      query = query.eq('state_code', region);
    }

    if (ageGroup) {
      query = query.eq('age_group', ageGroup);
    }

    if (gender) {
      query = query.eq('gender', gender);
    }

    const { data, error } = await query;

    if (error) {
      console.error('Error fetching rankings:', error);
      throw error;
    }

    return (data || []) as RankingWithTeam[];
  },

  /**
   * Get a single team by team_id_master UUID
   * @param id - team_id_master UUID
   * @returns Team object
   */
  async getTeam(id: string): Promise<Team> {
    const { data, error } = await supabase
      .from('teams')
      .select('*')
      .eq('team_id_master', id)
      .single();

    if (error) {
      console.error('Error fetching team:', error);
      throw error;
    }

    if (!data) {
      throw new Error(`Team with id ${id} not found`);
    }

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

