'use client';

import { useSearchParams } from 'next/navigation';
import { StateSpotlight } from '@/components/infographics';

/**
 * Clean render page for State Spotlight infographic export
 */
export default function StateRenderPage() {
  const searchParams = useSearchParams();
  const variant = (searchParams.get('variant') as 'square' | 'portrait') || 'portrait';
  const state = searchParams.get('state') || 'California';
  const stateCode = searchParams.get('code') || 'CA';
  const ageGroup = searchParams.get('age') || 'U14';
  const gender = (searchParams.get('gender') || 'Boys') as 'Boys' | 'Girls';
  
  const sampleTeams = [
    { rank: 1, teamName: 'LAFC Academy 2012', powerScore: 1892, movement: 3 },
    { rank: 2, teamName: 'LA Galaxy SD', powerScore: 1847, movement: -2 },
    { rank: 3, teamName: 'San Jose Earthquakes', powerScore: 1823, movement: 0 },
    { rank: 4, teamName: 'Strikers FC', powerScore: 1801, movement: 1 },
    { rank: 5, teamName: 'Real So Cal', powerScore: 1789, movement: 12 },
  ];
  
  return (
    <div data-infographic="state" className="inline-block">
      <StateSpotlight
        state={state}
        stateCode={stateCode}
        ageGroup={ageGroup}
        gender={gender}
        teams={sampleTeams}
        totalTeams={1247}
        variant={variant}
      />
    </div>
  );
}
