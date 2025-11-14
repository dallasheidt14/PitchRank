import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Hook to fetch all teams for search functionality
 * Returns all teams from the teams table (not just ranked teams)
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
        console.error('Error fetching teams for search:', error);
        throw error;
      }

      // Transform to RankingRow format (with null values for ranking fields)
      return (data || []).map(team => ({
        team_id_master: team.team_id_master,
        team_name: team.team_name,
        club_name: team.club_name,
        state_code: team.state_code,
        age_group: team.age_group,
        gender: team.gender as 'Male' | 'Female',
        national_rank: null,
        national_sos_rank: null,
        national_power_score: 0, // Default for sorting
        global_power_score: null,
        games_played: 0,
        wins: 0,
        losses: 0,
        draws: 0,
        win_percentage: null,
        strength_of_schedule: null,
        state_rank: null,
        state_sos_rank: null,
      })) as RankingRow[];
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - team list doesn't change often
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });
}

