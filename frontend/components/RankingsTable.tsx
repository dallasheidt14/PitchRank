'use client';

import { useMemo, useState, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useRankings } from '@/hooks/useRankings';
import { usePrefetchTeam } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { formatPowerScore, formatSOSIndex } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

interface RankingsTableProps {
  region: string | null; // null = national
  ageGroup: string;
  gender: 'Male' | 'Female' | null;
}

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed' | 'sos' | 'sosRank';
type SortDirection = 'asc' | 'desc';

const ROW_HEIGHT = 60; // Estimated row height in pixels

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

  // Optimized SOS Rank calculation per cohort
  const sortedBySOS = useMemo(() => {
    if (!rankings) return [];
    return [...rankings]
      .filter(t => typeof t.sos_norm === "number")
      .sort((a, b) => (b.sos_norm ?? 0) - (a.sos_norm ?? 0));
  }, [rankings]);

  const sosRanks = useMemo(() => {
    const map: Record<string, number> = {};
    sortedBySOS.forEach((t, i) => {
      map[t.team_id_master] = i + 1;
    });
    return map;
  }, [sortedBySOS]);

  // Sort rankings based on selected field
  const sortedRankings = useMemo(() => {
    if (!rankings) return [];

    const sorted = [...rankings].sort((a, b) => {
      let aValue: number | string;
      let bValue: number | string;

      switch (sortField) {
        case 'rank':
          // Use rank_in_state_final if region is set, otherwise rank_in_cohort_final
          aValue = region ? (a.rank_in_state_final ?? Infinity) : (a.rank_in_cohort_final ?? Infinity);
          bValue = region ? (b.rank_in_state_final ?? Infinity) : (b.rank_in_cohort_final ?? Infinity);
          break;
        case 'team':
          aValue = a.team_name.toLowerCase();
          bValue = b.team_name.toLowerCase();
          break;
        case 'powerScore':
          // Use power_score_final (ML-adjusted score)
          aValue = a.power_score_final;
          bValue = b.power_score_final;
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
          // Use sos_norm for sorting (normalized within cohort)
          aValue = a.sos_norm ?? 0;
          bValue = b.sos_norm ?? 0;
          break;
        case 'sosRank':
          aValue = sosRanks[a.team_id_master] ?? Infinity;
          bValue = sosRanks[b.team_id_master] ?? Infinity;
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
  }, [rankings, sortField, sortDirection, region, sosRanks]);

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

  const columnCount = region ? 7 : 8;

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
            <div className="grid border-b bg-muted/50 sticky top-0 z-10" style={{ gridTemplateColumns: region ? '80px 2fr 1fr 1fr 1fr 1fr 1fr' : '80px 2fr 1fr 1fr 1fr 1fr 1fr 1fr' }}>
              <div className="px-4 py-3 font-medium">
                <SortButton field="rank" label="Rank" />
              </div>
              <div className="px-4 py-3 font-medium">
                <SortButton field="team" label="Team" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div>
                      <SortButton field="powerScore" label="PowerScore (ML Adjusted)" />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>A machine-learning-enhanced ranking score that measures overall team strength based on offense, defense, schedule difficulty, and predictive performance patterns.</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="winPercentage" label="Win %" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <SortButton field="gamesPlayed" label="Games" />
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div>
                      <SortButton field="sosRank" label="SOS Rank (Cohort)" />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>SOS Rank is computed within this age and gender cohort using sos_norm.</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="px-4 py-3 font-medium text-right">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div>
                      <SortButton field="sos" label="SOS Index" />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>Strength of Schedule normalized within each age group and gender (0 = softest schedule, 100 = toughest).</p>
                  </TooltipContent>
                </Tooltip>
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
                  const displayRank = region ? team.rank_in_state_final : team.rank_in_cohort_final;
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
                        gridTemplateColumns: region ? '80px 2fr 1fr 1fr 1fr 1fr 1fr' : '80px 2fr 1fr 1fr 1fr 1fr 1fr 1fr',
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: `${virtualRow.size}px`,
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                    >
                      {/* Temporary verification logging (first row only) */}
                      {virtualRow.index === 0 && console.log("SOS DEBUG:", {
                        team: team.team_name,
                        sos_norm: team.sos_norm,
                        sosIndex: formatSOSIndex(team.sos_norm),
                        sosRank: sosRanks[team.team_id_master]
                      })}
                      <div className="px-4 py-3 font-semibold flex items-center">
                        {region ? (team.rank_in_state_final ?? '—') : (team.rank_in_cohort_final ?? '—')}
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
                      <div className="px-4 py-3 text-right font-semibold flex items-center justify-end">
                        {formatPowerScore(team.power_score_final)}
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
                          const sosRank = sosRanks[team.team_id_master];
                          return sosRank ? `#${sosRank}` : '—';
                        })()}
                      </div>
                      <div className="px-4 py-3 text-right flex items-center justify-end">
                        {formatSOSIndex(team.sos_norm)}
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
