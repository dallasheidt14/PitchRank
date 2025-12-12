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
    // Paginate to get all results (Supabase default limit is 1000)
    const BATCH_SIZE = 1000;
    const allResults: RankingWithTeam[] = [];
    let offset = 0;
    let hasMore = true;

    const table = region ? 'state_rankings_view' : 'rankings_view';
    const normalizedRegion = region?.toUpperCase();
    let normalizedAge: number | null = null;

    if (ageGroup) {
      normalizedAge = normalizeAgeGroup(ageGroup);
    }

    while (hasMore) {
      let query = supabase.from(table).select('*')
        .in('status', ['Active', 'Not Enough Ranked Games']); // Include Active and teams with not enough games, exclude Inactive (>180 days since last game)

      if (normalizedAge !== null) {
        query = query.eq('age', normalizedAge);
      }

      if (gender) {
        query = query.eq('gender', gender);
      }

      if (region) {
        query = query.eq('state', normalizedRegion);
      }

      // Sort by ML-adjusted score and paginate
      query = query
        .order('power_score_final', { ascending: false })
        .range(offset, offset + BATCH_SIZE - 1);

      const { data, error } = await query;

      if (error) {
        console.error(`Error fetching rankings from ${table}:`, error);
        throw error;
      }

      if (!data || data.length === 0) {
        hasMore = false;
      } else {
        allResults.push(...(data as RankingWithTeam[]));
        if (data.length < BATCH_SIZE) {
          hasMore = false;
        } else {
          offset += BATCH_SIZE;
        }
      }
    }

    return allResults;
  },

  /**
   * Get a single team by team_id_master UUID with ranking data
   * @param id - team_id_master UUID
   * @returns TeamWithRanking object (Team + Ranking data from rankings_view)
   */
  async getTeam(id: string): Promise<TeamWithRanking> {
    // Fetch team data
    const { data: teamData, error: teamError } = await supabase
      .from('teams')
      .select('*')
      .eq('team_id_master', id)
      .maybeSingle();

    if (teamError) {
      console.error('[api.getTeam] Error:', teamError.message);
      throw teamError;
    }

    if (!teamData) {
      throw new Error(`Team with id ${id} not found`);
    }

    // Fetch ranking data from rankings_view with explicit field list
    const { data: rankingData, error: rankingError } = await supabase
      .from('rankings_view')
      .select('*')
      .eq('team_id_master', id)
      .maybeSingle();

    if (rankingError) {
      console.warn('[api.getTeam] rankings_view error, continuing without ranking data:', rankingError.message);
    }

    // Fetch state rank and SOS rank from state_rankings_view
    const { data: stateRankData, error: stateRankError } = await supabase
      .from('state_rankings_view')
      .select('*')
      .eq('team_id_master', id)
      .maybeSingle();

    if (stateRankError) {
      console.warn('[api.getTeam] state_rankings_view error, continuing without state ranking data:', stateRankError.message);
    }

    // Fallback: If views returned no data, try querying rankings_full directly
    // This handles cases where teams exist in rankings_full but are filtered out by view WHERE clauses
    let rankingsFullData = null;
    if (!rankingData && !stateRankData) {
      const { data: rfData, error: rfError } = await supabase
        .from('rankings_full')
        .select('*')
        .eq('team_id', id)
        .maybeSingle();
      
      if (!rfError && rfData) {
        rankingsFullData = rfData;
        console.log('[api.getTeam] Found team in rankings_full directly (not in views)');
      }
    }

    // Fetch all games to calculate total games and win/loss/draw record
    const { data: gamesData, error: gamesDataError } = await supabase
      .from('games')
      .select('home_team_master_id, away_team_master_id, home_score, away_score')
      .or(`home_team_master_id.eq.${id},away_team_master_id.eq.${id}`);

    // Calculate total games count and win/loss/draw record from games
    const totalGamesCount = gamesData?.length ?? 0;
    let calculatedWins = 0;
    let calculatedLosses = 0;
    let calculatedDraws = 0;

    if (gamesData && gamesData.length > 0) {
      gamesData.forEach(game => {
        if (game.home_score !== null && game.away_score !== null) {
          const isHome = game.home_team_master_id === id;
          const teamScore = isHome ? game.home_score : game.away_score;
          const opponentScore = isHome ? game.away_score : game.home_score;

          if (teamScore > opponentScore) {
            calculatedWins++;
          } else if (teamScore < opponentScore) {
            calculatedLosses++;
          } else {
            calculatedDraws++;
          }
        }
      });
    }

    // Calculate win percentage
    const calculatedWinPercentage = totalGamesCount > 0
      ? ((calculatedWins + calculatedDraws * 0.5) / totalGamesCount) * 100
      : null;

    // Use calculated values if ranking data is missing or 0
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
    // Ensure age is always set (from rankingData, rankingsFullData, or converted from team.age_group)
    const age = rankingData?.age ?? 
      (rankingsFullData?.age_group ? normalizeAgeGroup(rankingsFullData.age_group) : null) ??
      (team.age_group ? normalizeAgeGroup(team.age_group) : null);
    
    // Normalize gender from various sources
    const genderFromRankings = rankingData?.gender ?? 
      (rankingsFullData?.gender ? (rankingsFullData.gender === 'Male' ? 'M' : rankingsFullData.gender === 'Female' ? 'F' : rankingsFullData.gender === 'Boys' ? 'M' : rankingsFullData.gender === 'Girls' ? 'F' : rankingsFullData.gender) : null);
    const gender = genderFromRankings ?? (team.gender === 'Male' ? 'M' : team.gender === 'Female' ? 'F' : 'M') as 'M' | 'F' | 'B' | 'G';

    // Create TeamWithRanking with state rank, total games, and calculated record
    // Use rankings_full as final fallback if views didn't return data
    const powerScoreFinal =
      rankingData?.power_score_final ??
      rankingData?.power_score ??
      stateRankData?.power_score_final ??
      stateRankData?.power_score ??
      rankingsFullData?.power_score_final ??
      null;

    const sosNorm =
      rankingData?.sos_norm ??
      rankingData?.strength_of_schedule ??
      stateRankData?.sos_norm ??
      rankingsFullData?.sos_norm ??
      null;

    const offenseNorm =
      rankingData?.offense_norm ??
      rankingData?.offense ??
      stateRankData?.offense_norm ??
      stateRankData?.offense ??
      rankingsFullData?.off_norm ??
      null;

    const defenseNorm =
      rankingData?.defense_norm ??
      rankingData?.defense ??
      stateRankData?.defense_norm ??
      stateRankData?.defense ??
      rankingsFullData?.def_norm ??
      null;

    const rankInCohortFinal =
      rankingData?.rank_in_cohort_final ??
      rankingData?.national_rank ??
      stateRankData?.rank_in_cohort_final ??
      stateRankData?.national_rank ??
      rankingsFullData?.rank_in_cohort_final ??
      null;

    // Compute rank_in_state_final with status filter to match rankings list display
    // IMPORTANT: The rankings list filters by status, so we must compute ranks the same way
    // to ensure consistency between list view and comparison view
    // The state_rankings_view computes ranks for ALL teams (including inactive),
    // but the rankings list only shows Active/Not Enough Ranked Games teams
    let rankInStateFinal: number | null = null;
    
    if (rankingData && rankingData.state && rankingData.age && rankingData.gender && powerScoreFinal !== null) {
      // Always recompute state rank with status filter to match rankings list
      // This ensures inactive teams don't affect the displayed ranks
      const { data: stateRankings, error: stateRankError } = await supabase
        .from('state_rankings_view')
        .select('team_id_master, power_score_final, status')
        .eq('state', rankingData.state)
        .eq('age', rankingData.age)
        .eq('gender', rankingData.gender)
        .in('status', ['Active', 'Not Enough Ranked Games']) // Match rankings list filter
        .gt('power_score_final', powerScoreFinal)
        .limit(10000); // Reasonable limit
      
      if (!stateRankError && stateRankings) {
        // Rank is 1 + number of teams with higher power score (only counting Active/Not Enough Ranked Games teams)
        rankInStateFinal = stateRankings.length + 1;
      } else if (stateRankError) {
        console.warn('[api.getTeam] Error computing filtered state rank, falling back to view rank:', stateRankError.message);
        // Fallback to rank from view if computation fails
        rankInStateFinal = stateRankData?.rank_in_state_final ?? stateRankData?.state_rank ?? null;
      }
    } else {
      // Fallback if we don't have enough data to compute
      rankInStateFinal = stateRankData?.rank_in_state_final ?? stateRankData?.state_rank ?? null;
    }

    const gamesPlayed =
      rankingData?.games_played ??
      rankingData?.games ??
      stateRankData?.games_played ??
      stateRankData?.games ??
      rankingsFullData?.games_played ??
      0;

    const winsValue =
      rankingData?.wins ??
      stateRankData?.wins ??
      rankingsFullData?.wins ??
      calculatedWins;

    const lossesValue =
      rankingData?.losses ??
      stateRankData?.losses ??
      rankingsFullData?.losses ??
      calculatedLosses;

    const drawsValue =
      rankingData?.draws ??
      stateRankData?.draws ??
      rankingsFullData?.draws ??
      calculatedDraws;

    const winPctValue =
      rankingData?.win_percentage ??
      rankingData?.win_pct ??
      stateRankData?.win_percentage ??
      stateRankData?.win_pct ??
      calculatedWinPercentage;

    // Compute sos_rank_state with status filter to match rankings list display
    // Similar to state rank, SOS ranks are pre-calculated for ALL teams (including inactive)
    // but the rankings list only shows Active/Not Enough Ranked Games teams
    let sosRankState: number | null = null;
    const sosNormState = stateRankData?.sos_norm_state ?? null;
    
    if (rankingData && rankingData.state && rankingData.age && rankingData.gender && sosNormState !== null) {
      // Recompute SOS rank with status filter to match rankings list
      const { data: sosRankings, error: sosRankError } = await supabase
        .from('state_rankings_view')
        .select('team_id_master, sos_norm_state, status')
        .eq('state', rankingData.state)
        .eq('age', rankingData.age)
        .eq('gender', rankingData.gender)
        .in('status', ['Active', 'Not Enough Ranked Games']) // Match rankings list filter
        .gt('sos_norm_state', sosNormState)
        .limit(10000);
      
      if (!sosRankError && sosRankings) {
        // Rank is 1 + number of teams with higher SOS (only counting Active/Not Enough Ranked Games teams)
        sosRankState = sosRankings.length + 1;
      } else if (sosRankError) {
        console.warn('[api.getTeam] Error computing filtered SOS rank, falling back to view rank:', sosRankError.message);
        // Fallback to rank from view if computation fails
        sosRankState = stateRankData?.sos_rank_state ?? stateRankData?.state_sos_rank ?? rankingData?.sos_rank_state ?? null;
      }
    } else {
      // Fallback if we don't have enough data to compute
      sosRankState = stateRankData?.sos_rank_state ?? stateRankData?.state_sos_rank ?? rankingData?.sos_rank_state ?? null;
    }

    const teamWithRanking: TeamWithRanking = {
      team_id_master: team.team_id_master,
      team_name: team.team_name,
      club_name: team.club_name,
      state: rankingData?.state ?? team.state_code,
      age: age,
      gender: gender,
      // Ranking fields (default to null if no ranking data)
      power_score_final: powerScoreFinal,
      sos_norm: sosNorm,
      sos_norm_state: sosNormState,
      sos_rank_national: rankingData?.sos_rank_national ?? rankingData?.national_sos_rank ?? null,
      sos_rank_state: sosRankState,
      offense_norm: offenseNorm,
      defense_norm: defenseNorm,
      rank_in_cohort_final: rankInCohortFinal,
      rank_in_state_final: rankInStateFinal,
      // Record fields (use calculated values as fallback)
      games_played: gamesPlayed,
      wins: winsValue,
      losses: lossesValue,
      draws: drawsValue,
      win_percentage: winPctValue,
      // Total games and record from games table
      total_games_played: totalGamesCount,
      total_wins: calculatedWins,
      total_losses: calculatedLosses,
      total_draws: calculatedDraws,
    };

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
    // Step 1: Resolve team ID to canonical (in case this team was merged)
    let canonicalTeamId = id;
    const { data: mergeData } = await supabase
      .from('team_merge_map')
      .select('canonical_team_id')
      .eq('deprecated_team_id', id)
      .maybeSingle();
    
    if (mergeData?.canonical_team_id) {
      canonicalTeamId = mergeData.canonical_team_id;
    }

    // Step 2: Get all deprecated team IDs that merge into this canonical team
    const { data: mergedTeams } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id')
      .eq('canonical_team_id', canonicalTeamId);
    
    // Build list of all team IDs to query (canonical + all deprecated teams merged into it)
    const teamIdsToQuery = [canonicalTeamId];
    if (mergedTeams && mergedTeams.length > 0) {
      mergedTeams.forEach((merge: { deprecated_team_id: string }) => {
        if (merge.deprecated_team_id) {
          teamIdsToQuery.push(merge.deprecated_team_id);
        }
      });
    }

    // Safety check: ensure we have at least one team ID to query
    if (teamIdsToQuery.length === 0) {
      return { games: [], lastScrapedAt: null };
    }

    // Step 3: Query games for all team IDs (canonical + merged teams)
    // Build OR conditions for all team IDs
    const orConditions = teamIdsToQuery
      .map((teamId) => `home_team_master_id.eq.${teamId},away_team_master_id.eq.${teamId}`)
      .join(',');
    
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('*')
      .or(orConditions)
      .order('game_date', { ascending: false })
      .limit(limit);

    if (gamesError) {
      console.error('[api.getTeamGames] Error:', gamesError.message);
      throw gamesError;
    }

    if (!games || games.length === 0) {
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

    return {
      games: enrichedGames,
      lastScrapedAt: mostRecentScrapedAt,
    };
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

  /**
  /**
   * Get enhanced match prediction with explanations
   * @param teamAId - First team's team_id_master UUID
   * @param teamBId - Second team's team_id_master UUID
   * @returns Prediction with explanations
   */
  async getMatchPrediction(teamAId: string, teamBId: string) {
    // Import prediction modules (dynamic to avoid circular dependencies)
    const { predictMatch } = await import('./matchPredictor');
    const { explainMatch } = await import('./matchExplainer');

    // Fetch team data
    const teamA = await this.getTeam(teamAId);
    const teamB = await this.getTeam(teamBId);

    // Fetch recent games for form calculation (last 60 days, only for Team A/B)
    // This optimized query only fetches games involving the two teams being compared,
    // eliminating the need for a hard limit and ensuring we get all relevant games
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - 60);

    const { data: gamesData, error: gamesError } = await supabase
      .from('games')
      .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
      .gte('game_date', cutoffDate.toISOString().split('T')[0])
      .not('home_score', 'is', null)
      .not('away_score', 'is', null)
      .or(`home_team_master_id.in.(${teamAId},${teamBId}),away_team_master_id.in.(${teamAId},${teamBId})`)
      .order('game_date', { ascending: false });

    if (gamesError) {
      console.error('[api.getMatchPrediction] Error fetching games:', gamesError);
      throw gamesError;
    }

    // Type assertion: We only need these fields for prediction
    // The full Game type has more fields, but predictMatch only uses these
    const games = (gamesData || []) as Game[];

    // Generate prediction
    const prediction = predictMatch(teamA, teamB, games);

    // Generate explanations
    const explanation = explainMatch(teamA, teamB, prediction);

    return {
      teamA: {
        team_id_master: teamA.team_id_master,
        team_name: teamA.team_name,
        club_name: teamA.club_name,
      },
      teamB: {
        team_id_master: teamB.team_id_master,
        team_name: teamB.team_name,
        club_name: teamB.club_name,
      },
      prediction,
      explanation,
    };
  },

  /**
   * Get rankings for multiple teams by their team_id_master UUIDs
   * @param teamIds - Array of team_id_master UUIDs
   * @returns Map of team_id_master to ranking data
   */
  async getTeamRankings(teamIds: string[]): Promise<Map<string, {
    power_score_final: number;
    rank_in_cohort_final: number;
    sos_norm: number;
  }>> {
    if (teamIds.length === 0) {
      return new Map();
    }

    const { data, error } = await supabase
      .from('rankings_view')
      .select('team_id_master, power_score_final, rank_in_cohort_final, sos_norm')
      .in('team_id_master', teamIds);

    if (error) {
      console.error('[api.getTeamRankings] Error fetching rankings:', error);
      throw error;
    }

    const rankingsMap = new Map<string, {
      power_score_final: number;
      rank_in_cohort_final: number;
      sos_norm: number;
    }>();

    data?.forEach((ranking: {
      team_id_master: string;
      power_score_final: number;
      rank_in_cohort_final: number;
      sos_norm: number;
    }) => {
      rankingsMap.set(ranking.team_id_master, {
        power_score_final: ranking.power_score_final,
        rank_in_cohort_final: ranking.rank_in_cohort_final,
        sos_norm: ranking.sos_norm,
      });
    });

    return rankingsMap;
  },

  /**
   * Get database statistics for the homepage
   * @returns Object with totalGames and totalTeams counts
   */
  async getDbStats(): Promise<{ totalGames: number; totalTeams: number }> {
    // Get total games count (only games with valid team IDs and scores)
    const { count: gamesCount, error: gamesError } = await supabase
      .from('games')
      .select('*', { count: 'exact', head: true })
      .not('home_team_master_id', 'is', null)
      .not('away_team_master_id', 'is', null)
      .not('home_score', 'is', null)
      .not('away_score', 'is', null);

    if (gamesError) {
      console.error('Error fetching games count:', gamesError);
      throw gamesError;
    }

    // Get total ranked teams count from rankings_full (faster than view)
    const { count: teamsCount, error: teamsError } = await supabase
      .from('rankings_full')
      .select('*', { count: 'exact', head: true })
      .not('power_score_final', 'is', null);

    if (teamsError) {
      console.error('Error fetching teams count:', teamsError);
      throw teamsError;
    }

    return {
      totalGames: gamesCount || 0,
      totalTeams: teamsCount || 0,
    };
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

