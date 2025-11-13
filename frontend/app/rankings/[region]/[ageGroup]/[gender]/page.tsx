'use client';

import { Suspense } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { RankingsFilter } from '@/components/RankingsFilter';
import { RankingsTable } from '@/components/RankingsTable';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

interface RankingsPageProps {
  params: {
    region: string;
    ageGroup: string;
    gender: string;
  };
}

export default function RankingsPage({ params }: RankingsPageProps) {
  const { region, ageGroup, gender } = params;

  const genderForAPI = gender
    ? (gender.charAt(0).toUpperCase() + gender.slice(1).toLowerCase()) as
        | 'Male'
        | 'Female'
    : null;

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title="PitchRank Rankings"
        description=""
        showBackButton
        backHref="/"
      />
      
      <div className="space-y-6">
        <RankingsFilter />
        
        <Suspense fallback={<RankingsTableSkeleton />}>
          <RankingsTable
            region={region === 'national' ? null : region}
            ageGroup={ageGroup}
            gender={genderForAPI}
          />
        </Suspense>
      </div>
    </div>
  );
}
