'use client';

import { Card, CardContent } from '@/components/ui/card';
import { TeamCardSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useTeam } from '@/lib/hooks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useMemo, useState, useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Star, ChevronDown, Loader2 } from 'lucide-react';
import { addToWatchlist, removeFromWatchlist, isWatched, addToSupabaseWatchlist, removeFromSupabaseWatchlist } from '@/lib/watchlist';
import type { WatchlistResponse } from '@/app/api/watchlist/route';
import { formatPowerScore } from '@/lib/utils';
import { useUser, hasPremiumAccess } from '@/hooks/useUser';
import { ShareButtons } from '@/components/ShareButtons';
import { NotificationBell } from '@/components/NotificationBell';
import { TeamSchema } from '@/components/TeamSchema';
import { trackTeamPageViewed, trackWatchlistAdded, trackWatchlistRemoved } from '@/lib/events';
import { toast } from '@/components/ui/Toaster';

interface TeamAlias {
  id: string;
  provider_team_id: string;
  match_method: string;
  match_confidence: number;
  review_status: string;
  division: string | null;  // MLS NEXT: 'HD' or 'AD'
  created_at: string;
  provider: {
    id: string;
    name: string;
  } | null;
}

interface TeamHeaderProps {
  teamId: string;
}

/**
 * TeamHeader component - displays team information header
 */
export function TeamHeader({ teamId }: TeamHeaderProps) {
  const { data: team, isLoading: teamLoading, isError: teamError, error: teamErrorObj, refetch: refetchTeam } = useTeam(teamId);
  const { profile, isLoading: userLoading, user } = useUser();
  const queryClient = useQueryClient();
  // Wait for user loading to complete before determining premium status
  // This prevents race conditions where profile is null during initial load
  const isPremium = !userLoading && hasPremiumAccess(profile);

  const [watched, setWatched] = useState(false);
  const [isToggling, setIsToggling] = useState(false);
  const hasTrackedPageView = useRef(false);

  // Aliases popover state
  const [aliasesOpen, setAliasesOpen] = useState(false);
  const [aliases, setAliases] = useState<TeamAlias[]>([]);
  const [aliasesLoading, setAliasesLoading] = useState(false);
  const [aliasesFetched, setAliasesFetched] = useState(false);

  // Fetch aliases when popover opens
  const fetchAliases = useCallback(async () => {
    if (aliasesFetched || aliasesLoading) return;

    setAliasesLoading(true);
    try {
      const response = await fetch(`/api/team-aliases/${teamId}`);
      if (response.ok) {
        const data = await response.json();
        setAliases(data.aliases || []);
        setAliasesFetched(true);
      }
    } catch (error) {
      console.error('Failed to fetch aliases:', error);
    } finally {
      setAliasesLoading(false);
    }
  }, [teamId, aliasesFetched, aliasesLoading]);

  // Fetch aliases when popover opens
  useEffect(() => {
    if (aliasesOpen && !aliasesFetched) {
      fetchAliases();
    }
  }, [aliasesOpen, aliasesFetched, fetchAliases]);

  // Team data from api.getTeam already includes ranking data (TeamWithRanking)
  // Use it directly instead of looking it up in rankings list
  const teamRanking = useMemo(() => {
    if (!team) {
      return null;
    }

    // Check if team has ranking fields (TeamWithRanking type)
    const hasRankingData = team.rank_in_cohort_final != null || team.power_score_final != null;

    // Return team itself if it has ranking data, otherwise null
    return hasRankingData ? team : null;
  }, [team]);

  // Check if team is watched
  // For premium users, check Supabase watchlist cache and subscribe to updates
  // For free users, check localStorage
  useEffect(() => {
    if (!teamId) return;

    if (isPremium) {
      // Function to check cache and update state
      const checkWatchlistCache = () => {
        const cachedWatchlist = queryClient.getQueryData<WatchlistResponse | null>(['watchlist']);
        if (cachedWatchlist?.teams) {
          const isInWatchlist = cachedWatchlist.teams.some(t => t.team_id_master === teamId);
          setWatched(isInWatchlist);
        }
      };

      // Check immediately
      checkWatchlistCache();

      // Subscribe to cache updates so we react when watchlist is fetched/updated
      const unsubscribe = queryClient.getQueryCache().subscribe((event) => {
        if (event.query.queryKey[0] === 'watchlist') {
          checkWatchlistCache();
        }
      });

      return () => unsubscribe();
    } else {
      // Free users use localStorage
      setWatched(isWatched(teamId));
    }
  }, [teamId, isPremium, queryClient]);

  // Track team page viewed once when team data loads
  useEffect(() => {
    if (team && !hasTrackedPageView.current) {
      hasTrackedPageView.current = true;
      trackTeamPageViewed({
        team_id_master: team.team_id_master,
        team_name: team.team_name,
        club_name: team.club_name,
        state: team.state,
        age: team.age,
        gender: team.gender,
        rank_in_cohort_final: team.rank_in_cohort_final,
        power_score_final: team.power_score_final,
      });
    }
  }, [team]);

  const handleWatchToggle = async () => {
    if (!team || isToggling) return;

    const eventPayload = {
      team_id_master: teamId,
      team_name: team.team_name,
      club_name: team.club_name,
      state: team.state,
      rank_in_cohort_final: team.rank_in_cohort_final,
    };

    setIsToggling(true);

    try {
      if (watched) {
        // Remove from watchlist
        if (isPremium) {
          const result = await removeFromSupabaseWatchlist(teamId);
          if (!result.success) {
            console.error('Failed to remove from watchlist:', result.message);
            toast({
              title: 'Error',
              description: result.message || 'Failed to remove from watchlist',
              variant: 'error',
            });
            return;
          }
          toast({
            title: 'Removed from watchlist',
            description: `${team.team_name} has been removed`,
            variant: 'success',
          });
          // Invalidate watchlist cache so the page shows updated data
          queryClient.invalidateQueries({ queryKey: ['watchlist'] });
        } else {
          removeFromWatchlist(teamId);
        }
        setWatched(false);
        trackWatchlistRemoved(eventPayload);
      } else {
        // Add to watchlist
        if (isPremium) {
          const result = await addToSupabaseWatchlist(teamId);
          if (!result.success) {
            console.error('Failed to add to watchlist:', result.message);
            toast({
              title: 'Error',
              description: result.message || 'Failed to add to watchlist',
              variant: 'error',
            });
            return;
          }
          toast({
            title: 'Added to watchlist',
            description: `${team.team_name} is now being tracked`,
            variant: 'success',
          });
          // Invalidate and refetch watchlist cache so the page shows updated data
          queryClient.invalidateQueries({ queryKey: ['watchlist'] });
          // Add small delay to ensure database commit completes before refetch
          await new Promise(resolve => setTimeout(resolve, 200));
          await queryClient.refetchQueries({ queryKey: ['watchlist'] });
        } else {
          addToWatchlist(teamId);
        }
        setWatched(true);
        trackWatchlistAdded(eventPayload);
      }
    } finally {
      setIsToggling(false);
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
              <div className="relative">
                <button
                  onClick={() => setAliasesOpen(!aliasesOpen)}
                  className="flex items-center gap-1.5 text-xl sm:text-2xl md:text-3xl font-display font-bold uppercase text-primary-foreground tracking-wide hover:text-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
                  aria-label="View team aliases"
                  aria-expanded={aliasesOpen}
                >
                  {team.team_name}
                  <ChevronDown className={`h-4 w-4 sm:h-5 sm:w-5 opacity-70 transition-transform ${aliasesOpen ? 'rotate-180' : ''}`} />
                </button>

                {/* Aliases Dropdown */}
                {aliasesOpen && (
                  <>
                    {/* Backdrop to close dropdown when clicking outside */}
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setAliasesOpen(false)}
                    />
                    <Card className="absolute left-0 top-full mt-2 w-80 z-50 shadow-lg border">
                      <div className="p-3 border-b">
                        <h3 className="font-semibold text-sm">Team Aliases</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          Provider IDs linked to this team
                        </p>
                      </div>
                      <div className="max-h-64 overflow-y-auto">
                        {aliasesLoading ? (
                          <div className="flex items-center justify-center p-4">
                            <Loader2 className="h-4 w-4 animate-spin mr-2" />
                            <span className="text-sm text-muted-foreground">Loading aliases...</span>
                          </div>
                        ) : aliases.length === 0 ? (
                          <div className="p-4 text-center text-sm text-muted-foreground">
                            No aliases found
                          </div>
                        ) : (
                          <div className="divide-y">
                            {aliases.map((alias) => (
                              <div key={alias.id} className="p-3 hover:bg-muted/50 transition-colors">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0 flex-1">
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                      <span className="font-mono text-sm font-medium truncate">
                                        {alias.provider_team_id}
                                      </span>
                                      {alias.division && (
                                        <Badge
                                          variant="outline"
                                          className={`text-xs shrink-0 ${
                                            alias.division === 'HD'
                                              ? 'border-green-500 text-green-600'
                                              : 'border-yellow-500 text-yellow-600'
                                          }`}
                                        >
                                          {alias.division}
                                        </Badge>
                                      )}
                                      {alias.provider?.name && (
                                        <Badge variant="secondary" className="text-xs shrink-0">
                                          {alias.provider.name}
                                        </Badge>
                                      )}
                                    </div>
                                    <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                                      <span className="capitalize">{alias.match_method.replace('_', ' ')}</span>
                                      <span>•</span>
                                      <span>{Math.round(alias.match_confidence * 100)}% confidence</span>
                                    </div>
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </Card>
                  </>
                )}
              </div>
              <Button
                variant={watched ? "secondary" : "outline"}
                size="sm"
                onClick={handleWatchToggle}
                disabled={isToggling}
                className={`transition-colors duration-300 ${watched ? '' : 'bg-transparent border-primary-foreground text-primary-foreground hover:bg-primary-foreground hover:text-primary'}`}
                aria-label={watched ? "Unwatch team" : "Watch team"}
              >
                {isToggling ? (
                  <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                ) : (
                  <Star className={`h-4 w-4 mr-1 ${watched ? 'fill-current' : ''}`} />
                )}
                {isToggling ? 'Saving...' : watched ? 'Watching' : 'Watch'}
              </Button>
              <NotificationBell />
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
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <div className="text-xs sm:text-sm text-muted-foreground mb-1">Games Played</div>
                    <div className="text-xl sm:text-2xl font-semibold">
                      {teamRanking?.games_played ?? 0}/{teamRanking?.total_games_played ?? 0}
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Ranked games (used in rankings) / Total games played</p>
                </TooltipContent>
              </Tooltip>
            </div>
            <div>
              <div className="text-xs sm:text-sm text-muted-foreground mb-1">Win %</div>
              <div className="text-xl sm:text-2xl font-semibold">
                {teamRanking?.win_percentage != null ? `${teamRanking.win_percentage.toFixed(1)}%` : '—'}
              </div>
            </div>
          </div>

          {teamRanking && (
            <>
            {/* Offense / Defense Gauges */}
            {(teamRanking.offense_norm != null || teamRanking.defense_norm != null) && (
              <div className="pt-4 border-t">
                <div className="grid grid-cols-2 gap-4">
                  {teamRanking.offense_norm != null && (() => {
                    const pct = Math.round(teamRanking.offense_norm * 100);
                    const color = pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-500' : 'bg-red-500';
                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div>
                            <div className="flex justify-between text-xs sm:text-sm mb-1">
                              <span className="text-muted-foreground">Offense</span>
                              <span className="font-semibold">{pct}th %ile</span>
                            </div>
                            <div className="h-2.5 bg-muted rounded-full overflow-hidden">
                              <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Offensive strength: better than {pct}% of teams in this age group</p>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })()}
                  {teamRanking.defense_norm != null && (() => {
                    const pct = Math.round(teamRanking.defense_norm * 100);
                    const color = pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-500' : 'bg-red-500';
                    return (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div>
                            <div className="flex justify-between text-xs sm:text-sm mb-1">
                              <span className="text-muted-foreground">Defense</span>
                              <span className="font-semibold">{pct}th %ile</span>
                            </div>
                            <div className="h-2.5 bg-muted rounded-full overflow-hidden">
                              <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Defensive strength: better than {pct}% of teams in this age group</p>
                        </TooltipContent>
                      </Tooltip>
                    );
                  })()}
                </div>
              </div>
            )}

            <div className="pt-4 border-t">
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">Record: </span>
                  <span className="font-medium">
                    {teamRanking.total_wins ?? 0}-{teamRanking.total_losses ?? 0}
                    {(teamRanking.total_draws ?? 0) > 0 && `-${teamRanking.total_draws}`}
                  </span>
                </div>
                <div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <span className="text-muted-foreground">State SOS: </span>
                        <span className="font-medium">
                          {teamRanking.sos_rank_state ? `#${teamRanking.sos_rank_state} in ${team.state || 'state'}` : '—'}
                        </span>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Strength of Schedule — #{teamRanking.sos_rank_state} toughest schedule in {team.state || 'state'} for this age group. Lower = harder opponents faced.</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <div>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span>
                        <span className="text-muted-foreground">National SOS: </span>
                        <span className="font-medium">
                          {teamRanking.sos_rank_national ? `#${teamRanking.sos_rank_national}` : '—'}
                        </span>
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>#{teamRanking.sos_rank_national} toughest schedule nationally for this age group. Lower = harder opponents faced.</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
              </div>
            </div>
            </>
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

