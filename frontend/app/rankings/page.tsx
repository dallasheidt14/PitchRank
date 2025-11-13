'use client';

import { useState } from 'react';
import { PageHeader } from '@/components/PageHeader';
import { RankingsFilter } from '@/components/RankingsFilter';
import { RankingsTable } from '@/components/RankingsTable';

export default function RankingsPage() {
  // Default filters
  const defaultRegion = 'national';
  const defaultAgeGroup = 'u12';
  const defaultGender = 'male';
  
  const [region, setRegion] = useState(defaultRegion);
  const [ageGroup, setAgeGroup] = useState(defaultAgeGroup);
  const [gender, setGender] = useState(defaultGender);

  // Convert gender from URL format (lowercase) to API format (capitalized)
  const genderForAPI = gender 
    ? (gender.charAt(0).toUpperCase() + gender.slice(1).toLowerCase()) as 'Male' | 'Female'
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
        
        <RankingsTable
          region={region === 'national' ? null : region}
          ageGroup={ageGroup}
          gender={genderForAPI}
        />
      </div>
    </div>
  );
}
