'use client';

import { useCallback } from 'react';
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
// Using native Date formatting instead of date-fns
import Link from 'next/link';
import { usePrefetchTeam } from '@/lib/hooks';
import type { GameWithTeams } from '@/lib/types';
import { MissingGamesForm } from '@/components/MissingGamesForm';
import { UnknownOpponentLink } from '@/components/UnknownOpponentLink';

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
  const lastScrapedAt: string | null = gamesData?.lastScrapedAt ?? null;

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
          <div className="flex items-start justify-between">
            <div>
              <CardTitle>Game History</CardTitle>
              <CardDescription>
                {limit ? `Latest ${limit} match results` : 'All match results'}
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
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
          <div className="flex items-start justify-between">
            <div>
              <CardTitle>Game History</CardTitle>
              <CardDescription>
                {limit ? `Latest ${limit} match results` : 'All match results'}
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
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
          <div className="flex items-start justify-between">
            <div>
              <CardTitle>Game History</CardTitle>
              <CardDescription>
                {limit ? `Latest ${limit} match results` : 'All match results'}
              </CardDescription>
            </div>
            <div className="flex flex-col items-end gap-2">
              <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
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
    <Card className="border-l-4 border-l-accent">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="font-display uppercase tracking-wide">Game History</CardTitle>
            <CardDescription>
              {limit ? `Latest ${limit} match results` : 'All match results'}
            </CardDescription>
          </div>
          <div className="flex flex-col items-end gap-2">
            <LastUpdated date={lastScrapedAt} label="Data updated" />
            <MissingGamesForm teamId={teamId} teamName={displayTeamName} />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Opponent</TableHead>
              <TableHead className="text-center">Result</TableHead>
              <TableHead className="text-right">Score</TableHead>
              <TableHead>Competition</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {games.map((game) => {
              const result = getResult(game, teamId);
              const opponent = getOpponent(game, teamId);
              const opponentClub = getOpponentClub(game, teamId);
              const opponentId = getOpponentId(game, teamId);
              const opponentProviderId = getOpponentProviderId(game, teamId);
              const score = getScore(game, teamId);

              return (
                <TableRow key={game.id}>
                  <TableCell className="text-sm">
                    {new Date(game.game_date).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </TableCell>
                  <TableCell>
                    {opponentId && opponent ? (
                      <div className="flex flex-col">
                        <Link
                          href={`/teams/${opponentId}`}
                          onMouseEnter={() => prefetchTeam(opponentId)}
                          className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block"
                          aria-label={`View ${opponent} team details`}
                        >
                          {opponent}
                        </Link>
                        {opponentClub && (
                          <span className="text-xs text-muted-foreground mt-0.5">
                            {opponentClub}
                          </span>
                        )}
                      </div>
                    ) : opponentProviderId ? (
                      <UnknownOpponentLink
                        game={game}
                        currentTeamId={teamId}
                        opponentProviderId={opponentProviderId}
                        onLinked={() => refetch()}
                        defaultAge={team?.age}
                        defaultGender={team?.gender}
                      />
                    ) : (
                      <span className="text-muted-foreground">{opponent || 'Unknown'}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    {result.text}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {score.team !== null && score.opponent !== null ? (
                      <span className={scoreColor(getTeamPerspectiveOverperformance(game, teamId))}>
                        {score.team} - {score.opponent}
                      </span>
                    ) : (
                      '—'
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {game.competition || game.division_name || '—'}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

