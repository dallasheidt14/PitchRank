import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import type { RankingRow } from '@/types/RankingRow';

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
  gender?: 'Male' | 'Female' | null
) {
  return useQuery<RankingRow[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    queryFn: async () => {
      if (!region) {
        // National rankings = return full slice from rankings_view
        let query = supabase
          .from('rankings_view')
          .select('*');

        if (ageGroup) {
          query = query.eq('age_group', ageGroup);
        }

        if (gender) {
          query = query.eq('gender', gender);
        }

        query = query.order('national_rank', { ascending: true });

        const { data, error } = await query;

        if (error) {
          console.error('Error fetching national rankings:', error);
          throw error;
        }

        return (data || []) as RankingRow[];
      } else {
        // State rankings = filtered national from state_rankings_view
        let query = supabase
          .from('state_rankings_view')
          .select('*')
          .eq('state_code', region);

        if (ageGroup) {
          query = query.eq('age_group', ageGroup);
        }

        if (gender) {
          query = query.eq('gender', gender);
        }

        query = query.order('power_score', { ascending: false });

        const { data, error } = await query;

        if (error) {
          console.error('Error fetching state rankings:', error);
          throw error;
        }

        return (data || []) as RankingRow[];
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - rankings update weekly
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
  });
}

