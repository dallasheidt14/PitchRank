'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowUp, ArrowDown, TrendingUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { composeTeamDisplay } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';
import type { MoversWindow } from '@/lib/movers';

interface RecentMoversProps {
  /** Top movers for the 7-day window, computed server-side. */
  initialMovers7d: RankingRow[];
  /** Top movers for the 30-day window, computed server-side. */
  initialMovers30d: RankingRow[];
  /** Default time window. Defaults to '7d' */
  defaultTimeWindow?: MoversWindow;
}

/**
 * RecentMovers - displays teams with the biggest rank changes over 7 or 30 days.
 *
 * Movers are computed server-side and passed in as props, so the homepage no
 * longer ships a client fetch of the full national cohort. Users toggle between
 * the two prebuilt windows.
 */
export function RecentMovers({ initialMovers7d, initialMovers30d, defaultTimeWindow = '7d' }: RecentMoversProps) {
  // Start from the default for SSR parity; read the saved preference after mount
  // so server and client first render match (no hydration mismatch).
  const [timeWindow, setTimeWindow] = useState<MoversWindow>(defaultTimeWindow);

  useEffect(() => {
    const saved = localStorage.getItem('recentMoversTimeWindow');
    // eslint-disable-next-line react-hooks/set-state-in-effect -- client-only pref read post-mount; lazy init would cause a hydration mismatch
    if (saved === '7d' || saved === '30d') setTimeWindow(saved);
  }, []);

  useEffect(() => {
    localStorage.setItem('recentMoversTimeWindow', timeWindow);
  }, [timeWindow]);

  const recentMovers = timeWindow === '7d' ? initialMovers7d : initialMovers30d;

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
      </CardContent>
    </Card>
  );
}
