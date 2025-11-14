'use client';

import { useMemo, useState, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
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

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed' | 'sos' | 'sosRank';
type SortDirection = 'asc' | 'desc';

interface RankingWithDelta extends RankingRow {
  delta: number;
}

const ROW_HEIGHT = 60; // Estimated row height in pixels

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

/**
 * Get border color class for top teams
 */
function getRankBorderClass(rank: number | null | undefined): string {
  if (!rank) return '';
  
  if (rank <= 3) {
    return 'border-l-4 border-yellow-500 dark:border-yellow-400';
  } else if (rank <= 10) {
    return 'border-l-4 border-gray-400 dark:border-gray-500';
  }
  return '';
}

export function RankingsTable({ region, ageGroup, gender }: RankingsTableProps) {
  const [sortField, setSortField] = useState<SortField>('rank');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const parentRef = useRef<HTMLDivElement>(null);

  const { data: rankings, isLoading, isError, error, refetch } = useRankings(region, ageGroup, gender);
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
        case 'sos':
          aValue = a.strength_of_schedule ?? 0;
          bValue = b.strength_of_schedule ?? 0;
          break;
        case 'sosRank':
          if (region) {
            aValue = a.state_sos_rank ?? Infinity;
            bValue = b.state_sos_rank ?? Infinity;
          } else {
            aValue = a.national_sos_rank ?? Infinity;
            bValue = b.national_sos_rank ?? Infinity;
          }
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

  // Virtualizer for rendering only visible rows
  const virtualizer = useVirtualizer({
    count: sortedRankings.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5, // Render 5 extra rows above/below viewport
  });

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
  if (isError) {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorDisplay error={error} retry={refetch} />
        </CardContent>
      </Card>
    );
  }
  if (!rankings?.length) return <div>No teams available.</div>;

  const virtualItems = virtualizer.getVirtualItems();
  const totalHeight = virtualizer.getTotalSize();
  const paddingTop = virtualItems.length > 0 ? virtualItems[0]?.start ?? 0 : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? totalHeight - (virtualItems[virtualItems.length - 1]?.end ?? 0)
      : 0;

  const columnCount = region ? 8 : 9;

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
          <div className="rounded-md border overflow-hidden">
            {/* Table Header */}
            <div className="grid border-b bg-muted/50 sticky top-0 z-10" style={{ gridTemplateColumns: region ? '80px 2fr 1fr 1fr 1fr 1fr 1fr 1fr' : '80px 2fr 100px 1fr 1fr 1fr 1fr 1fr 1fr' }}>
              <div className="px-4 py-3 font-medium">
                <SortButton field="rank" label="Rank" />
              </div>
              <div className="px-4 py-3 font-medium">
                <SortButton field="team" label="Team" />
              </div>
              {!region && (
                <div className="px-4 py-3 font-medium text-center">
                  Δ (National)
                </div>
              )}
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="powerScore" label="Power Score" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="winPercentage" label="Win %" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="gamesPlayed" label="Games" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="sosRank" label="SOS Rank" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="sos" label="SOS" />
              </div>
              <div className="px-4 py-3 font-medium text-center">
                Trajectory
              </div>
            </div>

            {/* Virtualized Table Body */}
            <div
              ref={parentRef}
              className="overflow-auto"
              style={{ height: '600px' }}
            >
              <div
                style={{
                  height: `${totalHeight}px`,
                  width: '100%',
                  position: 'relative',
                }}
              >
                {paddingTop > 0 && (
                  <div style={{ height: `${paddingTop}px` }} />
                )}
                {virtualItems.map((virtualRow) => {
                  const team = sortedRankings[virtualRow.index];
                  const displayRank = region ? team.state_rank : team.national_rank;
                  const borderClass = getRankBorderClass(displayRank ?? null);

                  return (
                    <div
                      key={team.team_id_master}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      className={`
                        grid border-b group cursor-pointer
                        hover:bg-accent/70 hover:shadow-md
                        transition-all duration-200 ease-in-out
                        hover:scale-[1.01] hover:z-10
                        ${borderClass}
                      `}
                      style={{
                        gridTemplateColumns: region ? '80px 2fr 1fr 1fr 1fr 1fr 1fr 1fr' : '80px 2fr 100px 1fr 1fr 1fr 1fr 1fr 1fr',
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: `${virtualRow.size}px`,
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                    >
                      <div className="px-4 py-3 font-semibold flex items-center">
                        {region ? (team.state_rank ?? '—') : (team.national_rank ?? '—')}
                      </div>
                      <div className="px-4 py-3">
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
                      </div>
                      {!region && (
                        <div className="px-4 py-3 text-center flex items-center justify-center">
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
                        </div>
                      )}
                      <div className="px-4 py-3 text-right font-semibold flex items-center justify-end">
                        {(team.power_score ?? team.national_power_score).toFixed(1)}
                      </div>
                      <div className="px-4 py-3 text-right flex items-center justify-end">
                        {team.win_percentage !== null
                          ? `${team.win_percentage.toFixed(1)}%`
                          : '—'}
                      </div>
                      <div className="px-4 py-3 text-right flex items-center justify-end">
                        {team.games_played}
                      </div>
                      <div className="px-4 py-3 text-right flex items-center justify-end">
                        {(() => {
                          const sosRank = region ? team.state_sos_rank : team.national_sos_rank;
                          return sosRank != null ? `#${sosRank}` : '—';
                        })()}
                      </div>
                      <div className="px-4 py-3 text-right flex items-center justify-end">
                        {team.strength_of_schedule !== null
                          ? team.strength_of_schedule.toFixed(3)
                          : '—'}
                      </div>
                      <div className="px-4 py-3 text-center flex items-center justify-center">
                        <MiniSparkline teamId={team.team_id_master} />
                      </div>
                    </div>
                  );
                })}
                {paddingBottom > 0 && (
                  <div style={{ height: `${paddingBottom}px` }} />
                )}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
