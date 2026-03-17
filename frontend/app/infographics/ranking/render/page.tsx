'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { RankingCard } from '@/components/infographics';

function RankingRenderContent() {
  const searchParams = useSearchParams();
  const variant = (searchParams.get('variant') as 'square' | 'story') || 'square';

  // Default sample data - can be overridden via URL params
  const rank = parseInt(searchParams.get('rank') || '1');
  const teamName = searchParams.get('team') || 'LAFC Academy 2012';
  const clubName = searchParams.get('club') || 'Los Angeles FC';
  const state = searchParams.get('state') || 'CA';
  const ageGroup = searchParams.get('age') || 'U14';
  const gender = (searchParams.get('gender') || 'Boys') as 'Boys' | 'Girls';
  const powerScore = parseInt(searchParams.get('score') || '1892');
  const record = searchParams.get('record') || '12-1-0';
  const movement = parseInt(searchParams.get('movement') || '5');

  return (
    <div data-infographic="ranking" className="inline-block">
      <RankingCard
        rank={rank}
        teamName={teamName}
        clubName={clubName}
        state={state}
        ageGroup={ageGroup}
        gender={gender}
        powerScore={powerScore}
        record={record}
        movement={movement}
        variant={variant}
      />
    </div>
  );
}

/**
 * Clean render page for Ranking Card infographic export
 * URL: /infographics/ranking/render?variant=square|story&team=...
 */
export default function RankingRenderPage() {
  return (
    <Suspense fallback={null}>
      <RankingRenderContent />
    </Suspense>
  );
}
