import { useQuery } from '@tanstack/react-query';
import { normalizeAgeGroup } from '@/lib/utils';
import { apiTimer } from '@/lib/performance';
import type { RankingRow } from '@/types/RankingRow';

/**
 * Fetch state rankings via the /api/rankings/state route, which uses the
 * get_state_rankings RPC (filters before ROW_NUMBER — no timeout).
 */
async function fetchStateRankings(
  region: string,
  ageGroup: string | undefined,
  gender: 'M' | 'F' | 'B' | 'G' | null | undefined
): Promise<RankingRow[]> {
  const BATCH_SIZE = 1000;
  const allResults: RankingRow[] = [];
  let offset = 0;
  let hasMore = true;

  const normalizedAge = ageGroup ? normalizeAgeGroup(ageGroup) : null;

  while (hasMore) {
    const params = new URLSearchParams({
      state: region,
      ...(normalizedAge !== null && { age: String(normalizedAge) }),
      ...(gender && { gender }),
      limit: String(BATCH_SIZE),
      offset: String(offset),
    });

    const res = await fetch(`/api/rankings/state?${params.toString()}`);

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      console.error('[useRankings] State rankings API error:', body.error || res.statusText);
      throw new Error(body.error || `State rankings request failed: ${res.status}`);
    }

    const data: RankingRow[] = await res.json();

    if (!data || data.length === 0) {
      hasMore = false;
    } else {
      allResults.push(...data);
      if (data.length < BATCH_SIZE) {
        hasMore = false;
      } else {
        offset += BATCH_SIZE;
      }
    }
  }

  return allResults;
}

/**
 * Fetch national rankings via the /api/rankings/national route, which uses the
 * get_national_rankings RPC (filters before pagination on rankings_full).
 */
async function fetchNationalRankings(
  ageGroup: string | undefined,
  gender: 'M' | 'F' | 'B' | 'G' | null | undefined
): Promise<RankingRow[]> {
  const BATCH_SIZE = 1000;
  const allResults: RankingRow[] = [];
  let offset = 0;
  let hasMore = true;

  const normalizedAge = ageGroup ? normalizeAgeGroup(ageGroup) : null;

  while (hasMore) {
    const params = new URLSearchParams({
      ...(normalizedAge !== null && { age: String(normalizedAge) }),
      ...(gender && { gender }),
      limit: String(BATCH_SIZE),
      offset: String(offset),
    });

    const res = await fetch(`/api/rankings/national?${params.toString()}`);

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      console.error('[useRankings] National rankings API error:', body.error || res.statusText);
      throw new Error(body.error || `National rankings request failed: ${res.status}`);
    }

    const data: RankingRow[] = await res.json();

    if (!data || data.length === 0) {
      hasMore = false;
    } else {
      allResults.push(...data);
      if (data.length < BATCH_SIZE) {
        hasMore = false;
      } else {
        offset += BATCH_SIZE;
      }
    }
  }

  return allResults;
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
  gender?: 'M' | 'F' | 'B' | 'G' | null,
  initialData?: RankingRow[]
) {
  // Only treat a NON-EMPTY server seed as initial data. An empty array (e.g. a
  // failed ISR fetch returning []) must not seed — leave it undefined so the
  // client fetches and can recover. A complete cohort (under the 2000-row server
  // cap) is marked fresh to skip the mount refetch; a capped cohort is marked
  // stale (0) so React Query backfills the rows beyond 2000.
  const seed = initialData !== undefined && initialData.length > 0 ? initialData : undefined;
  return useQuery<RankingRow[]>({
    queryKey: ['rankings', region, ageGroup, gender],
    enabled: true,
    queryFn: () =>
      apiTimer(
        'rankings:list',
        async () => {
          if (region) {
            return fetchStateRankings(region, ageGroup, gender);
          }
          return fetchNationalRankings(ageGroup, gender);
        },
        { region, ageGroup, gender }
      ),
    initialData: seed,
    initialDataUpdatedAt: seed === undefined ? undefined : seed.length < 2000 ? () => Date.now() : 0,
    staleTime: 2 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    retry: 2,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
  });
}
