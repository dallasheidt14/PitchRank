import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { MatchPredictionResponse } from './matchPredictionService';
import type { TeamTrajectory, GameWithTeams, GameExplainability, TeamWithRanking, RankHistoryPoint } from './types';

/**
 * React Query hooks for data fetching
 * These hooks provide caching, refetching, and error handling
 *
 * Caching Strategy:
 * - Rankings: 5 minutes stale time (data updates weekly)
 * - Team details: 10 minutes stale time
 * - Team games: 2 minutes stale time (more frequently updated)
 * - Team trajectory: 5 minutes stale time (calculated from games)
 *
 * Error Handling:
 * - All hooks use React Query's built-in error handling
 * - Errors are available via the `error` property in the hook return value
 * - Use `isError` and `error` to handle error states in components
 *
 * Prefetching:
 * - Use `queryClient.prefetchQuery()` to prefetch data before navigation
 * - Example: Prefetch team data when hovering over a team link
 */

// useRankings has been moved to @/hooks/useRankings
// Re-export for backward compatibility during migration
export { useRankings } from '@/hooks/useRankings';

/**
 * Get a single team by team_id_master UUID with ranking data
 * @param id - team_id_master UUID
 * @returns React Query hook result with TeamWithRanking data
 */
export function useTeam(id: string) {
  return useQuery<TeamWithRanking>({
    queryKey: ['team', id],
    queryFn: () => api.getTeam(id),
    enabled: !!id, // Only run query if id is provided
    staleTime: 15 * 60 * 1000, // 15 minutes (team data changes infrequently)
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
    retry: 1, // Retry once on failure
    throwOnError: false, // Never throw to error boundaries (React 19 compat)
  });
}

/**
 * Get team trajectory - performance over time periods
 * @param id - team_id_master UUID
 * @param periodDays - Number of days per period (default: 30)
 * @returns React Query hook result with trajectory data
 */
export function useTeamTrajectory(id: string, periodDays: number = 30) {
  return useQuery<TeamTrajectory[]>({
    queryKey: ['team-trajectory', id, periodDays],
    queryFn: () => api.getTeamTrajectory(id, periodDays),
    enabled: !!id,
    staleTime: 15 * 60 * 1000, // 15 minutes (calculated from games, updates weekly)
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
    retry: 1, // Retry once on failure (overrides global network-only retry)
  });
}

/**
 * Get games for a specific team
 * @param id - team_id_master UUID
 * @param limit - Maximum number of games to return (default: 50)
 * @returns React Query hook result with games data and lastScrapedAt date
 */
export function useTeamGames(id: string, limit: number = 50) {
  return useQuery<{ games: GameWithTeams[]; lastScrapedAt: string | null }>({
    queryKey: ['team-games', id, limit],
    queryFn: async () => {
      const result = await api.getTeamGames(id, limit);
      return result;
    },
    enabled: !!id,
    staleTime: 2 * 60 * 1000, // 2 minutes - games update more frequently
    gcTime: 15 * 60 * 1000, // Keep in cache for 15 minutes
    retry: 1, // Retry once on failure (overrides global network-only retry)
    throwOnError: false, // Never throw to error boundaries (React 19 compat)
  });
}

/**
 * Get persisted explainability rows for a team's visible games.
 * This uses a server route rather than direct browser-side Supabase.
 */
export function useGameExplainability(teamId: string, gameIds: string[], enabled: boolean) {
  const uniqueGameIds = Array.from(new Set(gameIds.filter(Boolean)));

  return useQuery<GameExplainability[]>({
    queryKey: ['game-explainability', teamId, uniqueGameIds],
    queryFn: () => api.getGameExplainability(teamId, uniqueGameIds),
    enabled: enabled && !!teamId && uniqueGameIds.length > 0,
    staleTime: 2 * 60 * 1000,
    gcTime: 15 * 60 * 1000,
    retry: 1,
    throwOnError: false,
  });
}

/**
 * Get ranking history for a team (weekly Monday snapshots, up to 12 months)
 * @param id - team_id_master UUID
 * @returns React Query hook result with RankHistoryPoint[]
 */
export function useRankHistory(id: string) {
  return useQuery<RankHistoryPoint[]>({
    queryKey: ['rank-history', id],
    queryFn: () => api.getRankHistory(id),
    enabled: !!id,
    staleTime: 30 * 60 * 1000, // 30 minutes (rankings update weekly on Mondays)
    gcTime: 60 * 60 * 1000, // 1 hour cache
    retry: 1,
  });
}

/**
 * Helper hook to prefetch team data
 * Useful for prefetching when hovering over team links
 */
export function usePrefetchTeam() {
  const queryClient = useQueryClient();

  return (id: string) => {
    queryClient.prefetchQuery({
      queryKey: ['team', id],
      queryFn: () => api.getTeam(id),
      staleTime: 10 * 60 * 1000,
    });
  };
}

/**
 * Get common opponents between two teams
 * @param team1Id - First team's team_id_master UUID
 * @param team2Id - Second team's team_id_master UUID
 * @returns React Query hook result with common opponents data
 */
export function useCommonOpponents(team1Id: string | null, team2Id: string | null) {
  return useQuery({
    queryKey: ['common-opponents', team1Id, team2Id],
    queryFn: () => api.getCommonOpponents(team1Id!, team2Id!),
    enabled: !!team1Id && !!team2Id && team1Id !== team2Id,
    staleTime: 30 * 60 * 1000, // 30 minutes (expensive query, game data updates weekly)
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });
}

/**
 * Get enhanced match prediction with explanations
 * @param teamAId - First team's team_id_master UUID
 * @param teamBId - Second team's team_id_master UUID
 * @returns React Query hook result with prediction and explanations
 */
export function useMatchPrediction(teamAId: string | null, teamBId: string | null) {
  return useQuery<MatchPredictionResponse | null>({
    queryKey: ['match-prediction', teamAId, teamBId],
    queryFn: () => api.getMatchPrediction(teamAId!, teamBId!),
    enabled: !!teamAId && !!teamBId && teamAId !== teamBId,
    staleTime: 15 * 60 * 1000, // 15 minutes (predictions based on weekly rankings)
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
    retry: false,
    throwOnError: false,
  });
}
