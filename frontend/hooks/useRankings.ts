import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
import { apiTimer } from '@/lib/performance';
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
  return useQuery<RankingRow[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    enabled: true,
    queryFn: () => apiTimer('rankings:list', async () => {
      const BATCH_SIZE = 1000;
      const allResults: RankingRow[] = [];
      let offset = 0;
      let hasMore = true;

      const table = region ? 'state_rankings_view' : 'rankings_view';
      const normalizedRegion = region?.toUpperCase();
      let normalizedAge: number | null = null;

      if (ageGroup) {
        normalizedAge = normalizeAgeGroup(ageGroup);
      }

      while (hasMore) {
        let query = supabase
          .from(table)
          .select('*')
          .in('status', ['Active', 'Not Enough Ranked Games']);

        if (region) {
          query = query.eq('state', normalizedRegion);
        }

        if (normalizedAge !== null) {
          query = query.eq('age', normalizedAge);
        }

        if (gender) {
          query = query.eq('gender', gender);
        }

        query = query
          .order('power_score_final', { ascending: false })
          .range(offset, offset + BATCH_SIZE - 1);

        const { data, error } = await query;

        if (error) {
          console.error(`[useRankings] Error fetching ${region ? 'state' : 'national'} rankings:`, error.message);
          throw error;
        }

        if (!data || data.length === 0) {
          hasMore = false;
        } else {
          allResults.push(...(data as RankingRow[]));
          if (data.length < BATCH_SIZE) {
            hasMore = false;
          } else {
            offset += BATCH_SIZE;
          }
        }
      }

      return allResults;
    }, { region, ageGroup, gender }),
    staleTime: 2 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });
}
