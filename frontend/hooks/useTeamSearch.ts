import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Hook to fetch all teams for search functionality
 * Returns a flattened list of all teams from rankings_view
 */
export function useTeamSearch() {
  return useQuery<RankingRow[]>({
    queryKey: ['team-search'],
    queryFn: async () => {
      // Fetch all teams from rankings_view (no filters)
      const { data, error } = await supabase
        .from('rankings_view')
        .select('*')
        .order('national_rank', { ascending: true })
        .limit(10000); // Reasonable limit for search

      if (error) {
        console.error('Error fetching teams for search:', error);
        throw error;
      }

      return (data || []) as RankingRow[];
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - team list doesn't change often
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });
}

