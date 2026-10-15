'use client';

import { TeamHeader } from '@/components/TeamHeader';
import { GameHistoryTable } from '@/components/GameHistoryTable';
import { UpcomingGamesTable } from '@/components/UpcomingGamesTable';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import dynamic from 'next/dynamic';
import { useSearchParams, useRouter } from 'next/navigation';
import { Suspense, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { SectionErrorBoundary } from '@/components/ui/SectionErrorBoundary';
import { markIfOpenedFromRankings, wasOpenedFromRankings } from '@/hooks/useRankingsViewState';
import { useTeam } from '@/lib/hooks';
import { formatGender, US_STATES } from '@/lib/constants';
import type { TeamWithRanking } from '@/lib/types';
import { backToRankingsPath, teamDisplayName } from '@/lib/utils';
import { ArrowLeft } from 'lucide-react';

// Lazy-load charts for better performance
const LazyTeamTrajectoryChart = dynamic(
  () => import('@/components/TeamTrajectoryChart').then((mod) => ({ default: mod.TeamTrajectoryChart })),
  { ssr: true, loading: () => <div className="h-64 animate-pulse bg-muted rounded-lg" /> }
);

const LazyMomentumMeter = dynamic(
  () => import('@/components/MomentumMeter').then((mod) => ({ default: mod.MomentumMeter })),
  { ssr: true, loading: () => <div className="h-32 animate-pulse bg-muted rounded-lg" /> }
);

const LazyTeamInsightsCard = dynamic(
  () => import('@/components/TeamInsightsCard').then((mod) => ({ default: mod.TeamInsightsCard })),
  { ssr: true, loading: () => <div className="h-40 animate-pulse bg-muted rounded-lg" /> }
);

const LazyClutchFactorCard = dynamic(
  () => import('@/components/ClutchFactorCard').then((mod) => ({ default: mod.ClutchFactorCard })),
  { ssr: true, loading: () => <div className="h-32 animate-pulse bg-muted rounded-lg" /> }
);

const LazyRankHistoryChart = dynamic(
  () => import('@/components/RankHistoryChart').then((mod) => ({ default: mod.RankHistoryChart })),
  { ssr: true, loading: () => <div className="h-[240px] animate-pulse bg-muted rounded-lg" /> }
);

interface TeamPageShellProps {
  id: string;
}

function BackToRankingsButtonContent({ teamId }: { teamId: string }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { data: team } = useTeam(teamId);
  const goingBackRef = useRef(false);

  // Forward before the board renders, or a back/forward-cache restore, brings this same page back.
  useEffect(() => {
    const releaseOnReturn = () => {
      if (wasOpenedFromRankings()) goingBackRef.current = false;
    };
    window.addEventListener('popstate', releaseOnReturn);
    window.addEventListener('pageshow', releaseOnReturn);
    return () => {
      window.removeEventListener('popstate', releaseOnReturn);
      window.removeEventListener('pageshow', releaseOnReturn);
    };
  }, []);

  const handleBackToRankings = () => {
    // history.back() is asynchronous: a second tap before it lands would go back twice, and one
    // after it lands, while this page is still up, would read the board's entry and push.
    if (goingBackRef.current) return;
    if (wasOpenedFromRankings()) {
      goingBackRef.current = true;
      router.back();
      return;
    }
    const target = backToRankingsPath(
      {
        region: searchParams.get('region'),
        ageGroup: searchParams.get('ageGroup'),
        gender: searchParams.get('gender'),
      },
      team
    );
    try {
      router.push(target);
    } catch (error) {
      console.error('Error navigating to rankings:', error);
      router.push('/rankings');
    }
  };

  return (
    <div className="mb-4">
      <Button variant="outline" size="sm" onClick={handleBackToRankings} className="flex items-center gap-2">
        <ArrowLeft size={16} />
        Back to Rankings
      </Button>
    </div>
  );
}

// Wrapper component that ensures useSearchParams is always in Suspense
function BackToRankingsButton({ teamId }: { teamId: string }) {
  return (
    <Suspense fallback={<div className="mb-4 h-9" />}>
      <BackToRankingsButtonContent teamId={teamId} />
    </Suspense>
  );
}

/** Home › Rankings › the team's board › the team; the URL alone would end in the team's id. */
function teamBreadcrumbs(id: string, team: TeamWithRanking | undefined) {
  const crumbs = [
    { label: 'Home', href: '/' },
    { label: 'Rankings', href: '/rankings' },
  ];
  // While the team loads, end on a crumb for this page so Rankings never reads as the current page.
  if (!team) return [...crumbs, { label: 'Team', href: `/teams/${id}` }];

  const board = backToRankingsPath({ region: null, ageGroup: null, gender: null }, team);
  if (board !== '/rankings') {
    const [region, ageGroup, gender] = board.split('/').slice(2);
    const place = region === 'national' ? 'National' : (US_STATES.find((s) => s.code === region)?.name ?? region);
    crumbs.push({ label: `${place} ${ageGroup.toUpperCase()} ${formatGender(gender)}`, href: board });
  }
  crumbs.push({ label: teamDisplayName(team), href: `/teams/${id}` });
  return crumbs;
}

export function TeamPageShell({ id }: TeamPageShellProps) {
  const queryClient = useQueryClient();
  const previousIdRef = useRef<string | null>(null);
  const { data: team } = useTeam(id);

  // Invalidate team-related queries when navigating to a different team
  // This ensures fresh data is fetched even if cached data exists
  useEffect(() => {
    if (previousIdRef.current && previousIdRef.current !== id) {
      // Invalidate all team-related queries for the new team
      queryClient.invalidateQueries({ queryKey: ['team', id] });
      queryClient.invalidateQueries({ queryKey: ['team-games', id] });
      queryClient.invalidateQueries({ queryKey: ['team-trajectory', id] });
      queryClient.invalidateQueries({ queryKey: ['rank-history', id] });
    }
    previousIdRef.current = id;
  }, [id, queryClient]);

  // A rankings row's push lands here; mark the entry so Back to Rankings can return to the board.
  useEffect(() => {
    markIfOpenedFromRankings();
  }, [id]);

  return (
    <>
      <div className="container mx-auto py-6 sm:py-8 px-4 sm:px-6">
        <Breadcrumbs items={teamBreadcrumbs(id, team)} />
        <BackToRankingsButton teamId={id} />

        <div className="space-y-6">
          <SectionErrorBoundary fallbackTitle="Failed to load team header.">
            <TeamHeader teamId={id} />
          </SectionErrorBoundary>

          {/* Phones get upcoming games ahead of the long game history; md+ keeps them atop the right column.
              Both copies share one query, and rendering twice keeps the reading order matching the screen. */}
          <div className="md:hidden">
            <SectionErrorBoundary fallbackTitle="Failed to load upcoming games.">
              <UpcomingGamesTable teamId={id} />
            </SectionErrorBoundary>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:gap-6 md:grid-cols-2">
            <SectionErrorBoundary fallbackTitle="Failed to load game history.">
              <GameHistoryTable teamId={id} />
            </SectionErrorBoundary>
            {/* Right column: Upcoming + Rank History + Momentum + Insights stacked */}
            <div className="flex flex-col gap-4">
              <div className="hidden md:block">
                <SectionErrorBoundary fallbackTitle="Failed to load upcoming games.">
                  <UpcomingGamesTable teamId={id} />
                </SectionErrorBoundary>
              </div>
              <SectionErrorBoundary fallbackTitle="Failed to load ranking history.">
                <LazyRankHistoryChart teamId={id} />
              </SectionErrorBoundary>
              <SectionErrorBoundary fallbackTitle="Failed to load momentum data.">
                <LazyMomentumMeter teamId={id} />
              </SectionErrorBoundary>
              <SectionErrorBoundary fallbackTitle="Failed to load insights.">
                <LazyTeamInsightsCard teamId={id} />
              </SectionErrorBoundary>
              <SectionErrorBoundary fallbackTitle="Failed to load clutch factor.">
                <LazyClutchFactorCard teamId={id} />
              </SectionErrorBoundary>
            </div>
          </div>

          <SectionErrorBoundary fallbackTitle="Failed to load trajectory chart.">
            <LazyTeamTrajectoryChart teamId={id} />
          </SectionErrorBoundary>
        </div>
      </div>
    </>
  );
}
