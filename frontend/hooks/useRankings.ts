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
  console.log('[useRankings] Hook called with:', { region, ageGroup, gender });
  console.log('[useRankings] Environment check:', {
    hasSupabaseUrl: !!process.env.NEXT_PUBLIC_SUPABASE_URL,
    hasAnonKey: !!process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  });
  
  const queryResult = useQuery<RankingRow[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    enabled: true, // Explicitly enable the query
    queryFn: async () => {
      console.log('[useRankings] Query function executing with:', { region, ageGroup, gender });
      
      if (!region) {
        // National rankings = return full slice from rankings_view
        let query = supabase
          .from('rankings_view')
          .select('*');

        // Normalize age group outside if block for use in logging
        const normalizedAge = ageGroup ? normalizeAgeGroup(ageGroup) : null;

        if (normalizedAge !== null) {
          query = query.eq('age', normalizedAge);
        }

        if (gender) {
          query = query.eq('gender', gender);
        }

        query = query.order('power_score_final', { ascending: false });

        console.log('[useRankings] Executing query with filters:', {
          ageFilter: normalizedAge,
          genderFilter: gender,
          queryString: query.toString(),
        });

        const { data, error } = await query;

        if (error) {
          console.error('[useRankings] Error fetching national rankings:', error);
          console.error('[useRankings] Error details:', {
            message: error.message,
            details: error.details,
            hint: error.hint,
            code: error.code,
          });
          throw error;
        }

        console.log('[useRankings] Raw response:', {
          dataType: typeof data,
          isArray: Array.isArray(data),
          count: data?.length || 0,
          rawData: data,
        });

        console.log('[useRankings] National rankings fetched:', {
          count: data?.length || 0,
          hasData: !!data && data.length > 0,
          sample: data?.[0] ? {
            team_id_master: data[0].team_id_master,
            team_name: data[0].team_name,
            age: data[0].age,
            gender: data[0].gender,
            power_score_final: data[0].power_score_final,
            allKeys: Object.keys(data[0]),
          } : null,
        });

        return (data || []) as RankingRow[];
      } else {
        // State rankings = filtered national from state_rankings_view
        // Normalize state to uppercase for case-insensitive matching
        const normalizedRegion = region?.toUpperCase();
        let query = supabase
          .from('state_rankings_view')
          .select('*')
          .eq('state', normalizedRegion);

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
          console.error('[useRankings] Error fetching state rankings:', error);
          console.error('[useRankings] Error details:', {
            message: error.message,
            details: error.details,
            hint: error.hint,
            code: error.code,
            region: normalizedRegion,
          });
          throw error;
        }

        console.log('[useRankings] State rankings fetched:', {
          region: normalizedRegion,
          count: data?.length || 0,
          hasData: !!data && data.length > 0,
          sample: data?.[0] ? {
            team_id_master: data[0].team_id_master,
            team_name: data[0].team_name,
            age: data[0].age,
            gender: data[0].gender,
            power_score_final: data[0].power_score_final,
          } : null,
        });

        return (data || []) as RankingRow[];
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - rankings update weekly
    gcTime: 30 * 60 * 1000, // Keep in cache for 30 minutes
  });
  
  console.log('[useRankings] Query result:', {
    isLoading: queryResult.isLoading,
    isError: queryResult.isError,
    error: queryResult.error,
    dataLength: queryResult.data?.length || 0,
    hasData: !!queryResult.data && queryResult.data.length > 0,
  });
  
  return queryResult;
}

