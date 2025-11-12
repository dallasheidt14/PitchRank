'use client';

import { useState, useMemo } from 'react';
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
import { useRankings } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { usePrefetchTeam } from '@/lib/hooks';
import type { RankingWithTeam } from '@/lib/types';

interface RankingsTableProps {
  region?: string;
  ageGroup?: string;
  gender?: string;
}

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed';
type SortDirection = 'asc' | 'desc';

/**
 * RankingsTable component - displays filtered rankings with sortable columns
 */
export function RankingsTable({ region, ageGroup, gender }: RankingsTableProps) {
  const [sortField, setSortField] = useState<SortField>('rank');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const { data: rankings, isLoading, isError } = useRankings(
    region === 'national' ? null : region,
    ageGroup,
    gender as 'Male' | 'Female' | undefined
  );
  const prefetchTeam = usePrefetchTeam();

  const sortedRankings = useMemo(() => {
    if (!rankings) return [];

    const sorted = [...rankings].sort((a, b) => {
      let aValue: number | string;
      let bValue: number | string;

      switch (sortField) {
        case 'rank':
          aValue = a.national_rank ?? Infinity;
          bValue = b.national_rank ?? Infinity;
          break;
        case 'team':
          aValue = a.team_name.toLowerCase();
          bValue = b.team_name.toLowerCase();
          break;
        case 'powerScore':
          aValue = a.national_power_score;
          bValue = b.national_power_score;
          break;
        case 'winPercentage':
          aValue = a.win_percentage ?? 0;
          bValue = b.win_percentage ?? 0;
          break;
        case 'gamesPlayed':
          aValue = a.games_played;
          bValue = b.games_played;
          break;
        default:
          return 0;
      }

      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortDirection === 'asc'
          ? aValue.localeCompare(bValue)
          : bValue.localeCompare(aValue);
      }

      return sortDirection === 'asc'
        ? (aValue as number) - (bValue as number)
        : (bValue as number) - (aValue as number);
    });

    return sorted;
  }, [rankings, sortField, sortDirection]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  const SortButton = ({ field, label }: { field: SortField; label: string }) => {
    const isActive = sortField === field;
    return (
      <button
        onClick={() => handleSort(field)}
        className="flex items-center gap-1 hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
        aria-label={`Sort by ${label}`}
      >
        {label}
        {isActive ? (
          sortDirection === 'asc' ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-50" />
        )}
      </button>
    );
  };

  const getRankChange = (currentIndex: number, currentRank: number | null): number => {
    if (!rankings || currentRank === null) return 0;
    const previousTeam = rankings.find(r => r.national_rank === currentRank - 1);
    if (!previousTeam) return 0;
    const previousIndex = sortedRankings.findIndex(r => r.team_id_master === previousTeam.team_id_master);
    return previousIndex - currentIndex;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rankings</CardTitle>
        <CardDescription>
          {region && `Region: ${region === 'national' ? 'National' : region.toUpperCase()}`}
          {ageGroup && ` • Age: ${ageGroup.toUpperCase()}`}
          {gender && ` • ${gender}`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && <TableSkeleton rows={10} />}

        {isError && (
          <div className="rounded-lg bg-destructive/10 p-4 text-destructive">
            <p className="text-sm">Failed to load rankings. Please try again later.</p>
          </div>
        )}

        {!isLoading && !isError && (
          <>
            {sortedRankings.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-8">
                No rankings found for the selected filters
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-20">
                      <SortButton field="rank" label="Rank" />
                    </TableHead>
                    <TableHead>
                      <SortButton field="team" label="Team" />
                    </TableHead>
                    <TableHead className="text-right">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex justify-end">
                            <SortButton field="powerScore" label="Power Score" />
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>National power score based on performance metrics</p>
                        </TooltipContent>
                      </Tooltip>
                    </TableHead>
                    <TableHead className="text-right">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex justify-end">
                            <SortButton field="winPercentage" label="Win %" />
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Win percentage (wins / games played)</p>
                        </TooltipContent>
                      </Tooltip>
                    </TableHead>
                    <TableHead className="text-right">
                      <SortButton field="gamesPlayed" label="Games" />
                    </TableHead>
                    <TableHead className="text-right">Record</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedRankings.map((team, index) => {
                    const rankChange = getRankChange(index, team.national_rank);
                    return (
                      <TableRow
                        key={team.team_id_master}
                        className="cursor-pointer hover:bg-accent/50"
                      >
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold">{team.national_rank || '—'}</span>
                            {rankChange !== 0 && (
                              <span
                                className={`flex items-center gap-0.5 text-xs ${
                                  rankChange > 0
                                    ? 'text-green-600 dark:text-green-400'
                                    : 'text-red-600 dark:text-red-400'
                                }`}
                              >
                                {rankChange > 0 ? (
                                  <ArrowUp className="h-3 w-3" />
                                ) : (
                                  <ArrowDown className="h-3 w-3" />
                                )}
                                {Math.abs(rankChange)}
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Link
                            href={`/teams/${team.team_id_master}`}
                            onMouseEnter={() => prefetchTeam(team.team_id_master)}
                            className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
                            aria-label={`View ${team.team_name} team details`}
                          >
                            {team.team_name}
                          </Link>
                          <div className="text-sm text-muted-foreground">
                            {team.club_name && <span>{team.club_name}</span>}
                            {team.state_code && (
                              <span className={team.club_name ? ' • ' : ''}>
                                {team.state_code}
                              </span>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-right font-semibold">
                          {team.national_power_score.toFixed(1)}
                        </TableCell>
                        <TableCell className="text-right">
                          {team.win_percentage !== null
                            ? `${team.win_percentage.toFixed(1)}%`
                            : '—'}
                        </TableCell>
                        <TableCell className="text-right">{team.games_played}</TableCell>
                        <TableCell className="text-right text-sm text-muted-foreground">
                          {team.wins}-{team.losses}
                          {team.draws > 0 && `-${team.draws}`}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
