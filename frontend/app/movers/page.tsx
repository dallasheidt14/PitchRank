'use client';

import { useState, useMemo } from 'react';
import { PageHeader } from '@/components/PageHeader';
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
import Link from 'next/link';
import { ArrowUp, ArrowDown } from 'lucide-react';
import { usePrefetchTeam } from '@/lib/hooks';
import { LineChart, Line, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';
import type { RankingWithTeam } from '@/lib/types';

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

export default function MoversPage() {
  const [region, setRegion] = useState<string>('national');
  const [ageGroup, setAgeGroup] = useState<string>('u12');
  const [gender, setGender] = useState<'Male' | 'Female'>('Male');
  
  const { data: rankings, isLoading, isError } = useRankings(
    region === 'national' ? null : region,
    ageGroup,
    gender
  );
  const prefetchTeam = usePrefetchTeam();

  // Calculate movers (teams with largest rank changes)
  const movers = useMemo(() => {
    if (!rankings || rankings.length < 2) return [];

    // Calculate rank changes (simplified - comparing with previous position)
    const moversWithDelta = rankings.map((team, index) => {
      const previousRank = index > 0 ? rankings[index - 1].national_rank : null;
      const delta = previousRank && team.national_rank
        ? previousRank - team.national_rank
        : 0;
      return { ...team, delta };
    });

    // Filter to teams with changes and sort by absolute delta
    return moversWithDelta
      .filter(team => Math.abs(team.delta) > 0)
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      .slice(0, 20);
  }, [rankings]);

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title="Recent Movers"
        description="Teams with the largest rank changes"
        showBackButton
        backHref="/"
      />

      <div className="space-y-6">
        {/* Filters */}
        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Filter movers by region, age group, and gender</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="text-sm font-medium mb-2 block">Region</label>
                <select
                  value={region}
                  onChange={(e) => setRegion(e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
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
              <div>
                <label className="text-sm font-medium mb-2 block">Age Group</label>
                <select
                  value={ageGroup}
                  onChange={(e) => setAgeGroup(e.target.value)}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
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
              <div>
                <label className="text-sm font-medium mb-2 block">Gender</label>
                <select
                  value={gender}
                  onChange={(e) => setGender(e.target.value as 'Male' | 'Female')}
                  className="w-full h-9 rounded-md border border-input bg-background px-3 py-1 text-sm transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary"
                  aria-label="Select gender"
                >
                  <option value="Male">Male</option>
                  <option value="Female">Female</option>
                </select>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Movers Table */}
        <Card>
          <CardHeader>
            <CardTitle>Top Movers</CardTitle>
            <CardDescription>
              Teams ranked by largest rank change (up or down)
            </CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading && <TableSkeleton rows={10} />}

            {isError && (
              <div className="rounded-lg bg-destructive/10 p-4 text-destructive">
                <p className="text-sm">Failed to load movers data. Please try again later.</p>
              </div>
            )}

            {!isLoading && !isError && (
              <>
                {movers.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-8">
                    No movers found for the selected filters
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Rank</TableHead>
                        <TableHead>Team</TableHead>
                        <TableHead className="text-center">Change</TableHead>
                        <TableHead className="text-right">Power Score</TableHead>
                        <TableHead className="text-center">Trajectory</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {movers.map((team) => (
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
                              className="font-medium hover:text-primary transition-colors duration-300 cursor-pointer inline-block"
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
                          </TableCell>
                          <TableCell className="text-right font-semibold">
                            {team.national_power_score.toFixed(1)}
                          </TableCell>
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

