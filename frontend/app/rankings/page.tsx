'use client';

import { Suspense, useState } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { RankingsFilter } from '@/components/RankingsFilter';
import { RankingsTable } from '@/components/RankingsTable';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';

export default function RankingsPage() {
  // Default filters - these will be updated by RankingsFilter component
  const [region, setRegion] = useState('national');
  const [ageGroup, setAgeGroup] = useState('u12');
  const [gender, setGender] = useState('male');

  // Convert gender from URL format (lowercase) to API format (single letter)
  const genderForAPI = gender 
    ? (gender === 'male' ? 'M' : gender === 'female' ? 'F' : null) as 'M' | 'F' | 'B' | 'G' | null
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
        <RankingsFilter 
          onFilterChange={(r, a, g) => {
            setRegion(r);
            setAgeGroup(a);
            setGender(g);
          }}
        />
        
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
