'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useMemo, useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { ArrowUp, ArrowDown, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ListSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { normalizeAgeGroup, composeTeamDisplay } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

type TimeWindow = '7d' | '30d';

/**
 * Module-level cache for the national rankings used by RecentMovers.
 *
 * Replaces a previous react-query usage so the homepage (sitewide entry)
 * doesn't ship @tanstack/react-query. Cache key is `${age}-${gender}`.
 */
const CACHE_TTL_MS = 2 * 60 * 1000; // 2 minutes (parity with prior staleTime)

type CacheKey = string;
const cache = new Map<CacheKey, { data: RankingRow[]; fetchedAt: number }>();
const inFlight = new Map<CacheKey, Promise<RankingRow[]>>();

async function fetchNationalRankings(ageGroup: string, gender: 'M' | 'F' | 'B' | 'G'): Promise<RankingRow[]> {
  const BATCH_SIZE = 1000;
  const allResults: RankingRow[] = [];
  let offset = 0;
  let hasMore = true;

  const normalizedAge = normalizeAgeGroup(ageGroup);

  while (hasMore) {
    const params = new URLSearchParams({
      ...(normalizedAge !== null && { age: String(normalizedAge) }),
      gender,
      limit: String(BATCH_SIZE),
      offset: String(offset),
    });

    const res = await fetch(`/api/rankings/national?${params.toString()}`);

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
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

function getOrFetchRankings(ageGroup: string, gender: 'M' | 'F' | 'B' | 'G', force: boolean): Promise<RankingRow[]> {
  const key: CacheKey = `${ageGroup}-${gender}`;
  const cached = cache.get(key);
  if (!force && cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return Promise.resolve(cached.data);
  }
  const existing = inFlight.get(key);
  if (existing) return existing;

  const promise = fetchNationalRankings(ageGroup, gender)
    .then((data) => {
      cache.set(key, { data, fetchedAt: Date.now() });
      return data;
    })
    .finally(() => {
      inFlight.delete(key);
    });

  inFlight.set(key, promise);
  return promise;
}

interface RecentMoversProps {
  /** Age group to display (e.g., 'u12'). Defaults to 'u12' */
  ageGroup?: string;
  /** Gender to display ('M' | 'F' | 'B' | 'G'). Defaults to 'M' */
  gender?: 'M' | 'F' | 'B' | 'G';
  /** Maximum number of teams to show. Defaults to 5 */
  maxItems?: number;
  /** Default time window. Defaults to '7d' */
  defaultTimeWindow?: TimeWindow;
}

/**
 * RecentMovers component - displays teams with the biggest rank changes
 *
 * Shows teams that have moved up or down the most in rankings over the past
 * 7 or 30 days. Users can toggle between time windows using the buttons.
 *
 * @example
 * ```tsx
 * <RecentMovers />
 * <RecentMovers ageGroup="u14" gender="F" maxItems={10} />
 * ```
 */
export function RecentMovers({
  ageGroup = 'u12',
  gender = 'M',
  maxItems = 5,
  defaultTimeWindow = '7d',
}: RecentMoversProps) {
  // Load time window preference from localStorage
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('recentMoversTimeWindow') as TimeWindow;
      return saved || defaultTimeWindow;
    }
    return defaultTimeWindow;
  });

  // Lazy initializers seed state from the module-level cache on first render.
  // No setState happens inside the effect's synchronous body; only the async
  // .then/.catch/.finally callbacks below ever update state.
  const [rankings, setRankings] = useState<RankingRow[] | undefined>(() => cache.get(`${ageGroup}-${gender}`)?.data);
  const [isLoading, setIsLoading] = useState<boolean>(() => !cache.get(`${ageGroup}-${gender}`));
  const [error, setError] = useState<Error | null>(null);

  const runFetch = useCallback(
    (force: boolean) => {
      let cancelled = false;

      getOrFetchRankings(ageGroup, gender, force)
        .then((data) => {
          if (cancelled) return;
          setRankings(data);
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
    },
    [ageGroup, gender]
  );

  useEffect(() => {
    // Lazy initializers above already populated state from cache when fresh.
    // Skip the fetch if we already have fresh data for this key.
    const cached = cache.get(`${ageGroup}-${gender}`);
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
      return;
    }
    return runFetch(false);
  }, [ageGroup, gender, runFetch]);

  const refetch = useCallback(() => {
    // Event handler — safe to setState synchronously.
    setIsLoading(true);
    setError(null);
    runFetch(true);
  }, [runFetch]);

  const isError = error !== null;

  // Save time window preference to localStorage
  useEffect(() => {
    localStorage.setItem('recentMoversTimeWindow', timeWindow);
  }, [timeWindow]);

  // Calculate recent movers based on real historical rank change data
  const recentMovers = useMemo(() => {
    if (!rankings?.length) return [];

    const rankChangeField = timeWindow === '7d' ? 'rank_change_7d' : 'rank_change_30d';

    return rankings
      .filter((team) => {
        const change = team[rankChangeField];
        // Must have a non-zero rank change
        if (change === null || change === undefined || Math.abs(change) === 0) return false;
        // Filter out teams with very few games (unreliable rank swings)
        if ((team.total_games_played ?? 0) < 8) return false;
        // Exclude teams that just became ranked (status indicates not enough games)
        if (team.status === 'Not Enough Ranked Games') return false;
        return true;
      })
      .sort((a, b) => {
        const changeA = Math.abs(a[rankChangeField] ?? 0);
        const changeB = Math.abs(b[rankChangeField] ?? 0);
        return changeB - changeA;
      })
      .slice(0, maxItems);
  }, [rankings, timeWindow, maxItems]);

  return (
    <Card className="border-l-4 border-l-primary shadow-md">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex-1">
            <CardTitle className="flex items-center gap-2 text-xl">
              <TrendingUp className="h-5 w-5 text-primary" />
              Recent Movers
            </CardTitle>
            <CardDescription className="text-sm">
              Biggest rank changes • {timeWindow === '7d' ? '7 days' : '30 days'}
            </CardDescription>
          </div>
          <div className="flex gap-1 flex-shrink-0">
            <Button
              variant={timeWindow === '7d' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setTimeWindow('7d')}
              aria-label="Show 7-day rank changes"
              aria-pressed={timeWindow === '7d'}
              className="font-semibold"
            >
              7D
            </Button>
            <Button
              variant={timeWindow === '30d' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setTimeWindow('30d')}
              aria-label="Show 30-day rank changes"
              aria-pressed={timeWindow === '30d'}
              className="font-semibold"
            >
              30D
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && <ListSkeleton items={maxItems} />}

        {isError && <ErrorDisplay error={error} retry={refetch} />}

        {!isLoading && !isError && (
          <>
            {recentMovers.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                No significant rank changes in the past {timeWindow === '7d' ? '7 days' : '30 days'}
              </p>
            ) : (
              <div className="space-y-1">
                {recentMovers.map((team) => {
                  const rankChange = timeWindow === '7d' ? (team.rank_change_7d ?? 0) : (team.rank_change_30d ?? 0);
                  const isImprovement = rankChange > 0;
                  const displayName = composeTeamDisplay(team);

                  return (
                    <Link
                      key={team.team_id_master}
                      href={`/teams/${team.team_id_master}`}
                      className="flex items-center justify-between p-3 rounded-md hover:bg-secondary/50 border border-transparent hover:border-border transition-all duration-300 group"
                      aria-label={`View ${displayName} - moved ${Math.abs(rankChange)} positions ${isImprovement ? 'up' : 'down'}`}
                      tabIndex={0}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-sm truncate group-hover:text-primary transition-colors">
                          {displayName}
                        </div>
                        <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                          <span className="font-mono">
                            {team.rank_in_cohort_final != null ? `#${team.rank_in_cohort_final}` : '—'}
                          </span>
                          {team.state && (
                            <>
                              <span>•</span>
                              <span>{team.state}</span>
                            </>
                          )}
                        </div>
                      </div>
                      <div
                        className={`flex items-center gap-1.5 text-sm font-bold px-2 py-1 rounded ${
                          isImprovement ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                        }`}
                        aria-label={`${isImprovement ? 'Improved' : 'Declined'} by ${Math.abs(rankChange)} ranks`}
                      >
                        {isImprovement ? (
                          <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
                        ) : (
                          <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
                        )}
                        <span>{Math.abs(rankChange)}</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
