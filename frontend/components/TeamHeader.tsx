'use client';

import { Card, CardContent } from '@/components/ui/card';
import { TeamCardSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useTeam, useRankings } from '@/lib/hooks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useMemo, useState, useEffect } from 'react';
import { Star } from 'lucide-react';
import { addToWatchlist, removeFromWatchlist, isWatched } from '@/lib/watchlist';
import { formatPowerScore, formatSOSIndex } from '@/lib/utils';

interface TeamHeaderProps {
  teamId: string;
}

/**
 * TeamHeader component - displays team information header
 */
export function TeamHeader({ teamId }: TeamHeaderProps) {
  const { data: team, isLoading: teamLoading, isError: teamError, error: teamErrorObj, refetch: refetchTeam } = useTeam(teamId);
  const [watched, setWatched] = useState(false);
  
  // Debug logging
  useEffect(() => {
    console.log('[TeamHeader] Component props:', { teamId });
    console.log('[TeamHeader] React Query state:', {
      isLoading: teamLoading,
      isError: teamError,
      error: teamErrorObj,
      hasTeam: !!team,
      team: team ? { name: team.team_name, id: team.team_id_master } : null,
      queryKey: ['team', teamId],
    });
  }, [teamId, teamLoading, teamError, teamErrorObj, team]);
  
  // Get ranking for this team
  const { data: rankings } = useRankings(
    team?.state_code || null,
    team?.age_group,
    team?.gender as 'Male' | 'Female' | null | undefined
  );
  
  const teamRanking = useMemo(() => {
    if (!rankings || !team) return null;
    const found = rankings.find(r => r.team_id_master === team.team_id_master);
    console.log('[TeamHeader] Finding team ranking:', {
      teamId: team.team_id_master,
      teamName: team.team_name,
      rankingsCount: rankings?.length,
      found: found ? { 
        rank_in_cohort_final: found.rank_in_cohort_final,
        rank_in_state_final: found.rank_in_state_final,
        power_score_final: found.power_score_final,
      } : null,
      searchParams: {
        state_code: team?.state_code,
        age_group: team?.age_group,
        gender: team?.gender
      }
    });
    return found || null;
  }, [rankings, team]);

  // Check if team is watched
  useEffect(() => {
    if (teamId) {
      setWatched(isWatched(teamId));
    }
  }, [teamId]);

  const handleWatchToggle = () => {
    if (watched) {
      removeFromWatchlist(teamId);
      setWatched(false);
    } else {
      addToWatchlist(teamId);
      setWatched(true);
    }
  };

  if (teamLoading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <TeamCardSkeleton />
        </CardContent>
      </Card>
    );
  }

  // Only show error if we're done loading and have no team data
  // If team data exists, render it even if there was a previous error
  if (!teamLoading && !team) {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorDisplay error={teamErrorObj || new Error('Failed to load team information')} retry={refetchTeam} />
        </CardContent>
      </Card>
    );
  }

  // TypeScript guard: if we reach here and loading is done, team must exist
  if (!team) {
    return null; // Should not happen, but satisfies TypeScript
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="space-y-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-2">
                <h1 className="text-3xl font-bold">{team.team_name}</h1>
                <Button
                  variant={watched ? "default" : "outline"}
                  size="sm"
                  onClick={handleWatchToggle}
                  className="transition-colors duration-300"
                  aria-label={watched ? "Unwatch team" : "Watch team"}
                >
                  <Star className={`h-4 w-4 mr-1 ${watched ? 'fill-current' : ''}`} />
                  {watched ? 'Watching' : 'Watch'}
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
                {team.club_name && (
                  <span className="text-lg">{team.club_name}</span>
                )}
                {team.state_code && (
                  <Badge variant="outline" className="ml-2">
                    {team.state_code}
                  </Badge>
                )}
                <Badge variant="outline">
                  {team.age_group.toUpperCase()} {team.gender}
                </Badge>
              </div>
            </div>
            <div className="text-right">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <div className="text-4xl font-bold">
                      {formatPowerScore(teamRanking?.power_score_final)}
                    </div>
                    <div className="text-sm text-muted-foreground">PowerScore (ML Adjusted)</div>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  <p>A machine-learning-enhanced ranking score that measures overall team strength based on offense, defense, schedule difficulty, and predictive performance patterns.</p>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 pt-4 border-t">
            <div>
              <div className="text-sm text-muted-foreground mb-1">National Rank</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.rank_in_cohort_final ? `#${teamRanking.rank_in_cohort_final}` : '—'}
              </div>
            </div>
            <div>
              <div className="text-sm text-muted-foreground mb-1">State Rank</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.rank_in_state_final ? `#${teamRanking.rank_in_state_final}` : '—'}
              </div>
            </div>
            <div>
              <div className="text-sm text-muted-foreground mb-1">Games Played</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.games_played || 0}
              </div>
            </div>
            <div>
              <div className="text-sm text-muted-foreground mb-1">Win %</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.win_percentage != null
                  ? `${teamRanking.win_percentage.toFixed(1)}%`
                  : '—'}
              </div>
            </div>
          </div>

          {teamRanking && (
            <div className="pt-4 border-t">
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Record: </span>
                  <span className="font-medium">
                    {teamRanking.wins}-{teamRanking.losses}
                    {teamRanking.draws > 0 && `-${teamRanking.draws}`}
                  </span>
                </div>
                {teamRanking.goals_for != null && (
                  <div>
                    <span className="text-muted-foreground">Goals For: </span>
                    <span className="font-medium">{teamRanking.goals_for}</span>
                  </div>
                )}
                <div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <span className="text-muted-foreground">SOS Index: </span>
                        <span className="font-medium">
                          {formatSOSIndex(teamRanking.sos_norm)}
                        </span>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Strength of Schedule normalized within each age group and gender (0 = softest schedule, 100 = toughest).</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
