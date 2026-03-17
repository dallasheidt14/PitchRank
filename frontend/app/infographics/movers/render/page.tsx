'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { WeeklyMovers } from '@/components/infographics';

function MoversRenderContent() {
  const searchParams = useSearchParams();
  const variant = (searchParams.get('variant') as 'square' | 'portrait') || 'portrait';
  const week = parseInt(searchParams.get('week') || '0') || undefined;

  // Sample data - in production this would come from API
  const sampleMovers = [
    { teamName: 'LAFC Academy', state: 'CA', ageGroup: 'U14', gender: 'Boys' as const, movement: 47, newRank: 12 },
    { teamName: 'Solar SC', state: 'TX', ageGroup: 'U13', gender: 'Girls' as const, movement: 35, newRank: 8 },
    { teamName: 'Baltimore Armour', state: 'MD', ageGroup: 'U15', gender: 'Boys' as const, movement: 29, newRank: 23 },
    { teamName: 'Tophat SC', state: 'GA', ageGroup: 'U12', gender: 'Girls' as const, movement: 24, newRank: 15 },
    { teamName: 'SC del Sol', state: 'AZ', ageGroup: 'U16', gender: 'Boys' as const, movement: 21, newRank: 31 },
  ];

  return (
    <div data-infographic="movers" className="inline-block">
      <WeeklyMovers movers={sampleMovers} week={week} variant={variant} />
    </div>
  );
}

/**
 * Clean render page for Weekly Movers infographic export
 * URL: /infographics/movers/render?variant=square|portrait
 */
export default function MoversRenderPage() {
  return (
    <Suspense fallback={null}>
      <MoversRenderContent />
    </Suspense>
  );
}
