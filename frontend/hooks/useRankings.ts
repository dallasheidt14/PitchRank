import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Get rankings filtered by region, age group, and gender
 * @param region - State code (2 letters) or null/undefined for national rankings
 * @param ageGroup - Age group filter (e.g., 'u10', 'u11') - will be normalized to integer
 * @param gender - Gender filter ('M', 'F', 'B', 'G')
 * @returns React Query hook result with rankings data
 */
export function useRankings(
  region?: string | null,
  ageGroup?: string,
  gender?: 'M' | 'F' | 'B' | 'G' | null
) {
  const queryResult = useQuery<RankingRow[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    enabled: true, // Explicitly enable the query
    queryFn: async () => {
      if (!region) {
        // National rankings = return full slice from rankings_view
        let query = supabase
          .from('rankings_view')
          .select('*')
          .eq('status', 'Active'); // Filter out inactive teams (>180 days since last game)

        let normalizedAge: number | null = null;
        if (ageGroup) {
          // Normalize age group to integer
          normalizedAge = normalizeAgeGroup(ageGroup);
          if (normalizedAge !== null) {
            query = query.eq('age', normalizedAge);
          }
        }

        if (gender) {
          query = query.eq('gender', gender);
        }

        query = query.order('power_score_final', { ascending: false });

        const { data, error } = await query;

        if (error) {
          console.error('[useRankings] Error fetching national rankings:', error.message);
          throw error;
        }

        // total_games_played is now calculated in the database view
        return (data || []) as RankingRow[];
      } else {
        // State rankings = filtered national from state_rankings_view
        // Normalize state to uppercase for case-insensitive matching
        const normalizedRegion = region?.toUpperCase();
        let query = supabase
          .from('state_rankings_view')
          .select('*')
          .eq('state', normalizedRegion)
          .eq('status', 'Active'); // Filter out inactive teams (>180 days since last game)

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

        query = query.order('power_score_final', { ascending: false });

        const { data, error } = await query;

        if (error) {
          console.error('[useRankings] Error fetching state rankings:', error.message);
          throw error;
        }

        // total_games_played is now calculated in the database view
        return (data || []) as RankingRow[];
      }
    },
    staleTime: 30 * 60 * 1000, // 30 minutes - rankings update weekly, no need for frequent refetch
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });

  return queryResult;
}
