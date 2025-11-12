'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
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

export default function RankingsPage() {
  const router = useRouter();
  
  // Default filters
  const defaultRegion = 'national';
  const defaultAgeGroup = 'u12';
  const defaultGender = 'male';
  
  const [region, setRegion] = useState(defaultRegion);
  const [ageGroup, setAgeGroup] = useState(defaultAgeGroup);
  const [gender, setGender] = useState(defaultGender);
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

  // Navigate to filtered URL when filters change
  useEffect(() => {
    if (region !== defaultRegion || ageGroup !== defaultAgeGroup || gender !== defaultGender) {
      router.replace(`/rankings/${region}/${ageGroup}/${gender}`);
    }
  }, [region, ageGroup, gender, router]);

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
        <Card className="w-full max-w-3xl mx-auto mb-6">
          <CardContent className="flex flex-col sm:flex-row items-center justify-between gap-4 py-6">
            {/* Region */}
            <div className="flex flex-col w-full sm:w-auto">
              <label className="text-sm text-muted-foreground mb-1">Region</label>
              <select
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                className="w-[180px] h-9 rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
                aria-label="Select region"
              >
                <option value="national">National</option>
                <option value="al">Alabama</option>
                <option value="ak">Alaska</option>
                <option value="az">Arizona</option>
                <option value="ar">Arkansas</option>
                <option value="ca">California</option>
                <option value="co">Colorado</option>
                <option value="ct">Connecticut</option>
                <option value="de">Delaware</option>
                <option value="fl">Florida</option>
                <option value="ga">Georgia</option>
                <option value="hi">Hawaii</option>
                <option value="id">Idaho</option>
                <option value="il">Illinois</option>
                <option value="in">Indiana</option>
                <option value="ia">Iowa</option>
                <option value="ks">Kansas</option>
                <option value="ky">Kentucky</option>
                <option value="la">Louisiana</option>
                <option value="me">Maine</option>
                <option value="md">Maryland</option>
                <option value="ma">Massachusetts</option>
                <option value="mi">Michigan</option>
                <option value="mn">Minnesota</option>
                <option value="ms">Mississippi</option>
                <option value="mo">Missouri</option>
                <option value="mt">Montana</option>
                <option value="ne">Nebraska</option>
                <option value="nv">Nevada</option>
                <option value="nh">New Hampshire</option>
                <option value="nj">New Jersey</option>
                <option value="nm">New Mexico</option>
                <option value="ny">New York</option>
                <option value="nc">North Carolina</option>
                <option value="nd">North Dakota</option>
                <option value="oh">Ohio</option>
                <option value="ok">Oklahoma</option>
                <option value="or">Oregon</option>
                <option value="pa">Pennsylvania</option>
                <option value="ri">Rhode Island</option>
                <option value="sc">South Carolina</option>
                <option value="sd">South Dakota</option>
                <option value="tn">Tennessee</option>
                <option value="tx">Texas</option>
                <option value="ut">Utah</option>
                <option value="vt">Vermont</option>
                <option value="va">Virginia</option>
                <option value="wa">Washington</option>
                <option value="wv">West Virginia</option>
                <option value="wi">Wisconsin</option>
                <option value="wy">Wyoming</option>
              </select>
            </div>

            {/* Age Group */}
            <div className="flex flex-col w-full sm:w-auto">
              <label className="text-sm text-muted-foreground mb-1">Age Group</label>
              <select
                value={ageGroup}
                onChange={(e) => setAgeGroup(e.target.value)}
                className="w-[180px] h-9 rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
                aria-label="Select age group"
              >
                <option value="u10">U10</option>
                <option value="u11">U11</option>
                <option value="u12">U12</option>
                <option value="u13">U13</option>
                <option value="u14">U14</option>
                <option value="u15">U15</option>
                <option value="u16">U16</option>
                <option value="u17">U17</option>
                <option value="u18">U18</option>
              </select>
            </div>

            {/* Gender */}
            <div className="flex flex-col w-full sm:w-auto">
              <label className="text-sm text-muted-foreground mb-1">Gender</label>
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value)}
                className="w-[180px] h-9 rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
                aria-label="Select gender"
              >
                <option value="male">Boys</option>
                <option value="female">Girls</option>
              </select>
            </div>
          </CardContent>
        </Card>
        
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
                              href={`/teams/${team.team_id_master}?region=${region}&ageGroup=${ageGroup}&gender=${gender}`}
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

