import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Hook to fetch all teams for search functionality
 * Returns all teams from the teams table (not just ranked teams)
 * Transforms to RankingRow format with default/null values for ranking fields
 */
export function useTeamSearch() {
  return useQuery<RankingRow[]>({
    queryKey: ['team-search'],
    queryFn: async () => {
      // Fetch ALL teams from master teams table (no limit - get everything)
      const { data, error } = await supabase
        .from('teams')
        .select('team_id_master, team_name, club_name, state_code, age_group, gender')
        .order('team_name', { ascending: true });
      // No limit - fetch all teams from master list

      if (error) {
        console.error('[useTeamSearch] Error fetching teams:', error);
        console.error('[useTeamSearch] Error details:', {
          message: error.message,
          details: error.details,
          hint: error.hint,
          code: error.code,
        });
        throw error;
      }

      console.log('[useTeamSearch] Teams fetched:', {
        count: data?.length || 0,
        hasData: !!data && data.length > 0,
        sample: data?.[0] ? {
          team_id_master: data[0].team_id_master,
          team_name: data[0].team_name,
        } : null,
      });

      // Transform to RankingRow format (with default/null values for ranking fields)
      return (data || []).map(team => {
        // Convert gender from database format ('Male'|'Female') to API format ('M'|'F')
        const genderCode = team.gender === 'Male' ? 'M' : team.gender === 'Female' ? 'F' : 'M' as 'M' | 'F' | 'B' | 'G';
        
        return {
          team_id_master: team.team_id_master,
          team_name: team.team_name,
          club_name: team.club_name,
          state: team.state_code, // Map state_code to state
          age: normalizeAgeGroup(team.age_group) ?? 0, // Convert age_group to integer age
          gender: genderCode,
          // Ranking fields (default values for unranked teams)
          power_score_final: 0,
          sos_norm: 0,
          offense_norm: null,
          defense_norm: null,
          rank_in_cohort_final: 0,
          // Record fields (default values)
          games_played: 0,
          wins: 0,
          losses: 0,
          draws: 0,
          win_percentage: null,
        } as RankingRow;
      });
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - team list doesn't change often
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });
}

