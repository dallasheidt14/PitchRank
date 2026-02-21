'use client';

import { useMemo, useState, useRef, memo, useCallback, useEffect } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useRankings } from '@/hooks/useRankings';
import { usePrefetchTeam } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { formatPowerScore } from '@/lib/utils';
import type { RankingRow } from '@/types/RankingRow';
import { trackRankingsViewed, trackSortUsed, trackTeamRowClicked } from '@/lib/events';
import { RankingsSchema } from '@/components/RankingsSchema';

interface RankingsTableProps {
  region: string | null; // null = national
  ageGroup: string;
  gender: 'M' | 'F' | 'B' | 'G' | null;
}

type SortField = 'rank' | 'team' | 'powerScore' | 'winPercentage' | 'gamesPlayed' | 'sos' | 'sosRank';
type SortDirection = 'asc' | 'desc';

const ROW_HEIGHT = 60; // Estimated row height in pixels

/**
 * Sort button component - defined outside RankingsTable so memo() works correctly
 */
const SortButton = memo(({ field, label, sortField, sortDirection, onSort }: {
  field: SortField;
  label: string | React.ReactNode;
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
}) => {
  const isActive = sortField === field;
  const labelText = typeof label === 'string' ? label : 'Sort';
  return (
    <button
      onClick={() => onSort(field)}
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

  const { data: rankings, isLoading, isFetching, isError, error, refetch } = useRankings(region, ageGroup, gender);
  const prefetchTeam = usePrefetchTeam();

  // Track rankings viewed when data loads
  useEffect(() => {
    if (rankings && rankings.length > 0) {
      trackRankingsViewed({
        region,
        age_group: ageGroup,
        gender,
        total_teams: rankings.length,
      });
    }
  }, [rankings?.length, region, ageGroup, gender]);

  // Use pre-calculated SOS ranks from database
  // sos_rank_national for national view, sos_rank_state for state view

  // Compute position-based state ranks from the filtered data.
  // The state_rankings_view computes rank_in_state_final using ROW_NUMBER() over
  // ALL teams (including inactive), but this page only shows Active/Not Enough Ranked Games.
  // This causes rank gaps (e.g., #1, #2, #5, #18 instead of #1, #2, #3, #4).
  // Fix: compute sequential ranks from the filtered data sorted by power_score_final.
  const computedStateRanks = useMemo(() => {
    if (!region || !rankings) return null;
    const map = new Map<string, number>();
    const sorted = [...rankings].sort((a, b) => {
      const diff = (b.power_score_final ?? 0) - (a.power_score_final ?? 0);
      if (diff !== 0) return diff;
      // Tie-break by SOS (higher = better)
      const aSos = a.sos_norm_state ?? a.sos_norm ?? 0;
      const bSos = b.sos_norm_state ?? b.sos_norm ?? 0;
      return bSos - aSos;
    });
    sorted.forEach((team, index) => {
      map.set(team.team_id_master, index + 1);
    });
    return map;
  }, [region, rankings]);

  // Helper to get the correct rank for display
  const getDisplayRank = useCallback((team: RankingRow): number | null | undefined => {
    if (region && computedStateRanks) {
      return computedStateRanks.get(team.team_id_master) ?? null;
    }
    return team.rank_in_cohort_final;
  }, [region, computedStateRanks]);

  // Sort rankings based on selected field with SOS tie-breaking
  const sortedRankings = useMemo(() => {
    if (!rankings) return [];

    const sorted = [...rankings].sort((a, b) => {
      let aValue: number | string;
      let bValue: number | string;

      switch (sortField) {
        case 'rank':
          // Use computed position-based ranks for state view, national rank for national view
          aValue = region
            ? (computedStateRanks?.get(a.team_id_master) ?? Infinity)
            : (a.rank_in_cohort_final ?? Infinity);
          bValue = region
            ? (computedStateRanks?.get(b.team_id_master) ?? Infinity)
            : (b.rank_in_cohort_final ?? Infinity);
          break;
        case 'team':
          aValue = a.team_name.toLowerCase();
          bValue = b.team_name.toLowerCase();
          break;
        case 'powerScore':
          // Use power_score_final (ML-adjusted score) - primary sort field
          aValue = a.power_score_final ?? 0;
          bValue = b.power_score_final ?? 0;
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

      const primaryCompare = sortDirection === 'asc'
        ? (aValue as number) - (bValue as number)
        : (bValue as number) - (aValue as number);

      // If primary values are equal, use SOS as tie-breaker (higher SOS = harder schedule = better)
      if (primaryCompare === 0 && (sortField === 'rank' || sortField === 'powerScore')) {
        const aSos = region ? (a.sos_norm_state ?? a.sos_norm ?? 0) : (a.sos_norm ?? 0);
        const bSos = region ? (b.sos_norm_state ?? b.sos_norm ?? 0) : (b.sos_norm ?? 0);
        return bSos - aSos; // Higher SOS ranks higher (tie-breaker always descending)
      }

      return primaryCompare;
    });

    return sorted;
  }, [rankings, sortField, sortDirection, region, computedStateRanks]);

  // Virtualizer for rendering only visible rows
  const virtualizer = useVirtualizer({
    count: sortedRankings.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5, // Render 5 extra rows above/below viewport
  });

  const handleSort = useCallback((field: SortField) => {
    const newDirection = sortField === field
      ? (sortDirection === 'asc' ? 'desc' : 'asc')
      : 'asc';

    // Track sort event
    trackSortUsed({
      column: field,
      direction: newDirection,
      region,
      age_group: ageGroup,
      gender,
    });

    if (sortField === field) {
      setSortDirection(newDirection);
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  }, [sortField, sortDirection, region, ageGroup, gender]);

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
  
  if (!rankings?.length) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div>No teams available.</div>
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

  // Prepare top teams for schema
  const topTeamsForSchema = sortedRankings.slice(0, 10).map(team => ({
    teamName: team.team_name,
    clubName: team.club_name ?? undefined,
    rank: team.national_rank ?? undefined,
    powerScore: team.national_power_score ?? undefined,
    state: team.state_code ?? undefined,
  }));

  return (
    <>
      {/* Rankings Schema for SEO */}
      <RankingsSchema
        region={region || 'national'}
        ageGroup={ageGroup}
        gender={gender === 'M' || gender === 'B' ? 'male' : 'female'}
        topTeams={topTeamsForSchema}
        totalTeams={sortedRankings.length}
        lastUpdated={rankings?.[0]?.last_calculated}
      />
      <Card data-testid="rankings-table-card" className="overflow-hidden border-0 shadow-lg">
      <CardHeader className="bg-gradient-to-r from-primary to-[oklch(0.28_0.08_165)] text-primary-foreground relative">
        <div className="absolute right-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <CardTitle data-testid="rankings-title" className="text-2xl sm:text-3xl font-bold uppercase tracking-wide flex items-center gap-2">
          Complete Rankings
          {/* Show loading indicator when fetching new data (but not initial load) */}
          {isFetching && !isLoading && (
            <span className="inline-block w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" aria-label="Loading..." />
          )}
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
              <div className="inline-block min-w-full align-middle min-w-[400px] sm:min-w-[500px]">
                {/* Table Header */}
                <div data-testid="rankings-table-header" className="grid border-b-2 border-primary bg-secondary/50 sticky top-0 z-10" style={{ gridTemplateColumns: '60px 2fr 1fr 1fr' }}>
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <SortButton field="rank" label="Rank" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                  </div>
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <SortButton field="team" label="Team" sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                  </div>
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="min-w-0 overflow-hidden">
                          <SortButton field="powerScore" label={<><span className="hidden sm:inline">PowerScore (ML Adjusted)</span><span className="sm:hidden">PS</span></>} sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>A machine-learning-enhanced ranking score that measures overall team strength based on offense, defense, schedule difficulty, and predictive performance patterns.</p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="min-w-0 overflow-hidden">
                          <SortButton field="sosRank" label={<><span className="hidden sm:inline">SOS Rank</span><span className="sm:hidden">SOS R</span></>} sortField={sortField} sortDirection={sortDirection} onSort={handleSort} />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>Strength of Schedule — how tough the opponents are. #1 = hardest schedule in this age group.</p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                </div>

                {/* Virtualized Table Body */}
                <div
                  ref={parentRef}
                  className="overflow-auto h-[400px] sm:h-[500px] md:h-[600px]"
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
                      const displayRank = getDisplayRank(team);
                      const borderClass = getRankBorderClass(displayRank ?? null);

                      return (
                        <div
                          key={team.team_id_master}
                          data-index={virtualRow.index}
                          data-testid={`rankings-row-${virtualRow.index}`}
                          ref={virtualizer.measureElement}
                          className={`
                            grid border-b group cursor-pointer
                            hover:bg-accent/70 hover:shadow-md
                            transition-all duration-200 ease-in-out
                            hover:scale-[1.01] hover:z-10
                            ${borderClass}
                          `}
                          style={{
                            gridTemplateColumns: '60px 2fr 1fr 1fr',
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            height: `${virtualRow.size}px`,
                            transform: `translateY(${virtualRow.start}px)`,
                            minHeight: '60px',
                          }}
                        >
                          <div className="px-1.5 sm:px-4 py-2 sm:py-3 font-semibold flex items-center gap-1 text-xs sm:text-base min-w-0 overflow-hidden">
                            {(() => {
                              const rank = getDisplayRank(team);
                              const change = region
                                ? (team.rank_change_state_7d ?? team.rank_change_7d)
                                : team.rank_change_7d;
                              return (
                                <>
                                  <span>{rank != null ? `#${rank}` : '—'}</span>
                                  {change != null && change !== 0 && (
                                    <Tooltip>
                                      <TooltipTrigger asChild>
                                        <span className={`inline-flex items-center text-[10px] sm:text-xs font-medium ${change > 0 ? 'text-green-600' : 'text-red-500'}`}>
                                          {change > 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                                          <span className="hidden sm:inline">{Math.abs(change)}</span>
                                        </span>
                                      </TooltipTrigger>
                                      <TooltipContent>
                                        <p>{change > 0 ? `Up ${change} spots` : `Down ${Math.abs(change)} spots`} in the last 7 days</p>
                                      </TooltipContent>
                                    </Tooltip>
                                  )}
                                </>
                              );
                            })()}
                          </div>
                          <div className="px-1.5 sm:px-4 py-2 sm:py-3 min-w-0 overflow-hidden">
                            <Link
                              href={`/teams/${team.team_id_master}?region=${region || 'national'}&ageGroup=${ageGroup}&gender=${gender?.toLowerCase() || 'male'}`}
                              onMouseEnter={() => prefetchTeam(team.team_id_master)}
                              onClick={() => trackTeamRowClicked({
                                team_id_master: team.team_id_master,
                                team_name: team.team_name,
                                club_name: team.club_name,
                                state: team.state,
                                age: team.age,
                                gender: team.gender,
                                rank_in_cohort_final: team.rank_in_cohort_final,
                                rank_in_state_final: getDisplayRank(team) as number | undefined,
                              })}
                              className="font-medium hover:text-primary transition-colors duration-300 focus-visible:outline-primary focus-visible:ring-2 focus-visible:ring-primary rounded cursor-pointer inline-block text-xs sm:text-sm truncate block w-full"
                              aria-label={`View ${team.team_name} team details`}
                            >
                              {team.team_name}
                            </Link>
                            <div className="text-xs sm:text-sm text-muted-foreground truncate w-full">
                              {team.club_name && <span>{team.club_name}</span>}
                              {team.club_name && team.state && <span> &bull; </span>}
                              {team.state && <span>{team.state}</span>}
                            </div>
                          </div>
                          <div className="px-1.5 sm:px-4 py-2 sm:py-3 text-right font-semibold flex items-center justify-end text-xs sm:text-sm min-w-0 overflow-hidden">
                            <span className="truncate">{formatPowerScore(team.power_score_final)}</span>
                          </div>
                          <div className="px-1.5 sm:px-4 py-2 sm:py-3 text-right flex items-center justify-end text-xs sm:text-sm min-w-0 overflow-hidden">
                            {(() => {
                              const sosRank = region ? team.sos_rank_state : team.sos_rank_national;
                              if (!sosRank) return <span className="truncate">—</span>;
                              const totalTeams = sortedRankings.length;
                              const pct = totalTeams > 0 ? Math.round((1 - (sosRank - 1) / totalTeams) * 100) : null;
                              return (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span className="truncate cursor-help">#{sosRank}</span>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>#{sosRank} toughest schedule{totalTeams > 0 ? ` out of ${totalTeams} teams` : ''}{pct != null ? ` — harder than ${pct}%` : ''}</p>
                                  </TooltipContent>
                                </Tooltip>
                              );
                            })()}
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
    </>
  );
}
