'use client';

import { useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useRankings } from '@/hooks/useRankings';
import { useTeamTrajectory } from '@/lib/hooks';
import { usePrefetchTeam } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';
import type { RankingRow } from '@/types/RankingRow';

interface RankingsTableProps {
  region: string | null; // null = national
  ageGroup: string;
  gender: 'Male' | 'Female' | null;
}

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed';
type SortDirection = 'asc' | 'desc';

interface RankingWithDelta extends RankingRow {
  delta: number;
}

/**
 * Mini sparkline component for trajectory visualization
 */
function MiniSparkline({ teamId }: { teamId: string }) {
  const { data: trajectory } = useTeamTrajectory(teamId, 30);
  
  const sparklineData = useMemo(() => {
    if (!trajectory || trajectory.length === 0) return [];
    return trajectory.slice(-6).map((point) => ({
      value: point.win_percentage,
    }));
  }, [trajectory]);

  if (!sparklineData || sparklineData.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }

  return (
    <ResponsiveContainer width={60} height={20}>
      <LineChart data={sparklineData}>
        <Line
          type="monotone"
          dataKey="value"
          stroke="hsl(var(--chart-1))"
          strokeWidth={2}
          dot={false}
        />
        <RechartsTooltip content={() => null} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function RankingsTable({ region, ageGroup, gender }: RankingsTableProps) {
  const [sortField, setSortField] = useState<SortField>('rank');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

  const { data: rankings, isLoading, isError } = useRankings(region, ageGroup, gender);
  const prefetchTeam = usePrefetchTeam();

  // Calculate delta for each team (national rank change)
  const rankingsWithDelta = useMemo(() => {
    if (!rankings || rankings.length < 2) return [];
    
    return rankings.map((team, index) => {
      const previousRank = index > 0 ? rankings[index - 1].national_rank : null;
      const delta = previousRank && team.national_rank
        ? previousRank - team.national_rank
        : 0;
      return { ...team, delta } as RankingWithDelta;
    });
  }, [rankings]);

  // Sort rankings based on selected field
  const sortedRankings = useMemo(() => {
    if (!rankingsWithDelta) return [];

    const sorted = [...rankingsWithDelta].sort((a, b) => {
      let aValue: number | string;
      let bValue: number | string;

      switch (sortField) {
        case 'rank':
          // Use state_rank if region is set, otherwise national_rank
          aValue = region ? (a.state_rank ?? Infinity) : (a.national_rank ?? Infinity);
          bValue = region ? (b.state_rank ?? Infinity) : (b.national_rank ?? Infinity);
          break;
        case 'team':
          aValue = a.team_name.toLowerCase();
          bValue = b.team_name.toLowerCase();
          break;
        case 'powerScore':
          // Use power_score if available (state rankings), otherwise national_power_score
          aValue = a.power_score ?? a.national_power_score;
          bValue = b.power_score ?? b.national_power_score;
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
  }, [rankingsWithDelta, sortField, sortDirection, region]);

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

  // Build description text
  const description = useMemo(() => {
    const parts: string[] = [];
    if (region) {
      parts.push(`Region: ${region === 'national' ? 'National' : region.toUpperCase()}`);
    }
    if (ageGroup) {
      parts.push(`Age: ${ageGroup.toUpperCase()}`);
    }
    if (gender) {
      parts.push(gender === 'Male' ? 'Boys' : gender === 'Female' ? 'Girls' : gender);
    }
    return parts.join(' • ');
  }, [region, ageGroup, gender]);

  if (isLoading) return <RankingsTableSkeleton />;
  if (isError) return <div className="text-red-500">Failed to load rankings.</div>;
  if (!rankings?.length) return <div>No teams available.</div>;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rankings</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
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
                {!region && (
                  <TableHead className="text-center">Δ (National)</TableHead>
                )}
                <TableHead className="text-right">
                  <SortButton field="powerScore" label="Power Score" />
                </TableHead>
                <TableHead className="text-right">
                  <SortButton field="winPercentage" label="Win %" />
                </TableHead>
                <TableHead className="text-right">
                  <SortButton field="gamesPlayed" label="Games" />
                </TableHead>
                <TableHead className="text-center">Trajectory</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedRankings.map((team) => (
                <TableRow
                  key={team.team_id_master}
                  className="hover:bg-accent/50 transition-colors duration-300"
                >
                  <TableCell className="font-semibold">
                    {region ? (team.state_rank ?? '—') : (team.national_rank ?? '—')}
                  </TableCell>
                  <TableCell>
                    <Link
                      href={`/teams/${team.team_id_master}?region=${region || 'national'}&ageGroup=${ageGroup}&gender=${gender?.toLowerCase() || 'male'}`}
                      onMouseEnter={() => prefetchTeam(team.team_id_master)}
                      className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block"
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
                  {!region && (
                    <TableCell className="text-center">
                      {team.delta !== 0 && (
                        <div
                          className={`inline-flex items-center gap-1 text-sm font-semibold ${
                            team.delta > 0
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-red-600 dark:text-red-400'
                          }`}
                        >
                          {team.delta > 0 ? (
                            <ArrowUp className="h-4 w-4" />
                          ) : (
                            <ArrowDown className="h-4 w-4" />
                          )}
                          {Math.abs(team.delta)}
                        </div>
                      )}
                      {team.delta === 0 && <span className="text-xs text-muted-foreground">—</span>}
                    </TableCell>
                  )}
                  <TableCell className="text-right font-semibold">
                    {(team.power_score ?? team.national_power_score).toFixed(1)}
                  </TableCell>
                  <TableCell className="text-right">
                    {team.win_percentage !== null
                      ? `${team.win_percentage.toFixed(1)}%`
                      : '—'}
                  </TableCell>
                  <TableCell className="text-right">{team.games_played}</TableCell>
                  <TableCell className="text-center">
                    <MiniSparkline teamId={team.team_id_master} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
