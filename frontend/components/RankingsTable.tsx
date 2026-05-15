'use client';

import { useDeferredValue, useMemo, useState, useRef, memo, useCallback, useEffect } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { ErrorDisplay } from '@/components/ui/ErrorDisplay';
import { useRankings } from '@/hooks/useRankings';
import { usePrefetchTeam } from '@/lib/hooks';
import Link from 'next/link';
import { ArrowUp, ArrowDown, ArrowUpDown, ChevronRight, Search, X } from 'lucide-react';
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
const SortButton = memo(
  ({
    field,
    label,
    sortField,
    sortDirection,
    onSort,
  }: {
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
  }
);
SortButton.displayName = 'SortButton';

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
  const [searchQuery, setSearchQuery] = useState('');
  const deferredQuery = useDeferredValue(searchQuery);
  const parentRef = useRef<HTMLDivElement>(null);

  const { data: rankings, isLoading, isFetching, isError, error, refetch } = useRankings(region, ageGroup, gender);
  const prefetchTeam = usePrefetchTeam();

  // Clear search query when cohort changes
  useEffect(() => {
    setSearchQuery('');
  }, [region, ageGroup, gender]);

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
  }, [rankings, region, ageGroup, gender]);

  // Use published ranks from the backend contract.
  const getDisplayRank = useCallback(
    (team: RankingRow): number | null | undefined => {
      return region ? (team.rank_in_state_final ?? null) : (team.rank_in_cohort_final ?? null);
    },
    [region]
  );

  const getDisplaySosRank = useCallback(
    (team: RankingRow): number | null | undefined => {
      return region ? (team.sos_rank_state ?? null) : (team.sos_rank_national ?? null);
    },
    [region]
  );

  // Sort rankings using published ranks and deterministic fallbacks.
  const sortedRankings = useMemo(() => {
    if (!rankings) return [];

    const sorted = [...rankings].sort((a, b) => {
      let aValue: number | string;
      let bValue: number | string;

      switch (sortField) {
        case 'rank':
          aValue = getDisplayRank(a) ?? Infinity;
          bValue = getDisplayRank(b) ?? Infinity;
          break;
        case 'team':
          aValue = a.team_name.toLowerCase();
          bValue = b.team_name.toLowerCase();
          break;
        case 'powerScore':
          aValue = a.power_score_final ?? 0;
          bValue = b.power_score_final ?? 0;
          break;
        case 'sosRank':
          aValue = getDisplaySosRank(a) ?? Infinity;
          bValue = getDisplaySosRank(b) ?? Infinity;
          break;
        default:
          return 0;
      }

      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortDirection === 'asc' ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
      }

      const primaryCompare =
        sortDirection === 'asc' ? (aValue as number) - (bValue as number) : (bValue as number) - (aValue as number);

      if (primaryCompare !== 0) {
        return primaryCompare;
      }

      const aRank = getDisplayRank(a) ?? Number.POSITIVE_INFINITY;
      const bRank = getDisplayRank(b) ?? Number.POSITIVE_INFINITY;
      if (aRank !== bRank) {
        return aRank - bRank;
      }

      return a.team_id_master.localeCompare(b.team_id_master);
    });

    return sorted;
  }, [getDisplayRank, getDisplaySosRank, rankings, sortField, sortDirection]);

  // Filter sorted rankings by search query.
  // Normalizes hyphens/punctuation to spaces and matches every token as a
  // substring so "pre elite" finds "Pre-Elite" and "2014 elite" matches
  // regardless of where the words appear in name/club.
  const visibleRankings = useMemo(() => {
    const normalize = (s: string) =>
      s
        .toLowerCase()
        .replace(/[-_./'"]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    const tokens = normalize(deferredQuery).split(' ').filter(Boolean);
    if (tokens.length === 0) return sortedRankings;
    return sortedRankings.filter((team) => {
      const haystack = normalize(`${team.team_name ?? ''} ${team.club_name ?? ''}`);
      return tokens.every((t) => haystack.includes(t));
    });
  }, [sortedRankings, deferredQuery]);

  // Virtualizer for rendering only visible rows
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: visibleRankings.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 5, // Render 5 extra rows above/below viewport
  });

  const handleSort = useCallback(
    (field: SortField) => {
      const newDirection = sortField === field ? (sortDirection === 'asc' ? 'desc' : 'asc') : 'asc';

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
    },
    [sortField, sortDirection, region, ageGroup, gender]
  );

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
      const genderLabel =
        gender === 'M'
          ? 'Boys'
          : gender === 'F'
            ? 'Girls'
            : gender === 'B'
              ? 'Boys'
              : gender === 'G'
                ? 'Girls'
                : gender;
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
          <div>No teams available — new rankings are running, check back shortly.</div>
        </CardContent>
      </Card>
    );
  }

  const virtualItems = virtualizer.getVirtualItems();
  const totalHeight = virtualizer.getTotalSize();
  const paddingTop = virtualItems.length > 0 ? (virtualItems[0]?.start ?? 0) : 0;
  const paddingBottom = virtualItems.length > 0 ? totalHeight - (virtualItems[virtualItems.length - 1]?.end ?? 0) : 0;

  // Prepare top teams for schema — only include teams with a published rank
  const topTeamsForSchema = sortedRankings
    .filter((team) => getDisplayRank(team) != null)
    .slice(0, 10)
    .map((team) => ({
      teamName: team.team_name,
      clubName: team.club_name ?? undefined,
      rank: getDisplayRank(team)!,
      powerScore: team.power_score_final ?? undefined,
      state: team.state ?? undefined,
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
          <CardTitle
            data-testid="rankings-title"
            className="text-2xl sm:text-3xl font-bold uppercase tracking-wide flex items-center gap-2"
          >
            Complete Rankings
            {/* Show loading indicator when fetching new data (but not initial load) */}
            {isFetching && !isLoading && (
              <span
                className="inline-block w-4 h-4 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin"
                aria-label="Loading..."
              />
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
        <CardContent className="px-2 sm:px-6">
          {sortedRankings.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">No rankings found for the selected filters</p>
          ) : (
            <div className="rounded-md border overflow-hidden">
              {/* Table wrapper - no horizontal scroll on mobile, columns flex to fit */}
              <div>
                {/* Sticky search input */}
                <div className="sticky top-0 z-20 bg-background border-b">
                  <div className="relative px-2 py-2 sm:px-4">
                    <Search className="absolute left-4 sm:left-6 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                    <input
                      type="search"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search your team"
                      aria-label="Search your team"
                      className="w-full h-9 pl-9 pr-9 rounded-md border border-input bg-background text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        aria-label="Clear search"
                        className="absolute right-3 sm:right-5 top-1/2 -translate-y-1/2 h-6 w-6 inline-flex items-center justify-center rounded text-muted-foreground hover:text-foreground"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                </div>
                {/* Table Header */}
                <div
                  data-testid="rankings-table-header"
                  className="grid grid-cols-[40px_1fr_50px_64px] sm:grid-cols-[70px_2fr_1fr_1fr_100px] border-b-2 border-primary bg-secondary/50 sticky top-[52px] z-10"
                >
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <SortButton
                      field="rank"
                      label="Rank"
                      sortField={sortField}
                      sortDirection={sortDirection}
                      onSort={handleSort}
                    />
                  </div>
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <SortButton
                      field="team"
                      label="Team"
                      sortField={sortField}
                      sortDirection={sortDirection}
                      onSort={handleSort}
                    />
                  </div>
                  <div className="px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="min-w-0 overflow-hidden">
                          <SortButton
                            field="powerScore"
                            label={
                              <>
                                <span className="hidden sm:inline">PowerScore (ML Adjusted)</span>
                                <span className="sm:hidden">PS</span>
                              </>
                            }
                            sortField={sortField}
                            sortDirection={sortDirection}
                            onSort={handleSort}
                          />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>
                          A machine-learning-enhanced ranking score that measures overall team strength based on
                          offense, defense, schedule difficulty, and predictive performance patterns.
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div className="hidden sm:block px-1.5 sm:px-4 py-2 sm:py-4 font-semibold text-right text-xs sm:text-sm uppercase tracking-wide min-w-0 overflow-hidden">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="min-w-0 overflow-hidden">
                          <SortButton
                            field="sosRank"
                            label={
                              <>
                                <span className="hidden sm:inline">SOS Rank</span>
                                <span className="sm:hidden">SOS R</span>
                              </>
                            }
                            sortField={sortField}
                            sortDirection={sortDirection}
                            onSort={handleSort}
                          />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>
                          Strength of Schedule — how tough the opponents are. #1 = hardest schedule in this age group.
                        </p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <div aria-hidden="true" />
                </div>

                {/* Virtualized Table Body */}
                <div ref={parentRef} className="rankings-body overflow-auto h-[660px] sm:h-[780px] md:h-[900px]">
                  <div
                    style={{
                      height: `${totalHeight}px`,
                      width: '100%',
                      position: 'relative',
                    }}
                  >
                    {paddingTop > 0 && <div style={{ height: `${paddingTop}px` }} />}
                    {virtualItems.map((virtualRow) => {
                      const team = visibleRankings[virtualRow.index];
                      const displayRank = getDisplayRank(team);
                      const borderClass = getRankBorderClass(displayRank ?? null);
                      const isTop3 = displayRank != null && displayRank <= 3;

                      return (
                        <Link
                          key={team.team_id_master}
                          href={`/teams/${team.team_id_master}?region=${region || 'national'}&ageGroup=${ageGroup}&gender=${gender?.toLowerCase() || 'male'}`}
                          draggable={false}
                          data-index={virtualRow.index}
                          data-testid={`rankings-row-${virtualRow.index}`}
                          ref={virtualizer.measureElement}
                          onMouseEnter={() => prefetchTeam(team.team_id_master)}
                          onClick={() =>
                            trackTeamRowClicked({
                              team_id_master: team.team_id_master,
                              team_name: team.team_name,
                              club_name: team.club_name,
                              state: team.state,
                              age: team.age,
                              gender: team.gender,
                              rank_in_cohort_final: team.rank_in_cohort_final,
                              rank_in_state_final: team.rank_in_state_final ?? undefined,
                            })
                          }
                          aria-label={`View ${team.team_name} team details`}
                          className={`
                            rankings-row-link touch-auto
                            grid grid-cols-[40px_1fr_50px_64px] sm:grid-cols-[70px_2fr_1fr_1fr_100px] border-b group
                            ${isTop3 ? 'hover:bg-accent/[0.12]' : 'hover:bg-primary/[0.04]'} hover:shadow-md
                            active:bg-primary/[0.10] active:scale-[0.997]
                            transition-[background-color,box-shadow,opacity,transform] duration-200 ease-in-out
                            hover:z-10
                            ${borderClass}
                          `}
                          style={{
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
                                        <span
                                          className={`inline-flex items-center text-[10px] sm:text-xs font-medium ${change > 0 ? 'text-green-600' : 'text-red-500'}`}
                                        >
                                          {change > 0 ? (
                                            <ArrowUp className="h-3 w-3" />
                                          ) : (
                                            <ArrowDown className="h-3 w-3" />
                                          )}
                                          <span className="hidden sm:inline">{Math.abs(change)}</span>
                                        </span>
                                      </TooltipTrigger>
                                      <TooltipContent>
                                        <p>
                                          {change > 0 ? `Up ${change} spots` : `Down ${Math.abs(change)} spots`} in the
                                          last 7 days
                                        </p>
                                      </TooltipContent>
                                    </Tooltip>
                                  )}
                                </>
                              );
                            })()}
                          </div>
                          <div className="px-1 sm:px-4 py-2 sm:py-3 min-w-0 overflow-hidden">
                            <span className="font-medium text-primary group-hover:text-primary/80 transition-colors duration-300 text-xs sm:text-sm truncate block w-full">
                              {team.team_name}
                            </span>
                            {(team.club_name || team.state) && (
                              <div className="text-xs sm:text-sm text-muted-foreground truncate w-full">
                                {team.club_name && <span>{team.club_name}</span>}
                                {team.club_name && team.state && <span> &bull; </span>}
                                {team.state && <span>{team.state.toUpperCase()}</span>}
                              </div>
                            )}
                          </div>
                          <div className="px-1.5 sm:px-4 py-2 sm:py-3 text-right font-semibold flex items-center justify-end text-xs sm:text-sm min-w-0 overflow-hidden">
                            <span className="truncate">{formatPowerScore(team.power_score_final)}</span>
                          </div>
                          <div className="hidden sm:flex px-1.5 sm:px-4 py-2 sm:py-3 text-right items-center justify-end text-xs sm:text-sm min-w-0 overflow-hidden">
                            {(() => {
                              const sosRank = getDisplaySosRank(team);
                              if (!sosRank) return <span className="truncate">—</span>;
                              const totalTeams = sortedRankings.length;
                              const pct = totalTeams > 0 ? Math.round((1 - (sosRank - 1) / totalTeams) * 100) : null;
                              return (
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <span className="truncate">#{sosRank}</span>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>
                                      #{sosRank} toughest schedule{totalTeams > 0 ? ` out of ${totalTeams} teams` : ''}
                                      {pct != null ? ` — harder than ${pct}%` : ''}
                                    </p>
                                  </TooltipContent>
                                </Tooltip>
                              );
                            })()}
                          </div>
                          <div className="flex items-center justify-end gap-1 px-1 sm:px-2">
                            <span className="text-[0.65rem] sm:text-[0.72rem] font-semibold sm:font-medium text-primary whitespace-nowrap opacity-100 translate-x-0 sm:opacity-0 sm:translate-x-2 sm:group-hover:opacity-100 sm:group-hover:translate-x-0 transition-all duration-[180ms] sm:delay-100">
                              View Team
                            </span>
                            <ChevronRight className="hidden sm:block sm:h-[1.1rem] sm:w-[1.1rem] sm:text-muted-foreground sm:opacity-50 sm:group-hover:text-primary sm:group-hover:opacity-100 sm:group-hover:translate-x-0.5 transition-all duration-200 shrink-0" />
                          </div>
                        </Link>
                      );
                    })}
                    {paddingBottom > 0 && <div style={{ height: `${paddingBottom}px` }} />}
                  </div>
                  {deferredQuery.trim() && visibleRankings.length === 0 && (
                    <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                      No teams match &ldquo;{deferredQuery.trim()}&rdquo; in this cohort.
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        data-testid="rankings-search-empty-clear"
                        className="block mx-auto mt-2 text-primary hover:underline"
                      >
                        Clear search
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  );
}
