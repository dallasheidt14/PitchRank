import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { Team, RankingWithTeam, TeamTrajectory, GameWithTeams } from './types';

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
 * Get a single team by team_id_master UUID
 * @param id - team_id_master UUID
 * @returns React Query hook result with team data
 */
export function useTeam(id: string) {
  console.log('[useTeam] Hook called with id:', id);
  const query = useQuery<Team>({
    queryKey: ['team', id],
    queryFn: async () => {
      console.log('[useTeam] Query function executing with id:', id);
      const result = await api.getTeam(id);
      console.log('[useTeam] Query function returned:', result?.team_name);
      return result;
    },
    enabled: !!id, // Only run query if id is provided
    staleTime: 10 * 60 * 1000, // 10 minutes
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
    retry: 1, // Retry once on failure
  });
  
  console.log('[useTeam] Query state:', {
    id,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    data: query.data ? { name: query.data.team_name } : null,
    queryKey: ['team', id],
  });
  
  return query;
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
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
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
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
  });
}

