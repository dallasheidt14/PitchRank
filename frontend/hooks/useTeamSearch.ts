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
 * Updated: 2024-11-23
 */
export function useTeamSearch() {
  return useQuery<RankingRow[]>({
    queryKey: ['team-search'],
    queryFn: async () => {
      const BATCH_SIZE = 1000; // Supabase default limit
      const allTeams: RankingRow[] = [];
      let offset = 0;
      let hasMore = true;

      // Fetch teams in batches until we've got them all
      while (hasMore) {
        const { data, error } = await supabase
          .from('teams')
          .select('team_id_master, team_name, club_name, state_code, age_group, gender')
          .order('team_name', { ascending: true })
          .range(offset, offset + BATCH_SIZE - 1);

        if (error) {
          console.error('[useTeamSearch] Error fetching teams:', error.message);
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

          // Create searchable name that combines team name + club name for cross-field matching
          // This allows "rebels san diego romero" to match team "B2014 Pre-ECNL (Romero)" from club "Rebels San Diego"
          const searchable_name = (() => {
            let name = team.team_name;

            // Add club name for combined searches (e.g., "rebels romero")
            if (team.club_name) {
              name += ' ' + team.club_name;
            }

            // Add year variations: "2015" ↔ "15"
            const fourDigitMatch = team.team_name.match(/20(0[9]|1[0-9]|2[0-9])\b/);
            if (fourDigitMatch) {
              name += ' ' + fourDigitMatch[1];
            }

            const twoDigitMatch = team.team_name.match(/\b(0[9]|1[0-9]|2[0-9])\b(?![\d])/);
            if (twoDigitMatch && !fourDigitMatch) {
              name += ' 20' + twoDigitMatch[1];
            }

            return name;
          })();

          return {
            team_id_master: team.team_id_master,
            team_name: team.team_name,
            searchable_name,
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
            // Total record fields (required by RankingRow type)
            total_games_played: 0,
            total_wins: 0,
            total_losses: 0,
            total_draws: 0,
            win_percentage: null,
          } as RankingRow;
        });

        allTeams.push(...transformedBatch);

        // If we got fewer than BATCH_SIZE, we've reached the end
        if (data.length < BATCH_SIZE) {
          hasMore = false;
        } else {
          offset += BATCH_SIZE;
        }
      }

      return allTeams;
    },
    staleTime: 10 * 60 * 1000, // 10 minutes - team list doesn't change often
    gcTime: 60 * 60 * 1000, // Keep in cache for 1 hour
  });
}

