'use client';

import { useCallback, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TableSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { LastUpdated } from '@/components/ui/LastUpdated';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useTeamGames, useTeam } from '@/lib/hooks';
import { formatGameDate } from '@/lib/dateUtils';
import Link from 'next/link';
import { usePrefetchTeam } from '@/lib/hooks';
import type { GameWithTeams } from '@/lib/types';
import { MissingGamesForm } from '@/components/MissingGamesForm';
import { UnknownOpponentLink } from '@/components/UnknownOpponentLink';
import { MergeTeamsDialogWrapper } from '@/components/MergeTeamsDialogWrapper';
import { useQueryClient } from '@tanstack/react-query';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

function UnlinkOpponentButton({
  game,
  currentTeamId,
  opponentName,
  onUnlinked,
}: {
  game: GameWithTeams;
  currentTeamId: string;
  opponentName: string | undefined;
  onUnlinked: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [isUnlinking, setIsUnlinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const isHome = game.home_team_master_id === currentTeamId;
  const opponentId = isHome ? game.away_team_master_id : game.home_team_master_id;
  const opponentProviderId = isHome ? game.away_provider_id : game.home_provider_id;

  const handleUnlink = async () => {
    setIsUnlinking(true);
    setError(null);

    try {
      const response = await fetch('/api/unlink-opponent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gameId: game.id,
          opponentProviderId,
          teamIdMaster: opponentId,
          unlinkAllGames: true,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to unlink team');
      }

      await queryClient.refetchQueries({
        queryKey: ['team-games', currentTeamId],
        type: 'active',
      });

      setIsOpen(false);
      onUnlinked();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setIsUnlinking(false);
    }
  };

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="text-muted-foreground hover:text-destructive transition-colors text-xs ml-1 opacity-0 group-hover:opacity-100 focus:opacity-100"
        title="Unlink this opponent"
        aria-label={`Unlink ${opponentName || 'opponent'}`}
      >
        &times;
      </button>
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Unlink Opponent</DialogTitle>
            <DialogDescription>
              Are you sure you want to unlink <strong>{opponentName || 'this opponent'}</strong> from this game?
              This will also unlink all other games with the same provider ID and remove the alias mapping.
            </DialogDescription>
          </DialogHeader>
          <div className="bg-muted/50 rounded-lg p-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-muted-foreground">Date:</span>{' '}
                <span className="font-medium">{formatGameDate(game.game_date)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Score:</span>{' '}
                <span className="font-medium">
                  {game.home_score !== null && game.away_score !== null
                    ? `${game.home_score} - ${game.away_score}`
                    : 'No score'}
                </span>
              </div>
            </div>
          </div>
          {error && (
            <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-3">
              <p className="text-red-800 dark:text-red-200 text-sm">{error}</p>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsOpen(false)} disabled={isUnlinking}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleUnlink} disabled={isUnlinking}>
              {isUnlinking ? 'Unlinking...' : 'Unlink'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

interface GameHistoryTableProps {
  teamId: string;
  limit?: number;
  teamName?: string;
}

/**
 * GameHistoryTable component - displays all games for a team
 */
export function GameHistoryTable({ teamId, limit, teamName }: GameHistoryTableProps) {
  // Default to 100 games for better performance - users rarely need all games at once
  const gamesLimit = limit ?? 100;
  const { data, isLoading, isError, error, refetch } = useTeamGames(teamId, gamesLimit);
  const prefetchTeam = usePrefetchTeam();
  
  // Fetch team name if not provided (React Query will reuse cached data from TeamHeader)
  const { data: team } = useTeam(teamId);
  const displayTeamName = teamName || team?.team_name || 'this team';
  
  // Extract games and lastScrapedAt from data with proper typing
  type TeamGamesData = { games: GameWithTeams[]; lastScrapedAt: string | null };
  const gamesData = data as TeamGamesData | undefined;
  const games: GameWithTeams[] | undefined = gamesData?.games;
  // Prefer team.last_scraped_at (updated every scrape run, even when no new games found)
  // over game-derived lastScrapedAt (only reflects when the most recent game was scraped)
  const lastScrapedAt: string | null = team?.last_scraped_at ?? gamesData?.lastScrapedAt ?? null;

  /**
   * Get the ML overperformance value from the team's perspective
   * Database stores from home team's perspective, so flip sign for away team
   */
  const getTeamPerspectiveOverperformance = useCallback((game: GameWithTeams, currentTeamId: string): number | null => {
    if (game.ml_overperformance === null || game.ml_overperformance === undefined) {
      return null;
    }

    const isHome = game.home_team_master_id === currentTeamId;
    // Home team: use value as-is. Away team: flip the sign
    return isHome ? game.ml_overperformance : -game.ml_overperformance;
  }, []);

  /**
   * Get color class for score based on ML over/underperformance
   * @param ml_overperformance - residual value (actual - expected goal margin) from team's perspective
   * Green highlight if ≥ +2 (outperformed by 2+ goals), Red highlight if ≤ -2 (underperformed by 2+ goals)
   * Note: Backend only provides ml_overperformance for teams with 6+ games
   */
  const scoreColor = useCallback((ml_overperformance: number | null): string => {
    if (ml_overperformance !== null && ml_overperformance !== undefined) {
      if (ml_overperformance >= 2) return "bg-green-100 dark:bg-green-900/30 px-2 py-1 rounded font-bold";
      if (ml_overperformance <= -2) return "bg-red-100 dark:bg-red-900/30 px-2 py-1 rounded font-bold";
    }
    return ""; // no highlight for neutral performance
  }, []);

  const getResult = useCallback((game: GameWithTeams, currentTeamId: string) => {
    const isHome = game.home_team_master_id === currentTeamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const opponentScore = isHome ? game.away_score : game.home_score;

    if (teamScore === null || opponentScore === null) return { text: '—' };

    if (teamScore > opponentScore) {
      return { text: 'W' };
    } else if (teamScore < opponentScore) {
      return { text: 'L' };
    } else {
      return { text: 'D' };
    }
  }, []);

  const getOpponent = useCallback((game: GameWithTeams, currentTeamId: string) => {
    const isHome = game.home_team_master_id === currentTeamId;
    return isHome ? game.away_team_name : game.home_team_name;
  }, []);

  const getOpponentClub = useCallback((game: GameWithTeams, currentTeamId: string) => {
    const isHome = game.home_team_master_id === currentTeamId;
    return isHome ? game.away_team_club_name : game.home_team_club_name;
  }, []);

  const getOpponentId = useCallback((game: GameWithTeams, currentTeamId: string) => {
    const isHome = game.home_team_master_id === currentTeamId;
    return isHome ? game.away_team_master_id : game.home_team_master_id;
  }, []);

  const getOpponentProviderId = useCallback((game: GameWithTeams, currentTeamId: string) => {
    const isHome = game.home_team_master_id === currentTeamId;
    return isHome ? game.away_provider_id : game.home_provider_id;
  }, []);

  const getScore = useCallback((game: GameWithTeams, currentTeamId: string) => {
    const isHome = game.home_team_master_id === currentTeamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const opponentScore = isHome ? game.away_score : game.home_score;
    return { team: teamScore, opponent: opponentScore };
  }, []);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>Game History</CardTitle>
              <CardDescription>
                {limit ? `Latest ${limit} match results` : 'All match results'}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:flex-col sm:items-end">
              <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
              {teamId && (
                <MergeTeamsDialogWrapper
                  currentTeamId={teamId}
                  currentTeamName={displayTeamName}
                  currentTeamAgeGroup={team?.age_group}
                  currentTeamGender={team?.gender}
                  currentTeamStateCode={team?.state_code}
                />
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={5} />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>Game History</CardTitle>
              <CardDescription>
                {limit ? `Latest ${limit} match results` : 'All match results'}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:flex-col sm:items-end">
              <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
              {teamId && (
                <MergeTeamsDialogWrapper
                  currentTeamId={teamId}
                  currentTeamName={displayTeamName}
                  currentTeamAgeGroup={team?.age_group}
                  currentTeamGender={team?.gender}
                  currentTeamStateCode={team?.state_code}
                />
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <ErrorDisplay error={error} retry={refetch} fallback={
            <div className="text-center py-8 text-muted-foreground">
              <p>No game history available</p>
            </div>
          } />
        </CardContent>
      </Card>
    );
  }

  if (!games || games.length === 0) {
    return (
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>Game History</CardTitle>
              <CardDescription>
                {limit ? `Latest ${limit} match results` : 'All match results'}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2 sm:flex-col sm:items-end">
              <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
              {teamId && (
                <MergeTeamsDialogWrapper
                  currentTeamId={teamId}
                  currentTeamName={displayTeamName}
                  currentTeamAgeGroup={team?.age_group}
                  currentTeamGender={team?.gender}
                  currentTeamStateCode={team?.state_code}
                />
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-muted-foreground">
            <p>No game history available</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-l-4 border-l-accent overflow-hidden">
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="font-display uppercase tracking-wide">Game History</CardTitle>
            <CardDescription>
              {limit ? `Latest ${limit} match results` : 'All match results'}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:flex-col sm:items-end">
            <LastUpdated date={lastScrapedAt} label="Data updated" />
            <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-0 sm:px-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Opponent</TableHead>
              <TableHead className="text-center">Result</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead className="hidden sm:table-cell">Competition</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {games.map((game) => {
              try {
                const result = getResult(game, teamId);
                const opponent = getOpponent(game, teamId);
                const opponentClub = getOpponentClub(game, teamId);
                const opponentId = getOpponentId(game, teamId);
                const opponentProviderId = getOpponentProviderId(game, teamId);
                const score = getScore(game, teamId);

                return (
                  <TableRow key={game.id} className="group">
                    <TableCell className="text-xs sm:text-sm whitespace-nowrap">
                      {formatGameDate(game.game_date, { month: 'short', day: 'numeric', year: '2-digit' })}
                    </TableCell>
                    <TableCell className="max-w-[140px] sm:max-w-none whitespace-normal sm:whitespace-nowrap">
                      {opponentId ? (
                        // Team is linked - show link or fallback text
                        <div className="flex flex-col">
                          <div className="flex items-center">
                            {opponent ? (
                              <Link
                                href={`/teams/${opponentId}`}
                                onMouseEnter={() => prefetchTeam(opponentId)}
                                className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block truncate sm:whitespace-normal sm:overflow-visible"
                                aria-label={`View ${opponent} team details`}
                                title={opponent}
                              >
                                {opponent}
                              </Link>
                            ) : (
                              // Team is linked but name lookup failed - still show link
                              <Link
                                href={`/teams/${opponentId}`}
                                onMouseEnter={() => prefetchTeam(opponentId)}
                                className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block text-muted-foreground"
                                aria-label="View team details"
                              >
                                (Team linked)
                              </Link>
                            )}
                            <UnlinkOpponentButton
                              game={game}
                              currentTeamId={teamId}
                              opponentName={opponent}
                              onUnlinked={() => refetch()}
                            />
                          </div>
                          {opponentClub && (
                            <span className="text-xs text-muted-foreground mt-0.5 truncate sm:whitespace-normal">
                              {opponentClub}
                            </span>
                          )}
                        </div>
                      ) : opponentProviderId ? (
                        // Team is NOT linked but has provider ID - show linking option
                        <UnknownOpponentLink
                          game={game}
                          currentTeamId={teamId}
                          opponentProviderId={opponentProviderId}
                          onLinked={() => refetch()}
                          defaultAge={team?.age}
                          defaultGender={team?.gender}
                        />
                      ) : (
                        // No team ID and no provider ID - truly unknown
                        <span className="text-muted-foreground truncate sm:whitespace-normal">{opponent || 'Unknown'}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-center">
                      {result.text}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {score.team !== null && score.opponent !== null ? (
                        <span className={scoreColor(getTeamPerspectiveOverperformance(game, teamId))}>
                          {score.team}-{score.opponent}
                        </span>
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell className="hidden sm:table-cell text-sm text-muted-foreground">
                      {game.competition || game.division_name || '—'}
                    </TableCell>
                  </TableRow>
                );
              } catch (rowError) {
                console.error('[GameHistoryTable] Error rendering row:', game?.id, rowError);
                return null;
              }
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

