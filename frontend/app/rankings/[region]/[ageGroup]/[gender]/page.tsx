'use client';

import { useMemo, useState } from 'react';
import { use } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { RankingsFilter } from '@/components/RankingsFilter';
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
import { useTeamTrajectory } from '@/lib/hooks';
import { usePrefetchTeam } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { LineChart, Line, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';
import type { RankingWithTeam } from '@/lib/types';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

interface RankingsPageProps {
  params: Promise<{
    region: string;
    ageGroup: string;
    gender: string;
  }>;
}

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed';
type SortDirection = 'asc' | 'desc';

interface RankingWithDelta extends RankingWithTeam {
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

export default function RankingsPage({ params }: RankingsPageProps) {
  const { region, ageGroup, gender } = use(params);
  const [sortField, setSortField] = useState<SortField>('rank');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  
  // Convert gender from URL format (lowercase) to API format (capitalized)
  const genderForAPI = gender 
    ? (gender.charAt(0).toUpperCase() + gender.slice(1).toLowerCase()) as 'Male' | 'Female'
    : undefined;
  
  const { data: rankings, isLoading, isError } = useRankings(
    region === 'national' ? null : region,
    ageGroup,
    genderForAPI
  );
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
  }, [rankingsWithDelta, sortField, sortDirection]);

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

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title="PitchRank Rankings"
        description=""
        showBackButton
        backHref="/"
      />
      
      <div className="space-y-6">
        <RankingsFilter />
        
        <Card>
          <CardHeader>
            <CardTitle>Rankings</CardTitle>
            <CardDescription>
              {region && `Region: ${region === 'national' ? 'National' : region.toUpperCase()}`}
              {ageGroup && ` • Age: ${ageGroup.toUpperCase()}`}
              {gender && ` • ${gender === 'male' ? 'Boys' : gender === 'female' ? 'Girls' : gender}`}
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
                        <TableHead className="text-center">Δ (National)</TableHead>
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
                            {team.national_rank || '—'}
                          </TableCell>
                          <TableCell>
                            <Link
                              href={`/teams/${team.team_id_master}`}
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
                          <TableCell className="text-right font-semibold">
                            {team.national_power_score.toFixed(1)}
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
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
