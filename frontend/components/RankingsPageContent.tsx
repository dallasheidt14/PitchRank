'use client';

import { Suspense } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { RankingsFilter } from '@/components/RankingsFilter';
import { RankingsTable } from '@/components/RankingsTable';
import { RankingsTableSkeleton } from '@/components/skeletons/RankingsTableSkeleton';
import { ShareButtons } from '@/components/ShareButtons';
import { Breadcrumbs } from '@/components/Breadcrumbs';
import { US_STATES } from '@/lib/constants';

interface RankingsPageContentProps {
  region: string;
  ageGroup: string;
  gender: string;
}

export function RankingsPageContent({ region, ageGroup, gender }: RankingsPageContentProps) {
  // Convert gender from URL format (lowercase) to API format (single letter)
  const genderForAPI = gender
    ? (gender === 'male' ? 'M' : gender === 'female' ? 'F' : null) as 'M' | 'F' | 'B' | 'G' | null
    : null;

  // Format region name for display
  const isNational = region === 'national';
  const stateName = isNational
    ? 'National'
    : US_STATES.find(s => s.code.toLowerCase() === region.toLowerCase())?.name || region.toUpperCase();

  // Format age group for display
  const ageGroupDisplay = ageGroup.toUpperCase();

  // Format gender for display
  const genderDisplay = gender === 'male' ? 'Boys' : 'Girls';

  // Create share title
  const shareTitle = `🏆 Check out the ${ageGroupDisplay} ${genderDisplay} ${stateName} soccer rankings on PitchRank!`;

  return (
    <div className="container mx-auto py-8 px-4">
      <Breadcrumbs />

      <PageHeader
        title="PitchRank Rankings"
        description=""
        showBackButton
        backHref="/"
      />

      <div className="space-y-6">
        <RankingsFilter />

        {/* Share Buttons */}
        <div className="flex justify-end">
          <ShareButtons
            title={shareTitle}
            hashtags={['YouthSoccer', 'SoccerRankings', 'PitchRank', `${ageGroupDisplay}Soccer`]}
            variant="compact"
          />
        </div>

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

