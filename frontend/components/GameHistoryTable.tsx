'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { TableSkeleton } from '@/components/ui/skeletons';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useTeamGames } from '@/lib/hooks';
// Using native Date formatting instead of date-fns
import Link from 'next/link';
import { usePrefetchTeam } from '@/lib/hooks';
import type { GameWithTeams } from '@/lib/types';

interface GameHistoryTableProps {
  teamId: string;
  limit?: number;
}

/**
 * GameHistoryTable component - displays recent games for a team
 */
export function GameHistoryTable({ teamId, limit = 10 }: GameHistoryTableProps) {
  const { data: games, isLoading, isError } = useTeamGames(teamId, limit);
  const prefetchTeam = usePrefetchTeam();

  const getResult = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
    const teamScore = isHome ? game.home_score : game.away_score;
    const opponentScore = isHome ? game.away_score : game.home_score;

    if (teamScore === null || opponentScore === null) return { text: '—', class: '' };

    if (teamScore > opponentScore) {
      return { text: 'W', class: 'text-green-600 dark:text-green-400 font-semibold' };
    } else if (teamScore < opponentScore) {
      return { text: 'L', class: 'text-red-600 dark:text-red-400 font-semibold' };
    } else {
      return { text: 'D', class: 'text-yellow-600 dark:text-yellow-400 font-semibold' };
    }
  };

  const getOpponent = (game: GameWithTeams, teamId: string) => {
    const isHome = game.home_team_master_id === teamId;
    return isHome ? game.away_team_name : game.home_team_name;
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
          <CardTitle>Recent Games</CardTitle>
          <CardDescription>Latest match results</CardDescription>
        </CardHeader>
        <CardContent>
          <TableSkeleton rows={5} />
        </CardContent>
      </Card>
    );
  }

  if (isError || !games || games.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Games</CardTitle>
          <CardDescription>Latest match results</CardDescription>
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
        <CardTitle>Recent Games</CardTitle>
        <CardDescription>Latest {limit} match results</CardDescription>
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
                      <Link
                        href={`/teams/${opponentId}`}
                        onMouseEnter={() => prefetchTeam(opponentId)}
                        className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
                        aria-label={`View ${opponent} team details`}
                      >
                        {opponent}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">{opponent || 'Unknown'}</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    <span className={result.class}>{result.text}</span>
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

