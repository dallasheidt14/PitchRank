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
import { ShareButtons } from '@/components/ShareButtons';
import { TeamSchema } from '@/components/TeamSchema';

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
    <>
      {/* Team Structured Data */}
      <TeamSchema
        teamName={team.team_name}
        clubName={team.club_name || undefined}
        state={team.state || undefined}
        ageGroup={team.age || undefined}
        gender={team.gender}
        rank={teamRanking?.rank_in_cohort_final || undefined}
        powerScore={teamRanking?.power_score_final || undefined}
        wins={teamRanking?.wins || undefined}
        losses={teamRanking?.losses || undefined}
        draws={teamRanking?.draws || undefined}
      />

      <Card className="border-l-4 border-l-accent overflow-hidden">
        {/* Team Name Header with Green Gradient */}
        <div className="relative bg-gradient-to-r from-primary to-primary/90 px-4 sm:px-6 py-4">
          <div className="absolute left-0 top-0 w-1.5 h-full bg-accent -skew-x-12" aria-hidden="true" />
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h1 className="text-xl sm:text-2xl md:text-3xl font-display font-bold uppercase text-primary-foreground tracking-wide">
                {team.team_name}
              </h1>
              <Button
                variant={watched ? "secondary" : "outline"}
                size="sm"
                onClick={handleWatchToggle}
                className={`transition-colors duration-300 ${watched ? '' : 'bg-transparent border-primary-foreground text-primary-foreground hover:bg-primary-foreground hover:text-primary'}`}
                aria-label={watched ? "Unwatch team" : "Watch team"}
              >
                <Star className={`h-4 w-4 mr-1 ${watched ? 'fill-current' : ''}`} />
                {watched ? 'Watching' : 'Watch'}
              </Button>
            </div>
            <div className="text-left sm:text-right">
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <div className="font-mono text-2xl sm:text-3xl font-bold text-accent">
                      {formatPowerScore(teamRanking?.power_score_final)}
                    </div>
                    <div className="text-xs sm:text-sm text-primary-foreground/80">PowerScore</div>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  <p>A machine-learning-enhanced ranking score that measures overall team strength based on offense, defense, schedule difficulty, and predictive performance patterns.</p>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
        </div>

        <CardContent className="pt-4 sm:pt-6 px-4 sm:px-6">
          <div className="space-y-4 sm:space-y-6">
            <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
              {team.club_name && (
                <span className="text-base sm:text-lg font-medium">{team.club_name}</span>
              )}
              {team.state && (
                <Badge variant="outline" className="ml-0 sm:ml-2">
                  {team.state}
                </Badge>
              )}
              <Badge variant="outline">
                {team.age != null ? `U${team.age}` : 'N/A'} {team.gender === 'M' ? 'Boys' : team.gender === 'F' ? 'Girls' : team.gender === 'B' ? 'Boys' : team.gender === 'G' ? 'Girls' : team.gender}
              </Badge>
            </div>

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-4 pt-4 border-t">
            <div>
              <div className="text-xs sm:text-sm text-muted-foreground mb-1">National Rank</div>
              <div className="text-xl sm:text-2xl font-semibold">
                {teamRanking?.rank_in_cohort_final ? `#${teamRanking.rank_in_cohort_final}` : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs sm:text-sm text-muted-foreground mb-1">State Rank</div>
              <div className="text-xl sm:text-2xl font-semibold">
                {teamRanking?.rank_in_state_final ? `#${teamRanking.rank_in_state_final}` : '—'}
              </div>
            </div>
            <div>
              <div className="text-xs sm:text-sm text-muted-foreground mb-1">Games Played</div>
              <div className="text-xl sm:text-2xl font-semibold">
                {teamRanking?.total_games_played ?? teamRanking?.games_played ?? 0}
              </div>
            </div>
            <div>
              <div className="text-xs sm:text-sm text-muted-foreground mb-1">Win %</div>
              <div className="text-xl sm:text-2xl font-semibold">
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

          {/* Share Buttons */}
          <div className="pt-4 border-t">
            <ShareButtons
              title={`⚽ ${team.team_name} is ranked #${teamRanking?.rank_in_cohort_final || 'N/A'} ${team.state ? `in ${team.state}` : 'nationally'} for ${team.age ? `U${team.age}` : ''} ${team.gender === 'M' || team.gender === 'B' ? 'Boys' : 'Girls'} on PitchRank!`}
              hashtags={['YouthSoccer', 'PitchRank', team.age ? `U${team.age}Soccer` : 'Soccer']}
            />
          </div>
        </div>
      </CardContent>
    </Card>
    </>
  );
}

