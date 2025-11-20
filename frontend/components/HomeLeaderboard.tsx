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
    <Card className="overflow-hidden border-0 shadow-lg">
      {/* Header with gradient background */}
      <CardHeader className="bg-gradient-to-r from-primary to-[oklch(0.28_0.08_165)] text-primary-foreground relative overflow-hidden">
        <div className="absolute right-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <CardTitle className="text-2xl sm:text-3xl font-bold uppercase tracking-wide">
          Top 10 Rankings
        </CardTitle>
        <CardDescription className="text-primary-foreground/80 text-base">
          U12 Male • National • Power Score
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && <ListSkeleton items={5} />}

        {isError && (
          <ErrorDisplay error={error} retry={refetch} />
        )}

        {!isLoading && !isError && (
          <div className="divide-y divide-border">
            {topTeams.length === 0 ? (
              <div className="text-sm text-muted-foreground text-center py-8 px-4">
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
                // Use real historical rank change data (7-day change)
                const rankChange = team.rank_change_7d ?? 0;
                const isTopThree = index < 3;

                // Determine badge style based on rank
                const getBadgeClass = (idx: number) => {
                  if (idx === 0) return 'badge-gold';
                  if (idx === 1) return 'badge-silver';
                  if (idx === 2) return 'badge-bronze';
                  return 'bg-secondary text-secondary-foreground';
                };

                return (
                  <Link
                    key={team.team_id_master}
                    href={`/teams/${team.team_id_master}`}
                    onMouseEnter={() => prefetchTeam(team.team_id_master)}
                    className={`flex items-center justify-between p-4 hover:bg-secondary/50 transition-all duration-300 group ${
                      isTopThree ? 'bg-accent/5' : ''
                    }`}
                    aria-label={`View ${team.team_name} team details`}
                    tabIndex={0}
                  >
                    <div className="flex items-center gap-4 sm:gap-6 flex-1 min-w-0">
                      <div className={`flex-shrink-0 w-10 sm:w-12 h-10 sm:h-12 rounded-full flex items-center justify-center font-bold text-lg sm:text-xl ${getBadgeClass(index)}`}>
                        {team.rank_in_cohort_final || '—'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-base sm:text-lg truncate group-hover:text-primary transition-colors">
                          {team.team_name}
                        </div>
                        <div className="text-sm text-muted-foreground truncate">
                          {team.club_name && <span className="font-medium">{team.club_name}</span>}
                          {team.state && (
                            <span className={team.club_name ? ' • ' : ''}>
                              {team.state}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 sm:gap-6 flex-shrink-0">
                      {rankChange !== 0 && (
                        <div className={`flex items-center gap-1 text-sm font-semibold ${
                          rankChange > 0 ? 'text-green-600' : 'text-red-600'
                        }`}>
                          {rankChange > 0 ? (
                            <ArrowUp className="h-4 w-4" />
                          ) : (
                            <ArrowDown className="h-4 w-4" />
                          )}
                          {Math.abs(rankChange)}
                        </div>
                      )}
                      <div className="text-right">
                        <div className="font-mono font-bold text-base sm:text-lg">
                          {formatPowerScore(team.power_score_final)}
                        </div>
                        <div className="text-xs text-muted-foreground uppercase tracking-wide">Power Score</div>
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
