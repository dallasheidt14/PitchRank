'use client';

import { useEffect } from 'react';
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

interface GameHistoryTableProps {
  teamId: string;
  limit?: number;
  teamName?: string;
}

/**
 * GameHistoryTable component - displays all games for a team
 */
export function GameHistoryTable({ teamId, limit, teamName }: GameHistoryTableProps) {
  // Use a very large number to fetch all games when no limit is specified
  const gamesLimit = limit ?? 10000;
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

  // Debug logging
  useEffect(() => {
    console.log('[GameHistoryTable] Data state:', {
      hasData: !!data,
      dataType: typeof data,
      gamesLength: games?.length,
      isLoading,
      isError,
      error: error?.message,
      teamId,
    });
  }, [data, games, isLoading, isError, error, teamId]);

  /**
   * Get color class for result based on ML over/underperformance
   * @param was_overperformed - true = overperformed (green), false = underperformed (red), null = neutral (gray)
   */
  const resultColor = (was_overperformed?: boolean | null): string => {
    if (was_overperformed === true) return "text-green-600 dark:text-green-400 font-bold";
    if (was_overperformed === false) return "text-red-600 dark:text-red-400 font-bold";
    return "text-gray-700 dark:text-gray-300"; // neutral
  };

  const getResult = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
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
  };

  const getOpponent = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
    return isHome ? game.away_team_name : game.home_team_name;
  };

  const getOpponentClub = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
    return isHome ? game.away_team_club_name : game.home_team_club_name;
  };

  const getOpponentId = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
    return isHome ? game.away_team_master_id : game.home_team_master_id;
  };

  const getScore = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const opponentScore = isHome ? game.away_score : game.home_score;
    return { team: teamScore, opponent: opponentScore };
  };

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
                    ) : (
                      <span className="text-muted-foreground">{opponent || 'Unknown'}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    <span className={resultColor(game.was_overperformed)}>
                      {result.text}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {score.team !== null && score.opponent !== null
                      ? `${score.team} - ${score.opponent}`
                      : '—'}
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

