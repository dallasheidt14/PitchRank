'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { RankingsFilter } from '@/components/RankingsFilter';
import { RankingsStickyFilters } from '@/components/RankingsStickyFilters';
import { RankingsTable } from '@/components/RankingsTable';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import { RelatedRankings } from '@/components/RelatedRankings';

interface RankingsPageContentProps {
  region: string;
  ageGroup: string;
  gender: string;
}

export function RankingsPageContent({ region, ageGroup, gender }: RankingsPageContentProps) {
  const genderForAPI = gender
    ? ((gender === 'male' ? 'M' : gender === 'female' ? 'F' : null) as 'M' | 'F' | 'B' | 'G' | null)
    : null;

  const filterCardRef = useRef<HTMLDivElement>(null);
  const [stickyVisible, setStickyVisible] = useState(false);

  useEffect(() => {
    const target = filterCardRef.current;
    if (!target) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        setStickyVisible(!entry.isIntersecting);
      },
      { threshold: 0, rootMargin: '-64px 0px 0px 0px' }
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  const scrollToFilters = () => {
    filterCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="container mx-auto py-8 px-4">
      <Breadcrumbs />

      <RankingsStickyFilters
        region={region}
        ageGroup={ageGroup}
        gender={gender}
        visible={stickyVisible}
        onChangeClick={scrollToFilters}
      />

      <div className="space-y-6">
        <div ref={filterCardRef}>
          <RankingsFilter />
        </div>

        <Suspense fallback={<RankingsTableSkeleton />}>
          <RankingsTable region={region === 'national' ? null : region} ageGroup={ageGroup} gender={genderForAPI} />
        </Suspense>

        <RelatedRankings currentRegion={region} currentAgeGroup={ageGroup} currentGender={gender} />
      </div>
    </div>
  );
}
