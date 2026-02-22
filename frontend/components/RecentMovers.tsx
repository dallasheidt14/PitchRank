'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useRankings, usePrefetchTeam } from '@/lib/hooks';
import { useMemo, useState, useEffect } from 'react';
import Link from 'next/link';
import { ArrowUp, ArrowDown, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ListSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';

type TimeWindow = '7d' | '30d';

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
  defaultTimeWindow = '7d'
}: RecentMoversProps) {
  // Load time window preference from localStorage
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('recentMoversTimeWindow') as TimeWindow;
      return saved || defaultTimeWindow;
    }
    return defaultTimeWindow;
  });

  const { data: rankings, isLoading, isError, error, refetch } = useRankings(null, ageGroup, gender);
  const prefetchTeam = usePrefetchTeam();

  // Save time window preference to localStorage
  useEffect(() => {
    localStorage.setItem('recentMoversTimeWindow', timeWindow);
  }, [timeWindow]);

  // Compute sequential national ranks from filtered data (avoids gaps from inactive teams)
  const computedNationalRanks = useMemo(() => {
    if (!rankings?.length) return new Map<string, number>();
    const map = new Map<string, number>();
    const sorted = [...rankings].sort((a, b) => {
      const diff = (b.power_score_final ?? 0) - (a.power_score_final ?? 0);
      if (diff !== 0) return diff;
      return (b.sos_norm ?? 0) - (a.sos_norm ?? 0);
    });
    sorted.forEach((team, index) => {
      map.set(team.team_id_master, index + 1);
    });
    return map;
  }, [rankings]);

  // Calculate recent movers based on real historical rank change data
  const recentMovers = useMemo(() => {
    if (!rankings?.length) return [];

    const rankChangeField = timeWindow === '7d' ? 'rank_change_7d' : 'rank_change_30d';

    return rankings
      .filter(team => {
        const change = team[rankChangeField];
        return change !== null && change !== undefined && Math.abs(change) > 0;
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
                  const rankChange = timeWindow === '7d'
                    ? team.rank_change_7d ?? 0
                    : team.rank_change_30d ?? 0;
                  const isImprovement = rankChange > 0;

                  return (
                    <Link
                      key={team.team_id_master}
                      href={`/teams/${team.team_id_master}`}
                      onMouseEnter={() => prefetchTeam(team.team_id_master)}
                      className="flex items-center justify-between p-3 rounded-md hover:bg-secondary/50 border border-transparent hover:border-border transition-all duration-300 group"
                      aria-label={`View ${team.team_name} - moved ${Math.abs(rankChange)} positions ${isImprovement ? 'up' : 'down'}`}
                      tabIndex={0}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-sm truncate group-hover:text-primary transition-colors">
                          {team.team_name}
                        </div>
                        <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                          <span className="font-mono">#{computedNationalRanks.get(team.team_id_master) ?? team.rank_in_cohort_final}</span>
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
                          isImprovement
                            ? 'bg-green-100 text-green-600'
                            : 'bg-red-100 text-red-600'
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
