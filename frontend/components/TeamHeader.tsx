'use client';

import { Card, CardContent } from '@/components/ui/card';
import { TeamCardSkeleton } from '@/components/ui/skeletons';
import { useTeam, useRankings } from '@/lib/hooks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useMemo, useState, useEffect } from 'react';
import { Star } from 'lucide-react';
import { addToWatchlist, removeFromWatchlist, isWatched } from '@/lib/watchlist';

interface TeamHeaderProps {
  teamId: string;
}

/**
 * TeamHeader component - displays team information header
 */
export function TeamHeader({ teamId }: TeamHeaderProps) {
  const { data: team, isLoading: teamLoading, isError: teamError, error: teamErrorObj } = useTeam(teamId);
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
        national_rank: found.national_rank,
        national_power_score: found.national_power_score,
        power_score: found.power_score 
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
          <div className="rounded-lg bg-destructive/10 p-4 text-destructive">
            <p className="text-sm font-semibold mb-2">Failed to load team information.</p>
            {process.env.NODE_ENV === 'development' && teamErrorObj && (
              <p className="text-xs text-muted-foreground mt-2">
                Error: {teamErrorObj instanceof Error ? teamErrorObj.message : JSON.stringify(teamErrorObj)}
                <br />
                Team ID: {teamId}
                <br />
                Has Team: {team ? 'Yes' : 'No'}
                <br />
                Is Error: {teamError ? 'Yes' : 'No'}
                <br />
                Is Loading: {teamLoading ? 'Yes' : 'No'}
              </p>
            )}
          </div>
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
              <div className="text-4xl font-bold">
                {teamRanking 
                  ? (teamRanking.national_power_score ?? teamRanking.power_score ?? null) != null
                    ? (teamRanking.national_power_score ?? teamRanking.power_score ?? 0).toFixed(1)
                    : '—'
                  : '—'}
              </div>
              <div className="text-sm text-muted-foreground">Power Score</div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t">
            <div>
              <div className="text-sm text-muted-foreground mb-1">National Rank</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.national_rank ? `#${teamRanking.national_rank}` : '—'}
              </div>
            </div>
            <div>
              <div className="text-sm text-muted-foreground mb-1">State Rank</div>
              <div className="text-2xl font-semibold">
                {teamRanking?.state_rank ? `#${teamRanking.state_rank}` : '—'}
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
                <div>
                  <span className="text-muted-foreground">Goals For: </span>
                  <span className="font-medium">{teamRanking.games_played > 0 ? (teamRanking.wins + teamRanking.draws * 0.5) : 0}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Strength of Schedule: </span>
                  <span className="font-medium">
                    {teamRanking.strength_of_schedule != null
                      ? teamRanking.strength_of_schedule.toFixed(2)
                      : '—'}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
