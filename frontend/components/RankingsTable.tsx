'use client';

import { useMemo, useState, useRef, memo, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useRankings } from '@/hooks/useRankings';
import { usePrefetchTeam } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Badge } from '@/components/ui/badge';
import { formatPowerScore, formatSOSIndex, normalizeAgeGroup } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';

interface RankingsTableProps {
  region: string | null; // null = national
  ageGroup: string;
  gender: 'M' | 'F' | 'B' | 'G' | null;
}

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed' | 'sos' | 'sosRank';
type SortDirection = 'asc' | 'desc';

const ROW_HEIGHT = 60; // Estimated row height in pixels

/**
 * Get border color class for top teams - Athletic Editorial style
 */
function getRankBorderClass(rank: number | null | undefined): string {
  if (!rank) return '';

  if (rank <= 3) {
    return 'border-l-4 border-accent bg-accent/5';
  } else if (rank <= 10) {
    return 'border-l-4 border-primary/30';
  }
  return '';
}

export function RankingsTable({ region, ageGroup, gender }: RankingsTableProps) {
  const [sortField, setSortField] = useState<SortField>('rank');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const parentRef = useRef<HTMLDivElement>(null);

  const { data: rankings, isLoading, isError, error, refetch } = useRankings(region, ageGroup, gender);
  const prefetchTeam = usePrefetchTeam();

  // Use pre-calculated SOS ranks from database
  // sos_rank_national for national view, sos_rank_state for state view

  // Sort rankings based on selected field
  // Teams with "Not Enough Ranked Games" are sorted separately (after Active teams)
  const sortedRankings = useMemo(() => {
    if (!rankings) return [];

    // Separate teams by status
    const activeTeams = rankings.filter(t => t.status === 'Active');
    const unrankedTeams = rankings.filter(t => t.status === 'Not Enough Ranked Games');
    const inactiveTeams = rankings.filter(t => t.status === 'Inactive');

    const sortTeams = (teams: RankingRow[]) => {
      return [...teams].sort((a, b) => {
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
          // Use power_score_final (ML-adjusted score) - primary sort field
          aValue = a.power_score_final;
          bValue = b.power_score_final;
          break;
        case 'winPercentage':
          aValue = a.win_percentage ?? 0;
          bValue = b.win_percentage ?? 0;
          break;
        case 'gamesPlayed':
          aValue = a.total_games_played;
          bValue = b.total_games_played;
          break;
        case 'sos':
          // Use sos_norm for sorting (normalized within cohort)
          aValue = a.sos_norm ?? 0;
          bValue = b.sos_norm ?? 0;
          break;
        case 'sosRank':
          // Use pre-calculated SOS rank from database
          aValue = region
            ? (a.sos_rank_state ?? Infinity)
            : (a.sos_rank_national ?? Infinity);
          bValue = region
            ? (b.sos_rank_state ?? Infinity)
            : (b.sos_rank_national ?? Infinity);
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
    };

    // Sort each group and combine: Active first, then Unranked, then Inactive
    const sortedActive = sortTeams(activeTeams);
    const sortedUnranked = sortTeams(unrankedTeams);
    const sortedInactive = sortTeams(inactiveTeams);

    return [...sortedActive, ...sortedUnranked, ...sortedInactive];
  }, [rankings, sortField, sortDirection, region]);

  // Virtualizer for rendering only visible rows
  const virtualizer = useVirtualizer({
    count: sortedRankings.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5, // Render 5 extra rows above/below viewport
  });

  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  }, [sortField, sortDirection]);

  const SortButton = memo(({ field, label }: { field: SortField; label: string | React.ReactNode }) => {
    const isActive = sortField === field;
    const labelText = typeof label === 'string' ? label : 'Sort';
    return (
      <button
        onClick={() => handleSort(field)}
        className="flex items-center gap-1 hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded"
        aria-label={`Sort by ${labelText}`}
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
  });

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
      const genderLabel = gender === 'M' ? 'Boys' : gender === 'F' ? 'Girls' : gender === 'B' ? 'Boys' : gender === 'G' ? 'Girls' : gender;
      parts.push(genderLabel);
    }
    return parts.join(' • ');
  }, [region, ageGroup, gender]);

  // Get last_calculated timestamp from first ranking (same for all rows)
  const lastCalculated = useMemo(() => {
    if (!rankings || rankings.length === 0) return null;
    return rankings[0].last_calculated;
  }, [rankings]);

  // Format timestamp for display
  const formattedLastCalculated = useMemo(() => {
    if (!lastCalculated) return null;

    try {
      const date = new Date(lastCalculated);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      // Format: "Dec 15, 2024"
      const formatted = date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      });

      // Add recency indicator
      if (diffDays === 0) {
        return `${formatted} (today)`;
      } else if (diffDays === 1) {
        return `${formatted} (yesterday)`;
      } else if (diffDays < 7) {
        return `${formatted} (${diffDays} days ago)`;
      } else {
        return formatted;
      }
    } catch (error) {
      console.error('Error formatting last_calculated date:', error);
      return null;
    }
  }, [lastCalculated]);

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
  
  // Debug: Show debug info
  if (!rankings?.length) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="text-sm text-muted-foreground text-center py-8">
            No teams available for the selected filters.
          </div>
        </CardContent>
      </Card>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();
  const totalHeight = virtualizer.getTotalSize();
  const paddingTop = virtualItems.length > 0 ? virtualItems[0]?.start ?? 0 : 0;
  const paddingBottom =
    virtualItems.length > 0
      ? totalHeight - (virtualItems[virtualItems.length - 1]?.end ?? 0)
      : 0;

  const columnCount = region ? 7 : 8;

  return (
    <Card className="overflow-hidden border-0 shadow-lg">
      <CardHeader className="bg-gradient-to-r from-primary to-[oklch(0.28_0.08_165)] text-primary-foreground relative">
        <div className="absolute right-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <CardTitle className="text-2xl sm:text-3xl font-bold uppercase tracking-wide">
          Complete Rankings
        </CardTitle>
        <CardDescription className="text-primary-foreground/90 text-sm sm:text-base">
          {description}
          {formattedLastCalculated && (
            <span className="block sm:inline sm:ml-2 text-xs mt-1 sm:mt-0">
              • Last updated: {formattedLastCalculated}
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {sortedRankings.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No rankings found for the selected filters
          </p>
        ) : (
          <div className="rounded-md border overflow-hidden">
            {/* Mobile: Horizontal scroll wrapper with momentum scrolling */}
            <div className="overflow-x-auto -mx-4 sm:mx-0 touch-pan-x">
              <div className="inline-block min-w-full align-middle" style={{ minWidth: region ? '700px' : '750px' }}>
                {/* Table Header */}
                <div className="grid border-b-2 border-primary bg-secondary/50 sticky top-0 z-10" style={{ gridTemplateColumns: region ? '60px 2fr 1fr 0.9fr 0.8fr 0.9fr 1fr' : '60px 2fr 1fr 0.9fr 0.8fr 0.9fr 1fr 1fr' }}>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-xs sm:text-sm uppercase tracking-wide">
                    <SortButton field="rank" label="Rank" />
                  </div>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-xs sm:text-sm uppercase tracking-wide">
                    <SortButton field="team" label="Team" />
                  </div>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div>
                          <SortButton field="powerScore" label={<><span className="hidden sm:inline">PowerScore (ML Adjusted)</span><span className="sm:hidden">PS</span></>} />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>A machine-learning-enhanced ranking score that measures overall team strength based on offense, defense, schedule difficulty, and predictive performance patterns.</p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide">
                    <SortButton field="winPercentage" label="Win %" />
                  </div>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div>
                          <SortButton field="gamesPlayed" label="Games" />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p className="text-sm">
                          <strong>Ranked Games / Total Games</strong>
                          <br />
                          <span className="text-muted-foreground">
                            Ranked: Last 30 games within 365 days (used for rankings)
                            <br />
                            Total: All games in database
                          </span>
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div>
                          <SortButton field="sosRank" label={<><span className="hidden sm:inline">SOS Rank</span><span className="sm:hidden">SOS R</span></>} />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>SOS Rank is computed within this age and gender cohort using sos_norm.</p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div className="px-2 sm:px-4 py-3 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div>
                          <SortButton field="sos" label="SOS" />
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
                            gridTemplateColumns: region ? '60px 2fr 1fr 0.9fr 0.8fr 0.9fr 1fr' : '60px 2fr 1fr 0.9fr 0.8fr 0.9fr 1fr 1fr',
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            height: `${virtualRow.size}px`,
                            transform: `translateY(${virtualRow.start}px)`,
                            minHeight: '60px',
                          }}
                        >
                          <div className="px-2 sm:px-4 py-2 sm:py-3 font-semibold flex items-center text-xs sm:text-base">
                            {(() => {
                              const rank = region ? team.rank_in_state_final : team.rank_in_cohort_final;
                              return rank != null ? `#${rank}` : '—';
                            })()}
                          </div>
                          <div className="px-2 sm:px-4 py-2 sm:py-3 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <Link
                                href={`/teams/${team.team_id_master}?region=${region || 'national'}&ageGroup=${ageGroup}&gender=${gender?.toLowerCase() || 'male'}`}
                                onMouseEnter={() => prefetchTeam(team.team_id_master)}
                                className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block text-xs sm:text-sm truncate"
                                aria-label={`View ${team.team_name} team details`}
                              >
                                {team.team_name}
                              </Link>
                              {team.status === 'Not Enough Ranked Games' && (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <Badge 
                                      variant="outline" 
                                      className="text-xs bg-yellow-50 text-yellow-700 border-yellow-300 hover:bg-yellow-100"
                                    >
                                      Unranked
                                    </Badge>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>This team has fewer than 5 ranked games. Rankings are provisional until more games are played.</p>
                                  </TooltipContent>
                                </Tooltip>
                              )}
                            </div>
                            <div className="text-xs sm:text-sm text-muted-foreground truncate">
                              {team.club_name && <span>{team.club_name}</span>}
                              {team.state && (
                                <span className={team.club_name ? ' • ' : ''}>
                                  {team.state}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="px-2 sm:px-4 py-2 sm:py-3 text-right font-semibold flex items-center justify-end text-xs sm:text-sm">
                            {formatPowerScore(team.power_score_final)}
                          </div>
                          <div className="px-2 sm:px-4 py-2 sm:py-3 text-right flex items-center justify-end text-xs sm:text-sm">
                            {team.win_percentage != null ? `${team.win_percentage.toFixed(1)}%` : '—'}
                          </div>
                          <div className="px-2 sm:px-4 py-2 sm:py-3 text-right flex items-center justify-end text-xs sm:text-sm">
                            {team.games_played}/{team.total_games_played}
                          </div>
                          <div className="px-2 sm:px-4 py-2 sm:py-3 text-right flex items-center justify-end text-xs sm:text-sm">
                            {(() => {
                              // Use pre-calculated SOS rank from database
                              const sosRank = region ? team.sos_rank_state : team.sos_rank_national;
                              return sosRank ? `#${sosRank}` : '—';
                            })()}
                          </div>
                          <div className="px-2 sm:px-4 py-2 sm:py-3 text-right flex items-center justify-end text-xs sm:text-sm">
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
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
