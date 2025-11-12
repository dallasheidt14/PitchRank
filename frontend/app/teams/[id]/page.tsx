'use client';

import { PageHeader } from '@/components/PageHeader';
import { TeamHeader } from '@/components/TeamHeader';
import { TeamTrajectoryChart } from '@/components/TeamTrajectoryChart';
import { GameHistoryTable } from '@/components/GameHistoryTable';
import { MomentumMeter } from '@/components/MomentumMeter';
import { use, Suspense } from 'react';
import dynamic from 'next/dynamic';
import { useSearchParams, useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { ArrowLeft } from 'lucide-react';

// Lazy-load charts for better performance
const LazyTeamTrajectoryChart = dynamic(
  () => import('@/components/TeamTrajectoryChart').then(mod => ({ default: mod.TeamTrajectoryChart })),
  { ssr: true, loading: () => <div className="h-64 animate-pulse bg-muted rounded-lg" /> }
);

const LazyMomentumMeter = dynamic(
  () => import('@/components/MomentumMeter').then(mod => ({ default: mod.MomentumMeter })),
  { ssr: true, loading: () => <div className="h-48 animate-pulse bg-muted rounded-lg" /> }
);

interface TeamPageProps {
  params: Promise<{
    id: string;
  }>;
}

function BackToRankingsButton() {
  const searchParams = useSearchParams();
  const router = useRouter();

  // Extract filter parameters from query string, with defaults
  const region = searchParams.get('region') || 'national';
  const ageGroup = searchParams.get('ageGroup') || 'u12';
  const gender = searchParams.get('gender') || 'male';

  const handleBackToRankings = () => {
    router.push(`/rankings/${region}/${ageGroup}/${gender}`);
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
      
      <Suspense fallback={<div className="mb-4 h-9" />}>
        <BackToRankingsButton />
      </Suspense>
      
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

