'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ListSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useRankings } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { usePrefetchTeam } from '@/lib/hooks';
import { useEffect, useRef } from 'react';
import { getWatchedTeams } from '@/lib/watchlist';
import { launchConfetti } from '@/components/ui/confetti';
import { formatPowerScore } from '@/lib/utils';
import { getErrorMessage } from '@/lib/errors';

/**
 * HomeLeaderboard component - displays featured rankings on the home page
 * Shows top 10 national teams for U12 Male as default
 * Triggers confetti when a watched team reaches #1
 */
export function HomeLeaderboard() {
  const { data: rankings, isLoading, isError, error, refetch } = useRankings(null, 'u12', 'M');
  const prefetchTeam = usePrefetchTeam();
  const confettiTriggeredRef = useRef<Set<string>>(new Set());

  // Get top 10 teams
  const topTeams = rankings?.slice(0, 10) || [];

  // Check for watched teams reaching #1 and trigger confetti
  useEffect(() => {
    if (!rankings || rankings.length === 0) return;
    
    const watchedTeams = getWatchedTeams();
    const topTeam = rankings[0];
    
    if (topTeam && topTeam.rank_in_cohort_final === 1 && watchedTeams.includes(topTeam.team_id_master)) {
      // Check if we've already triggered confetti for this team in this session
      const sessionKey = `confetti_${topTeam.team_id_master}`;
      const lastConfettiTeamId = sessionStorage.getItem('lastConfettiTeamId');
      
      if (lastConfettiTeamId !== topTeam.team_id_master && !confettiTriggeredRef.current.has(sessionKey)) {
        launchConfetti();
        sessionStorage.setItem('lastConfettiTeamId', topTeam.team_id_master);
        confettiTriggeredRef.current.add(sessionKey);
      }
    }
  }, [rankings]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Featured Rankings</CardTitle>
        <CardDescription>
          Top 10 U12 Male teams ranked by power score
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && <ListSkeleton items={5} />}

        {isError && (
          <ErrorDisplay error={error} retry={refetch} />
        )}

        {!isLoading && !isError && (
          <div className="space-y-2">
            {topTeams.length === 0 ? (
              <div className="text-sm text-muted-foreground text-center py-8">
                <p>No rankings data available</p>
                <p className="text-xs mt-2">
                  Rankings count: {rankings?.length || 0} | 
                  Loading: {isLoading ? 'Yes' : 'No'} | 
                  Error: {isError ? 'Yes' : 'No'}
                </p>
                {error && (
                  <p className="text-xs text-red-500 mt-2">
                    Error: {getErrorMessage(error)}
                  </p>
                )}
              </div>
            ) : (
              topTeams.map((team, index) => {
                const previousRank = index > 0 ? topTeams[index - 1].rank_in_cohort_final : null;
                const rankChange = previousRank && team.rank_in_cohort_final
                  ? previousRank - team.rank_in_cohort_final
                  : 0;

                return (
                  <Link
                    key={team.team_id_master}
                    href={`/teams/${team.team_id_master}`}
                    onMouseEnter={() => prefetchTeam(team.team_id_master)}
                    className="flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-accent hover:shadow-md transition-all duration-300"
                    aria-label={`View ${team.team_name} team details`}
                    tabIndex={0}
                  >
                    <div className="flex items-center gap-4 flex-1 min-w-0">
                      <div className="flex-shrink-0 w-8 text-center font-semibold">
                        {team.rank_in_cohort_final || '—'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate">{team.team_name}</div>
                        <div className="text-sm text-muted-foreground truncate">
                          {team.club_name && <span>{team.club_name}</span>}
                          {team.state && (
                            <span className={team.club_name ? ' • ' : ''}>
                              {team.state}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 flex-shrink-0">
                      {rankChange !== 0 && (
                        <div className={`flex items-center gap-1 text-xs ${
                          rankChange > 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                        }`}>
                          {rankChange > 0 ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : (
                            <ArrowDown className="h-3 w-3" />
                          )}
                          {Math.abs(rankChange)}
                        </div>
                      )}
                      <div className="text-right">
                        <div className="font-semibold">
                          {formatPowerScore(team.power_score_final)}
                        </div>
                        <div className="text-xs text-muted-foreground">PowerScore (ML Adjusted)</div>
                      </div>
                    </div>
                  </Link>
                );
              })
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
