'use client';

import { PageHeader } from '@/components/PageHeader';
import { RankingsTable } from '@/components/RankingsTable';
import { Card, CardContent } from '@/components/ui/card';
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
  const title = `${regionDisplay} ${ageGroup.toUpperCase()} ${gender} Rankings`;
  const description = `View rankings for ${ageGroup.toUpperCase()} ${gender} teams${region !== 'national' ? ` in ${regionDisplay}` : ' nationwide'}`;

  return (
    <div className="container mx-auto py-8 px-4">
      <PageHeader
        title={title}
        description={description}
        showBackButton
        backHref="/"
      />
      
      <div className="space-y-6">
        <RankingsTable region={region} ageGroup={ageGroup} gender={gender} />
        
        <Card>
          <CardContent className="pt-6">
            <div className="text-sm text-muted-foreground">
              <p className="mb-2">
                <strong>Filters applied:</strong>
              </p>
              <ul className="list-disc list-inside space-y-1">
                <li>Region: {regionDisplay}</li>
                <li>Age Group: {ageGroup.toUpperCase()}</li>
                <li>Gender: {gender}</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

