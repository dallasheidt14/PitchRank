'use client';

import { TeamHeader } from '@/components/TeamHeader';
import { TeamTrajectoryChart } from '@/components/TeamTrajectoryChart';
import { GameHistoryTable } from '@/components/GameHistoryTable';
import { MomentumMeter } from '@/components/MomentumMeter';
import { TeamInsightsCard } from '@/components/TeamInsightsCard';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import dynamic from 'next/dynamic';
import { useSearchParams, useRouter } from 'next/navigation';
import { Suspense, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { SectionErrorBoundary } from '@/components/ui/SectionErrorBoundary';
import { ArrowLeft } from 'lucide-react';

// Lazy-load charts for better performance
const LazyTeamTrajectoryChart = dynamic(
  () => import('@/components/TeamTrajectoryChart').then(mod => ({ default: mod.TeamTrajectoryChart })),
  { ssr: true, loading: () => <div className="h-64 animate-pulse bg-muted rounded-lg" /> }
);

const LazyMomentumMeter = dynamic(
  () => import('@/components/MomentumMeter').then(mod => ({ default: mod.MomentumMeter })),
  { ssr: true, loading: () => <div className="h-32 animate-pulse bg-muted rounded-lg" /> }
);

const LazyTeamInsightsCard = dynamic(
  () => import('@/components/TeamInsightsCard').then(mod => ({ default: mod.TeamInsightsCard })),
  { ssr: true, loading: () => <div className="h-40 animate-pulse bg-muted rounded-lg" /> }
);

interface TeamPageShellProps {
  id: string;
}

function BackToRankingsButtonContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // Extract filter parameters from query string, with defaults
  const region = searchParams.get('region') || 'national';
  const ageGroup = searchParams.get('ageGroup') || 'u12';
  const gender = searchParams.get('gender') || 'male';

  // Validate and sanitize parameters
  const validAgeGroups = ['u10', 'u11', 'u12', 'u13', 'u14', 'u15', 'u16', 'u17', 'u18'];
  const validGenders = ['male', 'female'];
  
  const sanitizedAgeGroup = validAgeGroups.includes(ageGroup.toLowerCase()) 
    ? ageGroup.toLowerCase() 
    : 'u12';
  const sanitizedGender = validGenders.includes(gender.toLowerCase())
    ? gender.toLowerCase()
    : 'male';
  const sanitizedRegion = region.toLowerCase() === 'national' 
    ? 'national' 
    : region.toLowerCase().slice(0, 2); // Ensure state codes are 2 letters

  const handleBackToRankings = () => {
    try {
      router.push(`/rankings/${sanitizedRegion}/${sanitizedAgeGroup}/${sanitizedGender}`);
    } catch (error) {
      console.error('Error navigating to rankings:', error);
      // Fallback to default rankings page
      router.push('/rankings/national/u12/male');
    }
  };

  return (
    <div className="mb-4">
      <Button
        variant="outline"
        size="sm"
        onClick={handleBackToRankings}
        className="flex items-center gap-2"
      >
        <ArrowLeft size={16} />
        Back to Rankings
      </Button>
    </div>
  );
}

// Wrapper component that ensures useSearchParams is always in Suspense
function BackToRankingsButton() {
  return (
    <Suspense fallback={<div className="mb-4 h-9" />}>
      <BackToRankingsButtonContent />
    </Suspense>
  );
}

export function TeamPageShell({ id }: TeamPageShellProps) {
  const queryClient = useQueryClient();
  const previousIdRef = useRef<string | null>(null);

  // Invalidate team-related queries when navigating to a different team
  // This ensures fresh data is fetched even if cached data exists
  useEffect(() => {
    if (previousIdRef.current && previousIdRef.current !== id) {
      // Invalidate all team-related queries for the new team
      queryClient.invalidateQueries({ queryKey: ['team', id] });
      queryClient.invalidateQueries({ queryKey: ['team-games', id] });
      queryClient.invalidateQueries({ queryKey: ['team-trajectory', id] });
    }
    previousIdRef.current = id;
  }, [id, queryClient]);

  return (
    <>
      {/* Page Header - Athletic Editorial Style */}
      <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12">
        <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <div className="container mx-auto px-4 sm:px-6">
          <Breadcrumbs />
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            Team Details
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            View rankings, trajectory, momentum, and full match history
          </p>
        </div>
      </div>

      <div className="container mx-auto py-6 sm:py-8 px-4 sm:px-6">
        <BackToRankingsButton />

        <div className="space-y-6">
          <SectionErrorBoundary fallbackTitle="Failed to load team header.">
            <TeamHeader teamId={id} />
          </SectionErrorBoundary>

          <div className="grid grid-cols-1 gap-4 sm:gap-6 md:grid-cols-2">
            <SectionErrorBoundary fallbackTitle="Failed to load game history.">
              <GameHistoryTable teamId={id} />
            </SectionErrorBoundary>
            {/* Right column: Momentum + Insights stacked */}
            <div className="flex flex-col gap-4">
              <SectionErrorBoundary fallbackTitle="Failed to load momentum data.">
                <LazyMomentumMeter teamId={id} />
              </SectionErrorBoundary>
              <SectionErrorBoundary fallbackTitle="Failed to load insights.">
                <LazyTeamInsightsCard teamId={id} />
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

