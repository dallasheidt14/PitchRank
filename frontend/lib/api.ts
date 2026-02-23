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
    // Phase 1: Fetch team data, ranking views, and merge map in parallel
    // These are all independent lookups that don't depend on each other
    const [teamResult, rankingResult, stateRankResult, mergeResult] = await Promise.all([
      supabase.from('teams').select('*').eq('team_id_master', id).maybeSingle(),
      supabase.from('rankings_view').select('*').eq('team_id_master', id).maybeSingle(),
      supabase.from('state_rankings_view').select('*').eq('team_id_master', id).maybeSingle(),
      supabase.from('team_merge_map').select('deprecated_team_id').eq('canonical_team_id', id),
    ]);

    const { data: teamData, error: teamError } = teamResult;
    const { data: rankingData, error: rankingError } = rankingResult;
    const { data: stateRankData, error: stateRankError } = stateRankResult;

    if (teamError) {
      console.error('[api.getTeam] Error:', teamError.message);
      throw teamError;
    }

    if (!teamData) {
      throw new Error(`Team with id ${id} not found`);
    }

    if (rankingError) {
      console.warn('[api.getTeam] rankings_view error, continuing without ranking data:', rankingError.message);
    }
    if (stateRankError) {
      console.warn('[api.getTeam] state_rankings_view error, continuing without state ranking data:', stateRankError.message);
    }

    // Fallback: If views returned no data, try querying rankings_full directly
    // Skip this fallback for deprecated teams — they are intentionally excluded from views
    let rankingsFullData = null;
    if (!rankingData && !stateRankData && !teamData?.is_deprecated) {
      const { data: rfData, error: rfError } = await supabase
        .from('rankings_full')
        .select('*')
        .eq('team_id', id)
        .maybeSingle();

      if (!rfError && rfData) {
        rankingsFullData = rfData;
      }
    }

    // Resolve merged team IDs so total games include games from deprecated teams
    const teamIdsForGameCount = [id];
    if (mergeResult.data && mergeResult.data.length > 0) {
      mergeResult.data.forEach((merge: { deprecated_team_id: string }) => {
        if (merge.deprecated_team_id) {
          teamIdsForGameCount.push(merge.deprecated_team_id);
        }
      });
    }

    // Phase 2: Fetch games data (depends on merge map resolution)
    const gameOrConditions = teamIdsForGameCount
      .map((teamId) => `home_team_master_id.eq.${teamId},away_team_master_id.eq.${teamId}`)
      .join(',');

    const { data: gamesData } = await supabase
      .from('games')
      .select('home_team_master_id, away_team_master_id, home_score, away_score')
      .or(gameOrConditions)
      .eq('is_excluded', false);

    // Calculate total games count and win/loss/draw record from games
    const totalGamesCount = gamesData?.length ?? 0;
    let calculatedWins = 0;
    let calculatedLosses = 0;
    let calculatedDraws = 0;

    const teamIdSet = new Set(teamIdsForGameCount);

    if (gamesData && gamesData.length > 0) {
      gamesData.forEach(game => {
        if (game.home_score !== null && game.away_score !== null) {
          const isHome = teamIdSet.has(game.home_team_master_id);
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

    const calculatedWinPercentage = totalGamesCount > 0
      ? ((calculatedWins + calculatedDraws * 0.5) / totalGamesCount) * 100
      : null;

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
    const age = rankingData?.age ??
      (rankingsFullData?.age_group ? normalizeAgeGroup(rankingsFullData.age_group) : null) ??
      (team.age_group ? normalizeAgeGroup(team.age_group) : null);

    const genderFromRankings = rankingData?.gender ??
      (rankingsFullData?.gender ? (rankingsFullData.gender === 'Male' ? 'M' : rankingsFullData.gender === 'Female' ? 'F' : rankingsFullData.gender === 'Boys' ? 'M' : rankingsFullData.gender === 'Girls' ? 'F' : rankingsFullData.gender) : null);
    const gender = genderFromRankings ?? (team.gender === 'Male' ? 'M' : team.gender === 'Female' ? 'F' : 'M') as 'M' | 'F' | 'B' | 'G';

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

    // Compute rank_in_state_final and sos_rank_state using COUNT queries (not fetching rows)
    // This avoids transferring up to 10K rows per query which caused frequent timeouts
    const stateForRank = rankingData?.state ?? stateRankData?.state ?? null;
    const ageForRank = rankingData?.age ?? stateRankData?.age ?? null;
    const genderForRank = rankingData?.gender ?? stateRankData?.gender ?? null;
    const sosNormState = stateRankData?.sos_norm_state ?? null;

    // Phase 3: Compute state rank and SOS rank in parallel using COUNT queries
    let rankInStateFinal: number | null = null;
    let sosRankState: number | null = null;

    if (stateForRank && ageForRank != null && genderForRank) {
      const stateRankPromise = powerScoreFinal !== null
        ? supabase
            .from('state_rankings_view')
            .select('*', { count: 'exact', head: true })
            .eq('state', stateForRank)
            .eq('age', ageForRank)
            .eq('gender', genderForRank)
            .in('status', ['Active', 'Not Enough Ranked Games'])
            .gt('power_score_final', powerScoreFinal)
        : null;

      const sosRankPromise = sosNormState !== null
        ? supabase
            .from('state_rankings_view')
            .select('*', { count: 'exact', head: true })
            .eq('state', stateForRank)
            .eq('age', ageForRank)
            .eq('gender', genderForRank)
            .in('status', ['Active', 'Not Enough Ranked Games'])
            .gt('sos_norm_state', sosNormState)
        : null;

      const [stateRankCount, sosRankCount] = await Promise.all([
        stateRankPromise,
        sosRankPromise,
      ]);

      if (stateRankCount && !stateRankCount.error && stateRankCount.count !== null) {
        rankInStateFinal = stateRankCount.count + 1;
      } else {
        if (stateRankCount?.error) {
          console.warn('[api.getTeam] Error computing filtered state rank, falling back:', stateRankCount.error);
        }
        rankInStateFinal = stateRankData?.rank_in_state_final ?? stateRankData?.state_rank ?? null;
      }

      if (sosRankCount && !sosRankCount.error && sosRankCount.count !== null) {
        sosRankState = sosRankCount.count + 1;
      } else {
        if (sosRankCount?.error) {
          console.warn('[api.getTeam] Error computing filtered SOS rank, falling back:', sosRankCount.error);
        }
        sosRankState = stateRankData?.sos_rank_state ?? stateRankData?.state_sos_rank ?? rankingData?.sos_rank_state ?? null;
      }
    } else {
      rankInStateFinal = stateRankData?.rank_in_state_final ?? stateRankData?.state_rank ?? null;
      sosRankState = stateRankData?.sos_rank_state ?? stateRankData?.state_sos_rank ?? rankingData?.sos_rank_state ?? null;
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

    const teamWithRanking: TeamWithRanking = {
      team_id_master: team.team_id_master,
      team_name: team.team_name,
      club_name: team.club_name,
      state: rankingData?.state ?? team.state_code,
      age: age,
      gender: gender,
      power_score_final: powerScoreFinal,
      sos_norm: sosNorm,
      sos_norm_state: sosNormState,
      sos_rank_national: rankingData?.sos_rank_national ?? rankingData?.national_sos_rank ?? null,
      sos_rank_state: sosRankState,
      offense_norm: offenseNorm,
      defense_norm: defenseNorm,
      rank_in_cohort_final: rankInCohortFinal,
      rank_in_state_final: rankInStateFinal,
      games_played: gamesPlayed,
      wins: winsValue,
      losses: lossesValue,
      draws: drawsValue,
      win_percentage: winPctValue,
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
    // Resolve merged team IDs so trajectory includes games from deprecated teams
    const teamIdsToQuery = [id];
    const { data: mergedTeams } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id')
      .eq('canonical_team_id', id);
    if (mergedTeams) {
      mergedTeams.forEach((merge: { deprecated_team_id: string }) => {
        if (merge.deprecated_team_id) teamIdsToQuery.push(merge.deprecated_team_id);
      });
    }

    // Build OR conditions for all team IDs (canonical + merged)
    const orConditions = teamIdsToQuery
      .map((teamId) => `home_team_master_id.eq.${teamId},away_team_master_id.eq.${teamId}`)
      .join(',');

    // Get all games for the team (including merged teams)
    const { data: games, error: gamesError } = await supabase
      .from('games')
      .select('*')
      .or(orConditions)
      .eq('is_excluded', false)
      .order('game_date', { ascending: true });

    if (gamesError) {
      console.error('Error fetching team games for trajectory:', gamesError);
      throw gamesError;
    }

    if (!games || games.length === 0) {
      return [];
    }

    // Build a Set of all team IDs for this team (canonical + merged)
    const teamIdSet = new Set(teamIdsToQuery);

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
        const metrics = calculatePeriodMetrics(periodGames, id, teamIdSet);
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
      const metrics = calculatePeriodMetrics(periodGames, id, teamIdSet);
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
      .eq('is_excluded', false)
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

    // Step 4: Resolve all team IDs through merge map (for opponents that may be deprecated)
    const teamIdsArray = Array.from(teamIds);
    const { data: mergeMaps } = await supabase
      .from('team_merge_map')
      .select('deprecated_team_id, canonical_team_id')
      .in('deprecated_team_id', teamIdsArray);

    // Create a map of deprecated -> canonical
    const mergeMap = new Map<string, string>();
    if (mergeMaps) {
      mergeMaps.forEach((merge: { deprecated_team_id: string; canonical_team_id: string }) => {
        mergeMap.set(merge.deprecated_team_id, merge.canonical_team_id);
      });
    }

    // Resolve all team IDs to their canonical forms
    const resolvedTeamIds = new Set<string>();
    teamIdsArray.forEach((teamId) => {
      const canonicalId = mergeMap.get(teamId) || teamId;
      resolvedTeamIds.add(canonicalId);
    });

    // Fetch team names for canonical teams
    const { data: teams, error: teamsError } = await supabase
      .from('teams')
      .select('team_id_master, team_name, club_name')
      .in('team_id_master', Array.from(resolvedTeamIds));

    if (teamsError) {
      // Continue without team names rather than failing
    }

    const teamNameMap = new Map<string, string>();
    const teamClubMap = new Map<string, string | null>();
    const teamIdResolutionMap = new Map<string, string>(); // Maps original ID -> canonical ID
    
    // Build resolution map
    teamIdsArray.forEach((teamId) => {
      const canonicalId = mergeMap.get(teamId) || teamId;
      teamIdResolutionMap.set(teamId, canonicalId);
    });

    // Build name maps using canonical IDs
    teams?.forEach((team: { team_id_master: string; team_name: string; club_name: string | null }) => {
      teamNameMap.set(team.team_id_master, team.team_name);
      teamClubMap.set(team.team_id_master, team.club_name);
    });

    // Enrich games with team names and club names, resolving through merges
    const enrichedGames = games.map((game: Game) => {
      // Resolve team IDs to canonical forms
      const homeCanonicalId = game.home_team_master_id 
        ? (teamIdResolutionMap.get(game.home_team_master_id) || game.home_team_master_id)
        : null;
      const awayCanonicalId = game.away_team_master_id
        ? (teamIdResolutionMap.get(game.away_team_master_id) || game.away_team_master_id)
        : null;

      return {
        ...game,
        // Update team IDs to canonical forms for links
        home_team_master_id: homeCanonicalId,
        away_team_master_id: awayCanonicalId,
        // Use canonical IDs to get team names
        home_team_name: homeCanonicalId
          ? teamNameMap.get(homeCanonicalId)
          : undefined,
        away_team_name: awayCanonicalId
          ? teamNameMap.get(awayCanonicalId)
          : undefined,
        home_team_club_name: homeCanonicalId
          ? teamClubMap.get(homeCanonicalId)
          : undefined,
        away_team_club_name: awayCanonicalId
          ? teamClubMap.get(awayCanonicalId)
          : undefined,
      };
    }) as GameWithTeams[];

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
    // Resolve merged team IDs so we find games from deprecated teams too
    const resolveTeamIds = async (teamId: string): Promise<string[]> => {
      const ids = [teamId];
      const { data: mergedTeams } = await supabase
        .from('team_merge_map')
        .select('deprecated_team_id')
        .eq('canonical_team_id', teamId);
      if (mergedTeams) {
        mergedTeams.forEach((merge: { deprecated_team_id: string }) => {
          if (merge.deprecated_team_id) ids.push(merge.deprecated_team_id);
        });
      }
      return ids;
    };

    const [team1Ids, team2Ids] = await Promise.all([
      resolveTeamIds(team1Id),
      resolveTeamIds(team2Id),
    ]);

    const team1IdSet = new Set(team1Ids);
    const team2IdSet = new Set(team2Ids);

    // Build OR conditions for all team IDs
    const team1OrConditions = team1Ids
      .map((id) => `home_team_master_id.eq.${id},away_team_master_id.eq.${id}`)
      .join(',');
    const team2OrConditions = team2Ids
      .map((id) => `home_team_master_id.eq.${id},away_team_master_id.eq.${id}`)
      .join(',');

    // Get all games for team1 and team2 in parallel
    const [team1Result, team2Result] = await Promise.all([
      supabase
        .from('games')
        .select('*')
        .or(team1OrConditions)
        .eq('is_excluded', false)
        .order('game_date', { ascending: false }),
      supabase
        .from('games')
        .select('*')
        .or(team2OrConditions)
        .eq('is_excluded', false)
        .order('game_date', { ascending: false }),
    ]);

    if (team1Result.error) {
      console.error('Error fetching team1 games:', team1Result.error);
      throw team1Result.error;
    }
    if (team2Result.error) {
      console.error('Error fetching team2 games:', team2Result.error);
      throw team2Result.error;
    }

    // Collect all opponent IDs from both teams' games for merge resolution
    const allOpponentIds = new Set<string>();
    const collectOpponents = (games: Game[], teamIdSet: Set<string>) => {
      games.forEach((game) => {
        if (game.home_team_master_id && !teamIdSet.has(game.home_team_master_id)) {
          allOpponentIds.add(game.home_team_master_id);
        }
        if (game.away_team_master_id && !teamIdSet.has(game.away_team_master_id)) {
          allOpponentIds.add(game.away_team_master_id);
        }
      });
    };
    collectOpponents(team1Result.data as Game[], team1IdSet);
    collectOpponents(team2Result.data as Game[], team2IdSet);

    // Resolve opponent IDs through merge map (deprecated -> canonical)
    const opponentIdsArray = Array.from(allOpponentIds);
    const { data: opponentMerges } = opponentIdsArray.length > 0
      ? await supabase
          .from('team_merge_map')
          .select('deprecated_team_id, canonical_team_id')
          .in('deprecated_team_id', opponentIdsArray)
      : { data: null };

    const opponentMergeMap = new Map<string, string>();
    if (opponentMerges) {
      opponentMerges.forEach((merge: { deprecated_team_id: string; canonical_team_id: string }) => {
        opponentMergeMap.set(merge.deprecated_team_id, merge.canonical_team_id);
      });
    }

    // Helper to resolve an opponent ID to its canonical form
    const resolveOpponentId = (id: string): string => opponentMergeMap.get(id) || id;

    // Find common opponents using canonical IDs
    const team1Opponents = new Map<string, Game>();
    (team1Result.data as Game[]).forEach((game) => {
      const isTeam1Home = game.home_team_master_id ? team1IdSet.has(game.home_team_master_id) : false;
      const rawOpponentId = isTeam1Home ? game.away_team_master_id : game.home_team_master_id;
      if (!rawOpponentId) return;
      const canonicalOpponentId = resolveOpponentId(rawOpponentId);
      // Exclude team2 as an opponent
      if (team2IdSet.has(rawOpponentId) || canonicalOpponentId === team2Id) return;
      if (!team1Opponents.has(canonicalOpponentId)) {
        team1Opponents.set(canonicalOpponentId, game);
      }
    });

    const team2Opponents = new Map<string, Game>();
    (team2Result.data as Game[]).forEach((game) => {
      const isTeam2Home = game.home_team_master_id ? team2IdSet.has(game.home_team_master_id) : false;
      const rawOpponentId = isTeam2Home ? game.away_team_master_id : game.home_team_master_id;
      if (!rawOpponentId) return;
      const canonicalOpponentId = resolveOpponentId(rawOpponentId);
      // Exclude team1 as an opponent
      if (team1IdSet.has(rawOpponentId) || canonicalOpponentId === team1Id) return;
      if (!team2Opponents.has(canonicalOpponentId)) {
        team2Opponents.set(canonicalOpponentId, game);
      }
    });

    // Find intersection
    const commonOpponentIds = Array.from(team1Opponents.keys()).filter(id =>
      team2Opponents.has(id)
    );

    // Get team names using canonical IDs
    const { data: teams } = commonOpponentIds.length > 0
      ? await supabase
          .from('teams')
          .select('team_id_master, team_name')
          .in('team_id_master', commonOpponentIds)
      : { data: null };

    const teamMap = new Map<string, string>();
    teams?.forEach((team: { team_id_master: string; team_name: string }) => {
      teamMap.set(team.team_id_master, team.team_name);
    });

    // Build result
    return commonOpponentIds.map(opponentId => {
      const team1Game = team1Opponents.get(opponentId)!;
      const team2Game = team2Opponents.get(opponentId)!;

      const team1IsHome = team1Game.home_team_master_id ? team1IdSet.has(team1Game.home_team_master_id) : false;
      const team2IsHome = team2Game.home_team_master_id ? team2IdSet.has(team2Game.home_team_master_id) : false;

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

    // Resolve merged team IDs so prediction includes games from deprecated teams
    const resolveTeamIds = async (teamId: string): Promise<string[]> => {
      const ids = [teamId];
      const { data: mergedTeams } = await supabase
        .from('team_merge_map')
        .select('deprecated_team_id')
        .eq('canonical_team_id', teamId);
      if (mergedTeams) {
        mergedTeams.forEach((merge: { deprecated_team_id: string }) => {
          if (merge.deprecated_team_id) ids.push(merge.deprecated_team_id);
        });
      }
      return ids;
    };

    const [teamAIds, teamBIds] = await Promise.all([
      resolveTeamIds(teamAId),
      resolveTeamIds(teamBId),
    ]);
    const allTeamIds = [...teamAIds, ...teamBIds];

    // Fetch recent games for form calculation (last 60 days, only for Team A/B + merged IDs)
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - 60);

    const { data: gamesData, error: gamesError } = await supabase
      .from('games')
      .select('id, game_date, home_team_master_id, away_team_master_id, home_score, away_score')
      .gte('game_date', cutoffDate.toISOString().split('T')[0])
      .not('home_score', 'is', null)
      .not('away_score', 'is', null)
      .or(`home_team_master_id.in.(${allTeamIds.join(',')}),away_team_master_id.in.(${allTeamIds.join(',')})`)
      .eq('is_excluded', false)
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
      .not('away_score', 'is', null)
      .eq('is_excluded', false);

    if (gamesError) {
      console.error('Error fetching games count:', gamesError);
      throw gamesError;
    }

    // Get total ranked teams count from rankings_view (only active teams)
    const { count: teamsCount, error: teamsError } = await supabase
      .from('rankings_view')
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
 * @param teamIdSet - Set of all team IDs belonging to this team (canonical + merged)
 */
function calculatePeriodMetrics(
  games: Game[],
  teamId: string,
  teamIdSet?: Set<string>
): Omit<TeamTrajectory, 'team_id' | 'period_start' | 'period_end'> {
  const idSet = teamIdSet || new Set([teamId]);
  let wins = 0;
  let losses = 0;
  let draws = 0;
  let goalsFor = 0;
  let goalsAgainst = 0;

  games.forEach((game) => {
    const isHome = game.home_team_master_id ? idSet.has(game.home_team_master_id) : false;
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
  // Use same formula as main win percentage: (wins + draws * 0.5) / total * 100
  const winPercentage =
    gamesPlayed > 0 ? ((wins + draws * 0.5) / gamesPlayed) * 100 : 0;
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

