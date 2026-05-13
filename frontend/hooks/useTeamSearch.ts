import { useEffect, useState, useCallback } from 'react';
import { createClientSupabase } from '@/lib/supabase/client';
import { normalizeAgeGroup, formatLeague, formatDistinction } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Hook to fetch all teams for search functionality
 * Returns all teams from the teams table (not just ranked teams)
 * Transforms to RankingRow format with default/null values for ranking fields
 *
 * Uses pagination to fetch all teams (handles >1000 teams by fetching in batches)
 *
 * Module-level cache + in-flight promise dedupe replaces React Query so the
 * sitewide nav search doesn't pull @tanstack/react-query into the anon bundle.
 * Cache lives for the lifetime of the page (no GC); refetch() forces a refresh.
 */

const CACHE_TTL_MS = 10 * 60 * 1000; // 10 minutes (parity with prior staleTime)

let cached: { data: RankingRow[]; fetchedAt: number } | null = null;
let inFlight: Promise<RankingRow[]> | null = null;

async function fetchModular11TeamIds(supabase: ReturnType<typeof createClientSupabase>): Promise<Set<string>> {
  const ids = new Set<string>();
  const BATCH_SIZE = 1000;
  let offset = 0;
  // Fetch all team_id_masters that have a Modular 11 (MLS Next) provider alias.
  // Used to suppress composeTeamDisplay for those teams — their team_name is already clean.

  while (true) {
    const { data, error } = await supabase
      .from('team_alias_map')
      .select('team_id_master, providers!inner(code)')
      .eq('providers.code', 'modular11')
      .range(offset, offset + BATCH_SIZE - 1);
    if (error) {
      console.warn('[useTeamSearch] Failed to load modular11 aliases — falling back to league check:', error.message);
      return ids;
    }
    if (!data || data.length === 0) break;
    for (const row of data) ids.add(row.team_id_master);
    if (data.length < BATCH_SIZE) break;
    offset += BATCH_SIZE;
  }
  return ids;
}

async function fetchAllTeams(): Promise<RankingRow[]> {
  const supabase = createClientSupabase();
  const BATCH_SIZE = 1000; // Supabase default limit
  const allTeams: RankingRow[] = [];
  let offset = 0;
  let hasMore = true;

  const modular11TeamIds = await fetchModular11TeamIds(supabase);

  // Fetch teams in batches until we've got them all
  while (hasMore) {
    const { data, error } = await supabase
      .from('teams')
      .select('team_id_master, team_name, club_name, league, distinction, state_code, age_group, gender')
      .eq('is_deprecated', false) // Filter out deprecated/merged teams
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
    const transformedBatch = data.map((team) => {
      // Convert gender from database format ('Male'|'Female') to API format ('M'|'F')
      const genderCode = team.gender === 'Male' ? 'M' : team.gender === 'Female' ? 'F' : ('M' as 'M' | 'F' | 'B' | 'G');

      // Create searchable name that combines team name + club name + composed-display
      // tokens (U{age}, league, distinction) so users can search using the same string
      // they see in the rankings table.
      const ageInt = normalizeAgeGroup(team.age_group);
      const leagueDisplay = formatLeague(team.league);
      const distinctionDisplay = formatDistinction(team.distinction);
      const searchable_name = (() => {
        let name = team.team_name;

        // Add club name for combined searches (e.g., "rebels romero")
        if (team.club_name) {
          name += ' ' + team.club_name;
        }

        // Add U{age} so "u14" matches even when team_name lacks it
        if (ageInt != null) {
          name += ' U' + ageInt;
        }

        // Add league + distinction (raw + formatted) so users can search the visible name
        if (team.league) {
          name += ' ' + team.league;
          if (leagueDisplay && leagueDisplay !== team.league) name += ' ' + leagueDisplay;
        }
        if (team.distinction) {
          name += ' ' + team.distinction.replace(/\|/g, ' ');
          if (distinctionDisplay) name += ' ' + distinctionDisplay;
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
        league: team.league ?? null,
        distinction: team.distinction ?? null,
        has_modular11_alias: modular11TeamIds.has(team.team_id_master),
        state: team.state_code, // Map state_code to state
        age: ageInt ?? 0, // Convert age_group to integer age
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
}

function getOrFetchTeams(force: boolean): Promise<RankingRow[]> {
  if (!force && cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return Promise.resolve(cached.data);
  }
  if (inFlight) return inFlight;

  inFlight = fetchAllTeams()
    .then((data) => {
      cached = { data, fetchedAt: Date.now() };
      return data;
    })
    .finally(() => {
      inFlight = null;
    });

  return inFlight;
}

interface UseTeamSearchReturn {
  data: RankingRow[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useTeamSearch(): UseTeamSearchReturn {
  // Lazy initializers seed state from the module-level cache on first render.
  // No setState happens inside the effect's synchronous body; only the async
  // .then/.catch/.finally callbacks below ever update state.
  const [data, setData] = useState<RankingRow[] | undefined>(() => cached?.data);
  const [isLoading, setIsLoading] = useState<boolean>(() => !cached);
  const [error, setError] = useState<Error | null>(null);

  const runFetch = useCallback((force: boolean) => {
    let cancelled = false;

    getOrFetchTeams(force)
      .then((teams) => {
        if (cancelled) return;
        setData(teams);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Lazy initializers above already populated state from cache when fresh.
    // Skip the fetch if we already have fresh data.
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
      return;
    }
    return runFetch(false);
  }, [runFetch]);

  const refetch = useCallback(() => {
    // Event handler — safe to setState synchronously.
    setIsLoading(true);
    setError(null);
    runFetch(true);
  }, [runFetch]);

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    refetch,
  };
}
