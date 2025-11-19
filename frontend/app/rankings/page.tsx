'use client';

import { Suspense, useState } from 'react';
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
    <>
      {/* Page Header - Athletic Editorial Style */}
      <div className="relative bg-secondary/30 border-b-2 border-primary py-8 sm:py-12">
        <div className="absolute left-0 top-0 w-2 h-full bg-accent -skew-x-12" aria-hidden="true" />
        <div className="container mx-auto px-4">
          <h1 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold uppercase text-primary mb-2">
            Rankings
          </h1>
          <p className="text-muted-foreground text-base sm:text-lg">
            Comprehensive youth soccer team rankings powered by V53E
          </p>
        </div>
      </div>

      <div className="container mx-auto py-6 sm:py-8 px-4">
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
    </>
  );
}
