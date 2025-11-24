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
  // Debug: Log hook call
  console.log('[useRankings] Hook called with:', { region, ageGroup, gender });

  const queryResult = useQuery<RankingRow[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    enabled: true, // Explicitly enable the query
    queryFn: async () => {
      console.log('[useRankings] queryFn executing...');
      // Paginate to get all results (Supabase default limit is 1000)
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

      // Debug logging
      console.log('[useRankings] Query params:', {
        table,
        region,
        normalizedRegion,
        ageGroup,
        normalizedAge,
        gender,
      });

      while (hasMore) {
        let query = supabase
          .from(table)
          .select('*')
          .eq('status', 'Active'); // Filter out inactive teams (>180 days since last game)

        if (region) {
          // Filter by state - try uppercase first (expected format)
          // If that returns no results, we'll try a case-insensitive approach
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

        // Debug logging for results
        if (offset === 0) {
          console.log(`[useRankings] First batch returned ${data?.length || 0} results`);
          if (data && data.length > 0) {
            // Log first few results to see actual state values
            const sampleStates = [...new Set(data.slice(0, 10).map(r => r.state))];
            console.log('[useRankings] Sample results:', {
              count: data.length,
              sample_states: sampleStates,
              first_result: {
                team_name: data[0].team_name,
                state: data[0].state,
                age: data[0].age,
                gender: data[0].gender,
                status: data[0].status,
              },
            });
          } else if (region && offset === 0) {
            // If no results on first batch with region filter, try case-insensitive search
            console.warn(`[useRankings] No results with uppercase state="${normalizedRegion}", trying case-insensitive...`);
            
            // Try querying without status filter first to see if there's any data
            const testQuery = supabase
              .from(table)
              .select('state, age, gender, status, team_name')
              .eq('age', normalizedAge!)
              .eq('gender', gender!)
              .limit(20);
            
            const { data: testData } = await testQuery;
            
            if (testData && testData.length > 0) {
              const uniqueStates = [...new Set(testData.map(r => r.state))];
              console.log('[useRankings] Found teams with states:', uniqueStates);
              console.log('[useRankings] Sample team states:', testData.slice(0, 5).map(t => ({
                team: t.team_name,
                state: t.state,
                status: t.status
              })));
            }
          }
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

      console.log('[useRankings] queryFn returning', allResults.length, 'results');
      return allResults;
    },
    staleTime: 30 * 60 * 1000, // 30 minutes - rankings update weekly, no need for frequent refetch
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });

  // Debug: Log query result state
  console.log('[useRankings] Query result:', {
    isLoading: queryResult.isLoading,
    isFetching: queryResult.isFetching,
    dataLength: queryResult.data?.length ?? 0,
    isError: queryResult.isError,
    error: queryResult.error?.message,
  });

  return queryResult;
}
