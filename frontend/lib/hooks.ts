import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { Team, RankingWithTeam, TeamTrajectory, GameWithTeams, TeamWithRanking } from './types';
import type { TeamPredictive } from '@/types/TeamPredictive';

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
 * Get predictive match result data for a team
 * @param teamId - team_id_master UUID
 * @returns React Query hook result with TeamPredictive data (or null)
 * Non-blocking: returns null if data unavailable (view may not exist in staging/local)
 */
export function usePredictive(teamId: string | null) {
  return useQuery<TeamPredictive | null>({
    queryKey: ['predictive', teamId],
    queryFn: async () => {
      if (!teamId) return null;
      return await api.getPredictive(teamId);
    },
    enabled: !!teamId,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
    retry: false, // Don't retry - gracefully handle missing view
  });
}

/**
 * Get enhanced match prediction with explanations
 * @param teamAId - First team's team_id_master UUID
 * @param teamBId - Second team's team_id_master UUID
 * @returns React Query hook result with prediction and explanations
 */
export function useMatchPrediction(teamAId: string | null, teamBId: string | null) {
  return useQuery({
    queryKey: ['match-prediction', teamAId, teamBId],
    queryFn: () => api.getMatchPrediction(teamAId!, teamBId!),
    enabled: !!teamAId && !!teamBId && teamAId !== teamBId,
    staleTime: 15 * 60 * 1000, // 15 minutes (predictions based on weekly rankings)
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
  });
}

/**
 * Get database statistics: total games and total ranked teams
 * @returns React Query hook result with stats data
 */
export function useDbStats() {
  return useQuery<{ totalGames: number; totalTeams: number }>({
    queryKey: ['db-stats'],
    queryFn: () => api.getDbStats(),
    staleTime: 60 * 60 * 1000, // 1 hour - stats don't change frequently
    gcTime: 24 * 60 * 60 * 1000, // Keep in cache for 24 hours
  });
}

