'use client';

import { PageHeader } from '@/components/PageHeader';
import { RankingsTable } from '@/components/RankingsTable';
import { RankingsFilter } from '@/components/RankingsFilter';
import { use } from 'react';

// Revalidate every hour for ISR caching
export const revalidate = 3600;

interface RankingsPageProps {
  params: Promise<{
    region: string;
    ageGroup: string;
    gender: string;
  }>;
}

export default function RankingsPage({ params }: RankingsPageProps) {
  const { region, ageGroup, gender } = use(params);
  
  const regionDisplay = region === 'national' ? 'National' : region.toUpperCase();
  const genderDisplay = gender === 'male' ? 'Boys' : gender === 'female' ? 'Girls' : gender;
  const title = `${regionDisplay} ${ageGroup.toUpperCase()} ${genderDisplay} Rankings`;
  const description = `View rankings for ${ageGroup.toUpperCase()} ${genderDisplay} teams${region !== 'national' ? ` in ${regionDisplay}` : ' nationwide'}`;

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title={title}
        description={description}
        showBackButton
        backHref="/"
      />
      
      <div className="space-y-6">
        <RankingsFilter />
        <RankingsTable region={region} ageGroup={ageGroup} gender={gender} />
      </div>
    </div>
  );
}

