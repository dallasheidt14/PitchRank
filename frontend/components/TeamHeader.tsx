'use client';

import { Card, CardContent } from '@/components/ui/card';
import { TeamCardSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useTeam } from '@/lib/hooks';
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
  
  // Team data from api.getTeam already includes ranking data (TeamWithRanking)
  // Use it directly instead of looking it up in rankings list
  const teamRanking = useMemo(() => {
    if (!team) {
      console.log('[TeamHeader] No team data');
      return null;
    }
    
    // Check if team has ranking fields (TeamWithRanking type)
    const hasRankingData = 'rank_in_cohort_final' in team || 'power_score_final' in team;
    
    console.log('[TeamHeader] Team ranking data:', {
      teamId: team.team_id_master,
      teamName: team.team_name,
      hasRankingData,
      rank_in_cohort_final: (team as any).rank_in_cohort_final,
      rank_in_state_final: (team as any).rank_in_state_final,
      win_percentage: (team as any).win_percentage,
      wins: (team as any).wins,
      losses: (team as any).losses,
      draws: (team as any).draws,
      games_played: (team as any).games_played,
      power_score_final: (team as any).power_score_final,
      sos_norm: (team as any).sos_norm,
      allKeys: Object.keys(team),
    });
    
    // Return team itself if it has ranking data, otherwise null
    return hasRankingData ? (team as any) : null;
  }, [team]);

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
                {team.state && (
                  <Badge variant="outline" className="ml-2">
                    {team.state}
                  </Badge>
                )}
                <Badge variant="outline">
                  {team.age != null ? `U${team.age}` : (team as any).age_group?.toUpperCase() || 'N/A'} {team.gender === 'M' ? 'Boys' : team.gender === 'F' ? 'Girls' : team.gender === 'B' ? 'Boys' : team.gender === 'G' ? 'Girls' : team.gender}
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
            {teamRanking?.rank_in_state_final && (
              <div>
                <div className="text-sm text-muted-foreground mb-1">State Rank</div>
                <div className="text-2xl font-semibold">
                  #{teamRanking.rank_in_state_final}
                </div>
              </div>
            )}
            <div>
              <div className="text-sm text-muted-foreground mb-1">Games Played</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.games_played || 0}
              </div>
            </div>
            <div>
              <div className="text-sm text-muted-foreground mb-1">Win %</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.win_percentage != null ? `${teamRanking.win_percentage.toFixed(1)}%` : '—'}
              </div>
            </div>
          </div>

          {teamRanking && (
            <div className="pt-4 border-t">
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Record: </span>
                  <span className="font-medium">
                    {teamRanking.wins ?? 0}-{teamRanking.losses ?? 0}
                    {(teamRanking.draws ?? 0) > 0 && `-${teamRanking.draws}`}
                  </span>
                </div>
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

