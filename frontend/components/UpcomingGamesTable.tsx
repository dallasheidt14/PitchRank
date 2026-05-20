'use client';

import { useCallback } from 'react';
import Link from 'next/link';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TableSkeleton } from '@/components/ui/skeletons';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useTeamUpcomingGames, usePrefetchTeam } from '@/lib/hooks';
import { formatGameDate } from '@/lib/dateUtils';
import type { GameWithTeams } from '@/lib/types';

interface UpcomingGamesTableProps {
  teamId: string;
  limit?: number;
}

export function UpcomingGamesTable({ teamId, limit }: UpcomingGamesTableProps) {
  // 50 is comfortable headroom — the busiest real team in current data
  // has ~18 upcoming games. Avoids silent truncation without producing a
  // 100-row scrolling card. Bump if real teams start hitting this cap.
  const gamesLimit = limit ?? 50;
  const { data, isLoading, isError, error, refetch } = useTeamUpcomingGames(teamId, gamesLimit);
  const prefetchTeam = usePrefetchTeam();
  const games: GameWithTeams[] | undefined = data?.games;

  const getOpponent = useCallback(
    (game: GameWithTeams) => {
      const isHome = game.home_team_master_id === teamId;
      return {
        id: isHome ? game.away_team_master_id : game.home_team_master_id,
        name: isHome ? game.away_team_name : game.home_team_name,
        club: isHome ? game.away_team_club_name : game.home_team_club_name,
        venue: isHome ? 'Home' : 'Away',
      };
    },
    [teamId]
  );

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="font-display uppercase tracking-wide">Upcoming Games</CardTitle>
          <CardDescription>Scheduled matches</CardDescription>
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={3} />
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="font-display uppercase tracking-wide">Upcoming Games</CardTitle>
          <CardDescription>Scheduled matches</CardDescription>
        </CardHeader>
        <CardContent>
          <ErrorDisplay
            error={error}
            retry={refetch}
            fallback={
              <div className="text-center py-6 text-muted-foreground">
                <p>No upcoming games scheduled</p>
              </div>
            }
          />
        </CardContent>
      </Card>
    );
  }

  if (!games || games.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="font-display uppercase tracking-wide">Upcoming Games</CardTitle>
          <CardDescription>Scheduled matches</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-center py-6 text-muted-foreground text-sm">
            <p>No upcoming games scheduled</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-l-4 border-l-primary overflow-hidden">
      <CardHeader>
        <CardTitle className="font-display uppercase tracking-wide">Upcoming Games</CardTitle>
        <CardDescription>
          {games.length === 1 ? '1 scheduled match' : `${games.length} scheduled matches`}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-0 sm:px-6">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>Opponent</TableHead>
              <TableHead className="text-center">Venue</TableHead>
              <TableHead className="hidden sm:table-cell">Competition</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {games.map((game) => {
              const opp = getOpponent(game);
              return (
                <TableRow key={game.id}>
                  <TableCell className="text-xs sm:text-sm whitespace-nowrap">
                    {formatGameDate(game.game_date, { month: 'short', day: 'numeric', year: '2-digit' })}
                  </TableCell>
                  <TableCell className="max-w-[140px] sm:max-w-none whitespace-normal sm:whitespace-nowrap">
                    {opp.id && opp.name ? (
                      <div className="flex flex-col">
                        <Link
                          href={`/teams/${opp.id}`}
                          onMouseEnter={() => prefetchTeam(opp.id!)}
                          className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block truncate sm:whitespace-normal sm:overflow-visible"
                          aria-label={`View ${opp.name} team details`}
                          title={opp.name}
                        >
                          {opp.name}
                        </Link>
                        {opp.club && (
                          <span className="text-xs text-muted-foreground mt-0.5 truncate sm:whitespace-normal">
                            {opp.club}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-muted-foreground truncate sm:whitespace-normal">
                        {opp.name || 'Unknown'}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-center text-xs sm:text-sm text-muted-foreground">{opp.venue}</TableCell>
                  <TableCell className="hidden sm:table-cell text-sm text-muted-foreground">
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
