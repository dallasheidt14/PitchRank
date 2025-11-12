'use client';

import { PageHeader } from '@/components/PageHeader';
import { TeamHeader } from '@/components/TeamHeader';
import { TeamTrajectoryChart } from '@/components/TeamTrajectoryChart';
import { GameHistoryTable } from '@/components/GameHistoryTable';
import { MomentumMeter } from '@/components/MomentumMeter';
import { use } from 'react';
import dynamic from 'next/dynamic';

// Lazy-load charts for better performance
const LazyTeamTrajectoryChart = dynamic(
  () => import('@/components/TeamTrajectoryChart').then(mod => ({ default: mod.TeamTrajectoryChart })),
  { ssr: true, loading: () => <div className="h-64 animate-pulse bg-muted rounded-lg" /> }
);

const LazyMomentumMeter = dynamic(
  () => import('@/components/MomentumMeter').then(mod => ({ default: mod.MomentumMeter })),
  { ssr: true, loading: () => <div className="h-48 animate-pulse bg-muted rounded-lg" /> }
);

// Revalidate every hour for ISR caching
export const revalidate = 3600;

interface TeamPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default function TeamPage({ params }: TeamPageProps) {
  const { id } = use(params);

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title="Team Details"
        description={`View detailed information and statistics`}
        showBackButton
        backHref="/"
      />
      
      <div className="space-y-6">
        <TeamHeader teamId={id} />
        
        <div className="grid gap-6 md:grid-cols-2">
          <GameHistoryTable teamId={id} limit={10} />
          <LazyMomentumMeter teamId={id} />
        </div>
        
        <LazyTeamTrajectoryChart teamId={id} />
      </div>
    </div>
  );
}

