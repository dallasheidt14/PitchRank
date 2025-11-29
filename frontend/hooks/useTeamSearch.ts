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

          // Create searchable name that includes:
          // 1. Year variations (2015 → 2015 15) for bidirectional matching
          // 2. Word tokens from team name for better partial word matching
          // 3. Club name tokens for searching by club name
          // This allows matching like:
          // - "rsl north chacon 15" matches "rsl north chacon 2015"
          // - "rsl north" matches "RSL North Chacon 2015"
          // - "north chacon" matches "RSL North Chacon 2015"
          // - "real salt lake" matches teams from "Real Salt Lake" club
          // - "rsl" matches teams from "RSL" or "Real Salt Lake" club
          const searchable_name = (() => {
            const additions: string[] = [];

            // For 4-digit years (2009-2019), add 2-digit form
            const fourDigitYears = team.team_name.match(/20(0[9]|1[0-9])\b/g) || [];
            fourDigitYears.forEach((y: string) => additions.push(y.slice(2)));

            // For standalone 2-digit years (not preceded by "20"), add 4-digit form
            const twoDigitYears = team.team_name.match(/(?<!20)(0[9]|1[0-9])\b/g) || [];
            twoDigitYears.forEach((y: string) => additions.push('20' + y));

            // Add individual words from team name for better partial matching
            // Split on spaces and non-word characters, filter out empty strings and years
            const teamWords = team.team_name
              .toLowerCase()
              .split(/[\s\-_.,;:!?()]+/)
              .filter(word => word.length > 2 && !/^\d+$/.test(word)); // Exclude short words and pure numbers
            
            additions.push(...teamWords);

            // Add club name and its word tokens if club_name exists
            // This allows searching by club name even when searching the searchable_name field
            if (team.club_name) {
              additions.push(team.club_name.toLowerCase());
              
              // Add individual words from club name
              const clubWords = team.club_name
                .toLowerCase()
                .split(/[\s\-_.,;:!?()]+/)
                .filter(word => word.length > 2 && !/^\d+$/.test(word));
              
              additions.push(...clubWords);
            }

            return additions.length > 0
              ? team.team_name + ' ' + additions.join(' ')
              : team.team_name;
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

