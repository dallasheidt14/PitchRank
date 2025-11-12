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

/**
 * Get rankings filtered by region, age group, and gender
 * @param region - State code (2 letters) or null/undefined for national rankings
 * @param ageGroup - Age group filter (e.g., 'u10', 'u11')
 * @param gender - Gender filter ('Male' or 'Female')
 * @returns React Query hook result with rankings data
 */
export function useRankings(
  region?: string | null,
  ageGroup?: string,
  gender?: 'Male' | 'Female'
) {
  return useQuery<RankingWithTeam[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    queryFn: () => api.getRankings(region, ageGroup, gender),
    staleTime: 5 * 60 * 1000, // 5 minutes - rankings update weekly
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
  });
}

/**
 * Get a single team by team_id_master UUID
 * @param id - team_id_master UUID
 * @returns React Query hook result with team data
 */
export function useTeam(id: string) {
  return useQuery<Team>({
    queryKey: ['team', id],
    queryFn: () => api.getTeam(id),
    enabled: !!id, // Only run query if id is provided
    staleTime: 10 * 60 * 1000, // 10 minutes
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
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
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
  });
}

/**
 * Get games for a specific team
 * @param id - team_id_master UUID
 * @param limit - Maximum number of games to return (default: 50)
 * @returns React Query hook result with games data
 */
export function useTeamGames(id: string, limit: number = 50) {
  return useQuery<GameWithTeams[]>({
    queryKey: ['team-games', id, limit],
    queryFn: () => api.getTeamGames(id, limit),
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

