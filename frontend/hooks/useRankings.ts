import { useQuery } from '@tanstack/react-query';
import { supabase } from '@/lib/supabaseClient';
import { normalizeAgeGroup } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Enriches rankings data with total_games_played count from the games table
 * @param rankings - Array of ranking rows
 * @returns Rankings with total_games_played added to each row
 */
async function enrichWithTotalGames(rankings: RankingRow[]): Promise<RankingRow[]> {
  if (!rankings || rankings.length === 0) {
    return rankings;
  }

  try {
    // Extract all team IDs
    const teamIds = rankings.map(r => r.team_id_master);

    // Query games table to count games per team
    // We need to fetch all games where team is either home or away
    // Use .in() filter combined with .or() for efficiency
    const { data: gamesData, error } = await supabase
      .from('games')
      .select('home_team_master_id, away_team_master_id')
      .or(`home_team_master_id.in.(${teamIds.join(',')}),away_team_master_id.in.(${teamIds.join(',')})`);

    if (error) {
      console.warn('[enrichWithTotalGames] Error fetching games data:', error);
      // Return rankings without total_games_played if query fails
      return rankings;
    }

    // Count games per team
    const gameCountMap = new Map<string, number>();

    if (gamesData) {
      gamesData.forEach(game => {
        // Count for home team (only if it's in our team list)
        if (game.home_team_master_id && teamIds.includes(game.home_team_master_id)) {
          gameCountMap.set(
            game.home_team_master_id,
            (gameCountMap.get(game.home_team_master_id) || 0) + 1
          );
        }
        // Count for away team (only if it's in our team list)
        if (game.away_team_master_id && teamIds.includes(game.away_team_master_id)) {
          gameCountMap.set(
            game.away_team_master_id,
            (gameCountMap.get(game.away_team_master_id) || 0) + 1
          );
        }
      });
    }

    // Merge counts into rankings
    const enrichedRankings = rankings.map(ranking => ({
      ...ranking,
      total_games_played: gameCountMap.get(ranking.team_id_master) || 0,
    }));

    console.log('[enrichWithTotalGames] Enriched rankings with total games:', {
      teamsProcessed: teamIds.length,
      gamesDataCount: gamesData?.length || 0,
      sample: enrichedRankings[0] ? {
        team_name: enrichedRankings[0].team_name,
        games_played: enrichedRankings[0].games_played,
        total_games_played: enrichedRankings[0].total_games_played,
      } : null,
    });

    return enrichedRankings;
  } catch (err) {
    console.error('[enrichWithTotalGames] Unexpected error:', err);
    // Return original rankings if something goes wrong
    return rankings;
  }
}

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

        let normalizedAge: number | null = null;
        if (ageGroup) {
          // Normalize age group to integer
          normalizedAge = normalizeAgeGroup(ageGroup);
          if (normalizedAge !== null) {
            query = query.eq('age', normalizedAge);
          }
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

        // Fetch total games count for all teams
        const rankingsWithTotalGames = await enrichWithTotalGames(data || []);
        return rankingsWithTotalGames as RankingRow[];
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

        // Fetch total games count for all teams
        const rankingsWithTotalGames = await enrichWithTotalGames(data || []);
        return rankingsWithTotalGames as RankingRow[];
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

