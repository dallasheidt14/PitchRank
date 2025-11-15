import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Hook to fetch all teams for search functionality
 * Returns all teams from the teams table (not just ranked teams)
 * Transforms to RankingRow format with default/null values for ranking fields
 * 
 * Uses pagination to fetch all teams (handles >1000 teams by fetching in batches)
 */
export function useTeamSearch() {
  return useQuery<RankingRow[]>({
    queryKey: ['team-search'],
    queryFn: async () => {
      const BATCH_SIZE = 1000; // Supabase default limit
      const allTeams: RankingRow[] = [];
      let offset = 0;
      let hasMore = true;

      console.log('[useTeamSearch] Starting to fetch all teams with pagination...');

      // Fetch teams in batches until we've got them all
      while (hasMore) {
        const { data, error } = await supabase
          .from('teams')
          .select('team_id_master, team_name, club_name, state_code, age_group, gender')
          .order('team_name', { ascending: true })
          .range(offset, offset + BATCH_SIZE - 1);

        if (error) {
          console.error('[useTeamSearch] Error fetching teams batch:', error);
          console.error('[useTeamSearch] Error details:', {
            message: error.message,
            details: error.details,
            hint: error.hint,
            code: error.code,
            offset,
            batchSize: BATCH_SIZE,
          });
          throw error;
        }

        if (!data || data.length === 0) {
          hasMore = false;
          break;
        }

        // Transform batch to RankingRow format
        const transformedBatch = data.map(team => {
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

        allTeams.push(...transformedBatch);
        
        console.log('[useTeamSearch] Fetched batch:', {
          batchSize: data.length,
          totalSoFar: allTeams.length,
          offset,
          hasMore: data.length === BATCH_SIZE,
        });

        // If we got fewer than BATCH_SIZE, we've reached the end
        if (data.length < BATCH_SIZE) {
          hasMore = false;
        } else {
          offset += BATCH_SIZE;
        }
      }

      console.log('[useTeamSearch] All teams fetched:', {
        totalCount: allTeams.length,
        batches: Math.ceil(allTeams.length / BATCH_SIZE),
        sample: allTeams[0] ? {
          team_id_master: allTeams[0].team_id_master,
          team_name: allTeams[0].team_name,
        } : null,
      });

      return allTeams;
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - team list doesn't change often
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });
}

